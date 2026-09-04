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
const extractWarehouseRows = context.extractOborWbWarehouseRows_;
const subtractMaps = context.subtractOborWbStockMaps_;
const warehouseRemainsAggregate = context.aggregateOborWbWarehouseRemainsRows_;
const resolveWarehouseReportValue = context.resolveOborWbWarehouseReportValue_;
assert.strictEqual(typeof aggregate, 'function');
assert.strictEqual(typeof warehouseAggregate, 'function');
assert.strictEqual(typeof extractWarehouseRows, 'function');
assert.strictEqual(typeof subtractMaps, 'function');
assert.strictEqual(typeof warehouseRemainsAggregate, 'function');
assert.strictEqual(typeof resolveWarehouseReportValue, 'function');
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
      { warehouseName: 'Склад WB', quantity: 32 },
      { warehouseName: 'Коледино', quantity: 999 },
    ],
  },
  {
    vendorCode: '23348-1',
    groups: [{ warehouses: [{ warehouseName: 'Склад WB', quantity: 3 }] }],
  },
], 'Склад WB');
assert.deepStrictEqual(JSON.parse(JSON.stringify(warehouseResult.values)), {
  '23348': 35,
});
assert.strictEqual(warehouseResult.validRows, 2);
const groupsPayload = {
  data: {
    groups: [{
      vendorCode: '23348-1',
      warehouses: [
        { warehouseName: 'Склад WB', quantity: 32 },
        { warehouseName: 'Коледино', quantity: 999 },
      ],
    }],
    currency: 'RUB',
  },
};
assert.strictEqual(extractWarehouseRows(groupsPayload).length, 1);
assert.strictEqual(extractWarehouseRows(groupsPayload)[0].vendorCode, '23348-1');
assert.deepStrictEqual(JSON.parse(JSON.stringify(subtractMaps({ '23348': 115 }, { '23348': 32 }))), {
  '23348': 83,
});
assert.deepStrictEqual(JSON.parse(JSON.stringify(subtractMaps({ 'a': 2 }, { 'a': 5 }))), {
  'a': 0,
});

const reportMaps = warehouseRemainsAggregate([
  { vendorCode: '23348-1', warehouses: [{ warehouseName: 'Всего находится на складах', quantity: 115 }, { warehouseName: 'Склад WB РФ', quantity: 32 }, { warehouseName: 'Электросталь', quantity: 40 }] },
  { vendorCode: '39171-1', warehouses: [{ warehouseName: 'Всего находится на складах', quantity: 82 }, { warehouseName: 'Склад WB РФ', quantity: 6 }, { warehouseName: 'Самара (Новосемейкино)', quantity: 51 }] },
  { vendorCode: '39171-2', warehouses: [{ warehouseName: 'Всего находится на складах', quantity: 1 }, { warehouseName: 'Тула', quantity: 1 }] },
  { vendorCode: '5032873-3', warehouses: [{ warehouseName: 'В пути до получателей', quantity: 3 }, { warehouseName: 'В пути возвраты на склад WB', quantity: 11 }, { warehouseName: 'Всего находится на складах', quantity: 65 }, { warehouseName: 'Склад WB РФ', quantity: 2 }, { warehouseName: 'Электросталь', quantity: 36 }] },
  { vendorCode: '55012-5', warehouses: [{ warehouseName: 'Всего находится на складах', quantity: 66 }, { warehouseName: 'Склад WB РФ', quantity: 8 }, { warehouseName: 'Краснодар', quantity: 16 }] },
  { vendorCode: '55146-5', warehouses: [{ warehouseName: 'Всего находится на складах', quantity: 59 }, { warehouseName: 'Склад WB РФ', quantity: 27 }, { warehouseName: 'СПБ Шушары', quantity: 9 }] },
]);
assert.deepStrictEqual(JSON.parse(JSON.stringify(reportMaps.total)), {
  '23348-1': 115, '39171-1': 82, '39171-2': 1, '5032873-3': 65, '55012-5': 66, '55146-5': 59,
});
assert.deepStrictEqual(JSON.parse(JSON.stringify(reportMaps.live)), {
  '23348-1': 32, '39171-1': 6, '39171-2': 0, '5032873-3': 2, '55012-5': 8, '55146-5': 27,
});
const reportDead = subtractMaps(reportMaps.total, reportMaps.live);
assert.deepStrictEqual(JSON.parse(JSON.stringify(reportDead)), {
  '23348-1': 83, '39171-1': 76, '39171-2': 1, '5032873-3': 63, '55012-5': 58, '55146-5': 32,
});
assert.strictEqual(resolveWarehouseReportValue(reportDead, '39171-1'), 76);
assert.strictEqual(resolveWarehouseReportValue(reportDead, '39171'), 76);
assert.strictEqual(resolveWarehouseReportValue(reportMaps.live, '39171'), 6);
assert.strictEqual(resolveWarehouseReportValue(reportDead, '39171-2'), 1);

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
context.wbAnalyticsWarehouseRemainsURL = () => 'https://example.test/warehouse-remains';
context.wbAnalyticsHeaders = () => ({ Authorization: 'redacted' });
let reportAttempts = 0;
context.retryFetch = url => {
  if (url.startsWith('https://example.test/warehouse-remains') && reportAttempts++ === 0) {
    return {
      getResponseCode: () => 429,
      getHeaders: () => ({ 'X-RateLimit-Retry': '1' }),
      getContentText: () => '{"status":429}',
    };
  }
  return {
    getResponseCode: () => 200,
    getContentText: () => JSON.stringify(
      url.includes('/status')
        ? { data: { status: 'done' } }
        : url.includes('/download')
          ? [{
              vendorCode: '23348-1',
              nmId: 23348001,
              warehouses: [
                { warehouseName: 'Всего находится на складах', quantity: 115 },
                { warehouseName: 'Склад WB РФ', quantity: 32 },
                { warehouseName: 'Коледино', quantity: 999 },
              ],
            }]
          : { data: { taskId: 'task-1' } }
    ),
  };
};
context.updateOborWbStockDirect();
assert.deepStrictEqual(JSON.parse(JSON.stringify(writes)), [
  { row: 2, column: 23, values: [[83], [0]] },
  { row: 2, column: 24, values: [[32], [0]] },
]);
assert.strictEqual(reportAttempts, 4);

console.log('OK: W получает мёртвый остаток 115 − 32 = 83');
console.log('OK: X получает quantity = 32 из Warehouse Inventory Report по «Склад WB РФ»');
