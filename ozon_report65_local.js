#!/usr/bin/env node
'use strict';

// Local equivalent of updateOzonReport65() for the UNIT API worksheet.
// The fixed Report65 columns are a documented service layout: U1 stores the
// common-extra coefficient, so U cannot be resolved by its visible header.
process.env.TZ = 'Asia/Dubai';

const fs = require('fs');
const path = require('path');
const csv = require('csv-parse/sync');
const axios = require('axios');
const dotenv = require('dotenv');
const { google } = require('googleapis');

const ROOT = __dirname;
const SPREADSHEET_ID = process.env.CHECKSHEETS_SPREADSHEET_ID || '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
const SHEET_NAME = 'UNIT API';
const SERVICE_ACCOUNT_FILE = process.env.GOOGLE_APPLICATION_CREDENTIALS || path.join(ROOT, 'nomadic-bedrock-485314-b0-d7624dedd83c.json');
const SECRET_FILE = process.env.OZON_REVIEWS_SECRETS_FILE || '/Users/vladimirgrebennikov/AI agents/secrets/ozon-reviews.env';
const FINANCE_URL = 'https://api-seller.ozon.ru/v1/finance/accrual/by-day';
const PRODUCT_INFO_URL = 'https://api-seller.ozon.ru/v3/product/info/list';
const PLACEMENT_CREATE_URL = 'https://api-seller.ozon.ru/v1/report/placement/by-products/create';
const REPORT_INFO_URL = 'https://api-seller.ozon.ru/v1/report/info';
const STORAGE_REPORT_MAX_WAIT_MS = 5 * 60 * 1000;
const STORAGE_REPORT_POLL_MS = 10 * 1000;
const FINANCE_PAGE_SIZE = 1000;
const PRODUCT_INFO_BATCH_SIZE = 1000;
const REQUEST_INTERVAL_MS = 50; // 20 requests/second, matching the shared Ozon Seller limit.
const MAX_HTTP_ATTEMPTS = 5;
const COMMON_COSTS_KEY = '__ozon_report65_common_costs__';
const HEADER_SCAN_ROWS = 20;

dotenv.config({ path: SECRET_FILE, quiet: true });
dotenv.config({ path: path.join(ROOT, '.env'), quiet: true });

// This Apps Script layout is intentionally fixed; column U is the exception
// because U1 is a coefficient cell rather than a visible header.
const COLUMNS = {
  article: 1,
  sku: 5,
  unitSum: 10,
  upd: 11,
  unitQty: 13,
  reward: 14,
  logistics: 15,
  overpayment: 16,
  storage: 19,
  extra: 20,
  commonExtra: 21,
  starsAndAcquiring: 22,
  clicks: 24,
  orders: 25,
};

const EXPECTED_HEADERS = {
  article: 'Артикул',
  sku: 'СКУ OZ',
  unitSum: 'UNIT СУММА',
  upd: 'УПД',
  unitQty: 'UNIT ШТ',
  reward: 'ВОЗНАГРАЖДЕНИЕ',
  logistics: 'ЛОГИСТИКА',
  overpayment: 'ПЕРЕПЛАТА',
  storage: 'ХРАНЕНИЕ',
  extra: 'ДОП',
  starsAndAcquiring: 'ЗВЕЗДЫ + ЭКВ',
  clicks: 'КЛИКИ',
  orders: 'ЗАКАЗЫ',
};

const REQUIRED_HEADER_KEYS = [
  'article', 'sku', 'unitSum', 'unitQty', 'reward', 'logistics',
  'overpayment', 'storage', 'extra', 'starsAndAcquiring', 'clicks', 'orders',
];

