const { google } = require("googleapis");
const axios = require("axios");
const path = require("path");

const SHEET_NAME = "ETM TR";
const SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI";

const ETM_TR_OZON_WAREHOUSE = 1020005000689690;
const ETM_TR_WB_WAREHOUSE = 1698545;

const ETM_TR_COLS = {
  ARTICUL: 1,
  CHRLID: 17,
  STOCK: 16,
};

const MIN_STOCK_THRESHOLD = 0;

const RPS = 10;
const WB_RPS = 0.12; // ~14 per minute = 1 req per 4.3 sec

const OZON_BASE_DELAY = 1000;
const WB_BASE_DELAY = 3000;
const OZON_MAX_RETRIES = 3;
const WB_MAX_RETRIES = 3; // 14 = 3 retries + 1 original = 4 total

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
  console.log(new Date().toISOString().split("T")[1].slice(0, -1) + " " + msg);
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
  const colStock = findCol("smr", ETM_TR_COLS.STOCK);

  log(
    `🔍 Колонки: Артикул=${colArticul}, chrlid=${colChrlid}, stocks smr=${colStock}`,
  );

  const maxCol = Math.max(colArticul, colChrlid, colStock);

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

    stocks.push({
      offer_id: offerId,
      chrlid: chrlid,
      stock: stock,
      original_stock: originalStock,
    });
  }

  log(`📊 Прочитано ${stocks.length} товаров из листа "${SHEET_NAME}"`);
  log(`   С chrlid: ${stocks.filter((s) => s.chrlid).length}`);

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
    return;
  }

  const batchSize = 100;
  const batches = Math.ceil(validStocks.length / batchSize);

  let successCount = 0;
  let errorCount = 0;

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
          if (isError) errorCount++;
          else successCount++;
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
      validBatch.push({ chrtId: idNum, amount: item.stock });
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

async function main() {
  console.log("============================================");
  console.log("🔄 СИНХРОНИЗАЦИЯ ОСТАТКОВ ETM TR (LOCAL)");
  console.log("============================================");

  const startTime = new Date();

  const auth = new google.auth.GoogleAuth({
    keyFile: path.join(
      __dirname,
      "nomadic-bedrock-485314-b0-ff60180040ed.json",
    ),
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });

  const client = await auth.getClient();
  google.options({ auth: client });

  log(`📊 Шаг 1: Чтение данных из листа "${SHEET_NAME}"...`);
  const stocks = await readETMStocksFromSheet(client);

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
  await updateETMStocksOzon(stocks);

  log("");
  log("🟣 Шаг 3: Обновление остатков WB (Новосемейкино)...");
  await updateETMStocksWB(stocks);

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
