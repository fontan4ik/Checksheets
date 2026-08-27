const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const sourcePath = path.join(__dirname, '..', 'Huckster цены.js');
const source = fs.readFileSync(sourcePath, 'utf8');
let capturedOptions = null;
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
  UrlFetchApp: {
    fetch: function(url, options) {
      capturedOptions = options;
      return { getResponseCode: function() { return 200; } };
    }
  },
  Utilities: { sleep: function() {} }
};
vm.createContext(context);
vm.runInContext(source, context, { filename: sourcePath });
context.hucksterFetchRaw_('/auth/credentials', {}, null);

assert.strictEqual(capturedOptions.headers.Accept, 'application/json');
console.log('test_huckster_api_headers: PASS');
