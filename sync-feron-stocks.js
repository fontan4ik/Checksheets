const { google } = require("googleapis");
const axios = require("axios");
const fs = require("fs");
const path = require("path");

const SHEET_NAME = "FERON TR";
const SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI";

const FERON_TR_OZON_WAREHOUSES = {
  MSK: 1020005000217829,
  SMR: 1020005000234124,
  NSB: 1020005008262970,
  EKB: 1020005023877890,
};

const FERON_TR_WB_WAREHOUSE = {
  MSK: 1449484,
  SMR: 798761,
  NSB: 1724900,
  // МГТ / Екатеринбург ФБС, склад WB «Екатеринбург».
  EKB: 1860503,
};

const FERON_TR_COLS = {
  VENDOR_CODE: 1,
  OZON_SKU: 5,
  // Special marketplace stock columns: S=MSK, T=SMR, U=NSB, V=EKB.
  STOCK_MSK: 19,
  STOCK_SMR: 20,
  STOCK_NSB: 21,
  STOCK_EKB: 22,
  CHRT_ID: 23,
};

const MIN_STOCK_THRESHOLD = 0;

const RPS = 10;
const WB_RPS = 0.1;

const OZON_BASE_DELAY = 1000;
const WB_BASE_DELAY = 3000;
const OZON_MAX_RETRIES = 3;
const WB_MAX_RETRIES = 3;
const OZON_POSTCHECK_DELAY_MS = 30000;
const OZON_POSTCHECK_RETRY_DELAY_MS = 60000;

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

async function readFeronStocksFromSheet(auth) {
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

  const colVendor = findCol("артикул", FERON_TR_COLS.VENDOR_CODE);
  const colOzonSku = findCol("sku ozon", FERON_TR_COLS.OZON_SKU);
  // Read special marketplace columns from FERON TR: S=MSK, T=SMR, U=NSB, V=EKB.
  const colStockMsk = FERON_TR_COLS.STOCK_MSK;
  const colStockSmr = FERON_TR_COLS.STOCK_SMR;
  const colStockNsb = FERON_TR_COLS.STOCK_NSB;
  const colStockEkb = FERON_TR_COLS.STOCK_EKB;
  const colChrtId =
    findCol("chrtid", findCol("chrlid", FERON_TR_COLS.CHRT_ID));

  log(
    `🔍 Колонки: offer_id=${colVendor}, sku_ozon=${colOzonSku}, MSK=${colStockMsk}, SMR=${colStockSmr}, NSB=${colStockNsb}, EKB=${colStockEkb}, chrtId=${colChrtId}`,
  );

  const maxCol = Math.max(
    colVendor,
    colOzonSku,
    colStockMsk,
    colStockSmr,
    colStockNsb,
    colStockEkb,
    colChrtId,
  );

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

    const vendorCode = row[colVendor - 1];
    const ozonSku = parseInt(row[colOzonSku - 1]) || 0;
    const originalStockMsk = parseInt(row[colStockMsk - 1]) || 0;
    const originalStockSmr = parseInt(row[colStockSmr - 1]) || 0;
    const originalStockNsb = parseInt(row[colStockNsb - 1]) || 0;
    const originalStockEkb = parseInt(row[colStockEkb - 1]) || 0;
    const chrtId = row[colChrtId - 1];

    if (!vendorCode) continue;

    const stockMsk = originalStockMsk;
    const stockSmr = originalStockSmr;
    const stockNsb = originalStockNsb;

    stocks.push({
      offer_id: vendorCode,
      ozon_sku: ozonSku,
      stock_msk: originalStockMsk,
      stock_smr: originalStockSmr,
      stock_nsb: originalStockNsb,
      stock_ekb: originalStockEkb,
      original_stock_msk: originalStockMsk,
      original_stock_smr: originalStockSmr,
      original_stock_nsb: originalStockNsb,
      original_stock_ekb: originalStockEkb,
      chrt_id: chrtId,
    });
  }

  log(`📊 Прочитано ${stocks.length} товаров из листа "${SHEET_NAME}"`);
  log(`   С chrtId: ${stocks.filter((s) => s.chrt_id).length}`);

  return stocks;
}

const wbToken =
  "Bearer eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg2MDUyMTMxLCJpZCI6IjAxOWMyZDI4LTI0MzMtNzY2MC1iZDU4LTRlNjVhYzMwM2E0YiIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.fZu3j3YZBrIIEAZ6KtuWjTZ7HfPS3sR8Z6vOdmfT5L8hpQmjvVq3zf9Io-2wXTifmda46JEKhCZafyUlTUfpdA";

