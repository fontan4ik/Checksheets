#!/usr/bin/env node
/**
 * Локальный аналог Apps Script «Ozon отзывы.js».
 *
 * Читает SKU из V листа «ТЕСТ», получает общий список отзывов Ozon
 * через POST /v2/review/list и записывает количество доставленных
 * отзывов в BL. Прогресс и карта счётчиков сохраняются в logs/.
 *
 * Секреты не хранятся в коде:
 *   OZON_CLIENT_ID / OZON_API_KEY — из защищённого файла
 *   GOOGLE_APPLICATION_CREDENTIALS — путь к service-account JSON
 */

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const axios = require("axios");
const dotenv = require("dotenv");
const { google } = require("googleapis");

const ROOT = __dirname;
const LOG_DIR = path.join(ROOT, "logs");
const STATE_FILE = path.join(LOG_DIR, "ozon-reviews-state.json");
const COUNTS_FILE = path.join(LOG_DIR, "ozon-reviews-counts.json");
const SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI";
const SHEET_NAME = "ТЕСТ";
const SKU_COLUMN_INDEX = 22; // V, 1-based
const OUTPUT_COLUMN_LETTER = "BL";
const PAGE_LIMIT = 100;
const REQUEST_INTERVAL_MS = Number(process.env.OZON_REVIEWS_REQUEST_INTERVAL_MS || 200);
const MAX_RUN_MS = Number(process.env.OZON_REVIEWS_MAX_RUN_MS || 15 * 60 * 1000);
const MAX_RETRIES = 4;
const SERVICE_ACCOUNT_FILE =
  process.env.GOOGLE_APPLICATION_CREDENTIALS ||
  path.join(ROOT, "nomadic-bedrock-485314-b0-d7624dedd83c.json");

const SECRET_FILE =
  process.env.OZON_REVIEWS_SECRETS_FILE ||
  "/Users/vladimirgrebennikov/AI agents/secrets/ozon-reviews.env";

// Load protected secrets first; dotenv does not overwrite already-set values.
dotenv.config({ path: SECRET_FILE, quiet: true });
dotenv.config({ path: path.join(ROOT, ".env"), quiet: true });

function text(value) {
  return String(value ?? "").trim();
}

function log(message) {
  console.log(`${new Date().toISOString()} ${message}`);
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function normalizeSku(value) {
  const sku = text(value);
  if (!sku || sku === "0" || Number.isNaN(Number(sku))) return "";
  return sku;
}

function quoteSheetName(name) {
  return `'${name.replace(/'/g, "''")}'`;
}

function atomicWriteJson(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const temporary = `${filePath}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(value)}\n`, { mode: 0o600 });
  fs.renameSync(temporary, filePath);
}

function readJson(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw new Error(`Не удалось прочитать ${filePath}: ${error.message}`);
  }
}

function skuFingerprint(skus) {
  return crypto.createHash("sha256").update(skus.join("\n")).digest("hex");
}

function getOzonHeaders() {
  const clientId = text(process.env.OZON_CLIENT_ID);
  const apiKey = text(process.env.OZON_API_KEY);
  if (!clientId || !apiKey) {
    throw new Error(
      `Не заданы OZON_CLIENT_ID/OZON_API_KEY. Ожидался защищённый файл ${SECRET_FILE}`,
    );
  }
  return {
    "Content-Type": "application/json",
    "Client-Id": clientId,
    "Api-Key": apiKey,
  };
}

async function createSheetsClient() {
  if (!fs.existsSync(SERVICE_ACCOUNT_FILE)) {
    throw new Error(`Не найден Google service-account JSON: ${SERVICE_ACCOUNT_FILE}`);
  }
  const auth = new google.auth.GoogleAuth({
    keyFile: SERVICE_ACCOUNT_FILE,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  return google.sheets({ version: "v4", auth: await auth.getClient() });
}

async function readSheetSkus(sheets) {
  const response = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: `${quoteSheetName(SHEET_NAME)}!A:BL`,
    majorDimension: "ROWS",
    valueRenderOption: "UNFORMATTED_VALUE",
  });
  const rows = response.data.values || [];
  if (rows.length < 2) return { lastRow: rows.length, skuValues: [], uniqueSkus: [] };

  const skuValues = rows.slice(1).map((row) => normalizeSku(row[SKU_COLUMN_INDEX - 1]));
  const uniqueSkus = [...new Set(skuValues.filter(Boolean))];
  return { lastRow: rows.length, skuValues, uniqueSkus };
}

function isRetryable(error) {
  const status = error.response?.status || 0;
  return status === 429 || status >= 500 || status === 0;
}

async function requestReviews(payload, headers, attempt = 0) {
  try {
    const response = await axios.post(
      "https://api-seller.ozon.ru/v2/review/list",
      payload,
      {
        headers,
        timeout: 30_000,
        validateStatus: () => true,
      },
    );
    if (response.status >= 200 && response.status < 300) return response.data;
    const error = new Error(`Ozon review/list HTTP ${response.status}`);
    error.response = response;
    throw error;
  } catch (error) {
    if (isRetryable(error) && attempt < MAX_RETRIES) {
      const delay = Math.min(30_000, 1_000 * 2 ** attempt);
      log(`Ozon review/list: повтор через ${delay / 1000} сек. (попытка ${attempt + 2}/${MAX_RETRIES + 1})`);
      await sleep(delay);
      return requestReviews(payload, headers, attempt + 1);
    }
    const responseText = text(error.response?.data?.message || error.response?.data?.error);
    throw new Error(`${error.message}${responseText ? `: ${responseText.slice(0, 300)}` : ""}`);
  }
}

