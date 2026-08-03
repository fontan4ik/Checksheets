#!/usr/bin/env node
'use strict';

/**
 * Ozon Local Sales → Checksheets local client.
 *
 * Ozon's Local Sales value is served by an internal Seller web-gateway route.
 * This script does not copy cookies or API keys: it connects to the already
 * authenticated local Chrome instance over CDP and executes fetch() inside
 * the Ozon page.
 *
 * Read-only total:
 *   node test/ozon-local-sales-api.js --from 2026-07-04 --to 2026-08-02
 *
 * Read-only per-SKU reconciliation:
 *   node test/ozon-local-sales-api.js --from 2026-07-04 --to 2026-08-02 --items
 *
 * Dry-run against UNIT API:
 *   node test/ozon-local-sales-api.js --from 2026-07-04 --to 2026-08-02 --items --sheet-dry-run
 *
 * Explicit write to UNIT API!ПЕРЕПЛАТА:
 *   node test/ozon-local-sales-api.js --from 2026-07-04 --to 2026-08-02 --write-sheet
 *
 * Requirements:
 *   - Chrome with remote debugging on 127.0.0.1:9227.
 *   - Authenticated seller.ozon.ru page open in that profile.
 *   - Existing project service-account file for Google Sheets access.
 *
 * Sheet writes are opt-in. Unmatched sheet rows retain their current value.
 */

const fs = require('fs');
const path = require('path');
const { google } = require('googleapis');

const DEFAULT_CDP_URL = process.env.OZON_CDP_URL || 'http://127.0.0.1:9227';
const COMPANY_ID = process.env.OZON_COMPANY_ID || '142355';
const STATISTIC_ENDPOINT = '/api/logistic/v1/statistic';
const ITEMS_ENDPOINT = '/api/logistic/v1/items/table';
const ITEMS_PAGE_SIZE = 28; // Ozon frontend default (T.UN)
const SPREADSHEET_ID = process.env.CHECKSHEETS_SPREADSHEET_ID || '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
const SHEET_NAME = process.env.CHECKSHEETS_SHEET_NAME || 'UNIT API';
const CREDENTIALS_FILE = process.env.GSHEETS_CREDS_FILE || path.resolve(__dirname, '..', 'nomadic-bedrock-485314-b0-d7624dedd83c.json');

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith('--')) continue;
    const key = token.slice(2);
    const value = argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[++i] : true;
    args[key] = value;
  }
  return args;
}

function parseDate(value, flag) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) throw new Error(`${flag} must be YYYY-MM-DD`);
  const [year, month, day] = value.split('-').map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) {
    throw new Error(`${flag} is not a valid calendar date`);
  }
  return { year, month, day };
}

function usage() {
  console.error('Usage: node test/ozon-local-sales-api.js --from YYYY-MM-DD --to YYYY-MM-DD [--items] [--sheet-dry-run|--write-sheet] [--cdp-url URL]');
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`CDP discovery failed: HTTP ${response.status}`);
  return response.json();
}

class CdpClient {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.nextId = 1;
    this.pending = new Map();
    this.opened = new Promise((resolve, reject) => {
      this.ws.addEventListener('open', resolve, { once: true });
      this.ws.addEventListener('error', reject, { once: true });
    });
    this.ws.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      if (!message.id) return;
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message || 'CDP error'));
      else pending.resolve(message.result);
    });
  }

  async send(method, params = {}) {
    await this.opened;
    const id = this.nextId++;
    const result = new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
    this.ws.send(JSON.stringify({ id, method, params }));
    return result;
  }

  close() { this.ws.close(); }
}

async function findOzonPage(cdpUrl) {
  const targets = await getJson(`${cdpUrl}/json/list`);
  const page = targets.find((target) => target.type === 'page' && /^https:\/\/seller\.ozon\.ru\//.test(target.url || '') && target.webSocketDebuggerUrl);
  if (!page) throw new Error('No seller.ozon.ru page found in the local CDP browser');
  return page;
}

async function fetchInPage(cdp, endpoint, body) {
  const expression = `(async () => {
    const response = await fetch(${JSON.stringify(endpoint)}, {
      method: 'POST', credentials: 'include',
      headers: {
        'content-type': 'application/json',
        'x-o3-company-id': ${JSON.stringify(COMPANY_ID)},
        'x-o3-app-name': 'seller-ui', 'x-o3-language': 'ru'
      },
      body: JSON.stringify(${JSON.stringify(body)})
    });
    const text = await response.text();
    let parsed = null;
    try { parsed = JSON.parse(text); } catch (_) { parsed = { rawPrefix: text.slice(0, 300) }; }
    return { status: response.status, body: parsed };
  })()`;
  const result = await cdp.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || 'Browser evaluation failed');
  return result.result.value;
}

