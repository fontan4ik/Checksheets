#!/usr/bin/env node

/*
 * Локальная трансляция остатков RS из StreamSupps в Ozon и Wildberries.
 *
 * Получение сырого остатка RS (колонка «RS SMR») остаётся в
 * rs_sync_local.py. Этот скрипт переносит marketplace-часть
 * «Синхронизация остатков RS.js» по образцу sync-feron-stocks.js:
 * он читает рассчитанные колонки «РЕЗЕРВ», «РУССКИЙ СВЕТ МОСКВА» и
 * «WB ВОЛЬТМИР ИТОГ» и выгружает их на фиксированные склады RS.
 */

const path = require("path");
const fs = require("fs");
const { google } = require("googleapis");
const axios = require("axios");
require("dotenv").config({ path: path.join(__dirname, ".env"), quiet: true });

const {
  sendTelegramAlert,
  sendFbsMultiWarehouseReport,
} = require("./telegram_notifier");
const { createWbStockAudit } = require("./wb_stock_audit");
const {
  STREAM_SUPPS_HEADERS,
  normalizeStreamSuppsHeader,
  resolveStreamSuppsColumns,
} = require("./stream_supps_schema");

const SPREADSHEET_ID = process.env.CHECKSHEETS_SPREADSHEET_ID ||
  "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI";
const SHEET_NAME = "StreamSupps";

const RS_OZON_WAREHOUSE_ID = 1020005005049870;
const RS_OZON_MOSCOW_WAREHOUSE_ID = 1020005030719640;
const RS_WB_WAREHOUSE_ID = 798761;

const RS_COLUMNS = {
  offer_id: STREAM_SUPPS_HEADERS.offerId,
  brand: STREAM_SUPPS_HEADERS.brand,
  chrt_id: STREAM_SUPPS_HEADERS.chrtId,
  stock: STREAM_SUPPS_HEADERS.reserve,
  // В StreamSupps есть legacy-дубликат этого заголовка в AE; X — заполненная
  // формулами колонка, поэтому выбираем её явно как первое вхождение.
  stock_moscow: { header: "РУССКИЙ СВЕТ МОСКВА", occurrence: 1 },
  wb_stock: STREAM_SUPPS_HEADERS.wbVoltmirTotal,
};

const OZON_API_URL = "https://api-seller.ozon.ru";
const WB_API_URL = "https://marketplace-api.wildberries.ru";
const OZON_RPS = 10;
const configuredWbRps = Number(process.env.RS_WB_RPS || 2);
const WB_RPS = Number.isFinite(configuredWbRps) ? Math.max(0.1, configuredWbRps) : 2;
const BATCH_SIZE_OZON = 100;
const BATCH_SIZE_WB = 200;
const MAX_RETRIES = 3;
const OZON_BASE_DELAY_MS = 1000;
const WB_BASE_DELAY_MS = 3000;
const configuredPostcheckDelay = Number(process.env.RS_OZON_POSTCHECK_DELAY_MS || 30000);
const configuredPostcheckRetryDelay = Number(process.env.RS_OZON_POSTCHECK_RETRY_DELAY_MS || 60000);
const POSTCHECK_DELAY_MS = Number.isFinite(configuredPostcheckDelay) ? Math.max(0, configuredPostcheckDelay) : 30000;
const POSTCHECK_RETRY_DELAY_MS = Number.isFinite(configuredPostcheckRetryDelay) ? Math.max(0, configuredPostcheckRetryDelay) : 60000;

function text(value) {
  return String(value ?? "").trim();
}

