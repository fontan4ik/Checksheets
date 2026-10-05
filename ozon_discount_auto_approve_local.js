#!/usr/bin/env node
'use strict';

process.env.TZ = 'Asia/Dubai';

const fs = require('fs');
const path = require('path');
const axios = require('axios');
const dotenv = require('dotenv');
const { google } = require('googleapis');

const ROOT = __dirname;
const SPREADSHEET_ID = process.env.CHECKSHEETS_SPREADSHEET_ID || '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
const DIFFERENCE_SHEET = 'ТЗ';
const SKU_SHEET = 'ТЕСТ';
const CREDENTIALS = process.env.GOOGLE_APPLICATION_CREDENTIALS || path.join(ROOT, 'nomadic-bedrock-485314-b0-d7624dedd83c.json');
const CACHE_PATH = process.env.OZON_DISCOUNT_CACHE_PATH || path.join(ROOT, 'logs', 'ozon_discount_difference_cache.json');
const SECRET_FILE = process.env.OZON_DISCOUNT_SECRETS_FILE || '/Users/vladimirgrebennikov/AI agents/secrets/ozon-reviews.env';
const DIFFERENCE_REFRESH_INTERVAL_MS = 7 * 24 * 60 * 60 * 1000;
const SHEETS_RANGE_DIFFERENCE = `'${DIFFERENCE_SHEET}'!A:AH`;
const SHEETS_RANGE_SKU = `'${SKU_SHEET}'!A:V`;
const OZON_LIST_URL = 'https://api-seller.ozon.ru/v2/actions/discounts-task/list';
const OZON_APPROVE_URL = 'https://api-seller.ozon.ru/v1/actions/discounts-task/approve';
const PAGE_LIMIT = 50;
const MAX_PAGES = 100;
const MAX_API_RETRIES = 4;
const APPROVAL_BATCH_SIZE = 50;

dotenv.config({ path: SECRET_FILE, quiet: true });
dotenv.config({ path: path.join(ROOT, '.env'), quiet: true });

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const normalizeHeader = value => String(value ?? '').trim().toLowerCase().replace(/ё/g, 'е').replace(/\s+/g, ' ');
const normalizeArticle = value => String(value ?? '').trim();

function log(message) {
  console.log(`${new Date().toISOString()} ${message}`);
}

function resolveUniqueHeader(headers, expected, sheetName) {
  const matches = [];
  headers.forEach((value, index) => {
    if (normalizeHeader(value) === normalizeHeader(expected)) matches.push(index);
  });
  if (matches.length !== 1) {
    throw new Error(`${sheetName}: заголовок «${expected}» найден ${matches.length} раз; обновление остановлено`);
  }
  return matches[0];
}

function parsePercent(value) {
  const normalized = String(value ?? '').trim().replace(/[\u00a0\u202f\s]/g, '');
  if (!normalized || !normalized.endsWith('%')) return null;
  const number = Number(normalized.slice(0, -1).replace(',', '.'));
  return Number.isFinite(number) ? number : null;
}

function normalizeSku(value) {
  let normalized = String(value ?? '').trim().replace(/[\u00a0\u202f\s]/g, '');
  if (!normalized) return null;
  if (/^\d{1,3}(?:,\d{3})+$/.test(normalized)) normalized = normalized.replace(/,/g, '');
  if (/^\d+\.0+$/.test(normalized)) normalized = normalized.replace(/\.0+$/, '');
  return /^\d+$/.test(normalized) ? normalized : null;
}

function finiteNumber(value) {
  const number = Number(value);
  return value !== null && value !== undefined && value !== '' && Number.isFinite(number) ? number : null;
}

async function createSheetsClient() {
  if (!fs.existsSync(CREDENTIALS)) throw new Error(`Нет service-account файла: ${CREDENTIALS}`);
  const auth = new google.auth.GoogleAuth({
    keyFile: CREDENTIALS,
    scopes: ['https://www.googleapis.com/auth/spreadsheets.readonly'],
  });
  return google.sheets({ version: 'v4', auth: await auth.getClient() });
}

