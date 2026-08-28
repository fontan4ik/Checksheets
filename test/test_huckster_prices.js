const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const sourcePath = path.join(__dirname, '..', 'Huckster цены.js');
const source = fs.readFileSync(sourcePath, 'utf8');
const context = {
  Array,
  JSON,
  Number,
  String,
  Math,
  isFinite,
  PropertiesService: {},
  Logger: {},
  LockService: {},
  SpreadsheetApp: {},
  UrlFetchApp: {},
  Utilities: {}
};
vm.createContext(context);
vm.runInContext(source, context, { filename: sourcePath });

assert.strictEqual(context.hucksterNormalizeKey_('  SKU-123  '), 'sku-123');
assert.strictEqual(context.hucksterNormalizeKey_(null), '');
assert.strictEqual(context.hucksterToPrice_('1 234'), '', 'Пробелы не должны молча превращаться в цену');
assert.strictEqual(context.hucksterToPrice_('1234,50'), 1234.5);
assert.strictEqual(context.hucksterToPrice_(0), 0);
assert.strictEqual(context.hucksterToPrice_(''), '');

const sampleItem = {
  uid: '039022(1)-1',
  market_price: 4006,
  upload_price: 5742,
  market_card_price: 3606.03
};
assert.strictEqual(
  JSON.stringify(context.hucksterMapPrices_(sampleItem)),
  JSON.stringify({
    displayedPrice: 5742,
    recommendedPrice: 3606.03,
    marketCardPrice: 3606.03,
    minPrice: ''
  })
);

const referenceItem = {
  upload_price: 6573,
  market_card_price: 4141.2,
  min_price: 5398
};
assert.strictEqual(
  JSON.stringify(context.hucksterMapPrices_(referenceItem)),
  JSON.stringify({
    displayedPrice: 6573,
    recommendedPrice: 4141.2,
    marketCardPrice: 4141.2,
    minPrice: 5398
  })
);

assert.strictEqual(context.hucksterColumnToLetter_(68), 'BP');
assert.strictEqual(context.hucksterColumnToLetter_(69), 'BQ');
assert.strictEqual(
  context.hucksterFindHeaderColumn_(['Артикул', ' Цена на витрине с картой Х ', 'Мин цена продажи Х'], 'Цена на витрине с картой Х', 'Цена на витрине с картой Х'),
  2
);
assert.strictEqual(
  context.hucksterFindHeaderColumn_(['Артикул', 'Цена на витрине с картой Х', 'Мин цена продажи Х'], 'Мин цена продажи Х', 'Мин цена продажи Х'),
  3
);

assert.strictEqual(
  context.hucksterExtractPasswordHash_('hashed-password'),
  'hashed-password'
);
assert.strictEqual(
  context.hucksterExtractPasswordHash_({ hash: 'hashed-password' }),
  'hashed-password'
);
assert.strictEqual(
  context.hucksterExtractPasswordHash_({ result: 'hashed-password' }),
  'hashed-password'
);
assert.strictEqual(context.hucksterExtractPasswordHash_({}), '');

const index = {};
context.hucksterAddRowKey_('SKU-1', 0, index);
context.hucksterAddRowKey_(' sku-1 ', 1, index);
context.hucksterAddRowKey_('', 2, index);
context.hucksterAddRowKey_(null, 3, index);
assert.strictEqual(JSON.stringify(Array.from(index['sku-1'])), JSON.stringify([0, 1]));
assert.strictEqual(index[''], undefined);

console.log('test_huckster_prices: PASS');
