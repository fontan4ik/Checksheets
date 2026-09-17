const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const count = 9000;
const props = new Map();
const writes = [];
const offerIds = Array.from({ length: count }, (_, i) => [`offer-${i + 1}`]);
const sheet = {
  getLastRow: () => count + 1,
  getRange: (row, column, length) => ({
    getValues: () => column === 1 ? offerIds : Array.from({ length }, () => ['old']),
    getFormulas: () => Array.from({ length }, () => ['']),
    setValues: values => writes.push({ row, column, length: values.length }),
  }),
};
const headerColumns = { 'Бренд': 3, 'Связка': 4, 'Картинка': 5, 'SKU Ozon': 22, 'Название модели': 24, 'Категория товара': 25 };
const context = {
  Date: { now: () => 0 },
  Logger: { log: () => {} },
  mainSheet: () => sheet,
  PropertiesService: { getScriptProperties: () => ({
    getProperty: key => props.get(key) || null,
    setProperty: (key, value) => props.set(key, value),
    deleteProperty: key => props.delete(key),
  }) },
  columnByHeader_: (_, header) => headerColumns[header],
  RPS: () => 20,
  rateLimitRPS: () => 0,
  ozonHeaders: () => ({}),
  retryFetch: (url, options) => ({ getContentText: () => JSON.stringify(
    url.includes('/tree') ? { result: [] } : { result: JSON.parse(options.payload).filter.offer_id.map(offer_id => ({ offer_id, sku: offer_id.slice(6), attributes: [] })) },
  ) }),
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'List_ТЕСТ__C_E_V_X_Y__Товары_Ozon.js'), 'utf8'), context);
context.updateProductsV2Core_();
assert.equal(props.get('OZON_PRODUCTS_V2_NEXT_OFFER'), '8000');
assert.equal(writes.length, 6);
assert(writes.every(write => write.row === 2 && write.length === 8000));
writes.length = 0;
context.updateProductsV2Core_();
assert.equal(props.has('OZON_PRODUCTS_V2_NEXT_OFFER'), false);
assert.equal(writes.length, 6);
assert(writes.every(write => write.row === 8002 && write.length === 1000));
console.log('PASS Ozon products continuation writes only processed rows');
