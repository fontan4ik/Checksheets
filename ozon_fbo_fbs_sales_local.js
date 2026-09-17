#!/usr/bin/env node
'use strict';

// Local replacement for the time-limited Apps Script AQ:AT sales job.
// All API pages must succeed before the four destination columns are written.
process.env.TZ = 'Asia/Dubai';
const fs = require('fs');
const path = require('path');
const axios = require('axios');
const dotenv = require('dotenv');
const { google } = require('googleapis');

const ROOT = __dirname;
const SPREADSHEET_ID = process.env.CHECKSHEETS_SPREADSHEET_ID || '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
const SHEET = 'ТЕСТ';
const CREDENTIALS = process.env.GOOGLE_APPLICATION_CREDENTIALS || path.join(ROOT, 'nomadic-bedrock-485314-b0-d7624dedd83c.json');
dotenv.config({ path: process.env.OZON_REVIEWS_SECRETS_FILE || '/Users/vladimirgrebennikov/AI agents/secrets/ozon-reviews.env', quiet: true });
dotenv.config({ path: path.join(ROOT, '.env'), quiet: true });

const FBS_STATUSES = ['awaiting_packaging', 'awaiting_deliver', 'delivering', 'driver_pickup', 'delivered'];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const text = value => String(value ?? '').trim();
const dateText = date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
const normalizedHeader = value => text(value).replace(/\s+/g, ' ').toLowerCase();

function verifySheetHeaders(headerRow) {
  const expected = { 21: 'SKU Ozon', 42: 'Продажи штуки месяц FBO', 43: 'Продажи штуки месяц FBS',
    44: 'Продажи штуки квартал FBO', 45: 'Продажи штуки квартал FBS' };
  for (const [index, header] of Object.entries(expected)) {
    if (normalizedHeader(headerRow[index]) !== normalizedHeader(header)) {
      throw new Error(`ТЕСТ: колонка ${Number(index) + 1} больше не называется «${header}»; запись AQ:AT остановлена`);
    }
  }
}

function periods(now = new Date()) {
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  return {
    month: [dateText(new Date(yesterday.getFullYear(), yesterday.getMonth() - 1, yesterday.getDate())), dateText(yesterday)],
    quarter: [dateText(new Date(now.getFullYear(), now.getMonth() - 3, now.getDate())), dateText(now)],
  };
}

function headers() {
  const clientId = text(process.env.OZON_CLIENT_ID);
  const apiKey = text(process.env.OZON_API_KEY);
  if (!clientId || !apiKey) throw new Error('Не заданы OZON_CLIENT_ID/OZON_API_KEY');
  return { 'Client-Id': clientId, 'Api-Key': apiKey, 'Content-Type': 'application/json' };
}

async function sheetsClient() {
  if (!fs.existsSync(CREDENTIALS)) throw new Error(`Нет service-account файла: ${CREDENTIALS}`);
  const auth = new google.auth.GoogleAuth({ keyFile: CREDENTIALS, scopes: ['https://www.googleapis.com/auth/spreadsheets'] });
  return google.sheets({ version: 'v4', auth: await auth.getClient() });
}

async function request(url, body, limiter) {
  for (let attempt = 0; attempt < 4; attempt++) {
    await limiter();
    try {
      const response = await axios.post(url, body, { headers: headers(), timeout: 30000, validateStatus: () => true });
      if (response.status >= 200 && response.status < 300) return response.data;
      if (response.status !== 429 && response.status < 500) throw new Error(`Ozon HTTP ${response.status}: ${JSON.stringify(response.data).slice(0, 400)}`);
      if (attempt === 3) throw new Error(`Ozon HTTP ${response.status}: ${JSON.stringify(response.data).slice(0, 400)}`);
    } catch (error) {
      if (attempt === 3 || (/Ozon HTTP 4\d\d/.test(error.message) && !/HTTP 429/.test(error.message))) throw error;
    }
    await sleep(Math.min(30000, 2000 * 2 ** attempt));
  }
  throw new Error('Ozon: исчерпаны повторы запроса');
}

function limiter(intervalMs) {
  let last = 0;
  return async () => {
    const wait = intervalMs - (Date.now() - last);
    if (wait > 0) await sleep(wait);
    last = Date.now();
  };
}

async function analyticsSales(from, to, throttle) {
  const totals = new Map();
  for (let offset = 0, page = 0; page < 100; offset += 1000, page++) {
    const data = await request('https://api-seller.ozon.ru/v1/analytics/data', {
      date_from: from, date_to: to, dimension: ['sku'], metrics: ['ordered_units'], limit: 1000, offset,
    }, throttle);
    const rows = data?.result?.data;
    if (!Array.isArray(rows)) throw new Error('Ozon analytics: нет result.data');
    for (const row of rows) {
      const sku = text(row.dimensions?.[0]?.id);
      if (sku) totals.set(sku, (totals.get(sku) || 0) + (Number(row.metrics?.[0]) || 0));
    }
    console.log(`analytics ${from}..${to}: страница ${page + 1}, строк ${rows.length}`);
    if (rows.length < 1000) return totals;
  }
  throw new Error('Ozon analytics: достигнут лимит 100 страниц');
}