function saveProgress(state, counts) {
  atomicWriteJson(STATE_FILE, state);
  atomicWriteJson(COUNTS_FILE, counts);
}

function loadOrCreateProgress(uniqueSkus) {
  const fingerprint = skuFingerprint(uniqueSkus);
  const state = readJson(STATE_FILE);
  const counts = readJson(COUNTS_FILE);
  if (
    state && counts && state.skuFingerprint === fingerprint &&
    state.status === "in_progress"
  ) {
    return { state, counts, resumed: true };
  }

  const freshState = {
    status: "in_progress",
    skuFingerprint: fingerprint,
    lastId: "",
    pages: 0,
    reviews: 0,
    startedAt: new Date().toISOString(),
  };
  const freshCounts = Object.fromEntries(uniqueSkus.map((sku) => [sku, 0]));
  saveProgress(freshState, freshCounts);
  return { state: freshState, counts: freshCounts, resumed: false };
}

async function writeResult(sheets, skuValues, counts, lastRow) {
  const values = [["Отзывы"]];
  for (const sku of skuValues) values.push([sku ? counts[sku] || 0 : ""]);
  if (lastRow > 0) {
    await sheets.spreadsheets.values.update({
      spreadsheetId: SPREADSHEET_ID,
      range: `${quoteSheetName(SHEET_NAME)}!${OUTPUT_COLUMN_LETTER}1:${OUTPUT_COLUMN_LETTER}${lastRow}`,
      valueInputOption: "RAW",
      requestBody: { majorDimension: "ROWS", values: values.slice(0, lastRow) },
    });
  }
}

async function processReviews(sheets, uniqueSkus, skuValues, lastRow) {
  const headers = getOzonHeaders();
  const progress = loadOrCreateProgress(uniqueSkus);
  const { state, counts } = progress;
  const startedAt = Date.now();
  let lastRequestAt = 0;

  log(`${progress.resumed ? "Продолжение" : "Новый проход"}: SKU=${uniqueSkus.length}, страниц=${state.pages}, отзывов=${state.reviews}`);

  while (Date.now() - startedAt < MAX_RUN_MS) {
    const wait = Math.max(0, REQUEST_INTERVAL_MS - (Date.now() - lastRequestAt));
    if (wait) await sleep(wait);
    lastRequestAt = Date.now();

    const data = await requestReviews(
      {
        last_id: state.lastId || "",
        limit: PAGE_LIMIT,
        sort_dir: "ASC",
        status: "ALL",
      },
      headers,
    );
    const reviews = Array.isArray(data.reviews) ? data.reviews : [];
    for (const review of reviews) {
      const sku = normalizeSku(review.sku);
      if (review.order_status === "DELIVERED" && sku && counts[sku] !== undefined) {
        counts[sku] += 1;
      }
    }

    state.pages += 1;
    state.reviews += reviews.length;
    state.lastId = text(data.last_id);
    saveProgress(state, counts);

    if (!data.has_next || !state.lastId || !reviews.length) {
      await writeResult(sheets, skuValues, counts, lastRow);
      state.status = "completed";
      state.completedAt = new Date().toISOString();
      saveProgress(state, counts);
      fs.rmSync(STATE_FILE, { force: true });
      fs.rmSync(COUNTS_FILE, { force: true });
      log(`Готово: BL обновлён, страниц=${state.pages}, отзывов просмотрено=${state.reviews}`);
      return { status: "completed", pages: state.pages, reviews: state.reviews };
    }

    if (state.pages % 25 === 0) {
      log(`Прогресс: страниц=${state.pages}, отзывов=${state.reviews}`);
    }
  }

  log(`Лимит локального запуска достигнут: прогресс сохранён, страниц=${state.pages}, отзывов=${state.reviews}`);
  return { status: "paused", pages: state.pages, reviews: state.reviews };
}

async function main() {
  const sheets = await createSheetsClient();
  const { lastRow, skuValues, uniqueSkus } = await readSheetSkus(sheets);
  if (lastRow < 2) {
    log("Лист «ТЕСТ» не содержит строк для обработки");
    return;
  }
  if (!uniqueSkus.length) {
    await writeResult(sheets, skuValues, {}, lastRow);
    log("В колонке V нет SKU Ozon; BL заполнен пустыми значениями");
    return;
  }
  await processReviews(sheets, uniqueSkus, skuValues, lastRow);
}

if (require.main === module) {
  main().catch((error) => {
    console.error(`❌ ${error.message}`);
    process.exitCode = 1;
  });
}

module.exports = {
  normalizeSku,
  skuFingerprint,
  quoteSheetName,
  isRetryable,
};