function columnLetter(column) {
  let value = Number(column);
  let result = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function log(message) {
  const now = new Date();
  const time = now.toLocaleTimeString("ru-RU", { hour12: false });
  const millis = String(now.getMilliseconds()).padStart(3, "0");
  console.log(`${time}.${millis} ${message}`);
}

function normalizeMarketplaceStock(value, brand) {
  const stock = Math.trunc(Number(value));
  if (!Number.isFinite(stock) || stock < 0) return 0;
  const isArlight = normalizeStreamSuppsHeader(brand) === "arlight";
  return stock === 1 && !isArlight ? 0 : stock;
}

function normalizeChrtId(value) {
  const raw = text(value).replace(/\u00a0/g, "").replace(/\s+/g, "").replace(/,/g, ".");
  if (!raw || !/^\d+(?:\.\d+)?$/.test(raw)) return null;
  const id = Math.trunc(Number(raw));
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

function resolveColumns(headers) {
  const result = resolveStreamSuppsColumns(headers, RS_COLUMNS, SHEET_NAME);
  Object.entries(result).forEach(([field, column]) => {
    log(`🔍 Схема RS: ${field} → ${columnLetter(column)}:${headers[column - 1]}`);
  });
  return result;
}

function serviceAccountFile() {
  return process.env.GOOGLE_APPLICATION_CREDENTIALS ||
    path.join(__dirname, "nomadic-bedrock-485314-b0-d7624dedd83c.json");
}

async function createSheetsClient() {
  const auth = new google.auth.GoogleAuth({
    keyFile: serviceAccountFile(),
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  const client = await auth.getClient();
  return google.sheets({ version: "v4", auth: client });
}

async function readRsStocksFromSheet(sheets) {
  const headerResponse = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: `${SHEET_NAME}!1:1`,
    valueRenderOption: "UNFORMATTED_VALUE",
  });
  const headers = headerResponse.data.values?.[0] || [];
  if (!headers.length) throw new Error(`Лист «${SHEET_NAME}» пуст или не найден`);

  const columns = resolveColumns(headers);
  const maxColumn = Math.max(...Object.values(columns));
  const response = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: `${SHEET_NAME}!A:${columnLetter(maxColumn)}`,
    majorDimension: "ROWS",
    valueRenderOption: "UNFORMATTED_VALUE",
  });
  const rows = response.data.values || [];
  const stocks = [];

  for (const row of rows.slice(1)) {
    const offerId = text(row[columns.offer_id - 1]);
    if (!offerId) continue;

    const brand = text(row[columns.brand - 1]);
    const originalStock = Math.max(0, Math.trunc(Number(row[columns.stock - 1]) || 0));
    const originalMoscowStock = Math.max(0, Math.trunc(Number(row[columns.stock_moscow - 1]) || 0));
    const originalWbStock = Math.max(0, Math.trunc(Number(row[columns.wb_stock - 1]) || 0));
    stocks.push({
      offer_id: offerId,
      brand,
      chrt_id: row[columns.chrt_id - 1],
      stock: normalizeMarketplaceStock(originalStock, brand),
      stock_moscow: normalizeMarketplaceStock(originalMoscowStock, brand),
      wb_stock: normalizeMarketplaceStock(originalWbStock, brand),
      original_stock: originalStock,
      original_moscow_stock: originalMoscowStock,
      original_wb_stock: originalWbStock,
    });
  }

  stocks.snapshotReadAt = new Date().toISOString();
  stocks.wbSourceColumns = {
    wb_stock: `${columnLetter(columns.wb_stock)}:${headers[columns.wb_stock - 1] || "WB ВОЛЬТМИР ИТОГ"}`,
  };
  log(`📊 Прочитано ${stocks.length} товаров из листа «${SHEET_NAME}»`);
  log(`   Остаток 1 обнулён: ${stocks.filter((item) => item.original_stock === 1 && normalizeStreamSuppsHeader(item.brand) !== "arlight").length}`);
  log(`   RS Москва с остатком > 0: ${stocks.filter((item) => item.stock_moscow > 0).length}`);
  log(`   Arlight с остатком 1 сохранён: ${stocks.filter((item) => item.original_stock === 1 && normalizeStreamSuppsHeader(item.brand) === "arlight").length}`);
  log(`   С chrtId: ${stocks.filter((item) => normalizeChrtId(item.chrt_id)).length}`);
  log(`🧾 WB snapshot: readAt=${stocks.snapshotReadAt}, sources=${JSON.stringify(stocks.wbSourceColumns)}`);
  return stocks;
}

