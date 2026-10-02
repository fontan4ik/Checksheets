#!/usr/bin/env node
'use strict';

// Writes confirmed Ozon buyout quantities to the rightmost two columns of ТЕСТ.
process.env.TZ = 'Asia/Dubai';

const fs = require('fs');
const path = require('path');
const axios = require('axios');
const dotenv = require('dotenv');
const { google } = require('googleapis');

const ROOT = __dirname;
const SPREADSHEET_ID = process.env.CHECKSHEETS_SPREADSHEET_ID || '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
const SHEET_NAME = 'ТЕСТ';
const CREDENTIALS = process.env.GOOGLE_APPLICATION_CREDENTIALS || path.join(ROOT, 'nomadic-bedrock-485314-b0-d7624dedd83c.json');
const BUYOUT_URL = 'https://api-seller.ozon.ru/v1/finance/products/buyout';
const SECRET_FILE = process.env.OZON_REVIEWS_SECRETS_FILE || '/Users/vladimirgrebennikov/AI agents/secrets/ozon-reviews.env';
const SKU_COLUMN = 22; // V: SKU Ozon
const MAX_PERIOD_DAYS = 31;
const MAX_ATTEMPTS = 5;
const REQUEST_INTERVAL_MS = 1200;
const QUARTER_HEADER = 'Выкупы Ozon, шт за 3 месяца';
const YEAR_HEADER = 'Выкупы Ozon, шт за 12 месяцев';
const OUTPUT_HEADERS = [QUARTER_HEADER, YEAR_HEADER];

dotenv.config({ path: SECRET_FILE, quiet: true });
dotenv.config({ path: path.join(ROOT, '.env'), quiet: true });

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const text = value => String(value ?? '').trim();

function log(message) {
  console.log(`${new Date().toISOString()} ${message}`);
}

function formatDate(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function parseDate(value) {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day);
}

function subtractCalendarMonths(date, months) {
  const targetMonthIndex = date.getMonth() - months;
  const year = date.getFullYear() + Math.floor(targetMonthIndex / 12);
  const month = ((targetMonthIndex % 12) + 12) % 12;
  const lastDay = new Date(year, month + 1, 0).getDate();
  return new Date(year, month, Math.min(date.getDate(), lastDay));
}

function getDateRanges(now = new Date()) {
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  return {
    quarter: { from: formatDate(subtractCalendarMonths(yesterday, 3)), to: formatDate(yesterday) },
    year: { from: formatDate(subtractCalendarMonths(yesterday, 12)), to: formatDate(yesterday) },
  };
}

function splitPeriod(from, to, maxDays = MAX_PERIOD_DAYS) {
  let current = parseDate(from);
  const end = parseDate(to);
  const periods = [];
  while (current <= end) {
    const chunkEnd = new Date(current);
    chunkEnd.setDate(chunkEnd.getDate() + maxDays - 1);
    if (chunkEnd > end) chunkEnd.setTime(end.getTime());
    periods.push({ from: formatDate(current), to: formatDate(chunkEnd) });
    current = new Date(chunkEnd);
    current.setDate(current.getDate() + 1);
  }
  return periods;
}

function normalizeSku(value) {
  return text(value).replace(/\s+/g, '');
}

function apiHeaders() {
  const clientId = text(process.env.OZON_CLIENT_ID);
  const apiKey = text(process.env.OZON_API_KEY);
  if (!clientId || !apiKey) throw new Error(`Не заданы OZON_CLIENT_ID/OZON_API_KEY; проверьте защищённый файл ${SECRET_FILE}`);
  return { 'Client-Id': clientId, 'Api-Key': apiKey, 'Content-Type': 'application/json' };
}

