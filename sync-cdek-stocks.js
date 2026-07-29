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
const { google } = require("googleapis");

const SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI";
const SHEET_NAME = "СДЕК TR";
const CDEK_BASE_URL = "https://cdek.orderadmin.ru/api";
const REQUEST_DELAY_MS = 120;
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

function collectUniqueArticles(rows, articleColumn) {
  const unique = new Set();
  for (const row of rows) {
    const article = text(row[articleColumn - 1]);
    if (article) unique.add(article);
  }
  if (!unique.size) throw new Error("В колонке art нет значений для CDEK-запроса");
  return [...unique];
}

function cdekHeaders() {
  const login = text(process.env.CDEK_FULFILLMENT_LOGIN);
  const apiKey = text(process.env.CDEK_FULFILLMENT_API_KEY);
  if (!login || !apiKey) {
    throw new Error("Не заданы CDEK_FULFILLMENT_LOGIN и/или CDEK_FULFILLMENT_API_KEY в окружении");
  }
  return {
    Accept: "application/json",
    Authorization: `Basic ${Buffer.from(`${login}:${apiKey}`, "utf8").toString("base64")}`,
  };
}

async function fetchJson(url, headers) {
  let lastStatus = null;
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(url, { headers, signal: controller.signal });
      lastStatus = response.status;
      if (response.ok) return await response.json();
      if (response.status !== 429 && response.status < 500) {
        throw new Error(`CDEK API вернул HTTP ${response.status}`);
      }
    } finally {
      clearTimeout(timer);
    }
    if (attempt < MAX_RETRIES) await sleep(1000 * attempt);
  }
  throw new Error(`CDEK API недоступен после ${MAX_RETRIES} попыток (последний HTTP ${lastStatus})`);
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

async function listOfferRefs(headers) {
  const refs = [];
  const seen = new Set();
  let url = `${CDEK_BASE_URL}/products/offer`;
  let pages = 0;

  while (url) {
    const payload = await fetchJson(url, headers);
    const offers = payload?._embedded?.product_offer;
    if (!Array.isArray(offers)) {
      throw new Error("CDEK вернул неожиданную структуру списка offers");
    }
    for (const offer of offers) {
      const shopId = offer?._embedded?.shop?.id ?? offer?.shop?.id;
      const offerId = offer?.id;
      if (!shopId || !offerId) {
        throw new Error("В списке CDEK отсутствует shop_id или product_id");
      }
      const key = `${shopId}:${offerId}`;
      if (!seen.has(key)) {
        seen.add(key);
        refs.push({ shopId, offerId });
      }
    }
    url = safeNextUrl(payload?._links?.next?.href);
    pages += 1;
    if (pages > 100) throw new Error("CDEK pagination превысила 100 страниц");
  }
  return refs;
}

async function loadStocks(articles, headers) {
  const required = new Set(articles);
  const stockByArticle = new Map();
  const refs = await listOfferRefs(headers);

  for (let index = 0; index < refs.length; index += 1) {
    const { shopId, offerId } = refs[index];
    const offer = await fetchJson(
      `${CDEK_BASE_URL}/products/offer/${encodeURIComponent(shopId)}/${encodeURIComponent(offerId)}`,
      headers,
    );
    const article = text(offer?.article);
    if (required.has(article)) {
      if (!Object.prototype.hasOwnProperty.call(offer || {}, "items")) {
        throw new Error(`Карточка CDEK ${offerId} для art «${article}» не содержит поля items`);
      }
      stockByArticle.set(article, (stockByArticle.get(article) || 0) + normalStock(offer.items));
    }
    if (index + 1 < refs.length) await sleep(REQUEST_DELAY_MS);
  }

  const missing = articles.filter((article) => !stockByArticle.has(article));
  if (missing.length) {
    throw new Error(`CDEK не нашёл ${missing.length} артикулов; пример: «${missing[0]}»`);
  }
  return stockByArticle;
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

async function writeStocks(sheets, rows, columns, stockByArticle) {
  const values = rows.map((row) => {
    const article = text(row[columns.art - 1]);
    if (!article) return [""];
    if (!stockByArticle.has(article)) {
      throw new Error(`Нет CDEK-остатка для art «${article}»; запись отменена`);
    }
    return [stockByArticle.get(article)];
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
  const articles = collectUniqueArticles(rows, columns.art);
  const stocks = await loadStocks(articles, cdekHeaders());
  const result = await writeStocks(sheets, rows, columns, stocks);
  const nonZero = result.values.filter(([value]) => Number(value) > 0).length;
  console.log(JSON.stringify({
    status: "ok",
    rows: result.values.length,
    uniqueArticles: articles.length,
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
  collectUniqueArticles,
  columnToLetter,
  listOfferRefs,
  loadStocks,
  normalStock,
  resolveColumns,
  safeNextUrl,
  writeStocks,
};