function ozonHeaders() {
  const clientId = text(process.env.OZON_CLIENT_ID) || "142355";
  const apiKey = text(process.env.OZON_API_KEY) || "fe539630-170b-4b48-b222-8ba092907a63";
  return { "Content-Type": "application/json", "Client-Id": clientId, "Api-Key": apiKey };
}

function wbToken() {
  const tokenFile = process.env.WB_API_TOKEN_FILE ||
    path.join(process.env.HOME || "/Users/vladimirgrebennikov", "AI agents", "secrets", "wb_api_token");
  const configured = text(process.env.WB_API_TOKEN);
  const raw = configured || (fs.existsSync(tokenFile) ? fs.readFileSync(tokenFile, "utf8").trim() : "");
  if (!raw) throw new Error(`WB API token не найден: задайте WB_API_TOKEN или WB_API_TOKEN_FILE (${tokenFile})`);
  return raw.toLowerCase().startsWith("bearer ") ? raw : `Bearer ${raw}`;
}

function wbHeaders() {
  return { Authorization: wbToken(), "Content-Type": "application/json" };
}

function isRetryable(error) {
  const code = error?.response?.status;
  return !code || code === 408 || code === 425 || code === 429 || code >= 500;
}

async function rateLimit(lastRequestAt, rps) {
  const interval = 1000 / rps;
  const wait = interval - (Date.now() - lastRequestAt);
  if (wait > 0) await sleep(wait);
  return Date.now();
}

async function sendOzonStocksBatch(batch, warehouseId, retry = 0) {
  try {
    const response = await axios.post(
      `${OZON_API_URL}/v2/products/stocks`,
      { stocks: batch.map((item) => ({ offer_id: item.offer_id, stock: item.stock, warehouse_id: warehouseId })) },
      { headers: ozonHeaders(), timeout: 30000 },
    );
    return { ok: true, code: response.status, data: response.data };
  } catch (error) {
    if (isRetryable(error) && retry < MAX_RETRIES) {
      const delay = OZON_BASE_DELAY_MS * 2 ** retry;
      log(`⏳ Ozon ${error.response?.status || "transport"}: retry ${retry + 1}/${MAX_RETRIES} через ${delay / 1000} сек.`);
      await sleep(delay);
      return sendOzonStocksBatch(batch, warehouseId, retry + 1);
    }
    return {
      ok: false,
      code: error.response?.status || 0,
      text: error.response?.data ? JSON.stringify(error.response.data) : error.message,
    };
  }
}

async function updateRsStocksOzon(
  stocks,
  { warehouseId = RS_OZON_WAREHOUSE_ID, stockField = "stock", label = "Ozon RS" } = {},
) {
  const valid = stocks.filter((item) => item.offer_id);
  const batches = Math.ceil(valid.length / BATCH_SIZE_OZON);
  let lastRequestAt = Date.now() - 1000 / OZON_RPS;
  let successCount = 0;
  let errorCount = 0;

  log(`🟠 ${label}: ${valid.length} товаров, склад ${warehouseId}`);
  for (let index = 0; index < batches; index += 1) {
    lastRequestAt = await rateLimit(lastRequestAt, OZON_RPS);
    const batch = valid.slice(index * BATCH_SIZE_OZON, (index + 1) * BATCH_SIZE_OZON)
      .map((item) => ({ ...item, stock: item[stockField] }));
    const result = await sendOzonStocksBatch(batch, warehouseId);
    if (!result.ok) {
      errorCount += batch.length;
      log(`❌ ${label}: ошибка пачки ${index + 1}/${batches}: ${result.code} ${result.text || ""}`);
      continue;
    }

    const items = Array.isArray(result.data?.result) ? result.data.result : [];
    if (!items.length) {
      successCount += batch.length;
    } else {
      for (const item of items) {
        const hasTooManyRequests = (item.errors || []).some((error) => error.code === "TOO_MANY_REQUESTS");
        if (item.updated || hasTooManyRequests) successCount += 1;
        else errorCount += 1;
      }
    }
    log(`✅ ${label}: пачка ${index + 1}/${batches} обработана (${batch.length} товаров)`);
  }
  log(`🟠 ${label}: ✅ ${successCount} обновлено, ❌ ${errorCount} ошибок`);
  return { successCount, errorCount };
}