async function requestBuyouts(dateFrom, dateTo, headers, limiter) {
  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
    await limiter();
    try {
      const response = await axios.post(BUYOUT_URL, { date_from: dateFrom, date_to: dateTo }, {
        headers,
        timeout: 30000,
        validateStatus: () => true,
      });
      if (response.status >= 200 && response.status < 300) {
        if (!Array.isArray(response.data?.products)) {
          throw new Error(`Ozon Buyout API: нет массива products за ${dateFrom}..${dateTo}`);
        }
        return response.data.products;
      }

      if (response.status !== 429 && response.status < 500) {
        throw new Error(`Ozon Buyout API HTTP ${response.status} за ${dateFrom}..${dateTo}: ${JSON.stringify(response.data).slice(0, 400)}`);
      }
      if (attempt === MAX_ATTEMPTS - 1) {
        throw new Error(`Ozon Buyout API HTTP ${response.status} за ${dateFrom}..${dateTo}: исчерпаны повторы`);
      }

      const retryAfter = Number(response.headers?.['retry-after']);
      const delayMs = Math.max(Number.isFinite(retryAfter) ? retryAfter * 1000 : 0, Math.min(60000, 10000 * 2 ** attempt));
      log(`Ozon HTTP ${response.status}: ${JSON.stringify(response.data).slice(0, 200)}; повтор через ${Math.ceil(delayMs / 1000)} сек`);
      await sleep(delayMs);
    } catch (error) {
      if (/^Ozon Buyout API HTTP 4\d\d/.test(error.message) || /нет массива products/.test(error.message)) throw error;
      if (attempt === MAX_ATTEMPTS - 1) throw error;
      const delayMs = Math.min(60000, 10000 * 2 ** attempt);
      log(`Сбой запроса Ozon; повтор через ${Math.ceil(delayMs / 1000)} сек: ${error.message}`);
      await sleep(delayMs);
    }
  }
  throw new Error('Ozon Buyout API: исчерпаны повторы');
}

async function fetchBuyouts(range, headers, limiter) {
  const quantities = new Map();
  let productRows = 0;
  const periods = splitPeriod(range.from, range.to);
  for (const period of periods) {
    const products = await requestBuyouts(period.from, period.to, headers, limiter);
    productRows += products.length;
    for (const product of products) {
      const sku = normalizeSku(product?.sku);
      if (!sku) continue;
      const quantity = Number(product?.quantity);
      if (!Number.isFinite(quantity)) {
        throw new Error(`Ozon Buyout API: некорректное quantity у SKU ${sku} за ${period.from}..${period.to}`);
      }
      quantities.set(sku, (quantities.get(sku) || 0) + quantity);
    }
    log(`Выкупы Ozon ${period.from}..${period.to}: товаров ${products.length}`);
  }
  return { quantities, productRows, chunkCount: periods.length };
}

function quoteSheetName(name) {
  return `'${name.replace(/'/g, "''")}'`;
}

function columnLetter(column) {
  let result = '';
  while (column > 0) {
    const remainder = (column - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    column = Math.floor((column - 1) / 26);
  }
  return result;
}

async function sheetsClient() {
  if (!fs.existsSync(CREDENTIALS)) throw new Error(`Нет service-account файла: ${CREDENTIALS}`);
  const auth = new google.auth.GoogleAuth({ keyFile: CREDENTIALS, scopes: ['https://www.googleapis.com/auth/spreadsheets'] });
  return google.sheets({ version: 'v4', auth: await auth.getClient() });
}

async function findSheet(sheets) {
  const response = await sheets.spreadsheets.get({
    spreadsheetId: SPREADSHEET_ID,
    fields: 'sheets.properties(sheetId,title,gridProperties(rowCount,columnCount))',
  });
  const sheet = (response.data.sheets || []).find(item => item.properties?.title === SHEET_NAME);
  if (!sheet) throw new Error(`Не найден лист «${SHEET_NAME}»`);
  return sheet.properties;
}

function chooseOutputColumns(headerRow) {
  const normalizedHeaders = headerRow.map(value => text(value).toLowerCase().replace(/ё/g, 'е').replace(/\s+/g, ' '));
  const wanted = OUTPUT_HEADERS.map(value => value.toLowerCase());
  const found = wanted.map(header => normalizedHeaders.flatMap((value, index) => value === header ? [index + 1] : []));
  if (found.some(matches => matches.length > 1)) throw new Error('ТЕСТ: заголовки квартальных/годовых выкупов дублируются');
  if (found.every(matches => matches.length === 1)) {
    const columns = found.map(matches => matches[0]);
    if (columns[1] !== columns[0] + 1) throw new Error('ТЕСТ: готовые колонки выкупов должны стоять рядом');
    return columns;
  }
  if (found.some(matches => matches.length > 0)) throw new Error('ТЕСТ: найден только один из двух заголовков выкупов; запись остановлена');

  let lastHeaderColumn = 0;
  normalizedHeaders.forEach((value, index) => { if (value) lastHeaderColumn = index + 1; });
  return [lastHeaderColumn + 1, lastHeaderColumn + 2];
}

async function ensureGridWidth(sheets, sheetProperties, requiredColumn) {
  const currentWidth = Number(sheetProperties.gridProperties?.columnCount) || 0;
  if (currentWidth >= requiredColumn) return;
  await sheets.spreadsheets.batchUpdate({
    spreadsheetId: SPREADSHEET_ID,
    requestBody: { requests: [{ appendDimension: { sheetId: sheetProperties.sheetId, dimension: 'COLUMNS', length: requiredColumn - currentWidth } }] },
  });
}

async function prepareOutput(sheets, sheetProperties, rowCount, outputColumns) {
  await ensureGridWidth(sheets, sheetProperties, Math.max(...outputColumns));
  const firstColumn = Math.min(...outputColumns);
  const lastColumn = Math.max(...outputColumns);
  const range = `${quoteSheetName(SHEET_NAME)}!${columnLetter(firstColumn)}1:${columnLetter(lastColumn)}${rowCount}`;
  const existing = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range,
    valueRenderOption: 'FORMULA',
  });
  const values = existing.data.values || [];
  const hasBothHeaders = outputColumns.every((column, index) => text(values[0]?.[column - firstColumn]) === OUTPUT_HEADERS[index]);
  if (!hasBothHeaders && values.some(row => row.some(value => Boolean(text(value))))) {
    throw new Error('ТЕСТ: целевые колонки содержат данные; таблица не изменена');
  }
  return { firstColumn, lastColumn };
}

