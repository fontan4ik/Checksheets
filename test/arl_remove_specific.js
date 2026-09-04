#!/usr/bin/env node

/*
 * Одноразовая операция для ARL TR:
 * 1) выставить stock=0 на Ozon и WB;
 * 2) проверить, что нули приняты;
 * 3) удалить подтверждённые строки из Google Sheets сервисным аккаунтом.
 *
 * Скрипт намеренно не удаляет строки, если любой шаг зануления или read-back
 * завершился ошибкой.
 */

const fs = require("fs");
const path = require("path");
const axios = require("axios");
const { google } = require("googleapis");

const SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI";
const SHEET_NAME = "ARL TR";
const SERVICE_ACCOUNT_FILE = path.join(
  __dirname,
  "..",
  "nomadic-bedrock-485314-b0-d7624dedd83c.json",
);
const SETTINGS_FILE = path.join(__dirname, "..", "settings.js");
const OZON_WAREHOUSE_ID = 1020005000217829;
const WB_WAREHOUSE_ID = 1449484;
const BATCH_SIZE = 100;
const TARGET_ARTICLES = [
  "023146(2)-1",
  "023144(2)-1",
  "023145(2)-1",
  "038431-1",
  "038429-1",
  "038430-1",
  "038428-1",
  "038426-1",
  "038423-1",
];

