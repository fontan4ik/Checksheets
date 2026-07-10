const { google } = require("googleapis");
const axios = require("axios");
const path = require("path");
const crypto = require("crypto");

const SHEET_NAME = "ETM TR";
const SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI";

const ETM_TR_OZON_WAREHOUSE = 1020005000689690;
const ETM_TR_WB_WAREHOUSE = 798761; // Updated to correct WB warehouse ID

const ETM_TR_COLS = {
  ARTICUL: 1,
  CHRLID: 17,
  STOCK: 16, // Ozon stock column
  WB_STOCK: 21, // Wildberries stock column U
};

const MIN_STOCK_THRESHOLD = 0;

const RPS = 10;
const WB_RPS = 0.12; // ~14 per minute = 1 req per 4.3 sec

const OZON_BASE_DELAY = 1000;
const WB_BASE_DELAY = 3000;
const OZON_MAX_RETRIES = 3;
const WB_MAX_RETRIES = 3; // 14 = 3 retries + 1 original = 4 total
const OZON_POSTCHECK_DELAY_MS = 30000;
const OZON_POSTCHECK_RETRY_DELAY_MS = 60000;
const STOCK_REPAIR_ATTEMPTS = parseInt(
  process.env.ETM_STOCK_REPAIR_ATTEMPTS || "2",
  10,
);
const STOCK_REPAIR_DELAY_MS = parseInt(
  process.env.ETM_STOCK_REPAIR_DELAY_MS || "60000",
  10,
);
const SHEET_STABILITY_READS = parseInt(
  process.env.ETM_SHEET_STABILITY_READS || "3",
  10,
);
const SHEET_STABILITY_INTERVAL_MS = parseInt(
  process.env.ETM_SHEET_STABILITY_INTERVAL_MS || "120000",
  10,
);
const SHEET_STABILITY_MAX_WAIT_MS = parseInt(
  process.env.ETM_SHEET_STABILITY_MAX_WAIT_MS || "1800000",
  10,
);

let lastRequestTime = Date.now() - 1000 / RPS;

function rateLimitRPS(lastTime, rps) {
  const minInterval = 1000 / rps;
  const now = Date.now();
  const elapsed = now - lastTime;
  if (elapsed < minInterval) {
    return new Promise((resolve) =>
      setTimeout(resolve, minInterval - elapsed),
    ).then(() => Date.now());
  }
  return Promise.resolve(Date.now());
}

function log(msg) {
  const localTime = new Date().toLocaleTimeString("ru-RU", { hour12: false });
  const ms = String(new Date().getMilliseconds()).padStart(3, "0");
  console.log(`${localTime}.${ms} ${msg}`);
}

function columnLetter(col) {
  let letter = "";
  while (col > 0) {
    const mod = (col - 1) % 26;
    letter = String.fromCharCode(65 + mod) + letter;
    col = Math.floor((col - mod) / 26);
  }
  return letter;
}

function isTransportError(code, errorText) {
  const text = String(errorText || "").toLowerCase();
  return (
    code === 0 ||
    text.includes("socket hang up") ||
    text.includes("timeout") ||
    text.includes("timed out") ||
    text.includes("econnreset") ||
    text.includes("etimedout") ||
    text.includes("network error")
  );
}

function numericCell(value) {
  const parsed = Number(String(value ?? "").replace(",", "."));
  return Number.isFinite(parsed) ? parsed : 0;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function readETMTRPUStabilitySnapshot(auth) {
  const sheets = google.sheets({ version: "v4", auth });
  const response = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: `${SHEET_NAME}!A:U`,
    majorDimension: "ROWS",
    valueRenderOption: "UNFORMATTED_VALUE",
  });

  const rows = (response.data.values || []).slice(1);
  const hash = crypto.createHash("sha256");
  let rowCount = 0;
  let withChrlid = 0;
  let ozonTotal = 0;
  let wbTotal = 0;
  let ozonPositiveCount = 0;
  let wbPositiveCount = 0;
  let wbNoChrlidPositiveCount = 0;
  let wbNoChrlidPositiveTotal = 0;

  rows.forEach((row) => {
    const offerId = String(row[ETM_TR_COLS.ARTICUL - 1] || "").trim();
    if (!offerId) return;

    const chrlid = String(row[ETM_TR_COLS.CHRLID - 1] || "").trim();
    const ozonStock = numericCell(row[ETM_TR_COLS.STOCK - 1]);
    const wbStock = numericCell(row[20]);

    rowCount++;
    if (chrlid) {
      withChrlid++;
    } else if (wbStock > 0) {
      wbNoChrlidPositiveCount++;
      wbNoChrlidPositiveTotal += wbStock;
    }
    ozonTotal += ozonStock;
    wbTotal += wbStock;
    if (ozonStock > 0) ozonPositiveCount++;
    if (wbStock > 0) wbPositiveCount++;
    hash.update(`${offerId}\t${chrlid}\t${ozonStock}\t${wbStock}\n`);
  });

  return {
    signature: hash.digest("hex"),
    rowCount,
    withChrlid,
    ozonTotal,
    wbTotal,
    ozonPositiveCount,
    wbPositiveCount,
    wbNoChrlidPositiveCount,
    wbNoChrlidPositiveTotal,
  };
}