async function fetchOzonStocksByOfferIds(offerIds, warehouseId, retry = 0) {
  const result = new Map();
  try {
    for (let offset = 0; offset < offerIds.length; offset += 500) {
      const response = await axios.post(
        `${OZON_API_URL}/v2/product/info/stocks-by-warehouse/fbs`,
        { offer_id: offerIds.slice(offset, offset + 500), warehouse_id: warehouseId, limit: 1000 },
        { headers: ozonHeaders(), timeout: 30000 },
      );
      for (const item of Array.isArray(response.data?.products) ? response.data.products : []) {
        if (String(item.warehouse_id) !== String(warehouseId)) continue;
        result.set(String(item.offer_id), (Number(item.present) || 0) + (Number(item.reserved) || 0));
      }
    }
    return result;
  } catch (error) {
    if (isRetryable(error) && retry < MAX_RETRIES) {
      const delay = OZON_BASE_DELAY_MS * 2 ** retry;
      log(`⏳ Ozon post-check ${error.response?.status || "transport"}: retry ${retry + 1}/${MAX_RETRIES} через ${delay / 1000} сек.`);
      await sleep(delay);
      return fetchOzonStocksByOfferIds(offerIds, warehouseId, retry + 1);
    }
    throw error;
  }
}

async function verifyRsOzonStocks(
  stocks,
  { warehouseId = RS_OZON_WAREHOUSE_ID, stockField = "stock", label = "RS" } = {},
) {
  const expected = stocks
    .filter((item) => item.offer_id)
    .map((item) => ({ ...item, stock: item[stockField] }));
  if (!expected.length) return { mismatches: [], stats: { sheetPositiveCount: 0, marketplacePositiveCount: 0, marketplaceTotalPieces: 0 } };
  const actual = await fetchOzonStocksByOfferIds(expected.map((item) => item.offer_id), warehouseId);
  const mismatches = [];
  let marketplacePositiveCount = 0;
  let marketplaceTotalPieces = 0;
  for (const item of expected) {
    const actualStock = actual.get(item.offer_id) || 0;
    if (actualStock > 0) {
      marketplacePositiveCount += 1;
      marketplaceTotalPieces += actualStock;
    }
    if (actualStock !== item.stock) {
      mismatches.push({ offer_id: item.offer_id, expected: item.stock, actual: actualStock });
    }
  }
  const stats = {
    sheetPositiveCount: expected.filter((item) => item.stock > 0).length,
    marketplacePositiveCount,
    marketplaceTotalPieces,
  };
  if (!mismatches.length) {
    log(`✅ Ozon post-check ${label}: расхождений не найдено (${marketplacePositiveCount} SKU, ${marketplaceTotalPieces} шт.)`);
  } else {
    log(`⚠️ Ozon post-check ${label}: найдено ${mismatches.length} расхождений`);
    mismatches.slice(0, 10).forEach((item) => log(`   - ${item.offer_id}: sheet=${item.expected}, ozon=${item.actual}`));
  }
  return { mismatches, stats };
}

function isWbCargoRestrictionError(responseText) {
  const source = text(responseText);
  try {
    const parsed = JSON.parse(source);
    const errors = Array.isArray(parsed) ? parsed : parsed.errors || parsed.error || [];
    return errors.some((error) => {
      const value = `${error.code || error.error || ""} ${error.message || error.detail || ""}`;
      return /CargoWarehouseRestriction|SGTKGTPlus|ODC|CD\+/.test(value);
    });
  } catch {
    return /CargoWarehouseRestriction|SGTKGTPlus|ODC|CD\+/.test(source);
  }
}