async function fetchAllItems(cdp, period) {
  const items = [];
  let offset = 0;
  let total = null;
  while (total === null || offset < total) {
    const response = await fetchInPage(cdp, ITEMS_ENDPOINT, {
      filter: { period, supplyPeriod: 'PERIOD_UNKNOWN' },
      limit: String(ITEMS_PAGE_SIZE), offset: String(offset)
    });
    if (response.status !== 200 || !response.body) throw new Error(`Items endpoint HTTP ${response.status} at offset ${offset}`);
    const pageItems = Array.isArray(response.body.items) ? response.body.items : [];
    total = Number(response.body.total || 0);
    items.push(...pageItems);
    if (!pageItems.length || items.length >= total) break;
    offset += pageItems.length;
  }
  return { items, total };
}

function sumItemOverpayments(items) {
  return Number(items.reduce((sum, item) => sum + Number(item?.metrics?.overpayment?.total || 0), 0).toFixed(2));
}

function normalizeKey(value) {
  return String(value ?? '').trim().toLowerCase().replace(/\s+/g, ' ');
}

function findColumn(headers, marker) {
  const needle = normalizeKey(marker);
  return headers.findIndex((value) => normalizeKey(value).includes(needle));
}

function columnToA1(index) {
  let n = index + 1;
  let output = '';
  while (n > 0) {
    const remainder = (n - 1) % 26;
    output = String.fromCharCode(65 + remainder) + output;
    n = Math.floor((n - 1) / 26);
  }
  return output;
}

async function getSheetsApi() {
  if (!fs.existsSync(CREDENTIALS_FILE)) throw new Error(`Google credentials file not found: ${CREDENTIALS_FILE}`);
  const auth = new google.auth.GoogleAuth({ keyFile: CREDENTIALS_FILE, scopes: ['https://www.googleapis.com/auth/spreadsheets'] });
  const client = await auth.getClient();
  return google.sheets({ version: 'v4', auth: client });
}

async function readSheetRows(sheets) {
  const response = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: `'${SHEET_NAME}'!A:Z`,
    valueRenderOption: 'UNFORMATTED_VALUE'
  });
  const rows = response.data.values || [];
  let headerIndex = -1;
  let columns = null;
  for (let i = 0; i < Math.min(rows.length, 20); i += 1) {
    const row = rows[i] || [];
    const article = findColumn(row, 'артикул');
    const sku = findColumn(row, 'ску oz');
    const overpayment = findColumn(row, 'переплата');
    if (article >= 0 && sku >= 0 && overpayment >= 0) {
      headerIndex = i;
      columns = { article, sku, overpayment };
      break;
    }
  }
  if (headerIndex < 0) throw new Error(`Required headers not found in '${SHEET_NAME}'`);
  return { rows, headerIndex, columns };
}

function makeItemMap(items) {
  const map = new Map();
  for (const item of items) {
    const sku = item?.sku || {};
    const value = Number(item?.metrics?.overpayment?.total || 0);
    for (const key of [sku.sku, sku.article]) {
      const normalized = normalizeKey(key);
      if (normalized) map.set(normalized, value);
    }
  }
  return map;
}

function buildSheetPlan(sheetData, items) {
  const itemMap = makeItemMap(items);
  const { rows, headerIndex, columns } = sheetData;
  const values = [];
  let matchedRows = 0;
  let unmatchedRows = 0;
  let newTotal = 0;
  let currentTotal = 0;
  for (let rowIndex = headerIndex + 1; rowIndex < rows.length; rowIndex += 1) {
    const row = rows[rowIndex] || [];
    const current = Number(row[columns.overpayment] || 0);
    currentTotal += Number.isFinite(current) ? current : 0;
    const keySku = normalizeKey(row[columns.sku]);
    const keyArticle = normalizeKey(row[columns.article]);
    const matched = itemMap.has(keySku) ? itemMap.get(keySku) : itemMap.get(keyArticle);
    if (matched === undefined) {
      unmatchedRows += 1;
      values.push([row[columns.overpayment] ?? '']);
      newTotal += Number.isFinite(current) ? current : 0;
    } else {
      matchedRows += 1;
      const sheetValue = Number((-matched).toFixed(2));
      values.push([sheetValue]);
      newTotal += sheetValue;
    }
  }
  return {
    values,
    headerRow: headerIndex + 1,
    firstDataRow: headerIndex + 2,
    lastDataRow: rows.length,
    columns,
    matchedRows,
    unmatchedRows,
    currentTotal: Number(currentTotal.toFixed(2)),
    newTotal: Number(newTotal.toFixed(2)),
    apiItems: items.length,
    apiOverpaymentTotal: sumItemOverpayments(items)
  };
}