async function waitForETMTRPUStability(auth) {
  const requiredReads = Math.max(1, SHEET_STABILITY_READS);
  const intervalMs = Math.max(1000, SHEET_STABILITY_INTERVAL_MS);
  const maxWaitMs = Math.max(intervalMs, SHEET_STABILITY_MAX_WAIT_MS);
  const deadline = Date.now() + maxWaitMs;
  let previousSignature = "";
  let stableReads = 0;
  let attempt = 0;

  log(
    `⏳ Ждём стабильности ETM TR P/U: ${requiredReads} одинаковых снимка, интервал ${Math.round(intervalMs / 1000)} сек, максимум ${Math.round(maxWaitMs / 60000)} мин`,
  );

  while (Date.now() <= deadline) {
    attempt++;
    let snapshot;
    try {
      snapshot = await readETMTRPUStabilitySnapshot(auth);
    } catch (err) {
      const delay = Math.min(30000, 5000 * Math.min(attempt, 6));
      log(
        `⚠️ Ошибка чтения P/U снимка ${attempt}: ${err.message || err}; повтор через ${Math.round(delay / 1000)} сек`,
      );
      await sleep(delay);
      continue;
    }

    stableReads =
      snapshot.signature === previousSignature ? stableReads + 1 : 1;
    previousSignature = snapshot.signature;

    log(
      `📊 P/U снимок ${attempt}: rows=${snapshot.rowCount}, chrlid=${snapshot.withChrlid}, P>0=${snapshot.ozonPositiveCount}, U>0=${snapshot.wbPositiveCount}, P_sum=${snapshot.ozonTotal}, U_sum=${snapshot.wbTotal}, U_without_chrlid=${snapshot.wbNoChrlidPositiveTotal} (${snapshot.wbNoChrlidPositiveCount} строк), stable=${stableReads}/${requiredReads}, hash=${snapshot.signature.slice(0, 12)}`,
    );

    if (stableReads >= requiredReads) {
      log("✅ ETM TR P/U стабильны, начинаем синхронизацию маркетплейсов");
      return snapshot;
    }

    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }

  throw new Error(
    `ETM TR P/U не стабилизировались за ${Math.round(maxWaitMs / 60000)} мин; marketplace sync остановлен`,
  );
}

async function readETMStocksFromSheet(auth) {
  const sheets = google.sheets({ version: "v4", auth });

  const spreadsheet = await sheets.spreadsheets.get({
    spreadsheetId: SPREADSHEET_ID,
  });
  const sheet = spreadsheet.data.sheets.find(
    (s) => s.properties.title === SHEET_NAME,
  );

  if (!sheet) {
    log(`❌ Лист "${SHEET_NAME}" не найден!`);
    return [];
  }

  const lastRow = sheet.properties.gridProperties.rowCount;

  if (lastRow < 2) {
    log(`❌ Нет данных на листе "${SHEET_NAME}"`);
    return [];
  }

  const lastCol = sheet.properties.gridProperties.columnCount;
  const headersResp = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: `${SHEET_NAME}!1:1`,
    valueRenderOption: "UNFORMATTED_VALUE",
  });

  const headers = (headersResp.data.values?.[0] || []).map((h) =>
    String(h).trim().toLowerCase(),
  );

  const findCol = (name, fallback) => {
    const idx = headers.indexOf(name.toLowerCase());
    return idx >= 0 ? idx + 1 : fallback;
  };

  const colArticul = findCol("артикул", ETM_TR_COLS.ARTICUL);
  const colChrlid = findCol("chrlid", ETM_TR_COLS.CHRLID);
  // Marketplace sync for ETM TR must always read SMR from column P.
  const colStock = ETM_TR_COLS.STOCK;
  const colWbStock = findCol("вб остатки", ETM_TR_COLS.WB_STOCK);

  log(
    `🔍 Колонки: Артикул=${columnLetter(colArticul)}(${colArticul}), chrlid=${columnLetter(colChrlid)}(${colChrlid}), SMR(P)=${colStock}, WB_STOCK(${columnLetter(colWbStock)})=${colWbStock}`,
  );

  const maxCol = Math.max(colArticul, colChrlid, colStock, colWbStock);

  const dataResp = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: `${SHEET_NAME}!A:${String.fromCharCode(64 + maxCol)}`,
    majorDimension: "ROWS",
  });

  const allRows = dataResp.data.values || [];
  const data = allRows.slice(1);

  const stocks = [];

  for (let i = 0; i < data.length; i++) {
    const row = data[i];

    const offerId = row[colArticul - 1];
    const chrlid = row[colChrlid - 1];
    const originalStock = parseInt(row[colStock - 1]) || 0;

    if (!offerId) continue;

    // Применяем порог: если остаток < MIN_STOCK_THRESHOLD, выгружаем 0
    const stock = originalStock >= MIN_STOCK_THRESHOLD ? originalStock : 0;
    const wb_stock = Number(row[colWbStock - 1]) || 0;

    // Validate wb_stock is a non‑negative integer
    if (!Number.isInteger(wb_stock) || wb_stock < 0) {
      log(`⚠️ Некорректный WB остаток у ${offerId} (chrlid=${chrlid}): ${row[colWbStock - 1]}`);
    }

    stocks.push({
      offer_id: offerId,
      chrlid: chrlid,
      stock: stock,
      wb_stock: wb_stock,
      original_stock: originalStock,
    });
  }

  log(`📊 Прочитано ${stocks.length} товаров из листа "${SHEET_NAME}"`);
  log(`   С chrlid: ${stocks.filter((s) => s.chrlid).length}`);

  return stocks;
}

