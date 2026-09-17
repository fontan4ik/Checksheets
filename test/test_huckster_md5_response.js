const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const sourcePath = path.join(__dirname, '..', 'Flow_ТЕСТ_ARL_TR__Цены_Huckster.js');
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

assert.strictEqual(
  context.hucksterParseMd5Response_('"0123456789abcdef0123456789abcdef"'),
  '0123456789abcdef0123456789abcdef'
);
assert.strictEqual(
  context.hucksterParseMd5Response_('0123456789abcdef0123456789abcdef'),
  '0123456789abcdef0123456789abcdef'
);
assert.throws(
  () => context.hucksterParseMd5Response_('<html>verification required</html>'),
  /некорректный JSON.*md5/i
);

console.log('test_huckster_md5_response: PASS');