function buildRows(sheetRows, quarterMap, yearMap) {
  const quarterValues = [];
  const yearValues = [];
  let validSkuRows = 0;
  let quarterNonZeroRows = 0;
  let yearNonZeroRows = 0;
  for (const row of sheetRows) {
    const sku = normalizeSku(row[SKU_COLUMN - 1]);
    if (!sku) {
      quarterValues.push(['']);
      yearValues.push(['']);
      continue;
    }
    validSkuRows++;
    const quarter = Math.round(quarterMap.get(sku) || 0);
    const year = Math.round(yearMap.get(sku) || 0);
    quarterValues.push([quarter]);
    yearValues.push([year]);
    if (quarter) quarterNonZeroRows++;
    if (year) yearNonZeroRows++;
  }
  if (!validSkuRows) throw new Error('ТЕСТ: в колонке V нет SKU Ozon для сопоставления выкупов');
  return { quarterValues, yearValues, validSkuRows, quarterNonZeroRows, yearNonZeroRows };
}

async function writeAndVerify(sheets, columns, rowCount, output) {
  const [quarterColumn, yearColumn] = columns;
  const sheetId = await getSheetId(sheets);
  const startRow = 1;
  const rowValues = Array.from({ length: rowCount }, (_, index) => [
    index === 0 ? QUARTER_HEADER : output.quarterValues[index - 1][0],
    index === 0 ? YEAR_HEADER : output.yearValues[index - 1][0],
  ]);
  const range = `${quoteSheetName(SHEET_NAME)}!${columnLetter(quarterColumn)}${startRow}:${columnLetter(yearColumn)}${rowCount}`;
  await sheets.spreadsheets.values.update({
    spreadsheetId: SPREADSHEET_ID,
    range,
    valueInputOption: 'RAW',
    requestBody: { values: rowValues },
  });
  const templateColumn = quarterColumn - 1;
  if (templateColumn < 1) throw new Error('ТЕСТ: не найден столбец для копирования формата новых полей');
  await sheets.spreadsheets.batchUpdate({
    spreadsheetId: SPREADSHEET_ID,
    requestBody: { requests: [
      ...columns.map(column => ({
        copyPaste: {
          source: { sheetId, startColumnIndex: templateColumn - 1, endColumnIndex: templateColumn },
          destination: { sheetId, startColumnIndex: column - 1, endColumnIndex: column },
          pasteType: 'PASTE_FORMAT',
        },
      })),
      {
        updateDimensionProperties: {
          range: { sheetId, dimension: 'COLUMNS', startIndex: quarterColumn - 1, endIndex: yearColumn },
          properties: { pixelSize: 170 },
          fields: 'pixelSize',
        },
      },
      {
        repeatCell: {
          range: { sheetId, startRowIndex: 1, endRowIndex: rowCount, startColumnIndex: quarterColumn - 1, endColumnIndex: yearColumn },
          cell: { userEnteredFormat: { numberFormat: { type: 'NUMBER', pattern: '#,##0' } } },
          fields: 'userEnteredFormat.numberFormat',
        },
      },
    ] },
  });
  const readback = await sheets.spreadsheets.values.get({ spreadsheetId: SPREADSHEET_ID, range, valueRenderOption: 'UNFORMATTED_VALUE' });
  const rows = readback.data.values || [];
  if (text(rows[0]?.[0]) !== QUARTER_HEADER || text(rows[0]?.[1]) !== YEAR_HEADER) {
    throw new Error('ТЕСТ: проверка заголовков после записи не прошла');
  }
  for (let index = 1; index < rowCount; index++) {
    const actualQuarter = rows[index]?.[0] ?? '';
    const actualYear = rows[index]?.[1] ?? '';
    const expectedQuarter = output.quarterValues[index - 1][0];
    const expectedYear = output.yearValues[index - 1][0];
    if (actualQuarter !== expectedQuarter || actualYear !== expectedYear) {
      throw new Error(`ТЕСТ: read-back не совпал в строке ${index + 1}`);
    }
  }
}

