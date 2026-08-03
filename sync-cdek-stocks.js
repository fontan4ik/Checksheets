#!/usr/bin/env node
/*
 * Локальная синхронизация CDEK Fulfillment → «СДЕК TR».
 *
 * Секреты передаются только в окружении процесса:
 *   CDEK_FULFILLMENT_LOGIN
 *   CDEK_FULFILLMENT_API_KEY
 *
 * Запись в Google Sheets выполняется сервисным аккаунтом из
 * GOOGLE_APPLICATION_CREDENTIALS либо стандартного файла проекта.
 */

const path = require("path");
require("dotenv").config({ path: path.join(__dirname, ".env"), quiet: true });
const axios = require("axios");
const { google } = require("googleapis");
const https = require("https");
const os = require("os");

const SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI";
const SHEET_NAME = "СДЕК TR";
const CDEK_BASE_URL = "https://cdek.orderadmin.ru/api";
// OrderAdmin advertises a limit of 3 requests. Keep a conservative one-request-per-second
// pace because this tenant returns HTTP 500, rather than 429, when the limit is exceeded.
const REQUEST_DELAY_MS = Math.max(334, Number(process.env.CDEK_REQUEST_DELAY_MS || 1000));
const MAX_RETRIES = 3;
const INCLUDED_STATES = new Set(["normal"]);
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

function columnToLetter(column) {
  let value = Number(column);
  let result = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

function resolveColumns(headers) {
  const columnsByHeader = new Map();
  headers.forEach((header, index) => {
    const name = normalizedHeader(header);
    if (!name) return;
    const columns = columnsByHeader.get(name) || [];
    columns.push(index + 1);
    columnsByHeader.set(name, columns);
  });

  const result = {};
  for (const name of ["art", "model", "stocks"]) {
    const columns = columnsByHeader.get(name) || [];
    if (columns.length !== 1) {
      throw new Error(`В листе «${SHEET_NAME}» заголовок «${name}» должен быть ровно один; найдено: ${columns.length}`);
    }
    result[name] = columns[0];
  }
  return result;
}

function collectUniqueModels(rows, modelColumn) {
  const unique = new Set();
  for (const row of rows) {
    const model = text(row[modelColumn - 1]);
    if (model) unique.add(model);
  }
  if (!unique.size) throw new Error("В колонке model нет значений для CDEK-запроса");
  return [...unique];
}

function cdekHeaders() {
  const configuredLogin = text(process.env.CDEK_FULFILLMENT_LOGIN);
  const apiKey = text(process.env.CDEK_FULFILLMENT_API_KEY);
  if (!configuredLogin || !apiKey) {
    throw new Error("Не заданы CDEK_FULFILLMENT_LOGIN и/или CDEK_FULFILLMENT_API_KEY в окружении");
  }
  const login = configuredLogin.includes("@")
    ? configuredLogin
    : `${configuredLogin.toLowerCase()}@ff.cdek.ru`;
  return {
    Accept: "application/json",
    Authorization: `Basic ${Buffer.from(`${login}:${apiKey}`, "utf8").toString("base64")}`,
  };
}

function getCdekBypassInterface(
  networkInterfaces = os.networkInterfaces(),
  preferred = text(process.env.CHECKSHEETS_BYPASS_INTERFACE),
) {
  const candidates = [...new Set([preferred, "en1", "en0"].filter(Boolean))];
  for (const interfaceName of candidates) {
    const address = (networkInterfaces[interfaceName] || []).find((entry) =>
      (entry.family === "IPv4" || entry.family === 4) && !entry.internal && entry.address,
    );
    if (address) return { interfaceName, sourceIp: address.address };
  }
  throw new Error(
    "Не найден активный LAN/Wi-Fi-интерфейс для обхода CDEK. " +
    "Укажите CHECKSHEETS_BYPASS_INTERFACE, если используется другой интерфейс.",
  );
}

function createCdekHttpClient(networkInterfaces = os.networkInterfaces()) {
  const { interfaceName, sourceIp } = getCdekBypassInterface(networkInterfaces);
  const httpsAgent = new https.Agent({ keepAlive: true, localAddress: sourceIp });
  console.log(`CDEK bypass interface: ${interfaceName} (${sourceIp})`);
  return { httpClient: axios, httpsAgent };
}

async function fetchJson(url, headers, httpClient = axios, httpsAgent) {
  let lastStatus = null;
  let lastContentType = null;
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt += 1) {
    try {
      const response = await httpClient.get(url, {
        headers,
        httpsAgent,
        timeout: 30000,
        validateStatus: () => true,
      });
      lastStatus = response.status || 0;
      lastContentType = response.headers?.["content-type"] || null;
      if (lastStatus >= 200 && lastStatus < 300) {
        if (!response.data || typeof response.data !== "object") {
          throw new Error(`CDEK API вернул некорректный JSON для ${new URL(url).pathname}`);
        }
        return response.data;
      }
      if (lastStatus !== 429 && lastStatus < 500) {
        throw new Error(`CDEK API вернул HTTP ${lastStatus}`);
      }
    } catch (error) {
      if (String(error?.message || "").startsWith("CDEK API вернул")) throw error;
      lastStatus = error.response?.status || lastStatus || 0;
      lastContentType = error.response?.headers?.["content-type"] || lastContentType;
    }
    if (attempt < MAX_RETRIES) await sleep(1000 * attempt);
  }
  throw new Error(
    `CDEK API недоступен после ${MAX_RETRIES} попыток ` +
    `(последний HTTP ${lastStatus}, ${new URL(url).pathname}, content-type: ${lastContentType || "не указан"})`,
  );
}

