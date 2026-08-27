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
assert.deepStrictEqual(index['sku-1'], [0, 1]);
assert.strictEqual(index[''], undefined);

console.log('test_huckster_prices: PASS');