const wbHeaders = () => ({
  Authorization: wbToken,
  "Content-Type": "application/json",
});

const ozonHeaders = () => ({
  "Content-Type": "application/json",
  "Client-Id": "142355",
  "Api-Key": "fe539630-170b-4b48-b222-8ba092907a63",
});

async function fetchOzonWarehouseStocksBySku(items, warehouseId) {
  const stockMap = new Map();
  const validItems = items.filter((item) => Number(item.ozon_sku) > 0);
  const chunkSize = 500;

  for (let i = 0; i < validItems.length; i += chunkSize) {
    const chunk = validItems.slice(i, i + chunkSize);
    const response = await axios.post(
      "https://api-seller.ozon.ru/v2/product/info/stocks-by-warehouse/fbs",
      {
        sku: chunk.map((item) => Number(item.ozon_sku)),
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
      stockMap.set(String(item.sku), {
        present: Number(item.present) || 0,
        reserved: Number(item.reserved) || 0,
        free_stock: Number(item.free_stock) || 0,
      });
    });
  }

  return stockMap;
}

async function verifyFeronOzonWarehouse(stocks, warehouse) {
  const expected = stocks.filter((s) => s.offer_id);
  if (expected.length === 0) return [];

  const actualMap = await fetchOzonWarehouseStocksBySku(expected, warehouse.id);

  const mismatches = [];
  const samples = [];

  expected.forEach((item) => {
    const expectedStock = Number(item[warehouse.col]) || 0;
    if (!Number(item.ozon_sku)) {
      return;
    }
    const actual = actualMap.get(String(item.ozon_sku));
    const actualStock = actual ? actual.present + actual.reserved : 0;
    if (actualStock !== expectedStock) {
      mismatches.push({
        offer_id: item.offer_id,
        ozon_sku: item.ozon_sku,
        expected: expectedStock,
        actual: actualStock,
        free: actual?.free_stock ?? 0,
      });
      if (samples.length < 10) {
        samples.push(
          `${item.offer_id} [sku=${item.ozon_sku}]: sheet=${expectedStock}, ozon=${actualStock}, free=${actual?.free_stock ?? 0}`,
        );
      }
    }
  });

  if (mismatches.length === 0) {
    log(`✅ Ozon post-check ${warehouse.name}: расхождений не найдено`);
    return [];
  }

  log(`⚠️ Ozon post-check ${warehouse.name}: найдено ${mismatches.length} расхождений`);
  samples.forEach((line) => log(`   - ${line}`));
  return mismatches;
}

