// Shared spreadsheet checkpoints must work across trigger owners and fail closed.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const zlib = require('zlib');
const crypto = require('crypto');
const source = fs.readFileSync(path.join(__dirname, '..', 'List_ТЕСТ__I_J_L_AO__Заказы_Ozon.js'), 'utf8');
const properties = {};
let cells = [], sheetCreated = false, driveCalls = 0;
const sheet = {
  getLastRow: () => cells.length, getMaxRows: () => 1000, hideSheet() {},
  clearContents() { cells = []; },
  getRange: (row, column, count = 1) => ({
    getValue: () => cells[row - 1]?.[0], getValues: () => cells.slice(row - 1, row - 1 + count),
    setValues: values => { cells = values; }
  })
};
const props = {
  getProperty: key => properties[key] || null,
  setProperty: (key, value) => { properties[key] = String(value); },
  deleteProperty: key => { delete properties[key]; }
};
function ownerContext() {
  const ctx = {
    Logger: { log() {} }, PropertiesService: { getScriptProperties: () => props },
    SpreadsheetApp: { getActiveSpreadsheet: () => ({
      getSheetByName: () => sheetCreated ? sheet : null,
      insertSheet: () => { sheetCreated = true; return sheet; }
    }) },
    ScriptApp: { getProjectTriggers: () => [] },
    DriveApp: { getFileById() { driveCalls++; throw new Error('Other owner private file'); },
      createFile() { driveCalls++; throw new Error('Unexpected Drive access'); } },
    Utilities: {
      DigestAlgorithm: { SHA_256: 'sha256' },
      computeDigest: (algorithm, text) => crypto.createHash(algorithm).update(text).digest(),
      newBlob: bytes => ({ getBytes: () => Buffer.from(bytes) }),
      gzip: blob => ({ getBytes: () => zlib.gzipSync(blob.getBytes()) }),
      ungzip: blob => ({ getDataAsString: () => zlib.gunzipSync(blob.getBytes()).toString() }),
      base64Encode: bytes => Buffer.from(bytes).toString('base64'),
      base64Decode: text => Buffer.from(text, 'base64')
    }
  };
  vm.createContext(ctx); vm.runInContext(source, ctx); return ctx;
}
const firstOwner = ownerContext(), secondOwner = ownerContext();
properties.OZON_ANALYTICS_RUN_ID = 'shared-run';
properties.OZON_ANALYTICS_RANGE_SIGNATURE = 'dates';
firstOwner.clearOzonAnalyticsTempStorage_();
firstOwner.appendOzonAnalyticsTempRows_([['shared-run', 0, '123', 7, 120]]);
secondOwner.appendOzonAnalyticsTempRows_([['shared-run', 0, '456', 2, 30]]);
const result = secondOwner.loadOzonAnalyticsTempMap_('shared-run', 0);
assert.equal(result['123'][0], 7); assert.equal(result['123'][1], 120);
assert.equal(result['456'][0], 2); assert.equal(driveCalls, 0);

// A corrupt or lost checkpoint must never be interpreted as empty analytics.
const original = cells.map(row => row.slice());
cells[1][0] = cells[1][0].slice(1);
assert.throws(() => secondOwner.readOzonAnalyticsTempPayload_(), /повреждён/);
assert.equal(properties.OZON_ANALYTICS_RUN_ID, 'shared-run');
cells = original; properties.OZON_ANALYTICS_RUN_ID = 'wrong-run';
assert.throws(() => secondOwner.readOzonAnalyticsTempPayload_(), /повреждён/);
properties.OZON_ANALYTICS_RUN_ID = 'shared-run';
cells = []; properties.OZON_ANALYTICS_BATCH_INDEX = '5';
assert.throws(() => secondOwner.readOzonAnalyticsTempPayload_(), /отсутствует/);
assert.equal(properties.OZON_ANALYTICS_BATCH_INDEX, '5');

// Legacy migration restarts ALL periods/batches without touching the private file.
properties.OZON_ANALYTICS_TEMP_FILE_ID = 'private-file';
properties.OZON_ANALYTICS_PERIOD_INDEX = '2';
properties.OZON_ANALYTICS_PERIOD_RETRY_COUNT = '3';
assert.throws(() => secondOwner.readOzonAnalyticsTempPayload_(), /сброса cursor/);
secondOwner.migrateOzonAnalyticsTempStorage_(props);
assert.equal(properties.OZON_ANALYTICS_TEMP_FILE_ID, undefined);
assert.equal(properties.OZON_ANALYTICS_BATCH_INDEX, undefined);
assert.equal(properties.OZON_ANALYTICS_PERIOD_INDEX, undefined);
assert.equal(properties.OZON_ANALYTICS_RUN_ID, undefined);
assert.equal(properties.OZON_ANALYTICS_RANGE_SIGNATURE, undefined);
assert.equal(properties.OZON_ANALYTICS_PERIOD_RETRY_COUNT, undefined);
assert.equal(driveCalls, 0);
assert.equal(secondOwner.readOzonAnalyticsTempPayload_().rows.length, 0);
console.log('PASS: cross-owner analytics checkpoint, preserved metrics, corrupt/missing state rejection, full legacy restart without Drive access.');
