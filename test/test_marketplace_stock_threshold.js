#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.join(__dirname, '..');
const settingsSource = fs.readFileSync(path.join(root, 'settings.js'), 'utf8');
const context = vm.createContext({});
vm.runInContext(settingsSource, context, { filename: 'settings.js' });

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
  'Синхронизация остатков RS.js': [
    'const RS_COL_BRAND = 4;',
    'const stock = normalizeMarketplaceStock(originalStock, brand)',
    'wb_stock: normalizeMarketplaceStock(wbStockForUpload, brand)',
    'stock: item.stock',
    'amount: item.wb_stock',
  ],
  'Синхронизация остатков ARL.js': [
    'const stock = normalizeMarketplaceStock(originalStock)',
    'stock: normalizeMarketplaceStock(item.stock)',
    'amount: normalizeMarketplaceStock(item.stock)',
  ],
  'Синхронизация остатков поставщиков в Яндекс.js': [
    'const SAMARA_SUPPLIER_YNX_SOURCE_BRAND_COLUMN = 4;',
    'count: normalizeMarketplaceStock(raw, brand)',
    'count: normalizeMarketplaceStock(item.count, item.brand)',
  ],
  'Синхронизация остатков Ozon НТЦ в Яндекс.js': [
    'count: normalizeMarketplaceStock(count)',
    'count: normalizeMarketplaceStock(item.count)',
  ],
  'sync-etm-stocks.js': [
    'BRAND: 4',
    'const stock = normalizeMarketplaceStock(originalStock, brand)',
    'const wb_stock = normalizeMarketplaceStock(row[colWbStock - 1], brand)',
    'stock: item.stock',
  ],
  'sync-feron-stocks.js': [
    'const colBrand = 4;',
    'stock_msk: normalizeMarketplaceStock(originalStockMsk, brand)',
    'stock_wb_voltmir: normalizeMarketplaceStock(wbVoltmirStock, brand)',
    'stock: item[colName]',
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

console.log('PASS marketplace stock rule: base 1 -> 0; Arlight/CDEK 1 -> 1; zero preserved');
