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
assert.strictEqual(typeof aggregate, 'function');
assert.strictEqual(typeof context.updateOborWbStockDirect, 'function');
assert.deepStrictEqual(
  JSON.parse(JSON.stringify(vm.runInContext(
    "OBOR_VALUE_CONFIG.filter(item => item.sourceType === 'wbAnalyticsStocks').map(item => ({key: item.key, targetHeader: item.targetHeader, sourceMapKey: item.sourceMapKey || item.key}))",
    context,
  ))),
  [
    { key: 'wbStock', targetHeader: 'ВБ всего', sourceMapKey: 'wbStockApi' },
    { key: 'wbStockObor', targetHeader: 'ВБ ост', sourceMapKey: 'wbStockApi' },
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

const writes = [];
const targetSheet = {
  getLastRow() {
    return 3;
  },
  getRange(row, column, numRows) {
    if (row === 2 && column === 1 && numRows === 2) {
      return { getValues: () => [['23348-1'], ['99999']] };
    }
    if (row === 2 && column === 23 && numRows === 2) {
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
context.wbAnalyticsHeaders = () => ({ Authorization: 'redacted' });
context.retryFetch = () => ({
  getResponseCode: () => 200,
  getContentText: () => JSON.stringify({
    data: {
      items: [{ vendorCode: '23348-1', metrics: { stockCount: 32 } }],
    },
  }),
});
context.updateOborWbStockDirect();
assert.deepStrictEqual(JSON.parse(JSON.stringify(writes)), [{
  row: 2,
  column: 23,
  values: [[32], [0]],
}]);

console.log('OK: актуальная Analytics-схема vendorCode/metrics.stockCount поддержана');
console.log('OK: суффиксы упаковки учитываются при прямой загрузке в ОБОР');
console.log('OK: отрицательный остаток обнуляется, пустой артикул пропускается');
console.log('OK: updateOborWbStockDirect записывает только колонку W');
