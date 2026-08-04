const { google } = require("googleapis");
const axios = require("axios");
const path = require("path");

const SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI";
const BATCH_SIZE = 1000;
const REQUEST_INTERVAL_MS = 5_000;
const MAX_RETRIES = 3;
let nextRequestAt = 0;

// Охватывает все активные выгрузки FBS: ETM, Feron и Arlight.
const SOURCES = [
  { sheet: "ETM TR", chrtHeader: "chrlid", warehouses: [798761] },
  {
    sheet: "FERON TR",
    chrtHeader: "chrlid",
    warehouses: [1449484, 798761, 1724900, 1860503],
  },
  { sheet: "ARL TR", chrtHeader: "chrlid", warehouses: [1449484] },
];

const wbToken = process.env.WB_API_TOKEN;

function log(message) {
  console.log(`${new Date().toLocaleTimeString("ru-RU", { hour12: false })} ${message}`);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isCargoRestriction(text) {
  return /CargoWarehouseRestriction|SGTKGTPlus|ODC|CD\+/i.test(text || "");
}

async function readChrtIds(sheets, source) {
  const response = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: `'${source.sheet}'`,
    majorDimension: "ROWS",
  });
  const rows = response.data.values || [];
  const headers = (rows[0] || []).map((value) => String(value || "")
    .trim().toLowerCase().replaceAll("ё", "е"));
  const column = headers.indexOf(source.chrtHeader);
  if (column < 0) {
    throw new Error(`${source.sheet}: не найден заголовок '${source.chrtHeader}'.`);
  }
  const ids = new Set();
  for (const row of rows.slice(1)) {
    const id = Number(row[column]);
    if (Number.isSafeInteger(id) && id > 0) ids.add(id);
  }
  log(`${source.sheet}: найдено ${ids.size} уникальных chrtId.`);
  return ids;
}

async function sendBatch(warehouseId, stocks, attempt = 0) {
  const delay = Math.max(0, nextRequestAt - Date.now());
  if (delay) await sleep(delay);
  nextRequestAt = Date.now() + REQUEST_INTERVAL_MS;
  try {
    const response = await axios.put(
      `https://marketplace-api.wildberries.ru/api/v3/stocks/${warehouseId}`,
      { stocks },
      {
        headers: {
          Authorization: wbToken.startsWith("Bearer ") ? wbToken : `Bearer ${wbToken}`,
          "Content-Type": "application/json",
        },
        timeout: 30000,
        validateStatus: () => true,
      },
    );
    const text = JSON.stringify(response.data || {});
    if ((response.status === 200 || response.status === 204)) return { ok: true };
    if (response.status === 429 && attempt < MAX_RETRIES) {
      const delay = 3000 * 2 ** attempt;
      log(`Склад ${warehouseId}: 429, повтор через ${delay / 1000} сек.`);
      await sleep(delay);
      return sendBatch(warehouseId, stocks, attempt + 1);
    }
    return { ok: false, cargoRestriction: response.status === 409 && isCargoRestriction(text), status: response.status, text };
  } catch (error) {
    if (attempt < MAX_RETRIES) {
      const delay = 3000 * 2 ** attempt;
      log(`Склад ${warehouseId}: ошибка сети, повтор через ${delay / 1000} сек.`);
      await sleep(delay);
      return sendBatch(warehouseId, stocks, attempt + 1);
    }
    return { ok: false, status: error.response?.status || 0, text: error.message };
  }
}

async function zeroWarehouse(warehouseId, ids) {
  const stocks = [...ids].map((chrtId) => ({ chrtId, amount: 0 }));
  let zeroed = 0;
  let skipped = 0;
  let failed = 0;

  async function zeroBatch(batch) {
    const result = await sendBatch(warehouseId, batch);
    if (result.ok) {
      zeroed += batch.length;
      return;
    }

    if (result.status === 409 && batch.length > 1) {
      const midpoint = Math.ceil(batch.length / 2);
      await zeroBatch(batch.slice(0, midpoint));
      await zeroBatch(batch.slice(midpoint));
      return;
    }

    if (result.cargoRestriction) skipped += batch.length;
    else failed += batch.length;
    log(`Склад ${warehouseId}: chrtId ${batch[0].chrtId} не обнулен (HTTP ${result.status}).`);
  }

  for (let offset = 0; offset < stocks.length; offset += BATCH_SIZE) {
    if (offset > 0) await sleep(REQUEST_INTERVAL_MS);
    const batch = stocks.slice(offset, offset + BATCH_SIZE);
    await zeroBatch(batch);
    log(`Склад ${warehouseId}: обработано ${Math.min(offset + BATCH_SIZE, stocks.length)}/${stocks.length}.`);
  }

  return { zeroed, skipped, failed, total: stocks.length };
}

async function main() {
  if (!wbToken) throw new Error("Не задана переменная окружения WB_API_TOKEN.");

  const auth = new google.auth.GoogleAuth({
    keyFile: path.join(__dirname, "nomadic-bedrock-485314-b0-d7624dedd83c.json"),
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  const sheets = google.sheets({ version: "v4", auth: await auth.getClient() });
  const warehouseIds = new Map();

  for (const source of SOURCES) {
    const ids = await readChrtIds(sheets, source);
    for (const warehouseId of source.warehouses) {
      const current = warehouseIds.get(warehouseId) || new Set();
      ids.forEach((id) => current.add(id));
      warehouseIds.set(warehouseId, current);
    }
  }

  for (const [warehouseId, ids] of warehouseIds) {
    log(`Начато обнуление FBS склада ${warehouseId}: ${ids.size} товаров.`);
    const result = await zeroWarehouse(warehouseId, ids);
    log(`Склад ${warehouseId}: ✅ ${result.zeroed}, ⏸️ ${result.skipped}, ❌ ${result.failed} из ${result.total}.`);
    if (result.failed > 0) process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(`❌ ${error.message}`);
  process.exitCode = 1;
});
