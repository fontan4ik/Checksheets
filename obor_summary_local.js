#!/usr/bin/env node
'use strict';

// Local replacement for the Apps Script updateOborSummary() scheduled job.
// It gathers every source (including the WB warehouse report) before writing
// any of the seven calculated columns, so a failed read leaves ОБОР untouched.
process.env.TZ = 'Asia/Dubai';

const fs = require('fs');
const os = require('os');
const path = require('path');
const axios = require('axios');
const dotenv = require('dotenv');
const { google } = require('googleapis');

const ROOT = __dirname;
const SPREADSHEET_ID = process.env.CHECKSHEETS_SPREADSHEET_ID ||
  '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
const TARGET_SHEET = 'ОБОР';
const WB_ANALYTICS_BASE_URL = 'https://seller-analytics-api.wildberries.ru';
const WB_WAREHOUSE_REMAINS_URL = `${WB_ANALYTICS_BASE_URL}/api/v1/warehouse_remains`;
const WB_TOTAL_WAREHOUSE = 'Всего находится на складах';
const WB_LIVE_WAREHOUSE = 'Склад WB РФ';
const WB_REQUEST_INTERVAL_MS = 12000;
const WB_REPORT_POLL_INTERVAL_MS = 5000;
const WB_REPORT_MAX_POLLS = 12;
const WB_REPORT_PAGE_LIMIT = 1000;
const WB_MAX_ATTEMPTS = 4;
const WB_TOKEN_FILE = process.env.WB_API_TOKEN_FILE ||
  path.join(os.homedir(), 'AI agents', 'secrets', 'wb_api_token');
const GOOGLE_CREDENTIALS = process.env.GOOGLE_APPLICATION_CREDENTIALS ||
  path.join(ROOT, 'nomadic-bedrock-485314-b0-d7624dedd83c.json');

dotenv.config({ path: path.join(ROOT, '.env'), quiet: true });

const VALUE_CONFIG = [
  {
    key: 'ozonStock',
    targetHeader: 'Озон ост',
    sourceSheet: 'ТЕСТ',
    articleColumn: 'A',
    valueColumns: ['F'],
    subtractColumns: [],
  },
  {
    key: 'ozonMonthWithdrawal',
    targetHeader: 'Уход месяц',
    sourceSheet: 'ТЕСТ',
    articleColumn: 'A',
    valueColumns: ['AQ', 'AR'],
    subtractColumns: ['BH'],
  },
  {
    key: 'ozonMonthBuyout',
    targetHeader: 'Факт выкупа месяц',
    sourceSheet: 'UNIT API',
    articleColumn: 'A',
    valueColumns: ['M'],
    subtractColumns: [],
  },
  { key: 'wbStock', targetHeader: 'ВБ всего', sourceType: 'wbWarehouseDead' },
  { key: 'wbStockObor', targetHeader: 'ВБ ост', sourceType: 'wbWarehouseLive' },
  {
    key: 'wbMonthWithdrawal',
    targetHeader: 'ВБ Ух',
    sourceSheet: 'ТЕСТ',
    articleColumn: 'A',
    valueColumns: ['AV', 'AW'],
    subtractColumns: [],
  },
  {
    key: 'wbMonthBuyout',
    targetHeader: 'ВБ факт выкуп месяц',
    sourceSheet: 'UNIT WB',
    articleColumn: 'A',
    valueColumns: ['AP'],
    subtractColumns: [],
  },
];

// Fixed source columns are part of the documented sheet layout. Verify their
// visible headers before using them so a moved column cannot silently corrupt
// the summary.
const SOURCE_HEADERS = [
  { sheet: 'ТЕСТ', column: 'A', header: 'Артикул' },
  { sheet: 'ТЕСТ', column: 'F', header: 'Остаток ФБО ОЗОН' },
  { sheet: 'ТЕСТ', column: 'AQ', header: 'Продажи штуки месяц FBO' },
  { sheet: 'ТЕСТ', column: 'AR', header: 'Продажи штуки месяц FBS' },
  { sheet: 'ТЕСТ', column: 'BH', header: 'Отмены Озон' },
  { sheet: 'ТЕСТ', column: 'AV', header: 'Продажи штуки месяц FBO ВБ' },
  { sheet: 'ТЕСТ', column: 'AW', header: 'Продажи штуки месяц FBS ВБ' },
  { sheet: 'UNIT API', column: 'A', header: 'Артикул' },
  { sheet: 'UNIT API', column: 'M', header: 'UNIT ШТ' },
  { sheet: 'UNIT WB', column: 'A', header: 'Артикул' },
  { sheet: 'UNIT WB', column: 'AP', header: 'ВЫКУП ШТ API' },
];