function text(value) {
  return String(value ?? "").trim();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseSettings() {
  const source = fs.readFileSync(SETTINGS_FILE, "utf8");
  const clientId = source.match(/const clientId = ['"]([^'"]+)['"]/s)?.[1];
  const apiKey = source.match(/const apiKey = ['"]([^'"]+)['"]/s)?.[1];
  const authorization = source.match(/Authorization:\s*['"]Bearer\s+([^'"]+)['"]/s)?.[1];
  if (!clientId || !apiKey || !authorization) {
    throw new Error("Не удалось безопасно прочитать Ozon/WB credentials из settings.js");
  }
  return { clientId, apiKey, authorization: `Bearer ${authorization}` };
}

function quoteSheetName(name) {
  return `'${name.replace(/'/g, "''")}'`;
}

async function createSheetsClient() {
  const auth = new google.auth.GoogleAuth({
    keyFile: SERVICE_ACCOUNT_FILE,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  return google.sheets({ version: "v4", auth: await auth.getClient() });
}

async function readTargetRows(sheets) {
  const response = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: `${quoteSheetName(SHEET_NAME)}!A1:Q`,
    valueRenderOption: "UNFORMATTED_VALUE",
  });
  const values = response.data.values || [];
  if (values.length < 2) throw new Error(`Лист «${SHEET_NAME}» пуст`);

  const headers = values[0].map(text);
  const rows = [];
  const targets = new Set(TARGET_ARTICLES);
  values.slice(1).forEach((row, index) => {
    const article = text(row[0]);
    if (!targets.has(article)) return;
    rows.push({
      rowNumber: index + 2,
      article,
      offerId: article,
      nmId: text(row[4]),
      stock: row[8],
      chrtId: text(row[9]),
    });
  });

  if (rows.length !== TARGET_ARTICLES.length) {
    throw new Error(
      `Ожидалось ${TARGET_ARTICLES.length} строк ARL TR, найдено ${rows.length}. ` +
        `Удаление отменено.`,
    );
  }
  const found = new Set(rows.map((row) => row.article));
  const missing = TARGET_ARTICLES.filter((article) => !found.has(article));
  if (missing.length) throw new Error(`Не найдены артикулы: ${missing.join(", ")}`);
  if (new Set(rows.map((row) => row.rowNumber)).size !== rows.length) {
    throw new Error("В ARL TR обнаружены повторяющиеся номера строк");
  }
  if (rows.some((row) => !row.chrtId)) {
    throw new Error("У одного или нескольких артикулов отсутствует chrtId WB");
  }

  const sortedRows = [...rows].sort((a, b) => a.rowNumber - b.rowNumber);
  const first = sortedRows[0].rowNumber;
  if (sortedRows.some((row, index) => row.rowNumber !== first + index)) {
    throw new Error("Целевые строки ARL TR не идут непрерывным блоком; удаление отменено");
  }

  return { headers, rows, firstRow: first, lastRow: first + rows.length - 1 };
}

function ozonHeaders(credentials) {
  return {
    "Content-Type": "application/json",
    "Client-Id": credentials.clientId,
    "Api-Key": credentials.apiKey,
  };
}

function wbHeaders(credentials) {
  return {
    Authorization: credentials.authorization,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
}

async function zeroOzon(rows, credentials) {
  const body = {
    stocks: rows.map((row) => ({
      offer_id: row.offerId,
      stock: 0,
      warehouse_id: OZON_WAREHOUSE_ID,
    })),
  };
  const response = await axios.post(
    "https://api-seller.ozon.ru/v2/products/stocks",
    body,
    { headers: ozonHeaders(credentials), timeout: 30000, validateStatus: () => true },
  );
  if (response.status < 200 || response.status >= 300) {
    throw new Error(`Ozon зануление: HTTP ${response.status}: ${JSON.stringify(response.data).slice(0, 500)}`);
  }
  const result = Array.isArray(response.data?.result) ? response.data.result : [];
  const errors = result.flatMap((item) =>
    (Array.isArray(item?.errors) ? item.errors : []).map((error) => ({
      offerId: item?.offer_id,
      code: error?.code,
      message: error?.message,
    })),
  );
  if (errors.length || result.length < rows.length) {
    throw new Error(`Ozon зануление не подтверждено: ${JSON.stringify({ resultCount: result.length, errors })}`);
  }
  return { status: response.status, resultCount: result.length };
}

async function zeroWildberries(rows, credentials) {
  const body = {
    stocks: rows.map((row) => ({ chrtId: Number(row.chrtId), amount: 0 })),
  };
  if (body.stocks.some((item) => !Number.isInteger(item.chrtId) || item.chrtId <= 0)) {
    throw new Error("WB зануление: найден невалидный chrtId");
  }
  const response = await axios.put(
    `https://marketplace-api.wildberries.ru/api/v3/stocks/${WB_WAREHOUSE_ID}`,
    body,
    { headers: wbHeaders(credentials), timeout: 30000, validateStatus: () => true },
  );
  if (response.status !== 200 && response.status !== 204) {
    throw new Error(`WB зануление: HTTP ${response.status}: ${JSON.stringify(response.data).slice(0, 500)}`);
  }
  return { status: response.status, itemCount: body.stocks.length };
}

async function verifyOzon(rows, credentials) {
  const response = await axios.post(
    "https://api-seller.ozon.ru/v2/product/info/stocks-by-warehouse/fbs",
    {
      offer_id: rows.map((row) => row.offerId),
      warehouse_id: OZON_WAREHOUSE_ID,
      limit: 1000,
    },
    { headers: ozonHeaders(credentials), timeout: 30000, validateStatus: () => true },
  );
  if (response.status < 200 || response.status >= 300) {
    throw new Error(`Ozon read-back: HTTP ${response.status}`);
  }
  const byOffer = new Map(
    (Array.isArray(response.data?.products) ? response.data.products : []).map((item) => [
      text(item.offer_id),
      (Number(item.present) || 0) + (Number(item.reserved) || 0),
    ]),
  );
  const nonZero = rows
    .map((row) => ({ article: row.offerId, stock: byOffer.get(row.offerId) || 0 }))
    .filter((item) => item.stock !== 0);
  if (nonZero.length) throw new Error(`Ozon read-back: ненулевые остатки ${JSON.stringify(nonZero)}`);
  return { returnedProducts: byOffer.size, nonZero: 0 };
}

async function verifyWildberries(rows, credentials) {
  // WB inventory read-back uses POST on the same endpoint and accepts chrtIds.
  const response = await axios.post(
    `https://marketplace-api.wildberries.ru/api/v3/stocks/${WB_WAREHOUSE_ID}`,
    { chrtIds: rows.map((row) => Number(row.chrtId)) },
    { headers: wbHeaders(credentials), timeout: 30000, validateStatus: () => true },
  );
  if (response.status !== 200) {
    throw new Error(`WB read-back: HTTP ${response.status}: ${JSON.stringify(response.data).slice(0, 500)}`);
  }
  const stocks = Array.isArray(response.data?.stocks) ? response.data.stocks : Array.isArray(response.data) ? response.data : [];
  const byChrt = new Map(stocks.map((item) => [String(item.chrtId), Number(item.amount) || 0]));
  const nonZero = rows
    .map((row) => ({ article: row.offerId, chrtId: row.chrtId, amount: byChrt.get(row.chrtId) || 0 }))
    .filter((item) => item.amount !== 0);
  if (nonZero.length) throw new Error(`WB read-back: ненулевые остатки ${JSON.stringify(nonZero)}`);
  return { returnedStocks: byChrt.size, nonZero: 0 };
}

async function deleteRows(sheets, firstRow, lastRow) {
  const meta = await sheets.spreadsheets.get({
    spreadsheetId: SPREADSHEET_ID,
    fields: "sheets(properties(sheetId,title,gridProperties(rowCount)))",
  });
  const sheet = (meta.data.sheets || []).find((item) => item.properties?.title === SHEET_NAME);
  if (!sheet) throw new Error(`Лист «${SHEET_NAME}» не найден при удалении`);
  await sheets.spreadsheets.batchUpdate({
    spreadsheetId: SPREADSHEET_ID,
    requestBody: {
      requests: [{
        deleteDimension: {
          range: {
            sheetId: sheet.properties.sheetId,
            dimension: "ROWS",
            startIndex: firstRow - 1,
            endIndex: lastRow,
          },
        },
      }],
    },
  });
  return { sheetId: sheet.properties.sheetId, deletedRows: lastRow - firstRow + 1 };
}

async function verifyDeleted(sheets) {
  const response = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: `${quoteSheetName(SHEET_NAME)}!A:A`,
    valueRenderOption: "UNFORMATTED_VALUE",
  });
  const remaining = new Set((response.data.values || []).flat().map(text));
  const stillPresent = TARGET_ARTICLES.filter((article) => remaining.has(article));
  if (stillPresent.length) throw new Error(`После удаления остались артикулы: ${stillPresent.join(", ")}`);
  return { stillPresent: 0 };
}