const wbToken =
  "Bearer eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjYwMzAydjEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjMsImVudCI6MSwiZXhwIjoxNzkzODMyMjk5LCJmb3IiOiJzZWxmIiwiaWQiOiIwMTlkZmNlNC0xNmU3LTc1ZmQtOWJmYi05YzBhOWE5OTQ2NmEiLCJpaWQiOjE5Nzg1NzA5LCJvaWQiOjE3NzU1NywicyI6NzM0NzAsInNpZCI6IjY4YjgyODQ2LTBkOTQtNGI0MS04NDU0LWRjMzUzMzQ4MmM5YSIsInQiOmZhbHNlLCJ1aWQiOjE5Nzg1NzA5fQ.FhzZXHwO6kQ2KEfYmanMo2_xumDIRrMbWyTIgJSeHztOOCViT8kBe55rZ9vBv_DSXsjR4S6teCplMh0S5OFn-w";

const wbHeaders = () => ({
  Authorization: wbToken,
  "Content-Type": "application/json",
});

const ozonHeaders = () => ({
  "Content-Type": "application/json",
  "Client-Id": "142355",
  "Api-Key": "fe539630-170b-4b48-b222-8ba092907a63",
});

async function fetchOzonWarehouseStocksByOfferIds(offerIds, warehouseId) {
  const stockMap = new Map();
  // Ozon returns multiple warehouse rows per offer_id even when warehouse_id is passed.
  // Large chunks with limit=1000 truncate the response and produce false zero mismatches.
  const chunkSize = 100;

  for (let i = 0; i < offerIds.length; i += chunkSize) {
    const chunk = offerIds.slice(i, i + chunkSize);
    const response = await axios.post(
      "https://api-seller.ozon.ru/v2/product/info/stocks-by-warehouse/fbs",
      {
        offer_id: chunk,
        warehouse_id: warehouseId,
        limit: 1000,
      },
      {
        headers: ozonHeaders(),
        timeout: 30000,
      },
    );

    const products = Array.isArray(response.data?.products)
      ? response.data.products
      : [];

    products.forEach((item) => {
      if (String(item.warehouse_id) !== String(warehouseId)) return;
      stockMap.set(String(item.offer_id), {
        present: Number(item.present) || 0,
        reserved: Number(item.reserved) || 0,
        free_stock: Number(item.free_stock) || 0,
      });
    });
  }

  return stockMap;
}

async function verifyETMOzonStocks(stocks) {
  const expected = stocks.filter((s) => s.offer_id);
  if (expected.length === 0) return [];

  const actualMap = await fetchOzonWarehouseStocksByOfferIds(
    expected.map((s) => String(s.offer_id)),
    ETM_TR_OZON_WAREHOUSE,
  );

  const mismatches = [];
  const samples = [];
  let sheetPositiveCount = 0;
  let marketplacePositiveCount = 0;

  expected.forEach((item) => {
    const actual = actualMap.get(String(item.offer_id));
    const freeStock = actual?.free_stock ?? 0;
    const present = actual?.present ?? 0;
    const reserved = actual?.reserved ?? 0;
    if (item.stock > 0) sheetPositiveCount++;
    if (freeStock > 0) marketplacePositiveCount++;
    if (freeStock !== item.stock) {
      mismatches.push({
        offer_id: item.offer_id,
        sheet: item.stock,
        free: freeStock,
        present,
        reserved,
      });
      if (samples.length < 10) {
        samples.push(
          `${item.offer_id}: sheet=${item.stock}, free=${freeStock}, present=${present}, reserved=${reserved}`,
        );
      }
    }
  });

  log(
    `📊 Ozon non-zero check (склад ЭТМ САМАРА ${ETM_TR_OZON_WAREHOUSE}): Google P>0=${sheetPositiveCount}, marketplace free_stock>0=${marketplacePositiveCount}, delta=${marketplacePositiveCount - sheetPositiveCount}`,
  );

  if (mismatches.length === 0) {
    log("✅ Ozon post-check: расхождений по складу ЭТМ САМАРА не найдено");
    return [];
  }

  log(`⚠️ Ozon post-check: найдено ${mismatches.length} расхождений по складу ЭТМ САМАРА`);
  samples.forEach((line) => log(`   - ${line}`));
  return mismatches;
}

