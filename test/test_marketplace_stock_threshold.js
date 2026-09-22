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