async function main() {
  const credentials = parseSettings();
  const sheets = await createSheetsClient();
  const snapshot = await readTargetRows(sheets);
  console.log(JSON.stringify({
    phase: "snapshot",
    rows: snapshot.rows.map((row) => ({ row: row.rowNumber, article: row.article, offerId: row.offerId, chrtId: row.chrtId, stock: row.stock })),
    block: `${snapshot.firstRow}:${snapshot.lastRow}`,
  }));

  const ozon = await zeroOzon(snapshot.rows, credentials);
  console.log(JSON.stringify({ phase: "ozon_zeroed", ...ozon }));
  const wb = await zeroWildberries(snapshot.rows, credentials);
  console.log(JSON.stringify({ phase: "wb_zeroed", ...wb }));

  await sleep(5000);
  let ozonVerification;
  let wbVerification;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      ozonVerification = await verifyOzon(snapshot.rows, credentials);
      wbVerification = await verifyWildberries(snapshot.rows, credentials);
      break;
    } catch (error) {
      if (attempt === 3) throw error;
      console.log(`read-back attempt ${attempt} failed; retrying in 10s: ${error.message}`);
      await sleep(10000);
    }
  }
  console.log(JSON.stringify({ phase: "verified_zero", ozon: ozonVerification, wb: wbVerification }));

  const deletion = await deleteRows(sheets, snapshot.firstRow, snapshot.lastRow);
  console.log(JSON.stringify({ phase: "rows_deleted", ...deletion }));
  const finalCheck = await verifyDeleted(sheets);
  console.log(JSON.stringify({ phase: "final_check", ...finalCheck }));
}

main().catch((error) => {
  console.error(`ARL remove failed: ${error.stack || error.message}`);
  process.exitCode = 1;
});
