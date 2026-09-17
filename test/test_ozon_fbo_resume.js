const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const rows = Array.from({ length: 300 }, (_, index) => {
  const row = Array(22).fill('');
  row[0] = `offer-${index + 1}`;
  row[5] = 9;
  row[21] = index + 1;
  return row;
});
const props = new Map();
let written;
let clock = 0;
const sheet = {
  getLastRow: () => 301,
  getRange: (_row, column) => ({
    getValues: () => column === 1 ? rows : [],
    setValues: values => { written = values; values.forEach((value, i) => { rows[i][5] = value[0]; }); },
  }),
};
const context = {
  Date: { now: () => { const value = clock; clock += 60000; return value; } },
  Logger: { log: () => {} },
  PropertiesService: { getScriptProperties: () => ({
    getProperty: key => props.get(key) || null,
    setProperty: (key, value) => props.set(key, value),
    deleteProperty: key => props.delete(key),
  }) },
  mainSheet: () => sheet,
  columnByHeader_: () => 6,
  RPS: () => 20,
  rateLimitRPS: () => 0,
  ozonHeaders: () => ({}),
  ozonFBOAvailableStocksApiURL: () => 'https://example.test/stocks',
  retryFetch: (_url, options) => {
    const skus = JSON.parse(options.payload).skus;
    return { getContentText: () => JSON.stringify({ items: skus.map(sku => ({ offer_id: `offer-${sku}`, available_stock_count: 1 })) }) };
  },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'List_ТЕСТ__F_G__Остатки_Ozon.js'), 'utf8'), context);
context.updateStockFBO_();
assert.equal(props.get('OZON_FBO_STOCK_NEXT_SKU'), '100');
assert.equal(written[0][0], 1);
assert.equal(written[99][0], 1);
assert.equal(written[100][0], 9);
context.updateStockFBO_();
assert.equal(props.get('OZON_FBO_STOCK_NEXT_SKU'), '200');
assert.equal(written[199][0], 1);
assert.equal(written[200][0], 9);
context.updateStockFBO_();
assert.equal(props.has('OZON_FBO_STOCK_NEXT_SKU'), false);
assert.equal(written[299][0], 1);
console.log('PASS Ozon FBO stock continuation preserves unprocessed rows');
