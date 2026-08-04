const { google } = require("googleapis");
const axios = require("axios");
const path = require("path");

const SHEET_NAME = "ETM TR";
const SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI";

const ETM_TR_OZON_WAREHOUSE = 1020005000689690;
const ETM_TR_WB_WAREHOUSE = 798761;

const ETM_TR_COLS = {
  ARTICUL: 1,
  CHRLID: 17,
};

const RPS = 10;
const WB_RPS = 0.12;

const OZON_BASE_DELAY = 1000;
const WB_BASE_DELAY = 3000;
const OZON_MAX_RETRIES = 3;
const WB_MAX_RETRIES = 3;

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

async function readETMItemsFromSheet(auth) {
  const sheets = google.sheets({ version: "v4", auth });

  const spreadsheet = await sheets.spreadsheets.get({
    spreadsheetId: SPREADSHEET_ID,
  });
  const sheet = spreadsheet.data.sheets.find(
    (s) => s.properties.title === SHEET_NAME,
  );

  if (!sheet) {
    throw new Error(`Лист "${SHEET_NAME}" не найден`);
  }

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
  const maxCol = Math.max(colArticul, colChrlid);

  const dataResp = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: `${SHEET_NAME}!A:${String.fromCharCode(64 + maxCol)}`,
    majorDimension: "ROWS",
  });

  const allRows = dataResp.data.values || [];
  const data = allRows.slice(1);
  const items = [];

  for (const row of data) {
    const offerId = row[colArticul - 1];
    const chrlid = row[colChrlid - 1];

    if (!offerId && !chrlid) continue;

    items.push({
      offer_id: offerId ? String(offerId) : "",
      chrlid: chrlid ? String(chrlid) : "",
      stock: 0,
      wb_stock: 0,
    });
  }

  log(`📊 Прочитано ${items.length} ETM товаров для зануления`);
  log(`   С offer_id: ${items.filter((item) => item.offer_id).length}`);
  log(`   С chrlid: ${items.filter((item) => item.chrlid).length}`);

  return items;
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