async function repairETMOzonMismatches(stocks, initialMismatches) {
  let mismatches = initialMismatches || [];
  const attempts = Math.max(0, STOCK_REPAIR_ATTEMPTS);

  for (let attempt = 1; attempt <= attempts && mismatches.length > 0; attempt++) {
    const repairItems = mismatches.map((item) => ({
      offer_id: item.offer_id,
      stock: item.sheet,
    }));
    const batchSize = 100;
    let updated = 0;
    let errors = 0;

    log(
      `🛠️ Ozon repair ${attempt}/${attempts}: повторно пишем ${repairItems.length} расхождений на склад ЭТМ САМАРА`,
    );

    for (let i = 0; i < repairItems.length; i += batchSize) {
      lastRequestTime = await rateLimitRPS(lastRequestTime, RPS);
      const batch = repairItems.slice(i, i + batchSize);
      const result = await updateETMStocksOzonWithRetry(
        batch,
        ETM_TR_OZON_WAREHOUSE,
      );

      if (result.ok && result.data?.result) {
        result.data.result.forEach((r) => {
          if (r.errors && r.errors.length > 0) {
            const isError = !r.errors.some((e) => e.code === "TOO_MANY_REQUESTS");
            if (isError) {
              errors++;
            } else {
              updated++;
            }
          } else if (r.updated) {
            updated++;
          }
        });
      } else {
        errors += batch.length;
      }
    }

    log(
      `🛠️ Ozon repair ${attempt}/${attempts}: ✅ ${updated}, ❌ ${errors}; ждём ${Math.round(STOCK_REPAIR_DELAY_MS / 1000)} сек и перепроверяем`,
    );
    await sleep(STOCK_REPAIR_DELAY_MS);
    mismatches = await verifyETMOzonStocks(stocks);
  }

  return mismatches;
}

async function updateETMStocksOzonWithRetry(
  batch,
  warehouseId,
  retryCount = 0,
) {
  const body = {
    stocks: batch.map((item) => ({
      offer_id: String(item.offer_id),
      stock: item.stock,
      warehouse_id: warehouseId,
    })),
  };

  try {
    const response = await axios.post(
      "https://api-seller.ozon.ru/v2/products/stocks",
      body,
      {
        headers: ozonHeaders(),
        timeout: 30000,
      },
    );

    return { ok: true, data: response.data };
  } catch (err) {
    const code = err.response?.status;
    const errorText = err.response?.data
      ? JSON.stringify(err.response.data)
      : err.message;

    if (code === 429 && retryCount < OZON_MAX_RETRIES) {
      const delay = OZON_BASE_DELAY * Math.pow(2, retryCount);
      log(
        "⏳ Ozon 429: ожидание " +
          delay / 1000 +
          " сек перед retry " +
          (retryCount + 1) +
          "/" +
          OZON_MAX_RETRIES +
          "...",
      );
      await new Promise((r) => setTimeout(r, delay));
      return updateETMStocksOzonWithRetry(batch, warehouseId, retryCount + 1);
    }

    if (code === 429) {
      log("⏭️ Ozon 429: пропуск после " + OZON_MAX_RETRIES + " попыток");
      return { ok: false, error: "MAX_RETRIES_EXCEEDED", code };
    }

    if (isTransportError(code || 0, errorText) && retryCount < OZON_MAX_RETRIES) {
      const delay = OZON_BASE_DELAY * Math.pow(2, retryCount);
      log(
        "⏳ Ozon transport error: ожидание " +
          delay / 1000 +
          " сек перед retry " +
          (retryCount + 1) +
          "/" +
          OZON_MAX_RETRIES +
          "...",
      );
      await new Promise((r) => setTimeout(r, delay));
      return updateETMStocksOzonWithRetry(batch, warehouseId, retryCount + 1);
    }

    return { ok: false, error: err.response?.data || err.message, code };
  }
}