const OUTPUT_FIELDS = [
  ['unitSum', 'UNIT СУММА', data => data.unitSum],
  ['unitQty', 'UNIT ШТ', data => data.unitQty],
  ['reward', 'ВОЗНАГРАЖДЕНИЕ', data => data.reward],
  ['logistics', 'ЛОГИСТИКА', data => data.logistics],
  ['overpayment', 'ПЕРЕПЛАТА', data => data.overpayment],
  ['storage', 'ХРАНЕНИЕ', data => data.storage],
  ['extra', 'ДОП', data => data.extra],
  ['commonExtra', 'ОЗОН ДОП ВОЗНЯ', data => data.commonExtra],
  ['starsAndAcquiring', 'ЗВЕЗДЫ + ЭКВ', data => data.starsAndAcquiring],
];

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const text = value => String(value ?? '').trim();
const normalizeKey = value => text(value).replace(/&#x([0-9a-f]+);/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
  .replace(/&#([0-9]+);/g, (_, dec) => String.fromCharCode(parseInt(dec, 10))).trim();
const normalizeHeader = value => normalizeKey(value).toLowerCase().replace(/ё/g, 'е').replace(/\s+/g, ' ').trim();

function log(message) {
  console.log(`${new Date().toISOString()} ${message}`);
}

function money(value) {
  if (value && typeof value === 'object' && value.amount !== undefined) value = value.amount;
  if (value === null || value === undefined || value === '') return 0;
  let normalized = String(value)
    .replace(/\u00a0/g, '')
    .replace(/\s+/g, '')
    .replace(/руб/gi, '')
    .replace(/[₽р]/gi, '');
  if (normalized.includes(',') && normalized.includes('.')) normalized = normalized.replace(/\./g, '').replace(',', '.');
  else normalized = normalized.replace(',', '.');
  const number = Number(normalized);
  return Number.isFinite(number) ? number : 0;
}

const roundMoney = value => Math.round((Number(value) || 0) * 100) / 100;

function createBucket() {
  return {
    unitSum: 0,
    unitQty: 0,
    reward: 0,
    logistics: 0,
    overpayment: 0,
    extra: 0,
    starsAndAcquiring: 0,
    commonExtra: 0,
    cpoPayment: 0,
    clicksPayment: 0,
  };
}

function sellerHeaders() {
  const clientId = text(process.env.OZON_CLIENT_ID);
  const apiKey = text(process.env.OZON_API_KEY);
  if (!clientId || !apiKey) {
    throw new Error(`Не заданы OZON_CLIENT_ID/OZON_API_KEY; проверьте защищённый файл ${SECRET_FILE}`);
  }
  return { 'Client-Id': clientId, 'Api-Key': apiKey, 'Content-Type': 'application/json' };
}

let lastSellerRequestAt = 0;
async function sellerRequest(url, payload, { responseType = 'json', timeout = 120_000 } = {}) {
  let lastError;
  for (let attempt = 0; attempt < MAX_HTTP_ATTEMPTS; attempt++) {
    const wait = REQUEST_INTERVAL_MS - (Date.now() - lastSellerRequestAt);
    if (wait > 0) await sleep(wait);
    lastSellerRequestAt = Date.now();
    try {
      const response = await axios.post(url, payload, {
        headers: sellerHeaders(),
        timeout,
        responseType,
        validateStatus: () => true,
      });
      if (response.status >= 200 && response.status < 300) return response.data;
      const detail = typeof response.data === 'string'
        ? response.data.slice(0, 300)
        : JSON.stringify(response.data || {}).slice(0, 300);
      lastError = new Error(`Ozon HTTP ${response.status}${detail ? `: ${detail}` : ''}`);
      if (response.status !== 429 && response.status < 500) throw lastError;
      const retryAfter = Number(response.headers?.['retry-after']);
      const delay = Math.max(Number.isFinite(retryAfter) ? retryAfter * 1000 : 0, Math.min(60_000, 5_000 * 2 ** attempt));
      if (attempt < MAX_HTTP_ATTEMPTS - 1) log(`Ozon HTTP ${response.status}; повтор через ${Math.ceil(delay / 1000)} сек.`);
      if (attempt < MAX_HTTP_ATTEMPTS - 1) await sleep(delay);
    } catch (error) {
      lastError = error;
      if (/^Ozon HTTP 4\d\d/.test(error.message)) throw error;
      if (attempt < MAX_HTTP_ATTEMPTS - 1) {
        const delay = Math.min(60_000, 2_000 * 2 ** attempt);
        log(`Сетевая ошибка Ozon; повтор через ${Math.ceil(delay / 1000)} сек. (${error.code || error.name})`);
        await sleep(delay);
      }
    }
  }
  throw lastError || new Error('Ozon: исчерпаны повторы запроса');
}

async function downloadReport(url) {
  let lastError;
  for (let attempt = 0; attempt < MAX_HTTP_ATTEMPTS; attempt++) {
    try {
      const response = await axios.get(url, { responseType: 'arraybuffer', timeout: 180_000, validateStatus: () => true });
      if (response.status >= 200 && response.status < 300) return Buffer.from(response.data);
      lastError = new Error(`Скачивание отчёта Ozon HTTP ${response.status}`);
      if (response.status !== 429 && response.status < 500) throw lastError;
    } catch (error) {
      lastError = error;
      if (/Скачивание отчёта Ozon HTTP 4\d\d/.test(error.message)) throw error;
    }
    if (attempt < MAX_HTTP_ATTEMPTS - 1) await sleep(Math.min(60_000, 2_000 * 2 ** attempt));
  }
  throw lastError || new Error('Не удалось скачать отчёт хранения');
}

async function createSheetsClient() {
  if (!fs.existsSync(SERVICE_ACCOUNT_FILE)) throw new Error(`Не найден Google service-account JSON: ${SERVICE_ACCOUNT_FILE}`);
  const auth = new google.auth.GoogleAuth({
    keyFile: SERVICE_ACCOUNT_FILE,
    scopes: ['https://www.googleapis.com/auth/spreadsheets'],
  });
  return google.sheets({ version: 'v4', auth: await auth.getClient() });
}

function quoteSheetName(name) {
  return `'${name.replace(/'/g, "''")}'`;
}

function columnLetter(column) {
  let value = column;
  let result = '';
  while (value > 0) {
    const remainder = (value - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

function findHeaderRow(rows) {
  const requiredLabels = REQUIRED_HEADER_KEYS.map(key => EXPECTED_HEADERS[key]);
  let best = { rowIndex: 0, score: -1, row: rows[0] || [] };
  for (let rowIndex = 0; rowIndex < Math.min(rows.length, HEADER_SCAN_ROWS); rowIndex++) {
    const row = rows[rowIndex] || [];
    const normalized = row.map(normalizeHeader);
    const score = requiredLabels.filter(header => normalized.includes(normalizeHeader(header))).length;
    if (score > best.score) best = { rowIndex, score, row };
  }
  const minScore = REQUIRED_HEADER_KEYS.length;
  if (best.score !== minScore) {
    throw new Error(`UNIT API: не найдена строка заголовков Report65 (${best.score}/${minScore} полей)`);
  }

  // Check the exact fixed read/write columns before any API work or sheet write.
  // The common-extra coefficient occupies U1; U is the only header exception.
  const headerChecks = Object.entries(EXPECTED_HEADERS).filter(([key]) => key !== 'commonExtra');
  const mismatches = [];
  for (const [key, expected] of headerChecks) {
    const actual = best.row[COLUMNS[key] - 1];
    if (normalizeHeader(actual) !== normalizeHeader(expected)) {
      mismatches.push(`${columnLetter(COLUMNS[key])}: ожидалось «${expected}», найдено «${text(actual)}»`);
    }
  }
  if (mismatches.length) throw new Error(`UNIT API: схема фиксированных колонок Report65 изменилась; запись остановлена: ${mismatches.join('; ')}`);
  return best.rowIndex;
}

async function readWorksheet(sheets) {
  const range = `${quoteSheetName(SHEET_NAME)}!A:Y`;
  const response = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range,
    valueRenderOption: 'UNFORMATTED_VALUE',
  });
  const rows = response.data.values || [];
  if (rows.length < 2) throw new Error('UNIT API: нет строк для обновления');
  const headerIndex = findHeaderRow(rows);
  const items = rows.slice(headerIndex + 1).map(row => ({
    article: normalizeKey(row[COLUMNS.article - 1]),
    sku: normalizeKey(row[COLUMNS.sku - 1]),
    upd: money(row[COLUMNS.upd - 1]),
  }));
  if (!items.length) throw new Error(`UNIT API: нет строк ниже заголовка ${headerIndex + 1}`);
  const validRows = items.filter(item => item.article || item.sku).length;
  if (!validRows) throw new Error('UNIT API: в колонках Артикул и СКУ OZ нет товаров');
  return { headerRow: headerIndex + 1, firstDataRow: headerIndex + 2, items, validRows };
}

function getDateRange(now = new Date()) {
  // Match GAS new Date(year, month - 1, day) rollover semantics exactly.
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  const from = new Date(now.getFullYear(), now.getMonth() - 1, now.getDate());
  const format = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  return { from: format(from), to: format(yesterday) };
}

function* eachDay(from, to) {
  const [fromYear, fromMonth, fromDay] = from.split('-').map(Number);
  const [toYear, toMonth, toDay] = to.split('-').map(Number);
  const current = new Date(Date.UTC(fromYear, fromMonth - 1, fromDay));
  const end = Date.UTC(toYear, toMonth - 1, toDay);
  while (current.getTime() <= end) {
    yield current.toISOString().slice(0, 10);
    current.setUTCDate(current.getUTCDate() + 1);
  }
}

function addSkuAmount(result, unknownTypes, sku, typeName, group, amount) {
  if (!amount) return;
  if (!group) {
    unknownTypes[typeName] = (unknownTypes[typeName] || 0) + amount;
    return;
  }
  if (!result[sku]) result[sku] = createBucket();
  result[sku][group] += amount;
}

function deliveryFeeGroup(typeId) {
  if (typeId === '32') return 'logistics';
  return typeId ? 'extra' : '';
}

function itemFeeGroup(typeId) {
  if (['1', '3', '51', '74'].includes(typeId)) return 'starsAndAcquiring';
  return typeId ? 'extra' : '';
}

function shouldCountUnitQty(saleAmount, sellerPrice, product) {
  if (saleAmount > 0 && sellerPrice > 0) return true;
  if (!(saleAmount < 0) || !(sellerPrice < 0)) return false;
  return (product?.delivery?.services || []).some(service => money(service?.accrued) > 0);
}

function calculateUnitQty(saleAmount, sellerPrice, product) {
  if (!shouldCountUnitQty(saleAmount, sellerPrice, product)) return 0;
  const quantity = Math.abs(saleAmount / sellerPrice);
  if (!Number.isFinite(quantity) || quantity <= 0) return 0;
  return Math.round(quantity);
}

function aggregateAccrual(result, unknownTypes, accrual) {
  const products = Array.isArray(accrual?.posting?.products) ? accrual.posting.products : [];
  for (const product of products) {
    const sku = normalizeKey(product?.sku);
    if (!sku) continue;
    const commission = product.commission || {};
    const saleAmount = money(commission.sale_amount);
    const sellerPrice = money(commission.seller_price);
    addSkuAmount(result, unknownTypes, sku, 'commission.sale_amount', 'unitSum', saleAmount);
    addSkuAmount(result, unknownTypes, sku, 'commission.unit_qty', 'unitQty', calculateUnitQty(saleAmount, sellerPrice, product));
    addSkuAmount(result, unknownTypes, sku, 'commission.commission', 'reward', money(commission.commission));

    const services = Array.isArray(product.delivery?.services) ? product.delivery.services : [];
    for (const service of services) {
      const typeId = normalizeKey(service?.type_id);
      const amount = money(service?.accrued);
      if (typeId === '32' && amount > 0) {
        addSkuAmount(result, unknownTypes, sku, 'delivery:32:overpayment', 'overpayment', -amount);
      } else {
        addSkuAmount(result, unknownTypes, sku, `delivery:${typeId}`, deliveryFeeGroup(typeId), amount);
      }
    }
  }

  const itemFees = Array.isArray(accrual?.item_fees?.fees) ? accrual.item_fees.fees : [];
  for (const itemFee of itemFees) {
    const sku = normalizeKey(itemFee?.sku);
    if (!sku) continue;
    for (const fee of (Array.isArray(itemFee.fees) ? itemFee.fees : [])) {
      const typeId = normalizeKey(fee?.type_id);
      addSkuAmount(result, unknownTypes, sku, `item_fee:${typeId}`, itemFeeGroup(typeId), money(fee?.accrued));
    }
  }

  const nonItemFee = accrual?.non_item_fee;
  if (nonItemFee && nonItemFee.type_id !== null && nonItemFee.type_id !== undefined) {
    const typeId = normalizeKey(nonItemFee.type_id);
    const amount = money(nonItemFee.accrued);
    if (amount) {
      if (!result[COMMON_COSTS_KEY]) result[COMMON_COSTS_KEY] = createBucket();
      const common = result[COMMON_COSTS_KEY];
      if (typeId === '41') common.clicksPayment += amount;
      else if (typeId === '54') common.cpoPayment += amount;
      else common.commonExtra += amount;
    }
  }
}

async function fetchAccruals(dateFrom, dateTo) {
  const result = {};
  const unknownTypes = {};
  let loaded = 0;
  let days = 0;
  for (const day of eachDay(dateFrom, dateTo)) {
    let lastId = '';
    const seenLastIds = new Set();
    let dayLoaded = 0;
    log(`Начисления Ozon: ${day}`);
    for (let page = 0; page < 10_000; page++) {
      const data = await sellerRequest(FINANCE_URL, { date: day, last_id: lastId });
      if (!data || !Array.isArray(data.accruals)) throw new Error(`Ozon accrual/by-day ${day}: отсутствует массив accruals`);
      for (const accrual of data.accruals) aggregateAccrual(result, unknownTypes, accrual);
      loaded += data.accruals.length;
      dayLoaded += data.accruals.length;
      const nextLastId = normalizeKey(data.last_id || '');
      if (!nextLastId || nextLastId === lastId || seenLastIds.has(nextLastId)) break;
      seenLastIds.add(nextLastId);
      lastId = nextLastId;
      if (page === 9_999) throw new Error(`Ozon accrual/by-day ${day}: превышен лимит страниц`);
    }
    days++;
    log(`Начисления Ozon ${day}: ${dayLoaded} записей`);
  }
  if (!loaded) throw new Error('Ozon accrual/by-day вернул 0 записей; запись в таблицу отменена');
  log(`Начисления Ozon: дней ${days}, записей ${loaded}, ключей ${Object.keys(result).length}`);
  const unknown = Object.entries(unknownTypes).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, 15);
  if (unknown.length) log(`Не классифицированные начисления: ${unknown.map(([key, value]) => `${key}=${roundMoney(value)}`).join('; ')}`);
  return result;
}

function addProductAliases(map, item) {
  if (!item) return;
  const offerId = normalizeKey(item.offer_id);
  if (!offerId) return;
  const aliases = [item.sku, item.fbo_sku, item.fbs_sku];
  for (const source of (Array.isArray(item.sources) ? item.sources : [])) aliases.push(source?.sku, source?.fbo_sku, source?.fbs_sku);
  for (const sku of aliases) {
    const key = normalizeKey(sku);
    if (key) map[key] = offerId;
  }
}

async function enrichOfferIds(accrualMap) {
  const skuKeys = Object.keys(accrualMap).filter(key => key !== COMMON_COSTS_KEY && /^\d+$/.test(key));
  if (!skuKeys.length) throw new Error('В начислениях Ozon не найдено SKU для сопоставления');
  const skuToOffer = {};
  for (let offset = 0; offset < skuKeys.length; offset += PRODUCT_INFO_BATCH_SIZE) {
    const batch = skuKeys.slice(offset, offset + PRODUCT_INFO_BATCH_SIZE);
    const data = await sellerRequest(PRODUCT_INFO_URL, { sku: batch });
    const items = Array.isArray(data?.items) ? data.items : (Array.isArray(data?.result?.items) ? data.result.items : null);
    if (!items) throw new Error(`Ozon product/info/list: нет массива items для пачки ${Math.floor(offset / PRODUCT_INFO_BATCH_SIZE) + 1}`);
    for (const item of items) addProductAliases(skuToOffer, item);
    log(`SKU → offer_id: пачка ${Math.floor(offset / PRODUCT_INFO_BATCH_SIZE) + 1}, ответов ${items.length}`);
  }
  let mapped = 0;
  for (const [sku, offerId] of Object.entries(skuToOffer)) {
    if (!accrualMap[sku]) continue;
    if (!accrualMap[offerId]) accrualMap[offerId] = createBucket();
    if (offerId === sku) continue;
    for (const field of Object.keys(createBucket())) accrualMap[offerId][field] += Number(accrualMap[sku][field]) || 0;
    mapped++;
  }
  if (!mapped) throw new Error('Ozon product/info/list не сопоставил начисления ни с одним offer_id');
  log(`SKU → offer_id: сопоставлено ${mapped} из ${skuKeys.length}`);
  return { mapped, skuCount: skuKeys.length };
}

async function createPlacementReport(dateFrom, dateTo) {
  const data = await sellerRequest(PLACEMENT_CREATE_URL, { date_from: dateFrom, date_to: dateTo });
  const code = text(data?.code || data?.result?.code);
  if (!code) throw new Error('Ozon не вернул code отчёта хранения; запись в таблицу отменена');
  log(`Создан отчёт хранения Ozon: ${code}`);
  return code;
}

async function waitForReport(code) {
  const started = Date.now();
  let attempt = 0;
  while (Date.now() - started < STORAGE_REPORT_MAX_WAIT_MS) {
    attempt++;
    const data = await sellerRequest(REPORT_INFO_URL, { code });
    const info = data?.result || data;
    if (!info || typeof info !== 'object') throw new Error(`Ozon report/info: некорректный ответ для ${code}`);
    const status = normalizeHeader(info.status || info.state || '');
    const fileUrl = text(info.file || info.file_url || info.download_url || info.url);
    log(`Отчёт хранения ${code}: попытка ${attempt}, статус ${status || 'не указан'}`);
    if (fileUrl) return fileUrl;
    if (status === 'error' || status === 'failed') throw new Error(`Ozon завершил отчёт хранения со статусом ${status}`);
    await sleep(STORAGE_REPORT_POLL_MS);
  }
  throw new Error(`Истекло время ожидания отчёта хранения ${code}`);
}

function columnIndexFromRef(ref) {
  const letters = String(ref || '').replace(/[0-9]/g, '');
  let index = 0;
  for (const letter of letters) index = index * 26 + letter.toUpperCase().charCodeAt(0) - 64;
  return Math.max(index - 1, 0);
}

function parseXlsxRows(buffer) {
  const zip = require('jszip');
  return zip.loadAsync(buffer).then(async workbook => {
    const names = Object.keys(workbook.files);
    const sharedFile = workbook.file('xl/sharedStrings.xml');
    const sharedStrings = [];
    if (sharedFile) {
      const xml = await sharedFile.async('string');
      const strings = xml.match(/<si(?:\s[^>]*)?>[\s\S]*?<\/si>/g) || [];
      for (const item of strings) sharedStrings.push([...item.matchAll(/<t(?:\s[^>]*)?>([\s\S]*?)<\/t>/g)].map(match => decodeXml(match[1])).join(''));
    }
    const sheetName = names.filter(name => /^xl\/worksheets\/sheet\d+\.xml$/.test(name)).sort()[0];
    if (!sheetName) return [];
    const xml = await workbook.file(sheetName).async('string');
    const rows = [];
    const rowNodes = xml.match(/<row(?:\s[^>]*)?>[\s\S]*?<\/row>/g) || [];
    for (const rowXml of rowNodes) {
      const row = [];
      let nextColumn = 0;
      const cells = rowXml.match(/<c(?:\s[^>]*)?(?:\/>|>[\s\S]*?<\/c>)/g) || [];
      for (const cellXml of cells) {
        const ref = (cellXml.match(/\br="([^"]+)"/) || [])[1] || '';
        const type = (cellXml.match(/\bt="([^"]+)"/) || [])[1] || '';
        // Ozon's XLSX export omits cell references but keeps all 12 columns
        // in order on every row; preserve that order when refs are absent.
        const col = ref ? columnIndexFromRef(ref) : nextColumn;
        nextColumn = col + 1;
        let value = '';
        if (type === 'inlineStr') {
          value = [...cellXml.matchAll(/<t(?:\s[^>]*)?>([\s\S]*?)<\/t>/g)].map(match => decodeXml(match[1])).join('');
        } else {
          const raw = (cellXml.match(/<v(?:\s[^>]*)?>([\s\S]*?)<\/v>/) || [])[1] || '';
          value = type === 's' ? (sharedStrings[Number(raw)] || '') : decodeXml(raw);
        }
        row[col] = value;
      }
      const max = row.length;
      rows.push(Array.from({ length: max }, (_, index) => row[index] ?? ''));
    }
    return rows.filter(row => row.some(value => String(value || '').trim()));
  });
}

function decodeXml(value) {
  return String(value || '').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&#x([0-9a-f]+);/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
    .replace(/&#([0-9]+);/g, (_, dec) => String.fromCharCode(parseInt(dec, 10)));
}

function parseCsvRows(buffer) {
  const content = buffer.toString('utf8').replace(/^\uFEFF/, '');
  const firstLine = content.split(/\r?\n/, 1)[0] || '';
  const delimiter = firstLine.includes(';') ? ';' : (firstLine.includes('\t') ? '\t' : ',');
  return csv.parse(content, { delimiter, relax_quotes: true, relax_column_count: true, skip_empty_lines: true });
}

async function parseReportRows(buffer) {
  if (buffer.subarray(0, 2).toString() !== 'PK') return parseCsvRows(buffer);
  const zip = require('jszip');
  const archive = await zip.loadAsync(buffer);
  const names = Object.keys(archive.files);
  if (names.some(name => /^xl\/worksheets\/sheet\d+\.xml$/.test(name))) return parseXlsxRows(buffer);
  const csvFiles = names.filter(name => !archive.files[name].dir && /\.csv$/i.test(name)).sort();
  if (!csvFiles.length) throw new Error('Отчёт хранения Ozon: в ZIP не найдены CSV/XLSX данные');
  const allRows = [];
  for (const name of csvFiles) allRows.push(...parseCsvRows(Buffer.from(await archive.file(name).async('nodebuffer'))));
  return allRows;
}

function findStorageHeader(rows) {
  for (let index = 0; index < Math.min(rows.length, 50); index++) {
    const joined = (rows[index] || []).map(normalizeHeader).join(' | ');
    const hasKey = joined.includes('sku') || joined.includes('артикул') || joined.includes('offer');
    const hasStorage = ['хран', 'размещ', 'storage', 'placement'].some(marker => joined.includes(marker));
    if (hasKey && hasStorage) return index;
  }
  return -1;
}

function findHeaderIndex(headers, markers) {
  for (const marker of markers) {
    const normalizedMarker = normalizeHeader(marker);
    const index = headers.findIndex(header => header.includes(normalizedMarker));
    if (index >= 0) return index;
  }
  return -1;
}

function storageMapFromRows(rows) {
  const headerIndex = findStorageHeader(rows);
  if (headerIndex < 0) throw new Error('Отчёт хранения Ozon: строка заголовков SKU/артикул + хранение не распознана');
  const headers = rows[headerIndex].map(normalizeHeader);
  const skuIndex = findHeaderIndex(headers, ['sku']);
  const offerIndex = findHeaderIndex(headers, ['артикул', 'offer']);
  let amountIndex = findHeaderIndex(headers, ['стоимость размещения', 'начисленная стоимость размещения', 'размещ', 'хран', 'storage', 'placement']);
  if (amountIndex < 0) amountIndex = findHeaderIndex(headers, ['начислено', 'сумма', 'итого']);
  if (amountIndex < 0 || (skuIndex < 0 && offerIndex < 0)) throw new Error('Отчёт хранения Ozon: не найдены колонки ключа товара и суммы');

  const storageMap = { bySku: {}, byOfferId: {}, parsedRows: 0 };
  for (let index = headerIndex + 1; index < rows.length; index++) {
    const row = rows[index] || [];
    const sku = skuIndex >= 0 ? normalizeKey(row[skuIndex]) : '';
    const offerId = offerIndex >= 0 ? normalizeKey(row[offerIndex]) : '';
    if (!sku && !offerId) continue;
    storageMap.parsedRows++;
    const amount = Math.abs(money(row[amountIndex]));
    if (!amount) continue;
    if (sku) storageMap.bySku[sku] = (storageMap.bySku[sku] || 0) + amount;
    if (offerId) storageMap.byOfferId[offerId] = (storageMap.byOfferId[offerId] || 0) + amount;
  }
  if (!storageMap.parsedRows) throw new Error('Отчёт хранения Ozon: не найдено строк товаров; запись отменена');
  log(`Отчёт хранения: строк товаров ${storageMap.parsedRows}, SKU ${Object.keys(storageMap.bySku).length}, артикулов ${Object.keys(storageMap.byOfferId).length}`);
  return storageMap;
}

async function fetchStorage(dateFrom, dateTo) {
  const reportCode = await createPlacementReport(dateFrom, dateTo);
  const fileUrl = await waitForReport(reportCode);
  const buffer = await downloadReport(fileUrl);
  const rows = await parseReportRows(buffer);
  if (!rows.length) throw new Error('Отчёт хранения Ozon пуст; запись отменена');
  return storageMapFromRows(rows);
}

function mergeBucket(target, source) {
  for (const field of Object.keys(createBucket())) target[field] += Number(source[field]) || 0;
}

function findAccrual(accrualMap, item) {
  return accrualMap[item.article] || accrualMap[item.sku] || createBucket();
}

function getStorageValue(storageMap, item) {
  if (item.sku && Object.prototype.hasOwnProperty.call(storageMap.bySku, item.sku)) return storageMap.bySku[item.sku];
  if (item.article && Object.prototype.hasOwnProperty.call(storageMap.byOfferId, item.article)) return storageMap.byOfferId[item.article];
  return 0;
}

function buildOutput(items, accrualMap, storageMap) {
  const commonCosts = accrualMap[COMMON_COSTS_KEY] || createBucket();
  let totalCommonExtraBase = 0;
  let totalUnitSum = 0;
  for (const item of items) {
    const accrual = findAccrual(accrualMap, item);
    totalCommonExtraBase += (Number(accrual.unitSum) || 0) + (Number(item.upd) || 0);
    totalUnitSum += Number(accrual.unitSum) || 0;
  }
  const commonExtraRate = totalCommonExtraBase ? (Number(commonCosts.commonExtra) || 0) / totalCommonExtraBase : 0;
  const data = items.map(item => {
    const accrual = findAccrual(accrualMap, item);
    const overpayment = Number(accrual.overpayment) || 0;
    return {
      unitSum: roundMoney(accrual.unitSum),
      unitQty: Math.round(Number(accrual.unitQty) || 0),
      reward: roundMoney(accrual.reward),
      logistics: roundMoney((Number(accrual.logistics) || 0) - overpayment),
      overpayment: roundMoney(overpayment),
      storage: roundMoney(getStorageValue(storageMap, item)),
      extra: roundMoney(accrual.extra),
      commonExtra: roundMoney(((Number(accrual.unitSum) || 0) + (Number(item.upd) || 0)) * commonExtraRate),
      starsAndAcquiring: roundMoney(accrual.starsAndAcquiring),
    };
  });
  const matchedAccrual = items.reduce((count, item) => {
    const accrual = findAccrual(accrualMap, item);
    return count + (['unitSum', 'unitQty', 'reward', 'logistics', 'overpayment', 'extra', 'starsAndAcquiring'].some(key => accrual[key]) ? 1 : 0);
  }, 0);
  const minMatchedRows = Math.max(100, Math.ceil(items.filter(item => item.article || item.sku).length * 0.005));
  if (matchedAccrual < minMatchedRows) {
    throw new Error(`Слишком мало строк сопоставлено с начислениями (${matchedAccrual}; минимум ${minMatchedRows}); таблица не изменена`);
  }
  return { data, matchedAccrual, commonExtraRate, commonCosts, totalCommonExtraBase, totalUnitSum };
}

function a1Range(column, startRow, rowCount) {
  const letter = columnLetter(column);
  return `${quoteSheetName(SHEET_NAME)}!${letter}${startRow}:${letter}${startRow + rowCount - 1}`;
}

async function writeOutput(sheets, sheetData, built) {
  const { data, commonExtraRate } = built;
  const updates = OUTPUT_FIELDS.map(([field, label, getter]) => ({
    range: a1Range(COLUMNS[field] || (field === 'commonExtra' ? COLUMNS.commonExtra : 0), sheetData.firstDataRow, data.length),
    majorDimension: 'ROWS',
    values: data.map(row => [getter(row)]),
  }));
  updates.push({
    range: `${quoteSheetName(SHEET_NAME)}!U1`,
    majorDimension: 'ROWS',
    values: [[Math.round((1 + commonExtraRate) * 10_000) / 10_000]],
  });
  const expectedCells = data.length * OUTPUT_FIELDS.length + 1;
  const response = await sheets.spreadsheets.values.batchUpdate({
    spreadsheetId: SPREADSHEET_ID,
    requestBody: { valueInputOption: 'RAW', data: updates },
  });
  const writtenCells = Number(response.data.totalUpdatedCells) || 0;
  if (writtenCells !== expectedCells) {
    throw new Error(`Google Sheets записал ${writtenCells} из ${expectedCells} ожидаемых ячеек`);
  }
  log(`Запись подтверждена Google Sheets: ${writtenCells} ячеек, ${data.length} строк`);

  const sampleIndex = data.findIndex(row => row.unitSum !== 0);
  if (sampleIndex >= 0) {
    const rowNumber = sheetData.firstDataRow + sampleIndex;
    const readBack = await sheets.spreadsheets.values.get({
      spreadsheetId: SPREADSHEET_ID,
      range: `${quoteSheetName(SHEET_NAME)}!J${rowNumber}:V${rowNumber}`,
      valueRenderOption: 'UNFORMATTED_VALUE',
    });
    const values = readBack.data.values?.[0] || [];
    const expected = data[sampleIndex];
    const checks = [
      [0, expected.unitSum, 'UNIT СУММА'], [3, expected.unitQty, 'UNIT ШТ'],
      [4, expected.reward, 'ВОЗНАГРАЖДЕНИЕ'], [5, expected.logistics, 'ЛОГИСТИКА'],
      [6, expected.overpayment, 'ПЕРЕПЛАТА'], [9, expected.storage, 'ХРАНЕНИЕ'],
      [10, expected.extra, 'ДОП'], [11, expected.commonExtra, 'ОЗОН ДОП ВОЗНЯ'],
      [12, expected.starsAndAcquiring, 'ЗВЕЗДЫ + ЭКВ'],
    ];
    const mismatch = checks.find(([index, value]) => roundMoney(values[index]) !== roundMoney(value));
    if (mismatch) throw new Error(`Read-back не совпал для ${mismatch[2]} в строке ${rowNumber}`);
    log(`Read-back подтверждён: строка ${rowNumber}, UNIT СУММА=${expected.unitSum}, ХРАНЕНИЕ=${expected.storage}`);
  } else {
    const coefficient = await sheets.spreadsheets.values.get({
      spreadsheetId: SPREADSHEET_ID,
      range: `${quoteSheetName(SHEET_NAME)}!U1`,
      valueRenderOption: 'UNFORMATTED_VALUE',
    });
    if (roundMoney(coefficient.data.values?.[0]?.[0]) !== roundMoney(1 + commonExtraRate)) {
      throw new Error('Read-back коэффициента ОЗОН ДОП ВОЗНЯ не совпал');
    }
  }
}

async function main() {
  const startedAt = Date.now();
  sellerHeaders();
  const sheets = await createSheetsClient();
  const sheetData = await readWorksheet(sheets);
  const range = getDateRange();
  log(`Ozon Report65: строк ${sheetData.items.length}, товаров ${sheetData.validRows}, заголовок ${sheetData.headerRow}, период ${range.from}..${range.to}`);

  const accrualMap = await fetchAccruals(range.from, range.to);
  const productMapping = await enrichOfferIds(accrualMap);
  const storageMap = await fetchStorage(range.from, range.to);
  const built = buildOutput(sheetData.items, accrualMap, storageMap);
  log(`Сопоставлено начислений: ${built.matchedAccrual}; сопоставлено SKU→offer_id: ${productMapping.mapped}/${productMapping.skuCount}`);
  log(`Общие расходы без артикула: ${roundMoney(built.commonCosts.commonExtra)}; база UNIT СУММА + УПД: ${roundMoney(built.totalCommonExtraBase)}; коэффициент: ${(1 + built.commonExtraRate).toFixed(4)}`);
  log(`UNIT СУММА за период: ${roundMoney(built.totalUnitSum)}; ХРАНЕНИЕ: ${roundMoney(Object.values(storageMap.bySku).reduce((sum, value) => sum + value, 0))}`);
  await writeOutput(sheets, sheetData, built);
  log(`DONE Ozon Report65; elapsed=${Math.round((Date.now() - startedAt) / 1000)} sec`);
}

if (require.main === module) {
  main().catch(error => {
    log(`FAILED Ozon Report65: ${error.message}`);
    process.exitCode = 1;
  });
}
