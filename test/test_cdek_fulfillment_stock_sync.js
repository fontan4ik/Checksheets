const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const scriptPath = path.join(__dirname, 'tmp', 'apps-script-local-backup-cdek-removal-20260729T135446Z', 'Синхронизация остатков СДЭК.js');
const source = fs.readFileSync(scriptPath, 'utf8');
assert.ok(source.includes("getProperty('CDEK_FULFILLMENT_LOGIN')"));
assert.ok(source.includes("getProperty('CDEK_FULFILLMENT_API_KEY')"));
assert.ok(!source.includes('IM-SPB603-613'));

const requests = [];
let written = null;
const headers = ['art', 'model', 'stocks'];
const rows = [
  ['100-1', '100', 0],
  ['100-2', '100', 0],
  ['200-1', '200', 0]
];
const fixtures = {
  '100': {
    _embedded: {
      product_offer: [{
        article: '100',
        items: [
          { state: 'normal', count: 3 },
          { state: 'booked', count: 9 },
          { state: 'normal', count: '2' }
        ]
      }]
    },
    _links: {}
  },
  '200': {
    _embedded: { product_offer: [{ article: '200', items: [{ state: 'normal', count: 5 }] }] },
    _links: {}
  }
};

const sheet = {
  getLastRow: () => rows.length + 1,
  getLastColumn: () => headers.length,
  getRange: (row, column, numRows, numColumns) => {
    if (row === 1) return { getValues: () => [headers] };
    if (row === 2 && column === 1) return { getValues: () => rows };
    if (row === 2 && column === 3 && numRows === rows.length && numColumns === 1) {
      return { setValues: (values) => { written = values; } };
    }
    throw new Error(`Unexpected range ${row}:${column}:${numRows}:${numColumns}`);
  }
};

const context = {
  console,
  encodeURIComponent,
  Number,
  String,
  Date,
  Math,
  JSON,
  Object,
  Array,
  Error,
  Logger: { log: () => {} },
  Utilities: {
    base64Encode: (value) => Buffer.from(value, 'utf8').toString('base64'),
    sleep: () => {}
  },
  PropertiesService: {
    getScriptProperties: () => ({
      getProperty: (name) => ({
        CDEK_FULFILLMENT_LOGIN: 'test-login',
        CDEK_FULFILLMENT_API_KEY: 'test-key'
      })[name] || null
    })
  },
  SpreadsheetApp: {
    openById: (id) => {
      assert.strictEqual(id, '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI');
      return { getSheetByName: (name) => { assert.strictEqual(name, 'СДЕК TR'); return sheet; } };
    }
  },
  UrlFetchApp: {
    fetch: (url, options) => {
      const parsed = new URL(url);
      const model = parsed.searchParams.get('filter[0][value]');
      requests.push({ model, authorization: options.headers.Authorization });
      assert.ok(fixtures[model], `unexpected model request: ${model}`);
      return { getResponseCode: () => 200, getContentText: () => JSON.stringify(fixtures[model]) };
    }
  }
};
vm.createContext(context);
vm.runInContext(source, context, { filename: scriptPath });
const result = context.syncCdekStocks();

assert.deepStrictEqual(requests.map((request) => request.model).sort(), ['100', '200']);
assert.strictEqual(requests.length, 2, 'duplicate model must be fetched once');
assert.ok(requests.every((request) => request.authorization === 'Basic dGVzdC1sb2dpbjp0ZXN0LWtleQ=='));
assert.strictEqual(JSON.stringify(written), JSON.stringify([[5], [5], [5]]), 'only normal CDEK stock must be summed and copied to duplicate models');
assert.strictEqual(result.rows, 3);
assert.strictEqual(result.models, 2);
console.log('PASS test_cdek_fulfillment_stock_sync');