async function updateETMStocksOzon(stocks) {
  log(
    `🟠 Обновление остатков Ozon (склад: ЭТМ САМАРА, ID: ${ETM_TR_OZON_WAREHOUSE})...`,
  );

  const validStocks = stocks.filter((s) => s.offer_id);
  if (validStocks.length === 0) {
    log(`⚠️ Нет товаров с offer_id`);
    return [];
  }

  const batchSize = 100;
  const batches = Math.ceil(validStocks.length / batchSize);

  let successCount = 0;
  let errorCount = 0;
  let loggedOzonErrors = 0;

  for (let i = 0; i < batches; i++) {
    lastRequestTime = await rateLimitRPS(lastRequestTime, RPS);

    const batch = validStocks.slice(i * batchSize, (i + 1) * batchSize);

    const result = await updateETMStocksOzonWithRetry(
      batch,
      ETM_TR_OZON_WAREHOUSE,
    );

    if (result.ok && result.data?.result) {
      result.data.result.forEach((r) => {
        if (r.errors && r.errors.length > 0) {
          const isError = !r.errors.some((e) => e.code === "TOO_MANY_REQUESTS");
          if (isError) {
            errorCount++;
            if (loggedOzonErrors < 20) {
              log(
                `❌ Ozon не обновил ${r.offer_id || "(без offer_id)"}: ${JSON.stringify(r.errors)}`,
              );
              loggedOzonErrors++;
            }
          } else {
            successCount++;
          }
        } else if (r.updated) {
          successCount++;
        }
      });
      log(`✅ Пачка ${i + 1}/${batches} обработана (${batch.length} товаров)`);
    } else {
      log(
        `❌ Ошибка API (пачка ${i + 1}/${batches}): ${result.code || result.error}`,
      );
      errorCount += batch.length;
    }
  }

  log(`🟠 Ozon: ✅ ${successCount} обновлено, ❌ ${errorCount} ошибок`);
  log(
    `⏳ Ожидание ${OZON_POSTCHECK_DELAY_MS / 1000} сек перед промежуточным Ozon post-check...`,
  );
  await new Promise((resolve) => setTimeout(resolve, OZON_POSTCHECK_DELAY_MS));

  const mismatches = await verifyETMOzonStocks(validStocks);
  if (mismatches.length > 0) {
    log(
      `ℹ️ Промежуточные расхождения по Ozon будут перепроверены в конце скрипта после WB: ${mismatches.length}`,
    );
  }
  return mismatches;
}

function isWBCargoRestrictionError(responseText) {
  try {
    const errorData = JSON.parse(responseText);
    const errorItems = Array.isArray(errorData)
      ? errorData
      : errorData?.errors || errorData?.error || [];

    if (!errorItems || errorItems.length === 0) return false;

    return errorItems.some((err) => {
      const code = String(err.code || err.error || "");
      const message = String(err.message || err.detail || "");
      return (
        code.includes("CargoWarehouseRestriction") ||
        message.includes("CargoWarehouseRestriction") ||
        code.includes("SGTKGTPlus") ||
        message.includes("SGTKGTPlus") ||
        message.includes("ODC") ||
        message.includes("CD+")
      );
    });
  } catch (e) {
    return (
      responseText.includes("CargoWarehouseRestriction") ||
      responseText.includes("SGTKGTPlus") ||
      responseText.includes("ODC") ||
      responseText.includes("CD+")
    );
  }
}

async function sendETMStocksBatch(batch, warehouseId, retryCount = 0) {
  const body = { stocks: batch };
  const url = `https://marketplace-api.wildberries.ru/api/v3/stocks/${warehouseId}`;

  try {
    const response = await axios.put(url, body, {
      headers: wbHeaders(),
      timeout: 30000,
    });

    const code = response.status;
    const text = JSON.stringify(response.data || {});

    if (code === 429 && retryCount < WB_MAX_RETRIES) {
      const delay = WB_BASE_DELAY * Math.pow(2, retryCount);
      log(
        "⏳ WB 429: ожидание " +
          delay / 1000 +
          " сек перед retry " +
          (retryCount + 1) +
          "/" +
          WB_MAX_RETRIES +
          "...",
      );
      await new Promise((r) => setTimeout(r, delay));
      return sendETMStocksBatch(batch, warehouseId, retryCount + 1);
    }

    if (code === 429) {
      log("⏭️ WB 429: пропуск после " + WB_MAX_RETRIES + " попыток");
      return { ok: false, code, text: "MAX_RETRIES_EXCEEDED" };
    }

    return {
      ok: code === 200 || code === 204,
      code,
      text,
      cargoRestriction: code === 409 && isWBCargoRestrictionError(text),
    };
  } catch (err) {
    const code = err.response?.status || 0;
    const text = err.response?.data
      ? JSON.stringify(err.response.data)
      : err.message;

    if (code === 429 && retryCount < WB_MAX_RETRIES) {
      const delay = WB_BASE_DELAY * Math.pow(2, retryCount);
      log(
        "⏳ WB 429: ожидание " +
          delay / 1000 +
          " сек перед retry " +
          (retryCount + 1) +
          "/" +
          WB_MAX_RETRIES +
          "...",
      );
      await new Promise((r) => setTimeout(r, delay));
      return sendETMStocksBatch(batch, warehouseId, retryCount + 1);
    }

    if (code === 429) {
      log("⏭️ WB 429: пропуск после " + WB_MAX_RETRIES + " попыток");
      return { ok: false, code, text: "MAX_RETRIES_EXCEEDED" };
    }

    if (isTransportError(code, text) && retryCount < WB_MAX_RETRIES) {
      const delay = WB_BASE_DELAY * Math.pow(2, retryCount);
      log(
        "⏳ WB transport error: ожидание " +
          delay / 1000 +
          " сек перед retry " +
          (retryCount + 1) +
          "/" +
          WB_MAX_RETRIES +
          "...",
      );
      await new Promise((r) => setTimeout(r, delay));
      return sendETMStocksBatch(batch, warehouseId, retryCount + 1);
    }

    return {
      ok: false,
      code,
      text,
      cargoRestriction: code === 409 && isWBCargoRestrictionError(text),
    };
  }
}

