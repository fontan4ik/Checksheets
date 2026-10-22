const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

let count = 9000;
const props = new Map();
const writes = [];
let omitAttributes = false;
const offerIds = Array.from({ length: count }, (_, i) => [`offer-${i + 1}`]);
const sheet = {
  getLastRow: () => count + 1,
  getParent: () => ({getId: () => 'sheet'}), getSheetId: () => 1,
  getRange: (row, column, length) => ({
    getValues: () => column === 1 ? offerIds.slice(0, count) : Array.from({ length }, () => ['old']),
    getFormulas: () => Array.from({ length }, () => ['']),
    setValues: values => writes.push({ row, column, length: values.length, values }),
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
  retryFetch: (url, options) => {
    const payload = JSON.parse(options.payload);
    let body;
    if (url.includes('/tree')) body = {result: []};
    else if (url.includes('/v3/')) {
      assert(!payload.filter, 'v3 identifiers must be top-level');
      body = {items: payload.offer_id.map(offer_id => ({offer_id, sku: offer_id.slice(6), primary_image: ['https://img/' + offer_id]}))};
    } else {
      assert.equal(payload.filter.visibility, 'ALL');
      body = {result: (omitAttributes ? [] : payload.filter.offer_id).map(offer_id => ({offer_id, attributes: [{id:85,values:[{value:'Brand'}]}]}))};
    }
    return {getContentText: () => JSON.stringify(body)};
  },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'List_ТЕСТ__C_E_V_X_Y__Товары_Ozon.js'), 'utf8'), context);
const firstResult = context.updateProductsV2Core_();
assert.equal(firstResult.complete, false);
assert.equal(firstResult.nextIndex, 8000);
assert.equal(firstResult.total, 9000);
assert.equal(firstResult.writeMode, 'native');
assert.equal(writes.find(write => write.column === 22).values[0][0], '1');
assert.equal(writes.find(write => write.column === 5).values[0][0], '=IMAGE("https://img/offer-1")');
assert.equal(writes.find(write => write.column === 3).values[0][0], 'Brand');
assert.equal(props.get('OZON_PRODUCTS_V2_NEXT_OFFER'), '8000');
assert.equal(writes.length, 6);
assert(writes.every(write => write.row === 2 && write.length === 8000));
writes.length = 0;
// An appended product must not restart already processed rows.
offerIds.push(['offer-9001']); count++;
assert.equal(context.updateProductsV2Core_().complete, true);
assert.equal(props.has('OZON_PRODUCTS_V2_NEXT_OFFER'), false);
assert.equal(writes.length, 6);
assert(writes.every(write => write.row === 8002 && write.length === 1001));
console.log('PASS Ozon products continuation writes only processed rows');

// v3-only cards still update SKU/image while old brand/model/name are preserved.
writes.length = 0;
count = 1; omitAttributes = true;
assert.equal(context.updateProductsV2Core_().complete, true);
assert.equal(writes.find(write => write.column === 22).values[0][0], '1');
assert.equal(writes.find(write => write.column === 5).values[0][0], '=IMAGE("https://img/offer-1")');
for (const column of [3, 4, 24, 25]) assert.equal(writes.find(write => write.column === column).values[0][0], 'old');
console.log('PASS v3-only offer metadata refresh preserves attribute fields');

// A previous REST403 persists a conservative native-write slice size.
writes.length = 0; count = 9000;
props.set('OZON_PRODUCTS_V2_NATIVE_WRITE', '1');
const nativeSlice = context.updateProductsV2Core_();
assert.equal(nativeSlice.nextIndex, 4000);
assert.equal(nativeSlice.processed, 4000);
assert.equal(nativeSlice.total, 9000);
assert.equal(nativeSlice.complete, false);
assert(writes.every(write => write.length === 4000));
console.log('PASS durable native fallback reduces slice to 4000 rows');
