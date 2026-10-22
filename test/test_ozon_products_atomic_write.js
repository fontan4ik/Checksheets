const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const native = [], requests = [], props = new Map();
let responseCode = 200;
const context = {
  Logger: {log() {}},
  PropertiesService: {getScriptProperties: () => ({setProperty: (k,v) => props.set(k,v), deleteProperty: k => props.delete(k)})},
  ScriptApp: {getOAuthToken: () => 'test-token'},
  UrlFetchApp: {fetch: (url, options) => {
    requests.push({url, body: JSON.parse(options.payload)});
    return {getResponseCode: () => responseCode};
  }}
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('List_ТЕСТ__C_E_V_X_Y__Товары_Ozon.js', 'utf8'), context);
const sheet = {getName: () => "ТЕ'СТ", getParent: () => ({getId: () => 'sheet'})};
const literalValues = ['00123', '=literal', "'quote", 12, true, '', '=IMAGE("https://img")', '=A1'];
const pending = Array.from({length:6}, (_, index) => ({
  column: [3,4,5,22,24,25][index],
  range: {setValues: values => native.push(values)},
  values: literalValues.map(value => [value]),
  formulaFlags: literalValues.map((_, index) => index >= 6)
}));
assert.equal(context.writeOzonProductColumns_(sheet, 8002, pending), 'rest');
assert.equal(requests.length, 1);
assert.equal(native.length, 0);
assert.equal(requests[0].body.data.length, 6);
assert.equal(requests[0].body.data[0].range, "'ТЕ''СТ'!C8002:C8009");
assert.deepEqual(requests[0].body.data[0].values.map(row => row[0]), ["'00123", "'=literal", "''quote", 12, true, '', '=IMAGE("https://img")', '=A1']);
responseCode = 403;
assert.equal(context.writeOzonProductColumns_(sheet, 2, pending), 'native');
assert.equal(native.length, 6);
assert.equal(props.get('OZON_PRODUCTS_V2_NATIVE_WRITE'), '1');
assert.deepEqual(native[0], pending[0].values);
native.length = 0;
responseCode = 500;
assert.throws(() => context.writeOzonProductColumns_(sheet, 2, pending), /HTTP 500/);
assert.equal(native.length, 0);
console.log('PASS atomic six-column REST write, text/number/formula fidelity, 403 fallback, 500 no partial writes');

responseCode = 200;
assert.equal(context.writeOzonProductColumns_(sheet, 2, pending), 'rest');
assert.equal(props.has('OZON_PRODUCTS_V2_NATIVE_WRITE'), false);
console.log('PASS native fallback checkpoint and automatic REST recovery');