async function processETMConflictIndividually(
  validBatch,
  warehouseId,
  batchLabel,
) {
  let successCount = 0;
  let skippedCount = 0;
  let errorCount = 0;

  log(
    `🔍 ${batchLabel}: дробление до отдельных товаров (${validBatch.length} шт)...`,
  );

  for (let j = 0; j < validBatch.length; j++) {
    if (j > 0 && j % 5 === 0) {
      await new Promise((r) => setTimeout(r, 3000));
    }

    const item = validBatch[j];
    const result = await sendETMStocksBatch([item], warehouseId);

    if (result.ok) {
      successCount++;
      continue;
    }

    if (result.cargoRestriction) {
      log(
        `⏸️ ${batchLabel}: пропущен ODC/CD+ chrtId=${item.chrtId}, amount=${item.amount}`,
      );
      skippedCount++;
      continue;
    }

    if (result.text === "MAX_RETRIES_EXCEEDED") {
      log(
        `⏭️ ${batchLabel}: chrtId=${item.chrtId} - 429 превышен лимит, пропущен`,
      );
      skippedCount++;
      continue;
    }

    log(
      `❌ ${batchLabel}: ошибка для chrtId=${item.chrtId}, code=${result.code}`,
    );
    errorCount++;
  }

  log(
    `📊 ${batchLabel}: поштучно ✅ ${successCount}, ⏸️ ${skippedCount}, ❌ ${errorCount}`,
  );

  return { successCount, skippedCount, errorCount };
}

async function updateETMStocksWB(stocks) {
  log(
    `🟣 Обновление остатков WB FBS (склад: Новосемейкино, ID: ${ETM_TR_WB_WAREHOUSE})...`,
  );

  const validStocks = stocks.filter((s) => s.chrlid);
  if (validStocks.length === 0) {
    log(`⚠️ Нет товаров с chrlid`);
    return;
  }

  log(`📦 Товаров для обработки: ${validStocks.length}`);

  const batchSize = 200;
  const batches = Math.ceil(validStocks.length / batchSize);

  lastRequestTime = Date.now() - 1000 / WB_RPS;
  let successCount = 0;
  let skippedCount = 0;
  let errorCount = 0;

  for (let i = 0; i < batches; i++) {
    lastRequestTime = rateLimitRPS(lastRequestTime, WB_RPS);

    const batch = validStocks.slice(i * batchSize, (i + 1) * batchSize);

    const validBatch = [];

    for (const item of batch) {
      const idNum = Number(item.chrlid);
      if (isNaN(idNum) || !item.chrlid) {
        errorCount++;
        continue;
      }
      // Use wb_stock for Wildberries amount
      // Ensure amount sent to WB is an integer
      const rawAmount = Number(item.wb_stock);
      const amount = Number.isInteger(rawAmount) && rawAmount >= 0 ? rawAmount : 0;
      if (amount !== rawAmount) {
        log(`⚠️ Коррекция WB amount для chrtId=${idNum}: исходное=${rawAmount}, использовано=${amount}`);
      }
      validBatch.push({ chrtId: idNum, amount: amount });
    }

    if (validBatch.length === 0) continue;

    const result = await sendETMStocksBatch(validBatch, ETM_TR_WB_WAREHOUSE);

    if (result.ok) {
      successCount += validBatch.length;
      log(
        `✅ Пачка ${i + 1}/${batches} обработана (${validBatch.length} товаров)`,
      );
      continue;
    }

    if (result.cargoRestriction) {
      log(`⚠️ WB 409 ODC/CD+ (пачка ${i + 1}/${batches}): дробление...`);
      const fallback = await processETMConflictIndividually(
        validBatch,
        ETM_TR_WB_WAREHOUSE,
        `Пачка ${i + 1}/${batches}`,
      );
      successCount += fallback.successCount;
      skippedCount += fallback.skippedCount;
      errorCount += fallback.errorCount;
      continue;
    }

    if (result.text === "MAX_RETRIES_EXCEEDED") {
      log(
        `⏭️ WB 429 (пачка ${i + 1}/${batches}): превышен лимит, пропущено ${validBatch.length} товаров`,
      );
      skippedCount += validBatch.length;
      continue;
    }

    log(`❌ Ошибка API (пачка ${i + 1}/${batches}): ${result.code}`);
    errorCount += validBatch.length;
  }

  log(
    `🟣 WB: ✅ ${successCount} обновлено, ⏸️ ${skippedCount} пропущено ODC/CD+, ❌ ${errorCount} ошибок`,
  );
}