async function sendRsWbStocksBatch(batch, retry = 0) {
  try {
    const response = await axios.put(
      `${WB_API_URL}/api/v3/stocks/${RS_WB_WAREHOUSE_ID}`,
      { stocks: batch.map((item) => ({ chrtId: item.chrtId, amount: item.amount })) },
      { headers: wbHeaders(), timeout: 30000 },
    );
    return { ok: response.status === 200 || response.status === 204, code: response.status, text: JSON.stringify(response.data || {}) };
  } catch (error) {
    const code = error.response?.status || 0;
    const responseText = error.response?.data ? JSON.stringify(error.response.data) : error.message;
    if (isRetryable(error) && retry < MAX_RETRIES) {
      const delay = WB_BASE_DELAY_MS * 2 ** retry;
      log(`⏳ WB ${code || "transport"}: retry ${retry + 1}/${MAX_RETRIES} через ${delay / 1000} сек.`);
      await sleep(delay);
      return sendRsWbStocksBatch(batch, retry + 1);
    }
    return {
      ok: false,
      code,
      text: code === 429 ? "MAX_RETRIES_EXCEEDED" : responseText,
      cargoRestriction: code === 409 && isWbCargoRestrictionError(responseText),
    };
  }
}

async function processRsWbConflictIndividually(batch, audit, batchIndex) {
  let successCount = 0;
  let skippedCount = 0;
  let errorCount = 0;
  const itemsByChrtId = new Map(batch.map((item) => [item.chrtId, item]));
  for (let index = 0; index < batch.length; index += 1) {
    if (index > 0 && index % 5 === 0) await sleep(3000);
    const item = batch[index];
    const result = await sendRsWbStocksBatch([item]);
    const auditItem = itemsByChrtId.get(item.chrtId);
    const common = { warehouseId: RS_WB_WAREHOUSE_ID, batchIndex, offerId: auditItem?.offerId, chrtId: item.chrtId, amount: item.amount };
    if (result.ok) {
      successCount += 1;
      audit.recordItemResult({ ...common, status: "success", code: result.code });
    } else if (result.cargoRestriction) {
      skippedCount += 1;
      audit.recordItemResult({ ...common, status: "cargo_restriction", code: result.code });
      log(`⏸️ WB RS: пропущен ODC/CD+ chrtId=${item.chrtId}, amount=${item.amount}`);
    } else if (result.text === "MAX_RETRIES_EXCEEDED") {
      skippedCount += 1;
      audit.recordItemResult({ ...common, status: "rate_limited", code: result.code });
    } else {
      errorCount += 1;
      audit.recordItemResult({ ...common, status: "error", code: result.code });
      log(`❌ WB RS: ошибка chrtId=${item.chrtId}, code=${result.code}`);
    }
  }
  return { successCount, skippedCount, errorCount };
}