async function getSheetId(sheets) {
  const props = await findSheet(sheets);
  return props.sheetId;
}

async function main() {
  const startedAt = Date.now();
  const headers = apiHeaders();
  const sheets = await sheetsClient();
  const sheetProperties = await findSheet(sheets);
  const rowsResponse = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: `${quoteSheetName(SHEET_NAME)}!A1:V`,
    valueRenderOption: 'UNFORMATTED_VALUE',
  });
  const rows = rowsResponse.data.values || [];
  if (rows.length < 2) throw new Error(`ТЕСТ: нет строк с товарами на листе «${SHEET_NAME}»`);
  const gridWidth = Number(sheetProperties.gridProperties?.columnCount) || 22;
  const headersResponse = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: `${quoteSheetName(SHEET_NAME)}!A1:${columnLetter(gridWidth)}1`,
    valueRenderOption: 'FORMATTED_VALUE',
  });
  const headerRow = headersResponse.data.values?.[0] || [];
  if (text(headerRow[SKU_COLUMN - 1]).replace(/\s+/g, ' ').toLowerCase() !== 'sku ozon') {
    throw new Error(`ТЕСТ: в колонке V ожидался заголовок «SKU Ozon», найдено «${text(headerRow[SKU_COLUMN - 1])}»`);
  }
  const columns = chooseOutputColumns(headerRow);
  const sheetRows = rows.slice(1);
  const outputArea = await prepareOutput(sheets, sheetProperties, rows.length, columns);
  const ranges = getDateRanges();
  log(`Ozon Buyout: лист ${SHEET_NAME}, строк ${sheetRows.length}, колонки ${columnLetter(columns[0])}:${columnLetter(columns[1])}`);
  log(`Период квартал: ${ranges.quarter.from}..${ranges.quarter.to}; год: ${ranges.year.from}..${ranges.year.to}`);

  let lastRequestAt = 0;
  const limiter = async () => {
    const wait = REQUEST_INTERVAL_MS - (Date.now() - lastRequestAt);
    if (wait > 0) await sleep(wait);
    lastRequestAt = Date.now();
  };
  const quarterResult = await fetchBuyouts(ranges.quarter, headers, limiter);
  const yearResult = await fetchBuyouts(ranges.year, headers, limiter);
  const output = buildRows(sheetRows, quarterResult.quantities, yearResult.quantities);

  // Recheck the output cells immediately before writing to avoid overwriting a concurrent edit.
  const { firstColumn, lastColumn } = outputArea;
  const targetRange = `${quoteSheetName(SHEET_NAME)}!${columnLetter(firstColumn)}1:${columnLetter(lastColumn)}${rows.length}`;
  const currentTarget = await sheets.spreadsheets.values.get({ spreadsheetId: SPREADSHEET_ID, range: targetRange, valueRenderOption: 'FORMULA' });
  const currentValues = currentTarget.data.values || [];
  const hasBothHeaders = text(currentValues[0]?.[columns[0] - firstColumn]) === QUARTER_HEADER &&
    text(currentValues[0]?.[columns[1] - firstColumn]) === YEAR_HEADER;
  if (!hasBothHeaders && currentValues.some(row => row.some(value => Boolean(text(value))))) {
    throw new Error('ТЕСТ: целевые колонки изменились после чтения; запись остановлена');
  }

  await writeAndVerify(sheets, columns, rows.length, output);
  log(`Запись подтверждена: строк ${sheetRows.length}, товаров со SKU ${output.validSkuRows}, ненулевых выкупов квартал ${output.quarterNonZeroRows}, год ${output.yearNonZeroRows}`);
  log(`Ответы Ozon: квартал ${quarterResult.productRows} строк/${quarterResult.chunkCount} запросов; год ${yearResult.productRows} строк/${yearResult.chunkCount} запросов`);
  log(`DONE Ozon Buyout periods; elapsed=${Math.round((Date.now() - startedAt) / 1000)} sec`);
}

if (require.main === module) {
  main().catch(error => {
    log(`FAILED Ozon Buyout periods: ${error.message}`);
    process.exitCode = 1;
  });
}

module.exports = { getDateRanges, splitPeriod };
