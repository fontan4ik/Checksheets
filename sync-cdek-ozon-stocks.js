#!/usr/bin/env node
/*
 * Локальная синхронизация «СДЕК TR» → Ozon FBS/rFBS склад «КГТ СДЭК».
 *
 * Секреты передаются только окружением процесса:
 *   OZON_CLIENT_ID
 *   OZON_API_KEY
 */

const path = require("path");
require("dotenv").config({ path: path.join(__dirname, ".env"), quiet: true });
const axios = require("axios");
const fs = require("fs");
const { google } = require("googleapis");

const SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI";
const SHEET_NAME = "СДЕК TR";
const WAREHOUSE_ID = 1020002321437000;
const WAREHOUSE_NAME = "КГТ СДЭК";
const OZON_API_URL = "https://api-seller.ozon.ru";
const BATCH_SIZE = 100;
const REQUEST_INTERVAL_MS = 120;
const MAX_RETRIES = 3;
const POSTCHECK_DELAY_MS = 30000;
const SERVICE_ACCOUNT_FILE =
  process.env.GOOGLE_APPLICATION_CREDENTIALS ||
  path.join(__dirname, "nomadic-bedrock-485314-b0-d7624dedd83c.json");

function text(value) {
  return String(value ?? "").trim();
}

function normalizedHeader(value) {
  return text(value).toLowerCase().replace(/ё/g, "е");
}