async function writeAndReadBack(sheets, plan) {
  const column = columnToA1(plan.columns.overpayment);
  const range = `'${SHEET_NAME}'!${column}${plan.firstDataRow}:${column}${plan.lastDataRow}`;
  await sheets.spreadsheets.values.update({
    spreadsheetId: SPREADSHEET_ID,
    range,
    valueInputOption: 'USER_ENTERED',
    requestBody: { values: plan.values }
  });
  const readBack = await sheets.spreadsheets.values.get({ spreadsheetId: SPREADSHEET_ID, range, valueRenderOption: 'UNFORMATTED_VALUE' });
  const values = readBack.data.values || [];
  let mismatches = 0;
  for (let i = 0; i < plan.values.length; i += 1) {
    const expected = plan.values[i][0];
    const actual = values[i]?.[0] ?? '';
    if (String(expected) !== String(actual)) mismatches += 1;
  }
  return { range, rows: plan.values.length, read_back_rows: values.length, mismatches };
}

function makePeriod(from, to) { return { from, to }; }

async function main() {
  const args = parseArgs(process.argv);
  if (!args.from || !args.to) { usage(); process.exitCode = 2; return; }
  if ((args['write-sheet'] || args['sheet-dry-run']) && !args.items) args.items = true;

  const period = makePeriod(parseDate(args.from, '--from'), parseDate(args.to, '--to'));
  const cdpUrl = args['cdp-url'] || DEFAULT_CDP_URL;
  const page = await findOzonPage(cdpUrl);
  const cdp = new CdpClient(page.webSocketDebuggerUrl);
  try {
    const statistic = await fetchInPage(cdp, STATISTIC_ENDPOINT, { period, flags: { skuFlag: { count: 3, withTopOverpaymentSku: true } } });
    const output = {
      endpoint: STATISTIC_ENDPOINT, page: page.url, period,
      http_status: statistic.status,
      local_data: statistic.body && statistic.body.localData,
      overpayment: statistic.body && statistic.body.overpayment,
      overpayment_reasons: statistic.body && statistic.body.overpaymentReasons,
      top_sku: statistic.body && statistic.body.overpaymentSku,
      calculation_days: statistic.body && statistic.body.calculationDays,
      grace: statistic.body && statistic.body.grace
    };

    let items = null;
    if (args.items) {
      const allItems = await fetchAllItems(cdp, period);
      items = allItems.items;
      output.items_endpoint = ITEMS_ENDPOINT;
      output.items_total = allItems.total;
      output.items_fetched = items.length;
      output.items_overpayment_sum = sumItemOverpayments(items);
      output.items_sum_matches_statistic = output.items_overpayment_sum === Number(output.overpayment?.total || NaN);

      if (args['sheet-dry-run'] || args['write-sheet']) {
        const sheets = await getSheetsApi();
        const sheetData = await readSheetRows(sheets);
        const plan = buildSheetPlan(sheetData, items);
        output.sheet_plan = {
          sheet: SHEET_NAME,
          header_row: plan.headerRow,
          data_rows: plan.values.length,
          matched_rows: plan.matchedRows,
          unmatched_rows_preserved: plan.unmatchedRows,
          api_items: plan.apiItems,
          api_overpayment_total: plan.apiOverpaymentTotal,
          planned_sheet_total: plan.newTotal,
          sheet_value_sign: 'negative_expense_like_existing_O.js'
        };
        if (args['write-sheet']) output.sheet_write = await writeAndReadBack(sheets, plan);
      }
    }

    console.log(JSON.stringify(output, null, 2));
    if (statistic.status !== 200 || !statistic.body?.overpayment || (args.items && !output.items_sum_matches_statistic)) process.exitCode = 1;
  } finally {
    cdp.close();
  }
}

main().catch((error) => { console.error(`ERROR: ${error.message}`); process.exitCode = 1; });
