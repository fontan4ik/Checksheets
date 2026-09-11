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

const requiredUsage = {
  'Синхронизация остатков RS.js': [
    'const RS_MIN_STOCK_THRESHOLD = MARKETPLACE_MIN_STOCK',
    'wb_stock: normalizeMarketplaceStock(wbStockForUpload)',
    'stock: normalizeMarketplaceStock(item.stock)',
    'amount: normalizeMarketplaceStock(item.wb_stock)',
  ],
  'Синхронизация остатков ARL.js': [
    'const stock = normalizeMarketplaceStock(originalStock)',
    'stock: normalizeMarketplaceStock(item.stock)',
    'amount: normalizeMarketplaceStock(item.stock)',
  ],
  'Синхронизация остатков поставщиков в Яндекс.js': [
    'count: normalizeMarketplaceStock(raw)',
    'count: normalizeMarketplaceStock(item.count)',
  ],
  'Синхронизация остатков Ozon НТЦ в Яндекс.js': [
    'count: normalizeMarketplaceStock(count)',
    'count: normalizeMarketplaceStock(item.count)',
  ],
  'sync-etm-stocks.js': [
    'const MIN_STOCK_THRESHOLD = 2;',
    'const wb_stock = normalizeMarketplaceStock(row[colWbStock - 1])',
    'stock: normalizeMarketplaceStock(item.stock)',
  ],
  'sync-feron-stocks.js': [
    'const MIN_STOCK_THRESHOLD = 2;',
    'stock_msk: normalizeMarketplaceStock(originalStockMsk)',
    'stock_wb_voltmir: normalizeMarketplaceStock(wbVoltmirStock)',
    'stock: normalizeMarketplaceStock(item[colName])',
  ],
  'sync-cdek-ozon-stocks.js': [
    'const MIN_STOCK_THRESHOLD = 2;',
    'stock: numberStock(item.stock)',
  ],
};

for (const [file, snippets] of Object.entries(requiredUsage)) {
  const source = fs.readFileSync(path.join(root, file), 'utf8');
  for (const snippet of snippets) {
    assert.ok(source.includes(snippet), `${file}: missing ${snippet}`);
  }
}

console.log('PASS marketplace stock threshold: 0/1 -> 0, 2+ -> unchanged');
