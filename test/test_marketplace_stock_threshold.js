#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.join(__dirname, '..');
const settingsSource = fs.readFileSync(path.join(root, 'Shared_Настройки.js'), 'utf8');
const context = vm.createContext({});
vm.runInContext(settingsSource, context, { filename: 'Shared_Настройки.js' });

for (const [input, expected] of [
  [-1, 0], [0, 0], [1, 0], ['1', 0], [1.9, 0],
  [2, 2], ['2', 2], [2.9, 2], [10, 10], ['bad', 0],
]) {
  const actual = vm.runInContext(
    `normalizeMarketplaceStock(${JSON.stringify(input)})`,
    context,
  );
  assert.strictEqual(actual, expected, `stock ${JSON.stringify(input)}`);
}

for (const [input, expected] of [[0, 0], [1, 1], [2, 2]]) {
  const actual = vm.runInContext(
    `normalizeMarketplaceStock(${JSON.stringify(input)}, ' ArLiGhT ')`,
    context,
  );
  assert.strictEqual(actual, expected, `Arlight stock ${JSON.stringify(input)}`);
}

const requiredUsage = {
  'Flow_UNIT_YNX__Остатки_поставщиков_Яндекс.js': [
    "const SAMARA_SUPPLIER_YNX_SOURCE_BRAND_HEADER = 'brand';",
    'count: normalizeMarketplaceStock(raw, brand)',
    'count: normalizeMarketplaceStock(item.count, item.brand)',
  ],
  'Flow_UNIT_YNX__Остатки_НТЦ_Яндекс.js': [
    'count: normalizeMarketplaceStock(count)',
    'count: normalizeMarketplaceStock(item.count)',
  ],
  'sync-etm-stocks.js': [
    'brand: STREAM_SUPPS_HEADERS.brand',
    'const stock = normalizeMarketplaceStock(originalStock, brand)',
    'const wb_stock = normalizeMarketplaceStock(row[colWbStock - 1], brand)',
    'stock: item.stock',
  ],
  'sync-feron-stocks.js': [
    'brand: STREAM_SUPPS_HEADERS.brand',
    'stock_msk: normalizeMarketplaceStock(originalStockMsk, brand)',
    'stock_wb_voltmir: normalizeMarketplaceStock(wbVoltmirStock, brand)',
    'stock_wb_feron_moscow: normalizeMarketplaceStock(wbFeronMoscowStock, brand)',
  ],
  'sync-cdek-ozon-stocks.js': [
    'return Math.trunc(parsed);',
    'stock: numberStock(item.stock)',
  ],
};

for (const [file, snippets] of Object.entries(requiredUsage)) {
  const source = fs.readFileSync(path.join(root, file), 'utf8');
  for (const snippet of snippets) {
    assert.ok(source.includes(snippet), `${file}: missing ${snippet}`);
  }
}

// Exercise the actual writer payload: forced-zero mode is intentional and must
// not be mistaken for bypassing the already-normalized per-brand quantity.
async function verifyFeronStockPayload() {
  const source = fs.readFileSync(path.join(root, 'sync-feron-stocks.js'), 'utf8');
  const start = source.indexOf('async function updateFeronStocksOzonWithRetry(');
  const end = source.indexOf('async function updateFeronStocksOzon(', start);
  assert(start >= 0 && end > start, 'production Ozon payload function found');
  const payloads = [];
  const writer = vm.createContext({
    axios: {post: async (url, body) => { payloads.push(JSON.parse(JSON.stringify(body))); return {data: {}}; }},
    ozonHeaders: () => ({}),
  });
  vm.runInContext(source.slice(start, end), writer);
  const batch = [{offer_id:'BASE',stock_msk:0},{offer_id:'ARLIGHT',stock_msk:1},{offer_id:'NORMAL',stock_msk:2}];
  await writer.updateFeronStocksOzonWithRetry(batch, 123, 'stock_msk');
  assert.deepStrictEqual(payloads[0].stocks.map(item => item.stock), [0,1,2], 'writer preserves normalized zero/Arlight one/base two');
  assert(payloads[0].stocks.every(item => item.warehouse_id === 123));
  await writer.updateFeronStocksOzonWithRetry(batch, 123, 'stock_msk', 0, true);
  assert.deepStrictEqual(payloads[1].stocks.map(item => item.stock), [0,0,0], 'explicit forced-zero mode overrides all quantities');
  assert.deepStrictEqual(batch.map(item => item.stock_msk), [0,1,2], 'writer never mutates its source snapshot');
}
verifyFeronStockPayload().then(() => {
  console.log('PASS marketplace stock rule: base 1 -> 0; Arlight/CDEK 1 -> 1; zero preserved');
}).catch(error => { console.error(error); process.exitCode = 1; });
