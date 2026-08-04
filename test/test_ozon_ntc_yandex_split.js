#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const sourcePath = require('path').join(__dirname, '..', 'Синхронизация остатков Ozon НТЦ в Яндекс.js');
const source = fs.readFileSync(sourcePath, 'utf8');

const context = {
  console,
  Logger: { log() {} },
  LockService: {},
  SpreadsheetApp: {},
  Utilities: {},
  retryFetch() { throw new Error('network must not be called in this test'); },
  ozonHeaders() { return {}; },
  YANDEX_MARKET_API_KEY() { return 'test'; },
};
vm.createContext(context);
vm.runInContext(source, context, { filename: sourcePath });

assert.strictEqual(context.parseOzonNtcYnxPrice_('1 234,50'), 1234.5);
assert.strictEqual(context.parseOzonNtcYnxPrice_('0'), null);
assert.strictEqual(context.parseOzonNtcYnxPrice_('abc'), null);
assert.strictEqual(context.parseOzonNtcYnxStock_('12'), 12);
assert.strictEqual(context.parseOzonNtcYnxStock_('12,0'), 12);
assert.strictEqual(context.parseOzonNtcYnxStock_('0'), 0);
assert.strictEqual(context.parseOzonNtcYnxStock_('12,5'), null);
assert.strictEqual(context.parseOzonNtcYnxStock_('-1'), null);

function mockSheet(values) {
  return {
    getLastRow() { return values.length; },
    getRange(row, col, rows, cols) {
      assert.strictEqual(row, 1);
      assert.strictEqual(col, 1);
      assert.strictEqual(rows, values.length);
      assert.ok(cols === 20 || cols === 25);
      return { getDisplayValues() { return values.map(r => r.slice(0, cols)); } };
    },
  };
}

const header = Array(25).fill('');
header[0] = 'offer_id';
header[19] = 'Целевая цена';
header[24] = 'НТЦ STOCK';
const rowA = Array(25).fill('');
rowA[0] = 'A-1'; rowA[19] = '1 299,90'; rowA[24] = '7';
const rowB = Array(25).fill('');
rowB[0] = 'B-2'; rowB[19] = '500'; rowB[24] = '0';
const sheet = mockSheet([header, rowA, rowB]);

const stockRows = context.readOzonNtcYnxUnitStockRows_(sheet);
assert.deepStrictEqual(JSON.parse(JSON.stringify(stockRows.rows)), [
  { rowNumber: 2, offerId: 'A-1' },
  { rowNumber: 3, offerId: 'B-2' },
]);
assert.deepStrictEqual(JSON.parse(JSON.stringify(context.readOzonNtcYnxYandexStockEntries_(sheet))), [
  { sku: 'A-1', count: 7 },
  { sku: 'B-2', count: 0 },
]);
assert.deepStrictEqual(JSON.parse(JSON.stringify(context.readOzonNtcYnxYandexPriceEntries_(sheet))), [
  { offerId: 'A-1', price: 1299.9 },
  { offerId: 'B-2', price: 500 },
]);

const requests = [];
context.retryFetch = (url, options) => {
  requests.push({ url, body: JSON.parse(options.payload) });
  return {
    getResponseCode() { return 200; },
    getContentText() {
      return JSON.stringify({
        cursor: '',
        items: [
          {
            offer_id: 'A-1',
            stocks: [
              { warehouse_ids: [102], present: 5, reserved: 2 },
              { warehouse_ids: [777], present: 99, reserved: 0 },
            ],
          },
          { offer_id: 'B-2', stocks: [{ warehouse_ids: [102], present: 0, reserved: 0 }] },
        ],
      });
    },
  };
};
const fetched = context.fetchOzonNtcStocks_([{ offerId: 'A-1' }, { offerId: 'B-2' }], '102');
assert.deepStrictEqual(JSON.parse(JSON.stringify(fetched)), { 'A-1': 7, 'B-2': 0 });
assert.strictEqual(requests.length, 1);
assert.strictEqual(requests[0].url, 'https://api-seller.ozon.ru/v4/product/info/stocks');
assert.deepStrictEqual(JSON.parse(JSON.stringify(requests[0].body)), {
  cursor: '',
  filter: { offer_id: ['A-1', 'B-2'], visibility: 'ALL' },
  limit: 2,
});
assert.ok(!Object.prototype.hasOwnProperty.call(requests[0].body, 'sku'));

const sourceStage1 = source.slice(source.indexOf('function syncOzonNtcStocksToUnitYnx'), source.indexOf('function syncUnitYnxNtcStocksToYandex'));
assert.ok(sourceStage1.includes('writeOzonNtcYnxStocks_'));
assert.ok(!sourceStage1.includes('uploadOzonNtcYnxStocksToYandex_'));
assert.ok(!sourceStage1.includes('uploadOzonNtcYnxPricesToYandex_'));
assert.ok(!/function\s+syncOzonNtcStocksToYandex\s*\(/.test(source));

console.log('OK: Ozon NTC split-function mapping and parsers verified');