async function fbsSales(from, to, throttle) {
  const totals = new Map();
  for (const status of FBS_STATUSES) {
    let offset = 0;
    for (let page = 0; page < 1000; page++) {
      const data = await request('https://api-seller.ozon.ru/v3/posting/fbs/list', {
        dir: 'ASC', filter: { since: `${from}T00:00:00.000Z`, to: `${to}T00:00:00.000Z`, status },
        limit: 1000, offset, with: { analytics_data: false, financial_data: false, translit: false },
      }, throttle);
      const postings = data?.result?.postings;
      if (!Array.isArray(postings)) throw new Error(`Ozon FBS ${status}: нет result.postings`);
      for (const posting of postings) for (const product of posting.products || []) {
        const sku = text(product.sku);
        const quantity = Number(product.quantity) || 0;
        if (sku && quantity > 0) totals.set(sku, (totals.get(sku) || 0) + quantity);
      }
      offset += postings.length;
      if (!data.result?.has_next) break;
      if (!postings.length) throw new Error(`Ozon FBS ${status}: has_next при пустой странице`);
      if (page === 999) throw new Error(`Ozon FBS ${status}: достигнут лимит страниц`);
    }
    console.log(`FBS ${from}..${to}, ${status}: ${offset} отправлений`);
  }
  return totals;
}

function resultRows(skus, totalMonth, fbsMonth, totalQuarter, fbsQuarter) {
  return skus.map(sku => {
    if (!sku) return ['', '', '', ''];
    const monthFbs = fbsMonth.get(sku) || 0;
    const quarterFbs = fbsQuarter.get(sku) || 0;
    return [Math.max(0, (totalMonth.get(sku) || 0) - monthFbs), monthFbs,
      Math.max(0, (totalQuarter.get(sku) || 0) - quarterFbs), quarterFbs];
  });
}

async function main({ dryRun = false, probe = false } = {}) {
  const sheets = await sheetsClient();
  const response = await sheets.spreadsheets.values.get({ spreadsheetId: SPREADSHEET_ID, range: `'${SHEET}'!A:AT`, valueRenderOption: 'UNFORMATTED_VALUE' });
  const rows = response.data.values || [];
  if (rows.length < 2) return;
  verifySheetHeaders(rows[0]);
  const skus = rows.slice(1).map(row => text(row[21]));
  const range = periods();
  console.log(`Ozon sales: ${skus.filter(Boolean).length} SKU, месяц ${range.month.join('..')}, квартал ${range.quarter.join('..')}`);
  if (dryRun) return;
  if (probe) {
    const analytics = await request('https://api-seller.ozon.ru/v1/analytics/data', {
      date_from: range.month[0], date_to: range.month[1], dimension: ['sku'], metrics: ['ordered_units'], limit: 1, offset: 0,
    }, limiter(0));
    const fbs = await request('https://api-seller.ozon.ru/v3/posting/fbs/list', {
      dir: 'ASC', filter: { since: `${range.month[0]}T00:00:00.000Z`, to: `${range.month[1]}T00:00:00.000Z`, status: 'delivered' },
      limit: 1, offset: 0, with: { analytics_data: false, financial_data: false, translit: false },
    }, limiter(0));
    if (!Array.isArray(analytics?.result?.data) || !Array.isArray(fbs?.result?.postings)) throw new Error('Ozon probe: неожиданный формат ответа');
    console.log('Ozon sales: оба API отвечают; запись в таблицу не выполнялась');
    return;
  }
  const analyticsThrottle = limiter(7000);
  const fbsThrottle = limiter(5000);
  const totalMonth = await analyticsSales(...range.month, analyticsThrottle);
  const totalQuarter = await analyticsSales(...range.quarter, analyticsThrottle);
  const fbsMonth = await fbsSales(...range.month, fbsThrottle);
  const fbsQuarter = await fbsSales(...range.quarter, fbsThrottle);
  const values = resultRows(skus, totalMonth, fbsMonth, totalQuarter, fbsQuarter);
  const columns = ['AQ', 'AR', 'AS', 'AT'];
  await sheets.spreadsheets.values.batchUpdate({
    spreadsheetId: SPREADSHEET_ID,
    requestBody: { valueInputOption: 'RAW', data: columns.map((column, index) => ({
      range: `'${SHEET}'!${column}2:${column}${rows.length}`,
      majorDimension: 'ROWS', values: values.map(row => [row[index]]),
    })) },
  });
  console.log(`Ozon sales: AQ:AT обновлены, строк ${values.length}`);
}

if (require.main === module) main({ dryRun: process.argv.includes('--dry-run'), probe: process.argv.includes('--probe') }).catch(error => {
  console.error(error.stack || error);
  process.exitCode = 1;
});

module.exports = { periods, resultRows, verifySheetHeaders, FBS_STATUSES };