async function updateRsStocksWb(stocks) {
  const valid = stocks.filter((item) => normalizeChrtId(item.chrt_id));
  if (!valid.length) {
    log("⚠️ WB RS: нет товаров с валидным chrtId");
    return { activeSku: 0, successCount: 0, skippedCount: 0, errorCount: 0 };
  }

  const audit = createWbStockAudit({
    scriptName: "sync-rs-stocks",
    sheetName: SHEET_NAME,
    sourceReadAt: stocks.snapshotReadAt,
  });
  log(`🧾 WB payload audit: ${audit.filePath} (runId=${audit.runId})`);
  let lastRequestAt = Date.now() - 1000 / WB_RPS;
  let successCount = 0;
  let skippedCount = 0;
  let errorCount = 0;
  const batches = Math.ceil(valid.length / BATCH_SIZE_WB);

  for (let index = 0; index < batches; index += 1) {
    lastRequestAt = await rateLimit(lastRequestAt, WB_RPS);
    const sourceBatch = valid.slice(index * BATCH_SIZE_WB, (index + 1) * BATCH_SIZE_WB);
    const prepared = sourceBatch.map((item) => ({
      offerId: item.offer_id,
      chrtId: normalizeChrtId(item.chrt_id),
      amount: item.wb_stock,
    }));
    const payload = audit.recordPayload({
      warehouseId: RS_WB_WAREHOUSE_ID,
      warehouseName: "ВольтМир (RS)",
      sourceColumn: stocks.wbSourceColumns?.wb_stock || "AC:WB ВОЛЬТМИР ИТОГ",
      batchIndex: index + 1,
      totalBatches: batches,
      items: prepared,
    });
    if (payload.shouldWarn) log(`⚠️ WB STALE SNAPSHOT: снимку уже ${payload.ageSeconds} сек.`);

    const requestBatch = prepared.map((item) => ({
      offerId: item.offerId,
      chrtId: item.chrtId,
      amount: item.amount,
    }));
    const result = await sendRsWbStocksBatch(requestBatch);
    if (result.ok) {
      successCount += requestBatch.length;
      audit.recordBatchResult({ warehouseId: RS_WB_WAREHOUSE_ID, batchIndex: index + 1, checksum: payload.checksum, status: "success", code: result.code, successCount: requestBatch.length });
      log(`✅ WB RS: пачка ${index + 1}/${batches} отправлена (${requestBatch.length} товаров)`);
      continue;
    }
    if (result.cargoRestriction) {
      log(`⚠️ WB RS 409 ODC/CD+ (пачка ${index + 1}/${batches}): дробление`);
      const fallback = await processRsWbConflictIndividually(requestBatch, audit, index + 1);
      successCount += fallback.successCount;
      skippedCount += fallback.skippedCount;
      errorCount += fallback.errorCount;
      audit.recordBatchResult({ warehouseId: RS_WB_WAREHOUSE_ID, batchIndex: index + 1, checksum: payload.checksum, status: "individual_fallback", code: result.code, ...fallback });
      continue;
    }
    if (result.text === "MAX_RETRIES_EXCEEDED") {
      skippedCount += requestBatch.length;
      audit.recordBatchResult({ warehouseId: RS_WB_WAREHOUSE_ID, batchIndex: index + 1, checksum: payload.checksum, status: "rate_limited", code: result.code, skippedCount: requestBatch.length });
      continue;
    }
    errorCount += requestBatch.length;
    audit.recordBatchResult({ warehouseId: RS_WB_WAREHOUSE_ID, batchIndex: index + 1, checksum: payload.checksum, status: "error", code: result.code, errorCount: requestBatch.length });
    log(`❌ WB RS: ошибка пачки ${index + 1}/${batches}: ${result.code} ${result.text || ""}`);
  }

  log(`🟣 WB RS: ✅ ${successCount} обновлено, ⏸️ ${skippedCount} пропущено, ❌ ${errorCount} ошибок`);
  return { activeSku: valid.filter((item) => item.wb_stock > 0).length, successCount, skippedCount, errorCount };
}