const text = value => String(value == null ? '' : value).trim();
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const quoteSheet = name => `'${String(name).replace(/'/g, "''")}'`;

function normalizeHeader(value) {
  return text(value).replace(/\s+/g, ' ').trim().toLocaleLowerCase('ru-RU').replace(/ё/g, 'е');
}

function normalizeArticle(value) {
  return String(value == null ? '' : value).replace(/[\s\u00a0]/g, '').trim();
}

function parseArticle(article) {
  const match = String(article).match(/^(.*)-([0-9]+)$/);
  if (!match) return { base: article, multiplier: 1 };
  return { base: match[1], multiplier: Number(match[2]) || 1 };
}

function parseNumber(value) {
  if (value === null || value === undefined || value === '') return 0;
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0;
  const parsed = Number(String(value).replace(/[\s\u00a0]/g, '').replace(/%/g, '').replace(/,/g, '.'));
  return Number.isFinite(parsed) ? parsed : 0;
}

function columnNumber(column) {
  return String(column).toUpperCase().split('').reduce(
    (result, letter) => result * 26 + letter.charCodeAt(0) - 64,
    0,
  );
}

function columnLetter(column) {
  let value = Number(column);
  let result = '';
  while (value > 0) {
    const remainder = (value - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

function parseSheetRows(response, sheetName) {
  const rows = response?.data?.values || [];
  if (!Array.isArray(rows)) throw new Error(`${sheetName}: Google Sheets вернул неожиданный формат`);
  return rows;
}

function validateHeaderAt(rows, sheetName, column, expected) {
  const actual = rows[0]?.[columnNumber(column) - 1];
  if (normalizeHeader(actual) !== normalizeHeader(expected)) {
    throw new Error(`${sheetName}: в колонке ${column} ожидался заголовок «${expected}», получен «${text(actual)}»`);
  }
}

function resolveUniqueHeader(headers, expected, sheetName) {
  const wanted = normalizeHeader(expected);
  const matches = headers.reduce((columns, value, index) => {
    if (normalizeHeader(value) === wanted) columns.push(index + 1);
    return columns;
  }, []);
  if (matches.length !== 1) {
    throw new Error(`${sheetName}: заголовок «${expected}» найден ${matches.length} раз; колонки: ${matches.join(', ') || '—'}`);
  }
  return matches[0];
}

function buildSourceMap(rows, item) {
  const articleIndex = columnNumber(item.articleColumn) - 1;
  const valueIndexes = item.valueColumns.map(column => columnNumber(column) - 1);
  const subtractIndexes = item.subtractColumns.map(column => columnNumber(column) - 1);
  const result = Object.create(null);

  rows.slice(1).forEach(row => {
    const article = normalizeArticle(row[articleIndex]);
    if (!article) return;
    const parsed = parseArticle(article);
    const value = valueIndexes.reduce((sum, index) => sum + parseNumber(row[index]), 0);
    const subtractValue = subtractIndexes.reduce((sum, index) => sum + parseNumber(row[index]), 0);
    result[parsed.base] = (result[parsed.base] || 0) + Math.max(0, value - subtractValue) * parsed.multiplier;
  });
  return result;
}

function normalizeWbBaseArticle(article) {
  const base = parseArticle(normalizeArticle(article)).base;
  // Sheets may remove leading zeroes from numeric-only article codes.
  return /^\d+$/.test(base) ? base.replace(/^0+(?=\d)/, '') : base;
}

function aggregateWarehouseRows(rows) {
  const total = Object.create(null);
  const live = Object.create(null);
  const totalByBase = Object.create(null);
  const liveByBase = Object.create(null);
  let validRows = 0;

  (rows || []).forEach(row => {
    const article = normalizeArticle(row && (row.vendorCode || row.supplierArticle));
    if (!article || !Array.isArray(row.warehouses)) return;
    const totalQuantity = row.warehouses.reduce((sum, warehouse) =>
      warehouse?.warehouseName === WB_TOTAL_WAREHOUSE
        ? sum + Math.max(0, parseNumber(warehouse.quantity))
        : sum, 0);
    const liveQuantity = row.warehouses.reduce((sum, warehouse) =>
      warehouse?.warehouseName === WB_LIVE_WAREHOUSE
        ? sum + Math.max(0, parseNumber(warehouse.quantity))
        : sum, 0);
    const multiplier = parseArticle(article).multiplier;
    const totalUnits = totalQuantity * multiplier;
    const liveUnits = liveQuantity * multiplier;
    const base = normalizeWbBaseArticle(article);

    total[article] = (total[article] || 0) + totalUnits;
    live[article] = (live[article] || 0) + liveUnits;
    totalByBase[base] = (totalByBase[base] || 0) + totalUnits;
    liveByBase[base] = (liveByBase[base] || 0) + liveUnits;
    validRows++;
  });

  return { total, live, totalByBase, liveByBase, validRows };
}

function subtractMaps(totalMap, liveMap) {
  const result = Object.create(null);
  const keys = new Set([...Object.keys(totalMap || {}), ...Object.keys(liveMap || {})]);
  keys.forEach(key => {
    result[key] = Math.max(0, parseNumber(totalMap?.[key]) - parseNumber(liveMap?.[key]));
  });
  return result;
}

function resolveWarehouseValue(valueMap, article, baseValueMap) {
  const exact = normalizeArticle(article);
  if (Object.prototype.hasOwnProperty.call(valueMap || {}, exact)) return valueMap[exact];
  const parsed = parseArticle(exact);
  const normalizedBase = normalizeWbBaseArticle(exact);
  if (exact === parsed.base && Object.prototype.hasOwnProperty.call(baseValueMap || {}, normalizedBase)) {
    return baseValueMap[normalizedBase];
  }
  const baseValue = valueMap?.[parsed.base];
  if (baseValue !== undefined) return baseValue * parsed.multiplier;
  if (exact === parsed.base && Object.prototype.hasOwnProperty.call(valueMap || {}, `${exact}-1`)) {
    return valueMap[`${exact}-1`];
  }
  return 0;
}

function wbToken() {
  const configured = text(process.env.WB_API_TOKEN);
  let token = configured;
  if (!token) {
    if (!fs.existsSync(WB_TOKEN_FILE)) throw new Error(`Не найден файл токена WB: ${WB_TOKEN_FILE}`);
    token = fs.readFileSync(WB_TOKEN_FILE, 'utf8').trim();
  }
  if (!token) throw new Error('Не задан токен WB');
  return token.toLowerCase().startsWith('bearer ') ? token : `Bearer ${token}`;
}

async function sheetsClient() {
  if (!fs.existsSync(GOOGLE_CREDENTIALS)) {
    throw new Error(`Нет файла service account: ${GOOGLE_CREDENTIALS}`);
  }
  const auth = new google.auth.GoogleAuth({
    keyFile: GOOGLE_CREDENTIALS,
    scopes: ['https://www.googleapis.com/auth/spreadsheets'],
  });
  return google.sheets({ version: 'v4', auth: await auth.getClient() });
}

async function readSheet(sheets, sheetName, lastColumn) {
  const range = `${quoteSheet(sheetName)}!A:${columnLetter(lastColumn)}`;
  const response = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range,
    valueRenderOption: 'UNFORMATTED_VALUE',
  });
  return parseSheetRows(response, sheetName);
}

function responseSummary(data) {
  if (typeof data === 'string') return data.slice(0, 500);
  try {
    return JSON.stringify(data).slice(0, 500);
  } catch (_) {
    return String(data).slice(0, 500);
  }
}

function retryDelay(response, attempt) {
  if (response?.status === 429) {
    const retrySeconds = Number(response.headers?.['x-ratelimit-retry']);
    return Math.min(300000, Math.max(WB_REQUEST_INTERVAL_MS,
      Number.isFinite(retrySeconds) && retrySeconds > 0 ? retrySeconds * 1000 : WB_REQUEST_INTERVAL_MS));
  }
  return Math.min(60000, 3000 * (2 ** (attempt - 1)));
}

async function waitForWbSlot(state) {
  const elapsed = Date.now() - state.lastRequestAt;
  if (state.lastRequestAt && elapsed < WB_REQUEST_INTERVAL_MS) {
    await sleep(WB_REQUEST_INTERVAL_MS - elapsed);
  }
}

async function wbRequest(url, method, body, state, action) {
  for (let attempt = 1; attempt <= WB_MAX_ATTEMPTS; attempt++) {
    await waitForWbSlot(state);
    let response;
    try {
      response = await axios.request({
        url,
        method,
        data: body,
        headers: { Authorization: wbToken(), 'Content-Type': 'application/json' },
        timeout: 90000,
        validateStatus: () => true,
      });
    } catch (error) {
      state.lastRequestAt = Date.now();
      if (attempt === WB_MAX_ATTEMPTS) throw new Error(`WB warehouse: сетевая ошибка (${action}): ${error.message}`);
      const delayMs = retryDelay(null, attempt);
      console.warn(`WB warehouse: сетевая ошибка; повтор ${attempt + 1}/${WB_MAX_ATTEMPTS} через ${Math.ceil(delayMs / 1000)} сек`);
      await sleep(delayMs);
      continue;
    }
    state.lastRequestAt = Date.now();
    if (response.status >= 200 && response.status < 300) return response.data;
    const detail = responseSummary(response.data);
    if ((response.status === 429 || response.status >= 500) && attempt < WB_MAX_ATTEMPTS) {
      const delayMs = retryDelay(response, attempt);
      console.warn(`WB warehouse: HTTP ${response.status}; повтор ${attempt + 1}/${WB_MAX_ATTEMPTS} через ${Math.ceil(delayMs / 1000)} сек`);
      await sleep(delayMs);
      continue;
    }
    throw new Error(`WB warehouse: HTTP ${response.status} (${action}): ${detail}`);
  }
  throw new Error(`WB warehouse: исчерпаны повторы (${action})`);
}

async function fetchWarehouseRemains() {
  const requestState = { lastRequestAt: 0 };
  const createUrl = `${WB_WAREHOUSE_REMAINS_URL}?locale=ru&groupBySa=true&groupByNm=true`;
  const createPayload = await wbRequest(createUrl, 'get', undefined, requestState, 'создание отчёта');
  const taskId = createPayload?.data?.taskId;
  if (!taskId) throw new Error(`WB warehouse report: в ответе создания нет taskId: ${responseSummary(createPayload)}`);
  console.log(`WB warehouse report: задача ${taskId} создана`);

  let statusPayload = null;
  for (let poll = 0; poll < WB_REPORT_MAX_POLLS; poll++) {
    await sleep(WB_REPORT_POLL_INTERVAL_MS);
    statusPayload = await wbRequest(
      `${WB_WAREHOUSE_REMAINS_URL}/tasks/${encodeURIComponent(taskId)}/status`,
      'get', undefined, requestState, 'проверка готовности');
    const status = statusPayload?.data?.status;
    if (status === 'done') break;
    if (status === 'failed' || status === 'canceled' || status === 'cancelled') {
      throw new Error(`WB warehouse report: задача ${taskId} завершилась со статусом ${status}: ${responseSummary(statusPayload)}`);
    }
    console.log(`WB warehouse report: ожидание, статус ${status || 'не указан'} (${poll + 1}/${WB_REPORT_MAX_POLLS})`);
  }
  if (statusPayload?.data?.status !== 'done') {
    throw new Error(`WB warehouse report: не готов после ${WB_REPORT_MAX_POLLS} проверок`);
  }

  let rows = await wbRequest(
    `${WB_WAREHOUSE_REMAINS_URL}/tasks/${encodeURIComponent(taskId)}/download`,
    'get', undefined, requestState, 'загрузка отчёта');
  if (typeof rows === 'string') {
    try { rows = JSON.parse(rows); } catch (error) {
      throw new Error(`WB warehouse report: ответ загрузки не является JSON: ${error.message}`);
    }
  }
  if (!Array.isArray(rows)) throw new Error('WB warehouse report: в загрузке ожидался массив товаров');

  const maps = aggregateWarehouseRows(rows);
  console.log(`WB warehouse report: строк=${rows.length}, артикулов=${Object.keys(maps.total).length}, склад «${WB_LIVE_WAREHOUSE}»=${Object.keys(maps.live).length}`);
  return maps;
}

function targetValues(item, targetRows, articleColumn, sourceMaps, wbMaps, sourceBaseMaps) {
  const valueMap = sourceMaps[item.key] || Object.create(null);
  const isWarehouse = item.sourceType === 'wbWarehouseDead' || item.sourceType === 'wbWarehouseLive';
  return targetRows.slice(1).map(row => {
    const article = normalizeArticle(row[articleColumn - 1]);
    if (!article) return [''];
    const parsed = parseArticle(article);
    const raw = isWarehouse
      ? resolveWarehouseValue(valueMap, article, sourceBaseMaps[item.key])
      : (valueMap[parsed.base] || 0);
    return [Math.round((Number(raw) || 0) * 100) / 100];
  });
}

async function updateOborSummary({ dryRun = process.argv.includes('--dry-run') } = {}) {
  const sheets = await sheetsClient();
  const targetRows = await readSheet(sheets, TARGET_SHEET, 702); // A:ZZ
  if (!targetRows.length) throw new Error('ОБОР: отсутствует строка заголовков');
  const targetHeaderRow = targetRows[0];
  const articleColumn = resolveUniqueHeader(targetHeaderRow, 'Артикул', TARGET_SHEET);
  const targetColumns = Object.create(null);
  VALUE_CONFIG.forEach(item => {
    targetColumns[item.key] = resolveUniqueHeader(targetHeaderRow, item.targetHeader, TARGET_SHEET);
  });

  const lastSourceColumns = Object.create(null);
  SOURCE_HEADERS.forEach(item => {
    lastSourceColumns[item.sheet] = Math.max(lastSourceColumns[item.sheet] || 1, columnNumber(item.column));
  });
  const sourceRows = Object.create(null);
  for (const [sheetName, lastColumn] of Object.entries(lastSourceColumns)) {
    sourceRows[sheetName] = await readSheet(sheets, sheetName, lastColumn);
    if (!sourceRows[sheetName].length) throw new Error(`${sheetName}: отсутствует строка заголовков`);
  }
  SOURCE_HEADERS.forEach(item => validateHeaderAt(sourceRows[item.sheet], item.sheet, item.column, item.header));

  const sourceMaps = Object.create(null);
  VALUE_CONFIG.forEach(item => {
    if (!item.sourceSheet) return;
    sourceMaps[item.key] = buildSourceMap(sourceRows[item.sourceSheet], item);
  });

  // API and all source reads complete before the first destination write.
  const wbMaps = await fetchWarehouseRemains();
  const deadByArticle = subtractMaps(wbMaps.total, wbMaps.live);
  const deadByBase = subtractMaps(wbMaps.totalByBase, wbMaps.liveByBase);
  sourceMaps.wbStock = deadByArticle;
  sourceMaps.wbStockObor = wbMaps.live;
  const sourceBaseMaps = {
    wbStock: deadByBase,
    wbStockObor: wbMaps.liveByBase,
  };

  const rowCount = Math.max(0, targetRows.length - 1);
  if (!rowCount) {
    console.log('ОБОР: нет строк для записи');
    return { rows: 0, nonZero: {} };
  }

  const updates = [];
  const nonZero = Object.create(null);
  for (const item of VALUE_CONFIG) {
    const values = targetValues(item, targetRows, articleColumn, sourceMaps, wbMaps, sourceBaseMaps);
    nonZero[item.key] = values.reduce((count, row) => count + (Number(row[0]) !== 0 ? 1 : 0), 0);
    const column = targetColumns[item.key];
    const letter = columnLetter(column);
    // Refresh headers too; this removes any legacy formula left in a header cell.
    updates.push({ range: `${quoteSheet(TARGET_SHEET)}!${letter}1`, majorDimension: 'ROWS', values: [[item.targetHeader]] });
    updates.push({ range: `${quoteSheet(TARGET_SHEET)}!${letter}2:${letter}${targetRows.length}`, majorDimension: 'ROWS', values });
    console.log(`Подготовлено: ${item.targetHeader}; строк=${rowCount}; ненулевых=${nonZero[item.key]}`);
  }

  if (dryRun) {
    console.log(`ОБОР: dry-run; подготовлены ${updates.length} диапазонов, запись отключена`);
    return { rows: rowCount, nonZero, dryRun: true };
  }

  await sheets.spreadsheets.values.batchUpdate({
    spreadsheetId: SPREADSHEET_ID,
    requestBody: { valueInputOption: 'RAW', data: updates },
  });
  console.log(`ОБОР: updateOborSummary завершён; строк=${rowCount}; заголовков обновлено=${VALUE_CONFIG.length}; СДЭК Остаток отключён`);
  return { rows: rowCount, nonZero };
}

if (require.main === module) {
  updateOborSummary().catch(error => {
    console.error(error.stack || error);
    process.exitCode = 1;
  });
}

module.exports = {
  aggregateWarehouseRows,
  buildSourceMap,
  normalizeWbBaseArticle,
  parseArticle,
  parseNumber,
  resolveWarehouseValue,
  subtractMaps,
  updateOborSummary,
};