function quoteSheetName(name) {
  return `'${name.replace(/'/g, "''")}'`;
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function numberStock(value) {
  const parsed = Number(String(value ?? "").replace(",", "."));
  if (!Number.isFinite(parsed) || parsed < 0) return 0;
  return Math.trunc(parsed);
}

function parseLegacyOzonCredentials(source) {
  const clientId = source.match(/const clientId\s*=\s*process\.env\.OZON_CLIENT_ID\s*\|\|\s*["']([^"']+)["']/)?.[1];
  const apiKey = source.match(/const apiKey\s*=\s*\n?\s*process\.env\.OZON_API_KEY\s*\|\|\s*["']([^"']+)["']/)?.[1];
  return { clientId: text(clientId), apiKey: text(apiKey) };
}

function legacyOzonCredentials() {
  const legacyPath = path.join(__dirname, "ozon_fbs_warehouse_api.js");
  try {
    return parseLegacyOzonCredentials(fs.readFileSync(legacyPath, "utf8"));
  } catch {
    return { clientId: "", apiKey: "" };
  }
}

function ozonHeaders() {
  const legacy = legacyOzonCredentials();
  const clientId = text(process.env.OZON_CLIENT_ID) || legacy.clientId;
  const apiKey = text(process.env.OZON_API_KEY) || legacy.apiKey;
  if (!clientId || !apiKey) {
    throw new Error("Не заданы OZON_CLIENT_ID и/или OZON_API_KEY в окружении");
  }
  return {
    "Content-Type": "application/json",
    "Client-Id": clientId,
    "Api-Key": apiKey,
  };
}

function resolveColumns(headers) {
  const byName = new Map();
  headers.forEach((header, index) => {
    const name = normalizedHeader(header);
    if (!name) return;
    const columns = byName.get(name) || [];
    columns.push(index + 1);
    byName.set(name, columns);
  });

  const columns = {};
  for (const name of ["art", "tr"]) {
    const matches = byName.get(name) || [];
    if (matches.length !== 1) {
      throw new Error(`В листе «${SHEET_NAME}» заголовок «${name}» должен быть ровно один; найдено: ${matches.length}`);
    }
    columns[name] = matches[0];
  }
  return columns;
}

async function createSheetsClient() {
  const auth = new google.auth.GoogleAuth({
    keyFile: SERVICE_ACCOUNT_FILE,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  return google.sheets({ version: "v4", auth: await auth.getClient() });
}

async function readCdekStocks(sheets) {
  const response = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: `${quoteSheetName(SHEET_NAME)}!A:ZZ`,
    valueRenderOption: "UNFORMATTED_VALUE",
  });
  const values = response.data.values || [];
  if (values.length < 2) throw new Error(`Лист «${SHEET_NAME}» пуст`);

  const columns = resolveColumns(values[0]);
  const byOfferId = new Map();
  for (const row of values.slice(1)) {
    const offerId = text(row[columns.art - 1]);
    if (!offerId) continue;
    if (byOfferId.has(offerId)) {
      throw new Error(`Повторяющийся art «${offerId}» в листе «${SHEET_NAME}»`);
    }
    byOfferId.set(offerId, numberStock(row[columns.tr - 1]));
  }
  if (!byOfferId.size) throw new Error(`В листе «${SHEET_NAME}» нет art для выгрузки`);

  return [...byOfferId.entries()].map(([offer_id, stock]) => ({ offer_id, stock }));
}

function isRetryable(error) {
  const status = error.response?.status || 0;
  return status === 429 || status >= 500 || !status;
}

async function postWithRetry(url, body, headers, retry = 0, httpClient = axios) {
  try {
    return await httpClient.post(url, body, { headers, timeout: 30000 });
  } catch (error) {
    if (isRetryable(error) && retry < MAX_RETRIES) {
      await sleep(1000 * 2 ** retry);
      return postWithRetry(url, body, headers, retry + 1, httpClient);
    }
    throw error;
  }
}

async function uploadBatch(batch, headers, httpClient = axios) {
  const response = await postWithRetry(
    `${OZON_API_URL}/v2/products/stocks`,
    {
      stocks: batch.map((item) => ({
        offer_id: item.offer_id,
        stock: item.stock,
        warehouse_id: WAREHOUSE_ID,
      })),
    },
    headers,
    0,
    httpClient,
  );
  const results = Array.isArray(response.data?.result) ? response.data.result : [];
  const errors = results.filter((result) => Array.isArray(result.errors) && result.errors.length > 0);
  if (errors.length) {
    const sample = errors[0];
    throw new Error(`Ozon не принял ${errors.length} позиций; пример offer_id «${sample.offer_id || "?"}»`);
  }
  return results.filter((result) => result.updated).length;
}

async function uploadStocks(stocks, headers, httpClient = axios) {
  let updated = 0;
  for (let start = 0; start < stocks.length; start += BATCH_SIZE) {
    const batch = stocks.slice(start, start + BATCH_SIZE);
    updated += await uploadBatch(batch, headers, httpClient);
    if (start + BATCH_SIZE < stocks.length) await sleep(REQUEST_INTERVAL_MS);
  }
  return updated;
}

async function fetchOzonStocks(stocks, headers, httpClient = axios) {
  const result = new Map();
  for (let start = 0; start < stocks.length; start += BATCH_SIZE) {
    const batch = stocks.slice(start, start + BATCH_SIZE);
    const response = await postWithRetry(
      `${OZON_API_URL}/v2/product/info/stocks-by-warehouse/fbs`,
      { offer_id: batch.map((item) => item.offer_id), warehouse_id: WAREHOUSE_ID, limit: 1000 },
      headers,
      0,
      httpClient,
    );
    for (const item of response.data?.products || []) {
      if (String(item.warehouse_id) !== String(WAREHOUSE_ID)) continue;
      result.set(text(item.offer_id), Number(item.free_stock) || 0);
    }
    if (start + BATCH_SIZE < stocks.length) await sleep(REQUEST_INTERVAL_MS);
  }
  return result;
}

async function main() {
  const startedAt = Date.now();
  const headers = ozonHeaders();
  const sheets = await createSheetsClient();
  const stocks = await readCdekStocks(sheets);
  const positive = stocks.filter((item) => item.stock > 0).length;
  const total = stocks.reduce((sum, item) => sum + item.stock, 0);
  if (process.argv.includes("--dry-run")) {
    console.log(JSON.stringify({
      status: "dry-run",
      warehouse: WAREHOUSE_NAME,
      warehouseId: WAREHOUSE_ID,
      rows: stocks.length,
      positive,
      total,
    }));
    return;
  }

  const updated = await uploadStocks(stocks, headers);
  await sleep(POSTCHECK_DELAY_MS);
  const actual = await fetchOzonStocks(stocks, headers);
  const mismatches = stocks.filter(
    (item) => (actual.get(item.offer_id) || 0) !== item.stock,
  );

  console.log(JSON.stringify({
    status: mismatches.length ? "partial" : "ok",
    warehouse: WAREHOUSE_NAME,
    warehouseId: WAREHOUSE_ID,
    rows: stocks.length,
    positive,
    total,
    updated,
    mismatches: mismatches.length,
    durationSec: Math.round((Date.now() - startedAt) / 1000),
  }));
  if (mismatches.length) process.exitCode = 2;
}

if (require.main === module) {
  main().catch((error) => {
    console.error(`CDEK → Ozon stock sync failed: HTTP ${error.response?.status || 0} ${error.message}`);
    process.exit(1);
  });
}

module.exports = {
  numberStock,
  fetchOzonStocks,
  legacyOzonCredentials,
  parseLegacyOzonCredentials,
  postWithRetry,
  readCdekStocks,
  resolveColumns,
  uploadBatch,
  uploadStocks,
};