async function refreshDifferenceCache() {
  const sheets = await createSheetsClient();
  const response = await sheets.spreadsheets.values.batchGet({
    spreadsheetId: SPREADSHEET_ID,
    ranges: [SHEETS_RANGE_DIFFERENCE, SHEETS_RANGE_SKU],
    valueRenderOption: 'FORMATTED_VALUE',
  });
  const differenceRows = response.data.valueRanges?.[0]?.values || [];
  const skuRows = response.data.valueRanges?.[1]?.values || [];
  if (!differenceRows.length || !skuRows.length) throw new Error('В таблице отсутствует строка заголовков');

  const differenceHeaders = differenceRows[0];
  const skuHeaders = skuRows[0];
  const articleColumn = resolveUniqueHeader(differenceHeaders, 'Артикул', DIFFERENCE_SHEET);
  const differenceColumn = resolveUniqueHeader(differenceHeaders, 'РАЗНИЦА', DIFFERENCE_SHEET);
  if (differenceColumn !== 33) throw new Error('Лист ТЗ: заголовок «РАЗНИЦА» должен находиться в колонке AH');
  const skuColumn = resolveUniqueHeader(skuHeaders, 'SKU Ozon', SKU_SHEET);

  // ТЕСТ column A is the documented offer_id key; its current header cell is blank.
  const skuArticleHeader = normalizeHeader(skuHeaders[0]);
  if (skuArticleHeader && skuArticleHeader !== normalizeHeader('Артикул')) {
    throw new Error(`${SKU_SHEET}: ожидается ключ-артикул в колонке A; найден другой заголовок`);
  }

  const differenceByArticle = new Map();
  let unusableDifferenceRows = 0;
  for (const row of differenceRows.slice(1)) {
    const article = normalizeArticle(row[articleColumn]);
    if (!article) continue;
    const difference = parsePercent(row[differenceColumn]);
    if (difference === null) {
      unusableDifferenceRows++;
      continue;
    }
    if (differenceByArticle.has(article) && differenceByArticle.get(article) !== difference) {
      throw new Error(`Лист ${DIFFERENCE_SHEET}: у одного артикула указаны разные значения РАЗНИЦА`);
    }
    differenceByArticle.set(article, difference);
  }

  const differenceBySku = Object.create(null);
  let matchedRows = 0;
  let matchedRowsWithoutSku = 0;
  for (const row of skuRows.slice(1)) {
    const article = normalizeArticle(row[0]);
    if (!article || !differenceByArticle.has(article)) continue;
    const sku = normalizeSku(row[skuColumn]);
    if (!sku) {
      matchedRowsWithoutSku++;
      continue;
    }
    const difference = differenceByArticle.get(article);
    if (Object.hasOwn(differenceBySku, sku) && differenceBySku[sku] !== difference) {
      throw new Error(`Лист ${SKU_SHEET}: у одного SKU найдены разные значения РАЗНИЦА`);
    }
    differenceBySku[sku] = difference;
    matchedRows++;
  }

  const skuCount = Object.keys(differenceBySku).length;
  if (!skuCount) throw new Error('Не удалось сопоставить РАЗНИЦА с SKU Ozon; кэш не обновлён');

  const cache = {
    version: 1,
    spreadsheetId: SPREADSHEET_ID,
    differenceSheet: DIFFERENCE_SHEET,
    skuSheet: SKU_SHEET,
    refreshedAt: new Date().toISOString(),
    articleCount: differenceByArticle.size,
    matchedRows,
    matchedRowsWithoutSku,
    unusableDifferenceRows,
    skuCount,
    differenceBySku,
  };
  fs.mkdirSync(path.dirname(CACHE_PATH), { recursive: true });
  const temporaryPath = `${CACHE_PATH}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(temporaryPath, `${JSON.stringify(cache)}\n`, { encoding: 'utf8', mode: 0o600 });
  fs.renameSync(temporaryPath, CACHE_PATH);
  log(`Кэш РАЗНИЦА обновлён из Google Sheets: SKU ${skuCount}; строк без процента ${unusableDifferenceRows}; артикулов без SKU ${matchedRowsWithoutSku}`);
}

function readFreshDifferenceCache() {
  if (!fs.existsSync(CACHE_PATH)) throw new Error('Кэш РАЗНИЦА отсутствует; выполните еженедельное обновление Google Sheets');
  const cache = JSON.parse(fs.readFileSync(CACHE_PATH, 'utf8'));
  const refreshedAt = Date.parse(cache.refreshedAt);
  const age = Date.now() - refreshedAt;
  if (cache.version !== 1 || !cache.differenceBySku || !Number.isFinite(refreshedAt) || age < 0 || age >= DIFFERENCE_REFRESH_INTERVAL_MS) {
    throw new Error('Кэш РАЗНИЦА старше 7 дней или повреждён; заявки не будут одобряться до обновления');
  }
  return cache;
}

function ozonHeaders() {
  const clientId = String(process.env.OZON_CLIENT_ID || '').trim();
  const apiKey = String(process.env.OZON_API_KEY || '').trim();
  if (!clientId || !apiKey) throw new Error(`Не заданы OZON_CLIENT_ID/OZON_API_KEY; проверьте защищённый файл ${SECRET_FILE}`);
  return { 'Client-Id': clientId, 'Api-Key': apiKey, 'Content-Type': 'application/json' };
}

async function ozonPost(url, body, headers, options = {}) {
  let lastError;
  for (let attempt = 0; attempt < (options.retry ? MAX_API_RETRIES : 1); attempt++) {
    let response;
    try {
      response = await axios.post(url, body, {
        headers,
        timeout: 30000,
        validateStatus: () => true,
      });
    } catch (error) {
      lastError = error;
      if (!options.retry || attempt === MAX_API_RETRIES - 1) throw error;
      await sleep(1000 * 2 ** attempt);
      continue;
    }

    if (response.status >= 200 && response.status < 300) return response.data;
    const retryable = response.status === 429 || response.status >= 500;
    const message = `Ozon API HTTP ${response.status}: ${JSON.stringify(response.data).slice(0, 500)}`;
    if (!options.retry || !retryable || attempt === MAX_API_RETRIES - 1) throw new Error(message);
    const retryAfter = Number(response.headers?.['retry-after']);
    await sleep(Math.max(Number.isFinite(retryAfter) ? retryAfter * 1000 : 0, 1000 * 2 ** attempt));
  }
  throw lastError || new Error('Ozon API: исчерпаны повторы');
}

async function fetchNewTasks(headers) {
  const tasks = [];
  const seenIds = new Set();
  let lastId;
  for (let page = 0; page < MAX_PAGES; page++) {
    const body = { limit: PAGE_LIMIT, status: 'NEW' };
    if (lastId !== undefined) body.last_id = lastId;
    const response = await ozonPost(OZON_LIST_URL, body, headers, { retry: true });
    if (!Array.isArray(response?.tasks)) throw new Error('Ozon discounts-task/list v2 вернул ответ без массива tasks');
    const pageTasks = response.tasks;
    for (const task of pageTasks) {
      const id = String(task?.id ?? '');
      if (id && !seenIds.has(id)) {
        seenIds.add(id);
        tasks.push(task);
      }
    }
    if (pageTasks.length < PAGE_LIMIT) return tasks;
    const nextLastId = finiteNumber(pageTasks[pageTasks.length - 1]?.id);
    if (nextLastId === null || nextLastId === lastId) throw new Error('Ozon discounts-task/list v2: некорректная пагинация last_id');
    lastId = nextLastId;
  }
  throw new Error(`Ozon discounts-task/list v2: превышен предел страниц ${MAX_PAGES}`);
}

function selectEligibleTasks(tasks, cache) {
  const eligible = [];
  let skippedStatus = 0;
  let skippedData = 0;
  let skippedRule = 0;
  for (const task of tasks) {
    if (String(task?.status || '').toUpperCase() !== 'NEW') {
      skippedStatus++;
      continue;
    }
    const sku = normalizeSku(task?.sku);
    const requestedDiscount = finiteNumber(task?.requested_discount);
    const requestedPrice = finiteNumber(task?.requested_price);
    const taskId = finiteNumber(task?.id);
    const difference = sku ? finiteNumber(cache.differenceBySku[sku]) : null;
    if (taskId === null || requestedDiscount === null || requestedDiscount < 0 || requestedDiscount > 100 || requestedPrice === null || requestedPrice <= 0 || difference === null) {
      skippedData++;
      continue;
    }
    // Percent values are compared in percentage points; equality is not enough.
    // Ignore sub-nanopercentage floating-point noise; a real positive margin is still required.
    if (difference + 1 - requestedDiscount <= 1e-9) {
      skippedRule++;
      continue;
    }
    const approval = { id: taskId, approved_price: requestedPrice };
    const requestedQuantityMax = finiteNumber(task?.requested_quantity_max);
    if (requestedQuantityMax !== null && requestedQuantityMax > 0) {
      approval.approved_quantity_min = 1;
      approval.approved_quantity_max = requestedQuantityMax;
    }
    eligible.push(approval);
  }
  return { eligible, skippedStatus, skippedData, skippedRule };
}

async function runPoll({ dryRun = false } = {}) {
  let cache;
  try {
    cache = readFreshDifferenceCache();
  } catch (error) {
    log(`Проверка заявок пропущена: ${error.message}`);
    return;
  }
  const headers = ozonHeaders();
  const tasks = await fetchNewTasks(headers);
  const selection = selectEligibleTasks(tasks, cache);
  log(`Заявки Ozon NEW: ${tasks.length}; подходят условию: ${selection.eligible.length}; не прошли условие: ${selection.skippedRule}; без данных: ${selection.skippedData}; прочие статусы: ${selection.skippedStatus}`);
  if (dryRun || !selection.eligible.length) return;

  for (let offset = 0; offset < selection.eligible.length; offset += APPROVAL_BATCH_SIZE) {
    const batch = selection.eligible.slice(offset, offset + APPROVAL_BATCH_SIZE);
    // This workflow intentionally calls only the approve endpoint. It has no decline path.
    const response = await ozonPost(OZON_APPROVE_URL, { tasks: batch }, headers);
    const result = response?.result || {};
    const successCount = Number(result.success_count) || 0;
    const failCount = Number(result.fail_count) || 0;
    log(`Одобрение заявок: успешно ${successCount}; ошибок ${failCount}`);
    if (failCount > 0) log(`Ошибки одобрения: ${JSON.stringify(result.fail_details || []).slice(0, 1500)}`);
    if (failCount > 0 || successCount + failCount !== batch.length) {
      throw new Error(`Ozon подтвердил ${successCount} из ${batch.length} заявок; следующая проверка повторно обработает оставшиеся NEW`);
    }
  }
}

async function main() {
  const mode = process.argv[2] || '--poll';
  if (mode === '--refresh-differences') {
    await refreshDifferenceCache();
    return;
  }
  if (mode === '--dry-run') {
    await runPoll({ dryRun: true });
    return;
  }
  if (mode === '--poll') {
    await runPoll();
    return;
  }
  throw new Error(`Неизвестный режим: ${mode}`);
}

main().catch(error => {
  log(`Ошибка автоодобрения скидок: ${error.stack || error.message}`);
  process.exitCode = 1;
});
