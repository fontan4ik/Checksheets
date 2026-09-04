#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const sourcePath = path.join(__dirname, '..', 'ОБОР формулы.js');
const source = fs.readFileSync(sourcePath, 'utf8');
const context = {
  encodeURIComponent,
  console,
  SpreadsheetApp: {},
  Logger: { log() {} },
  Session: { getScriptTimeZone: () => 'Europe/Moscow' },
  Utilities: { formatDate: () => '2026-08-31', sleep() {} },
};
vm.createContext(context);
vm.runInContext(source, context, { filename: sourcePath });

const aggregate = context.aggregateOborWbStockRows_;
const warehouseAggregate = context.aggregateOborWbWarehouseStockRows_;
const subtractMaps = context.subtractOborWbStockMaps_;
assert.strictEqual(typeof aggregate, 'function');
assert.strictEqual(typeof warehouseAggregate, 'function');
assert.strictEqual(typeof subtractMaps, 'function');
assert.strictEqual(typeof context.updateOborWbStockDirect, 'function');
assert.deepStrictEqual(
  JSON.parse(JSON.stringify(vm.runInContext(
    "OBOR_VALUE_CONFIG.filter(item => item.key === 'wbStock' || item.key === 'wbStockObor').map(item => ({key: item.key, targetHeader: item.targetHeader, sourceType: item.sourceType, sourceMapKey: item.sourceMapKey || item.key, warehouseName: item.warehouseName || null}))",
    context,
  ))),
  [
    { key: 'wbStock', targetHeader: 'ВБ всего', sourceType: 'wbAnalyticsDeadStocks', sourceMapKey: 'wbStockDeadApi', warehouseName: null },
    { key: 'wbStockObor', targetHeader: 'ВБ ост', sourceType: 'wbAnalyticsWarehouseStocks', sourceMapKey: 'wbStockWbRfApi', warehouseName: 'Склад WB РФ' },
  ],
);

const result = aggregate([
  { supplierArticle: '55222', quantity: 2 },
  { supplierArticle: '55222', quantity: 3 },
  { supplierArticle: '55222-10', quantity: 7 },
  { supplierArticle: '55222-5', quantity: 1 },
  { supplierArticle: '55222-foo', quantity: 99 },
  { supplierArticle: '', quantity: 100 },
  { supplierArticle: '99999-2', quantity: -4 },
]);

assert.deepStrictEqual(JSON.parse(JSON.stringify(result.values)), {
  '55222': 5 + 7 * 10 + 1 * 5,
  '55222-foo': 99,
  '99999': 0,
});
assert.strictEqual(result.validRows, 6);

const analyticsResult = aggregate([
  { vendorCode: '77001', metrics: { stockCount: 4 }, quantity: 999 },
  { vendorCode: '77001-2', metrics: { stockCount: 3 } },
  { vendorCode: '77001', metrics: { stockCount: 1 } },
]);
assert.deepStrictEqual(JSON.parse(JSON.stringify(analyticsResult.values)), {
  '77001': 11,
});
assert.strictEqual(analyticsResult.validRows, 3);

const warehouseResult = warehouseAggregate([
  {
    vendorCode: '23348-1',
    warehouses: [
      { warehouseName: 'Склад WB РФ', quantity: 32 },
      { warehouseName: 'Коледино', quantity: 999 },
    ],
  },
  {
    vendorCode: '23348-1',
    groups: [{ warehouses: [{ warehouseName: 'Склад WB РФ', quantity: 3 }] }],
  },
], 'Склад WB РФ');
assert.deepStrictEqual(JSON.parse(JSON.stringify(warehouseResult.values)), {
  '23348': 35,
});
assert.strictEqual(warehouseResult.validRows, 2);
assert.deepStrictEqual(JSON.parse(JSON.stringify(subtractMaps({ '23348': 115 }, { '23348': 32 }))), {
  '23348': 83,
});
assert.deepStrictEqual(JSON.parse(JSON.stringify(subtractMaps({ 'a': 2 }, { 'a': 5 }))), {
  'a': 0,
});

const writes = [];
const targetSheet = {
  getLastRow() {
    return 3;
  },
  getRange(row, column, numRows) {
    if (row === 2 && column === 1 && numRows === 2) {
      return { getValues: () => [['23348-1'], ['99999']] };
    }
    if ((column === 23 || column === 24) && row === 2 && numRows === 2) {
      return {
        setValues(values) {
          writes.push({ row, column, values });
        },
      };
    }
    throw new Error(`Unexpected range: row=${row}, column=${column}, numRows=${numRows}`);
  },
};

context.SpreadsheetApp = {
  openById() {
    return { getSheetByName: () => targetSheet };
  },
  flush() {},
};
context.wbAnalyticsStocksURL = () => 'https://example.test/stocks';
context.wbAnalyticsStocksGroupsURL = () => 'https://example.test/groups';
context.wbAnalyticsHeaders = () => ({ Authorization: 'redacted' });
context.retryFetch = url => ({
  getResponseCode: () => 200,
  getContentText: () => JSON.stringify({
    data: {
      items: url === 'https://example.test/stocks'
        ? [{ vendorCode: '23348-1', metrics: { stockCount: 115 } }]
        : [{
            vendorCode: '23348-1',
            warehouses: [
              { warehouseName: 'Склад WB РФ', quantity: 32 },
              { warehouseName: 'Коледино', quantity: 999 },
            ],
          }],
    },
  }),
});
context.updateOborWbStockDirect();
assert.deepStrictEqual(JSON.parse(JSON.stringify(writes)), [
  { row: 2, column: 23, values: [[83], [0]] },
  { row: 2, column: 24, values: [[32], [0]] },
]);

console.log('OK: W получает мёртвый остаток 115 − 32 = 83');
console.log('OK: X получает живой остаток warehouses[].quantity = 32 по «Склад WB РФ»');