async function fetchETMWBStocks(warehouseId, chrtIds) {
  const stockMap = new Map();
  const failedChrtIds = new Set();
  const chunkSize = 1000;
  
  for (let i = 0; i < chrtIds.length; i += chunkSize) {
    const chunk = chrtIds.slice(i, i + chunkSize);
    
    if (i > 0) await new Promise((resolve) => setTimeout(resolve, 550));
    
    try {
      const response = await axios.post(
        `https://marketplace-api.wildberries.ru/api/v3/stocks/${warehouseId}`,
        { chrtIds: chunk },
        { headers: wbHeaders(), timeout: 20000 }
      );
      
      const stocks = Array.isArray(response.data?.stocks) ? response.data.stocks : [];
      stocks.forEach((item) => {
        stockMap.set(Number(item.chrtId), Number(item.amount) || 0);
      });
    } catch (err) {
      chunk.forEach((chrtId) => failedChrtIds.add(Number(chrtId)));
      log(`❌ Ошибка API при запросе остатков склада ${warehouseId}: ${err.response ? JSON.stringify(err.response.data) : err.message}`);
    }
  }
  
  return { stockMap, failedChrtIds };
}

async function verifyETMWBStocks(stocks) {
  const expected = stocks.filter((s) => s.chrlid);
  if (expected.length === 0) return [];

  const uniqueChrtIds = [...new Set(expected.map(item => Number(item.chrlid)))];
  
  log(`🟣 WB post-check: запрос остатков для ${uniqueChrtIds.length} chrtId...`);
  const { stockMap: actualMap, failedChrtIds } = await fetchETMWBStocks(
    ETM_TR_WB_WAREHOUSE,
    uniqueChrtIds,
  );
  if (failedChrtIds.size > 0) {
    log(
      `⚠️ WB post-check неполный: не удалось прочитать ${failedChrtIds.size} chrtId, они исключены из сравнения`,
    );
  }

  const mismatches = [];
  const samples = [];
  const expectedByChrtId = new Map();
  
  expected.forEach((item) => {
    const idNum = Number(item.chrlid);
    const previous = expectedByChrtId.get(idNum) || 0;
    expectedByChrtId.set(idNum, Math.max(previous, item.wb_stock));
    if (failedChrtIds.has(idNum)) return;
    const actual = actualMap.get(idNum) ?? 0;
    if (actual !== item.wb_stock) {
      mismatches.push({
        offer_id: item.offer_id,
        chrtId: idNum,
        sheet: item.wb_stock,
        wb: actual
      });
      if (samples.length < 10) {
        samples.push(
          `${item.offer_id} (chrtId=${idNum}): sheet=${item.wb_stock}, wb=${actual}`
        );
      }
    }
  });

  let sheetPositiveCount = 0;
  let marketplacePositiveCount = 0;
  let excludedCount = 0;
  expectedByChrtId.forEach((sheetStock, chrtId) => {
    if (failedChrtIds.has(chrtId)) {
      excludedCount++;
      return;
    }
    if (sheetStock > 0) sheetPositiveCount++;
    if ((actualMap.get(chrtId) ?? 0) > 0) marketplacePositiveCount++;
  });

  const excludedText = excludedCount > 0 ? `, исключено из сравнения=${excludedCount}` : "";
  log(
    `📊 WB non-zero check (склад Новосемейкино ${ETM_TR_WB_WAREHOUSE}): Google U>0=${sheetPositiveCount}, marketplace amount>0=${marketplacePositiveCount}, delta=${marketplacePositiveCount - sheetPositiveCount}${excludedText}`,
  );
  
  if (mismatches.length === 0) {
    log("✅ WB post-check: расхождений по складу Новосемейкино не найдено");
  } else {
    log(`⚠️ WB post-check: найдено ${mismatches.length} расхождений по складу Новосемейкино`);
    samples.forEach((line) => log(`   - ${line}`));
    if (mismatches.length > 10) {
      log(`   ... и ещё ${mismatches.length - 10} расхождений`);
    }
  }

  return mismatches;
}