async function updateETMStocksOzonWithRetry(
  batch,
  warehouseId,
  retryCount = 0,
) {
  const body = {
    stocks: batch.map((item) => ({
      offer_id: String(item.offer_id),
      stock: 0,
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
        `⏳ Ozon 429: ожидание ${delay / 1000} сек перед retry ${retryCount + 1}/${OZON_MAX_RETRIES}...`,
      );
      await new Promise((r) => setTimeout(r, delay));
      return updateETMStocksOzonWithRetry(batch, warehouseId, retryCount + 1);
    }

    if (
      isTransportError(code || 0, errorText) &&
      retryCount < OZON_MAX_RETRIES
    ) {
      const delay = OZON_BASE_DELAY * Math.pow(2, retryCount);
      log(
        `⏳ Ozon transport error: ожидание ${delay / 1000} сек перед retry ${retryCount + 1}/${OZON_MAX_RETRIES}...`,
      );
      await new Promise((r) => setTimeout(r, delay));
      return updateETMStocksOzonWithRetry(batch, warehouseId, retryCount + 1);
    }

    return { ok: false, error: err.response?.data || err.message, code };
  }
}

async function updateETMStocksOzon(items) {
  log(
    `🟠 Зануление остатков Ozon (склад: ЭТМ САМАРА, ID: ${ETM_TR_OZON_WAREHOUSE})...`,
  );

  const validItems = items.filter((item) => item.offer_id);
  if (validItems.length === 0) {
    log("⚠️ Нет товаров с offer_id");
    return;
  }

  const batchSize = 100;
  const batches = Math.ceil(validItems.length / batchSize);
  let successCount = 0;
  let errorCount = 0;

  for (let i = 0; i < batches; i++) {
    lastRequestTime = await rateLimitRPS(lastRequestTime, RPS);

    const batch = validItems.slice(i * batchSize, (i + 1) * batchSize);
    const result = await updateETMStocksOzonWithRetry(
      batch,
      ETM_TR_OZON_WAREHOUSE,
    );

    if (result.ok && result.data?.result) {
      result.data.result.forEach((row) => {
        if (row.errors && row.errors.length > 0) {
          errorCount++;
          return;
        }
        if (row.updated) {
          successCount++;
        }
      });
      log(`✅ Ozon пачка ${i + 1}/${batches} обработана (${batch.length} товаров)`);
    } else {
      errorCount += batch.length;
      log(
        `❌ Ozon ошибка API (пачка ${i + 1}/${batches}): ${result.code || result.error}`,
      );
    }
  }

  log(`🟠 Ozon: ✅ ${successCount} занулено, ❌ ${errorCount} ошибок`);
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

    return {
      ok: response.status === 200 || response.status === 204,
      code: response.status,
      text: JSON.stringify(response.data || {}),
      cargoRestriction:
        response.status === 409 &&
        isWBCargoRestrictionError(JSON.stringify(response.data || {})),
    };
  } catch (err) {
    const code = err.response?.status || 0;
    const text = err.response?.data
      ? JSON.stringify(err.response.data)
      : err.message;

    if (code === 429 && retryCount < WB_MAX_RETRIES) {
      const delay = WB_BASE_DELAY * Math.pow(2, retryCount);
      log(
        `⏳ WB 429: ожидание ${delay / 1000} сек перед retry ${retryCount + 1}/${WB_MAX_RETRIES}...`,
      );
      await new Promise((r) => setTimeout(r, delay));
      return sendETMStocksBatch(batch, warehouseId, retryCount + 1);
    }

    if (isTransportError(code, text) && retryCount < WB_MAX_RETRIES) {
      const delay = WB_BASE_DELAY * Math.pow(2, retryCount);
      log(
        `⏳ WB transport error: ожидание ${delay / 1000} сек перед retry ${retryCount + 1}/${WB_MAX_RETRIES}...`,
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
      log(`⏸️ ${batchLabel}: пропущен ODC/CD+ chrtId=${item.chrtId}`);
      skippedCount++;
      continue;
    }

    errorCount++;
    log(`❌ ${batchLabel}: ошибка для chrtId=${item.chrtId}, code=${result.code}`);
  }

  log(
    `📊 ${batchLabel}: поштучно ✅ ${successCount}, ⏸️ ${skippedCount}, ❌ ${errorCount}`,
  );

  return { successCount, skippedCount, errorCount };
}

async function updateETMStocksWB(items) {
  log(
    `🟣 Зануление остатков WB FBS (склад: Новосемейкино, ID: ${ETM_TR_WB_WAREHOUSE})...`,
  );

  const validItems = items.filter((item) => item.chrlid);
  if (validItems.length === 0) {
    log("⚠️ Нет товаров с chrlid");
    return;
  }

  const batchSize = 200;
  const batches = Math.ceil(validItems.length / batchSize);

  lastRequestTime = Date.now() - 1000 / WB_RPS;
  let successCount = 0;
  let skippedCount = 0;
  let errorCount = 0;

  for (let i = 0; i < batches; i++) {
    lastRequestTime = await rateLimitRPS(lastRequestTime, WB_RPS);

    const batch = validItems.slice(i * batchSize, (i + 1) * batchSize);
    const validBatch = [];

    for (const item of batch) {
      const idNum = Number(item.chrlid);
      if (Number.isNaN(idNum) || !item.chrlid) {
        errorCount++;
        continue;
      }
      validBatch.push({ chrtId: idNum, amount: 0 });
    }

    if (validBatch.length === 0) continue;

    const result = await sendETMStocksBatch(validBatch, ETM_TR_WB_WAREHOUSE);

    if (result.ok) {
      successCount += validBatch.length;
      log(`✅ WB пачка ${i + 1}/${batches} обработана (${validBatch.length} товаров)`);
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

    errorCount += validBatch.length;
    log(`❌ WB ошибка API (пачка ${i + 1}/${batches}): ${result.code}`);
  }

  log(
    `🟣 WB: ✅ ${successCount} занулено, ⏸️ ${skippedCount} пропущено ODC/CD+, ❌ ${errorCount} ошибок`,
  );
}

async function main() {
  console.log("============================================");
  console.log("🔄 ЗАНУЛЕНИЕ ОСТАТКОВ ETM TR");
  console.log("============================================");

  const auth = new google.auth.GoogleAuth({
    keyFile: path.join(
      __dirname,
      "nomadic-bedrock-485314-b0-d7624dedd83c.json",
    ),
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });

  const client = await auth.getClient();
  google.options({ auth: client });

  log(`📊 Чтение ETM идентификаторов из листа "${SHEET_NAME}"...`);
  const items = await readETMItemsFromSheet(client);

  if (items.length === 0) {
    log("❌ Нет данных для зануления");
    return;
  }

  log("🟠 Шаг 1: зануление Ozon...");
  await updateETMStocksOzon(items);

  log("🟣 Шаг 2: зануление WB...");
  // await updateETMStocksWB(items); // Выгрузка на WB временно отключена.

  log("✅ Зануление ETM завершено");
}

main().catch((err) => {
  console.error("❌ Ошибка:", err);
  process.exit(1);
});