async function main({ dryRun = false, skipPostcheck = false } = {}) {
  const startedAt = Date.now();
  log("============================================");
  log("🔄 СИНХРОНИЗАЦИЯ ОСТАТКОВ RS (LOCAL)");
  log("============================================");

  const sheets = await createSheetsClient();
  let stocks;
  for (let attempt = 1; attempt <= 5; attempt += 1) {
    try {
      log(`📊 Чтение листа «${SHEET_NAME}» (попытка ${attempt}/5)...`);
      stocks = await readRsStocksFromSheet(sheets);
      break;
    } catch (error) {
      if (attempt === 5) throw error;
      log(`⚠️ Ошибка чтения Google Sheets: ${error.message || error}`);
      await sleep(5000 * attempt);
    }
  }
  if (!stocks?.length) throw new Error(`В листе «${SHEET_NAME}» не найдено товаров RS для синхронизации`);
  stocks.slice(0, 5).forEach((item) => log(`  - ${item.offer_id} | Ozon=${item.stock} | WB=${item.wb_stock} | chrtId=${item.chrt_id || "(нет)"}`));
  if (dryRun) {
    log("✅ Dry-run: записи в Ozon/WB не выполнялись");
    return;
  }

  const ozonStats = await updateRsStocksOzon(stocks);
  const ozonMoscowStats = await updateRsStocksOzon(stocks, {
    warehouseId: RS_OZON_MOSCOW_WAREHOUSE_ID,
    stockField: "stock_moscow",
    label: "Ozon RS Москва",
  });
  const wbStats = await updateRsStocksWb(stocks);
  let postcheck = { mismatches: [], stats: { sheetPositiveCount: stocks.filter((item) => item.stock > 0).length, marketplacePositiveCount: null, marketplaceTotalPieces: null } };
  if (!skipPostcheck) {
    log(`⏳ Ожидание ${POSTCHECK_DELAY_MS / 1000} сек перед Ozon post-check...`);
    await sleep(POSTCHECK_DELAY_MS);
    postcheck = await verifyRsOzonStocks(stocks);
    if (postcheck.mismatches.length) {
      log(`⏳ Ожидание ${POSTCHECK_RETRY_DELAY_MS / 1000} сек перед повторной проверкой...`);
      await sleep(POSTCHECK_RETRY_DELAY_MS);
      await verifyRsOzonStocks(stocks);
    }
  }

  const durationSec = Math.round((Date.now() - startedAt) / 1000);
  try {
    await sendFbsMultiWarehouseReport({
      supplier: "RS",
      marketplace: "Ozon",
      totalSku: stocks.length,
      warehouses: [
        { warehouseName: "RS (резерв)", activeSku: postcheck.stats.sheetPositiveCount, marketplaceStockSku: postcheck.stats.marketplacePositiveCount, marketplaceTotalPieces: postcheck.stats.marketplaceTotalPieces },
        { warehouseName: "РУССКИЙ СВЕТ МОСКВА", activeSku: stocks.filter((item) => item.stock_moscow > 0).length, marketplaceStockSku: null, marketplaceTotalPieces: null },
      ],
      durationSec,
    });
    await sendFbsMultiWarehouseReport({
      supplier: "RS",
      marketplace: "ВБ",
      totalSku: stocks.length,
      warehouses: [{ warehouseName: "ВольтМир (RS)", activeSku: wbStats.activeSku, marketplaceStockSku: null, marketplaceTotalPieces: null }],
      durationSec,
    });
  } catch (error) {
    log(`⚠️ Не удалось поставить сводку RS в Telegram: ${error.message || error}`);
  }
  log(`✅ RS local sync завершён за ${durationSec} сек. Ozon RS: ${ozonStats.successCount} ok, Ozon Москва: ${ozonMoscowStats.successCount} ok, WB: ${wbStats.successCount} ok`);
  return { stocks, ozonStats, ozonMoscowStats, wbStats, postcheck, durationSec };
}

if (require.main === module) {
  const dryRun = process.argv.includes("--dry-run");
  const skipPostcheck = process.argv.includes("--skip-postcheck");
  main({ dryRun, skipPostcheck }).catch(async (error) => {
    console.error(`❌ Ошибка RS local sync: ${error.stack || error}`);
    try {
      await sendTelegramAlert("sync_rs_stocks", error.message || String(error), error.stack || null);
    } catch (telegramError) {
      console.error(`Не удалось отправить Telegram алерт: ${telegramError.message || telegramError}`);
    }
    process.exit(1);
  });
}

module.exports = {
  BATCH_SIZE_OZON,
  BATCH_SIZE_WB,
  RS_OZON_WAREHOUSE_ID,
  RS_OZON_MOSCOW_WAREHOUSE_ID,
  RS_WB_WAREHOUSE_ID,
  normalizeMarketplaceStock,
  normalizeChrtId,
  resolveColumns,
  isWbCargoRestrictionError,
  readRsStocksFromSheet,
  updateRsStocksOzon,
  updateRsStocksWb,
  verifyRsOzonStocks,
  sendRsWbStocksBatch,
  readRSStocksFromSheet: readRsStocksFromSheet,
  updateRSStocksOzon: updateRsStocksOzon,
  updateRSStocksWB: updateRsStocksWb,
  syncRSStocks: main,
  main,
};