async function repairETMWBMismatches(stocks, initialMismatches) {
  let mismatches = initialMismatches || [];
  const attempts = Math.max(0, STOCK_REPAIR_ATTEMPTS);

  for (let attempt = 1; attempt <= attempts && mismatches.length > 0; attempt++) {
    const validBatch = [];
    let skippedInvalid = 0;

    mismatches.forEach((item) => {
      const chrtId = Number(item.chrtId);
      const amount = Number(item.sheet);
      if (!Number.isFinite(chrtId) || chrtId <= 0 || !Number.isInteger(amount) || amount < 0) {
        skippedInvalid++;
        return;
      }
      validBatch.push({ chrtId, amount });
    });

    if (validBatch.length === 0) {
      log(`🛠️ WB repair ${attempt}/${attempts}: нет валидных chrtId для повторной записи`);
      break;
    }

    log(
      `🛠️ WB repair ${attempt}/${attempts}: повторно пишем ${validBatch.length} расхождений на склад Новосемейкино`,
    );

    const batchSize = 200;
    let successCount = 0;
    let skippedCount = 0;
    let errorCount = skippedInvalid;

    for (let i = 0; i < validBatch.length; i += batchSize) {
      const batch = validBatch.slice(i, i + batchSize);
      const result = await sendETMStocksBatch(batch, ETM_TR_WB_WAREHOUSE);

      if (result.ok) {
        successCount += batch.length;
        continue;
      }

      if (result.cargoRestriction) {
        const fallback = await processETMConflictIndividually(
          batch,
          ETM_TR_WB_WAREHOUSE,
          `WB repair ${attempt}/${attempts} пачка ${Math.floor(i / batchSize) + 1}`,
        );
        successCount += fallback.successCount;
        skippedCount += fallback.skippedCount;
        errorCount += fallback.errorCount;
        continue;
      }

      errorCount += batch.length;
    }

    log(
      `🛠️ WB repair ${attempt}/${attempts}: ✅ ${successCount}, ⏸️ ${skippedCount}, ❌ ${errorCount}; ждём ${Math.round(STOCK_REPAIR_DELAY_MS / 1000)} сек и перепроверяем`,
    );
    await sleep(STOCK_REPAIR_DELAY_MS);
    mismatches = await verifyETMWBStocks(stocks);
  }

  return mismatches;
}

async function main() {
  console.log("============================================");
  console.log("🔄 СИНХРОНИЗАЦИЯ ОСТАТКОВ ETM TR (LOCAL)");
  console.log("============================================");

  const startTime = new Date();

  const auth = new google.auth.GoogleAuth({
    keyFile: path.join(
      __dirname,
      "nomadic-bedrock-485314-b0-d7624dedd83c.json",
    ),
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });

  const client = await auth.getClient();
  google.options({ auth: client });

  await waitForETMTRPUStability(client);

  let stocks = [];
  const maxReadRetries = 5;
  for (let attempt = 1; attempt <= maxReadRetries; attempt++) {
    try {
      log(`📊 Шаг 1: Чтение данных из листа "${SHEET_NAME}" (попытка ${attempt}/${maxReadRetries})...`);
      stocks = await readETMStocksFromSheet(client);
      break;
    } catch (err) {
      log(`⚠️ Ошибка чтения листа (попытка ${attempt}/${maxReadRetries}): ${err.message || err}`);
      if (attempt === maxReadRetries) throw err;
      const delay = 5000 * attempt;
      log(`⏳ Ожидание ${delay / 1000} сек перед повтором...`);
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }

  if (stocks.length === 0) {
    log("❌ Нет данных для синхронизации");
    return;
  }

  log(`📋 Примеры данных (первые 5):`);
  stocks.slice(0, 5).forEach((s) => {
    log(
      `  - ${s.offer_id} | chrlid: ${s.chrlid || "(нет)"} | Stock: ${s.stock}`,
    );
  });

  log("");
  log("🟠 Шаг 2: Обновление остатков Ozon (ЭТМ САМАРА)...");
  const ozonPendingMismatches = await updateETMStocksOzon(stocks);

  log("");
  log("🟣 Шаг 3: Обновление остатков WB (Новосемейкино)...");
  await updateETMStocksWB(stocks);

  log("");
  log(
    `🟠 Шаг 4: Финальная полная перепроверка Ozon после завершения WB; первичных расхождений было ${ozonPendingMismatches.length}`,
  );
  log(
    `⏳ Дополнительное ожидание ${OZON_POSTCHECK_RETRY_DELAY_MS / 1000} сек перед финальным Ozon post-check...`,
  );
  await new Promise((resolve) =>
    setTimeout(resolve, OZON_POSTCHECK_RETRY_DELAY_MS),
  );
  const finalOzonMismatches = await verifyETMOzonStocks(stocks);
  await repairETMOzonMismatches(stocks, finalOzonMismatches);

  log("");
  log("🟣 Шаг 5: Ожидание 15 минут перед финальным WB post-check...");
  await new Promise((resolve) => setTimeout(resolve, 15 * 60 * 1000));
  const finalWBMismatches = await verifyETMWBStocks(stocks);
  await repairETMWBMismatches(stocks, finalWBMismatches);

  const endTime = new Date();
  const duration = Math.round((endTime - startTime) / 1000);

  log("");
  console.log("============================================");
  log(`✅ Синхронизация завершена за ${duration} сек.`);
  console.log("============================================");
}

main().catch((err) => {
  console.error("❌ Ошибка:", err);
  process.exit(1);
});