async function updateFeronStocksOzonWithRetry(
  batch,
  warehouseId,
  colName,
  retryCount = 0,
) {
  const body = {
    stocks: batch.map((item) => ({
      offer_id: String(item.offer_id),
      stock: item[colName],
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
      return updateFeronStocksOzonWithRetry(batch, warehouseId, colName, retryCount + 1);
    }

    if (code === 429) {
      log("⏭️ Ozon 429: пропуск после " + OZON_MAX_RETRIES + " попыток");
      return { ok: false, error: "MAX_RETRIES_EXCEEDED", code };
    }

    return { ok: false, error: err.response?.data || err.message, code };
  }
}

async function updateFeronStocksOzon(stocks) {
  log(`🟠 Обновление остатков Ozon (4 склада)...`);

  const validStocks = stocks.filter((s) => s.offer_id);
  if (validStocks.length === 0) {
    log(`⚠️ Нет товаров с offer_id`);
    return;
  }

  const warehouses = [
    {
      key: "MSK",
      name: "Москва",
      id: FERON_TR_OZON_WAREHOUSES.MSK,
      col: "stock_msk",
    },
    {
      key: "SMR",
      name: "Самара",
      id: FERON_TR_OZON_WAREHOUSES.SMR,
      col: "stock_smr",
    },
    {
      key: "NSB",
      name: "Новосибирск",
      id: FERON_TR_OZON_WAREHOUSES.NSB,
      col: "stock_nsb",
    },
    {
      key: "EKB",
      name: "Екатеринбург",
      id: FERON_TR_OZON_WAREHOUSES.EKB,
      col: "stock_ekb",
    },
  ];

  let totalSuccess = 0;
  let totalError = 0;
  const pendingChecks = [];

  for (const wh of warehouses) {
    log(`\n📦 Обработка склада: ${wh.name} (ID: ${wh.id})...`);

    const batchSize = 100;
    const batches = Math.ceil(validStocks.length / batchSize);

    let warehouseSuccess = 0;
    let warehouseError = 0;

    for (let i = 0; i < batches; i++) {
      lastRequestTime = await rateLimitRPS(lastRequestTime, RPS);

      const batch = validStocks.slice(i * batchSize, (i + 1) * batchSize);

      log(`📤 Отправка на Ozon ${wh.name}: ${batch.length} товаров, первый: offer_id=${batch[0]?.offer_id}, ${wh.col}=${batch[0]?.[wh.col]}`);

      const result = await updateFeronStocksOzonWithRetry(batch, wh.id, wh.col);

      if (result.ok && result.data?.result) {
        result.data.result.forEach((r) => {
          if (r.errors && r.errors.length > 0) {
            const isError = !r.errors.some(
              (e) => e.code === "TOO_MANY_REQUESTS",
            );
            if (isError) warehouseError++;
            else warehouseSuccess++;
          } else if (r.updated) {
            warehouseSuccess++;
          }
        });
        log(`✅ Пачка ${i + 1}/${batches} обработана`);
      } else {
        log(
          `❌ Ошибка API (пачка ${i + 1}/${batches}): ${result.code || result.error}`,
        );
        warehouseError += batch.length;
      }
    }

    log(
      `🟠 ${wh.name}: ✅ ${warehouseSuccess} обновлено, ❌ ${warehouseError} ошибок`,
    );
    log(
      `⏳ Ожидание ${OZON_POSTCHECK_DELAY_MS / 1000} сек перед промежуточным Ozon post-check ${wh.name}...`,
    );
    await new Promise((resolve) => setTimeout(resolve, OZON_POSTCHECK_DELAY_MS));
    const mismatches = await verifyFeronOzonWarehouse(validStocks, wh);
    if (mismatches.length > 0) {
      log(
        `ℹ️ Промежуточные расхождения Ozon ${wh.name} будут перепроверены в конце скрипта после WB: ${mismatches.length}`,
      );
      pendingChecks.push({ warehouse: wh, mismatches });
    }
    totalSuccess += warehouseSuccess;
    totalError += warehouseError;
  }

  log(`\n🟠 Ozon Всего: ✅ ${totalSuccess} обновлено, ❌ ${totalError} ошибок`);
  return pendingChecks;
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

async function sendFeronWBStocksBatch(batch, warehouseId, retryCount = 0) {
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
      return sendFeronWBStocksBatch(batch, warehouseId, retryCount + 1);
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
      return sendFeronWBStocksBatch(batch, warehouseId, retryCount + 1);
    }

    if (code === 429) {
      log("⏭️ WB 429: пропуск после " + WB_MAX_RETRIES + " попыток");
      return { ok: false, code, text: "MAX_RETRIES_EXCEEDED" };
    }

    return {
      ok: false,
      code,
      text,
      cargoRestriction: code === 409 && isWBCargoRestrictionError(text),
    };
  }
}

async function processFeronWBConflictIndividually(
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
    const result = await sendFeronWBStocksBatch([item], warehouseId);

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

async function updateFeronStocksWB(stocks) {
  log(`🟣 Обновление остатков WB FBS (4 склада)...`);

  const validStocks = stocks.filter((s) => s.chrt_id);
  if (validStocks.length === 0) {
    log(`⚠️ Нет товаров с chrtId`);
    return;
  }

  log(`📦 Товаров для обработки: ${validStocks.length}`);

  const warehouses = [
    {
      key: "MSK",
      name: "Москва",
      id: FERON_TR_WB_WAREHOUSE.MSK,
      col: "stock_msk",
    },
    {
      key: "SMR",
      name: "Самара",
      id: FERON_TR_WB_WAREHOUSE.SMR,
      col: "stock_smr",
    },
    {
      key: "NSB",
      name: "Новосибирск",
      id: FERON_TR_WB_WAREHOUSE.NSB,
      col: "stock_nsb",
    },
    {
      key: "EKB",
      name: "Екатеринбург",
      id: FERON_TR_WB_WAREHOUSE.EKB,
      col: "stock_ekb",
    },
  ];

  lastRequestTime = Date.now() - 1000 / WB_RPS;
  let totalSuccess = 0;
  let totalSkipped = 0;
  let totalError = 0;

  for (const wh of warehouses) {
    log(`\n📦 Обработка склада: ${wh.name} (ID: ${wh.id})...`);

    const batchSize = 200;
    const batches = Math.ceil(validStocks.length / batchSize);

    let warehouseSuccess = 0;
    let warehouseSkipped = 0;
    let warehouseError = 0;

    for (let i = 0; i < batches; i++) {
      lastRequestTime = rateLimitRPS(lastRequestTime, WB_RPS);

      const batch = validStocks.slice(i * batchSize, (i + 1) * batchSize);

      const validBatch = [];

      for (const item of batch) {
        const idNum = Number(item.chrt_id);
        if (isNaN(idNum) || !item.chrt_id) {
          warehouseError++;
          continue;
        }
        validBatch.push({ chrtId: idNum, amount: item[wh.col] });
      }

      if (validBatch.length === 0) continue;

      log(`📤 Отправка на WB ${wh.name}: ${validBatch.length} товаров, первый: chrtId=${validBatch[0]?.chrtId}, amount=${validBatch[0]?.amount}`);

      const result = await sendFeronWBStocksBatch(validBatch, wh.id);

      if (result.ok) {
        warehouseSuccess += validBatch.length;
        log(
          `✅ Пачка ${i + 1}/${batches} обработана (${validBatch.length} товаров)`,
        );
        continue;
      }

      if (result.cargoRestriction) {
        log(`⚠️ WB 409 ODC/CD+ (пачка ${i + 1}/${batches}): дробление...`);
        const fallback = await processFeronWBConflictIndividually(
          validBatch,
          wh.id,
          `Пачка ${i + 1}/${batches}`,
        );
        warehouseSuccess += fallback.successCount;
        warehouseSkipped += fallback.skippedCount;
        warehouseError += fallback.errorCount;
        continue;
      }

      if (result.text === "MAX_RETRIES_EXCEEDED") {
        log(
          `⏭️ WB 429 (пачка ${i + 1}/${batches}): превышен лимит, пропущено ${validBatch.length} товаров`,
        );
        warehouseSkipped += validBatch.length;
        continue;
      }

      log(`❌ Ошибка API (пачка ${i + 1}/${batches}): ${result.code}`);
      warehouseError += validBatch.length;
    }

    log(
      `🟣 ${wh.name}: ✅ ${warehouseSuccess} обновлено, ⏸️ ${warehouseSkipped} пропущено ODC/CD+, ❌ ${warehouseError} ошибок`,
    );
    totalSuccess += warehouseSuccess;
    totalSkipped += warehouseSkipped;
    totalError += warehouseError;
  }

  log(
    `\n🟣 WB Всего: ✅ ${totalSuccess} обновлено, ⏸️ ${totalSkipped} пропущено ODC/CD+, ❌ ${totalError} ошибок`,
  );
}

async function main() {
  console.log("============================================");
  console.log("🔄 СИНХРОНИЗАЦИЯ ОСТАТКОВ FERON (LOCAL)");
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

  let stocks = [];
  const maxReadRetries = 5;
  for (let attempt = 1; attempt <= maxReadRetries; attempt++) {
    try {
      log(`📊 Шаг 1: Чтение данных из листа "${SHEET_NAME}" (попытка ${attempt}/${maxReadRetries})...`);
      stocks = await readFeronStocksFromSheet(client);
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
      `  - ${s.offer_id} | MSK: ${s.stock_msk} | SMR: ${s.stock_smr} | NSB: ${s.stock_nsb} | chrtId: ${s.chrt_id || "(нет)"}`,
    );
  });

  log(``);
  log(`🟠 Шаг 2: Обновление остатков Ozon...`);
  const ozonPendingChecks = await updateFeronStocksOzon(stocks);

  log(``);
  log(`🟣 Шаг 3: Обновление остатков WB...`);
  await updateFeronStocksWB(stocks);

  if (ozonPendingChecks.length > 0) {
    log(``);
    log(`🟠 Шаг 4: Финальная перепроверка расхождений Ozon после завершения WB...`);
    log(
      `⏳ Дополнительное ожидание ${OZON_POSTCHECK_RETRY_DELAY_MS / 1000} сек перед финальным Ozon post-check...`,
    );
    await new Promise((resolve) =>
      setTimeout(resolve, OZON_POSTCHECK_RETRY_DELAY_MS),
    );

    for (const pending of ozonPendingChecks) {
      await verifyFeronOzonWarehouse(
        pending.mismatches.map((item) => ({
          offer_id: item.offer_id,
          [pending.warehouse.col]: item.expected,
        })),
        pending.warehouse,
      );
    }
  }

  const endTime = new Date();
  const duration = Math.round((endTime - startTime) / 1000);

  log(``);
  console.log("============================================");
  log(`✅ Синхронизация завершена за ${duration} сек.`);
  console.log("============================================");
}

main().catch((err) => {
  console.error("❌ Ошибка:", err);
  process.exit(1);
});