function normalStock(items) {
  if (items === null) return 0;
  if (!Array.isArray(items)) throw new Error("В карточке CDEK поле items имеет неизвестный формат");
  return items.reduce((sum, item) => {
    if (!INCLUDED_STATES.has(normalizedHeader(item?.state))) return sum;
    const count = Number(item.count);
    if (!Number.isFinite(count) || count < 0) {
      throw new Error("CDEK вернул некорректный остаток items.count");
    }
    return sum + Math.trunc(count);
  }, 0);
}

function safeNextUrl(nextHref) {
  if (!nextHref) return null;
  const next = String(nextHref);
  if (!next.startsWith(`${CDEK_BASE_URL}/products/offer`)) {
    throw new Error("CDEK вернул небезопасную ссылку пагинации");
  }
  return next;
}

async function loadStocks(models, headers, httpClient = axios, httpsAgent) {
  const stockByModel = new Map();
  let matched = 0;

  for (let index = 0; index < models.length; index += 1) {
    const model = models[index];
    let url = `${CDEK_BASE_URL}/products/offer?filter%5B0%5D%5Btype%5D=eq&filter%5B0%5D%5Bfield%5D=article&filter%5B0%5D%5Bvalue%5D=${encodeURIComponent(model)}`;
    let total = 0;
    let pages = 0;
    let found = false;

    while (url) {
      const payload = await fetchJson(url, headers, httpClient, httpsAgent);
      const offers = payload?._embedded?.product_offer;
      if (!Array.isArray(offers)) {
        throw new Error(`CDEK вернул неожиданную структуру списка для model «${model}»`);
      }
      for (const offer of offers) {
        if (text(offer?.article) !== model) continue;
        if (!Object.prototype.hasOwnProperty.call(offer || {}, "items")) {
          throw new Error(`CDEK не вернул поле items для model «${model}»`);
        }
        total += normalStock(offer.items);
        found = true;
      }
      url = safeNextUrl(payload?._links?.next?.href);
      pages += 1;
      if (pages > 100) throw new Error(`CDEK pagination превысила 100 страниц для model «${model}»`);
    }

    if (found) matched += 1;
    stockByModel.set(model, total);
    if (index + 1 < models.length) await sleep(REQUEST_DELAY_MS);
  }
  console.log(JSON.stringify({
    cdekMatchedByExactModel: matched,
    cdekMissingByExactModel: models.length - matched,
  }));
  return stockByModel;
}

async function createSheetsClient() {
  const auth = new google.auth.GoogleAuth({
    keyFile: SERVICE_ACCOUNT_FILE,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  return google.sheets({ version: "v4", auth: await auth.getClient() });
}

async function readSheet(sheets) {
  const response = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: `${quoteSheetName(SHEET_NAME)}!A1:ZZ`,
  });
  const values = response.data.values || [];
  if (values.length < 2) throw new Error(`Лист «${SHEET_NAME}» пуст`);
  return { headers: values[0], rows: values.slice(1) };
}

async function writeStocks(sheets, rows, columns, stockByModel) {
  const values = rows.map((row) => {
    const model = text(row[columns.model - 1]);
    if (!model) return [""];
    if (!stockByModel.has(model)) {
      throw new Error(`Нет CDEK-остатка для model «${model}»; запись отменена`);
    }
    return [stockByModel.get(model)];
  });

  const stockLetter = columnToLetter(columns.stocks);
  const range = `${quoteSheetName(SHEET_NAME)}!${stockLetter}2:${stockLetter}${values.length + 1}`;
  await sheets.spreadsheets.values.update({
    spreadsheetId: SPREADSHEET_ID,
    range,
    valueInputOption: "RAW",
    requestBody: { values },
  });
  return { range, values };
}

async function main() {
  const startedAt = Date.now();
  const sheets = await createSheetsClient();
  const { headers, rows } = await readSheet(sheets);
  const columns = resolveColumns(headers);
  const models = collectUniqueModels(rows, columns.model);
  const { httpClient, httpsAgent } = createCdekHttpClient();
  let stocks;
  try {
    stocks = await loadStocks(models, cdekHeaders(), httpClient, httpsAgent);
  } finally {
    httpsAgent.destroy();
  }
  if (process.argv.includes("--dry-run")) {
    console.log(JSON.stringify({
      status: "dry-run",
      rows: rows.length,
      uniqueModels: models.length,
      nonZero: [...stocks.values()].filter((value) => value > 0).length,
    }));
    return;
  }
  const result = await writeStocks(sheets, rows, columns, stocks);
  const nonZero = result.values.filter(([value]) => Number(value) > 0).length;
  console.log(JSON.stringify({
    status: "ok",
    rows: result.values.length,
    uniqueModels: models.length,
    nonZero,
    range: result.range,
    durationSec: Math.round((Date.now() - startedAt) / 1000),
  }));
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

if (require.main === module) {
  main().catch((error) => {
    console.error(`CDEK stock sync failed: ${error.message}`);
    process.exit(1);
  });
}

module.exports = {
  collectUniqueModels,
  columnToLetter,
  createCdekHttpClient,
  fetchJson,
  getCdekBypassInterface,
  loadStocks,
  normalStock,
  resolveColumns,
  safeNextUrl,
  writeStocks,
};
