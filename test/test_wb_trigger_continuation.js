const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const zlib = require('zlib');
const path = require('path');
const source = name => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');

// Exercise a two-page FBO response that crosses the invocation deadline.
let now = 0, written, checkpoint = [], checkpointCreated = false, httpCalls = 0;
const scratch = {
  getLastRow: () => checkpoint.length, getMaxRows: () => 1000,
  hideSheet() {}, clearContents() { checkpoint = []; },
  getRange: (row, column, count) => ({
    getValues: () => checkpoint.slice(row - 1, row - 1 + count),
    setValues: values => { checkpoint = values; }
  })
};
const dataSheet = { getLastRow: () => 2, getRange: (row, column) => ({
  getValues: () => [[column === 1 ? 'ART' : column === 20 ? 99 : 7]],
  getFormulas: () => [['']], setValues: values => { written = values; }
}) };
const response = items => ({ getResponseCode: () => 200,
  getContentText: () => JSON.stringify({ data: { items } }) });
const ctx = {
  Date: { now: () => now }, Logger: { log() {} },
  SpreadsheetApp: { getActiveSpreadsheet: () => ({
    getSheetByName: () => checkpointCreated ? scratch : null,
    insertSheet: () => { checkpointCreated = true; return scratch; }
  }) },
  Utilities: {
    newBlob: bytes => ({ getBytes: () => Buffer.from(bytes),
      getDataAsString: () => Buffer.from(bytes).toString() }),
    gzip: blob => ({ getBytes: () => zlib.gzipSync(blob.getBytes()) }),
    ungzip: blob => ({ getDataAsString: () => zlib.gunzipSync(blob.getBytes()).toString() }),
    base64Encode: bytes => Buffer.from(bytes).toString('base64'),
    base64Decode: text => Buffer.from(text, 'base64'), sleep: ms => { now += ms; }
  },
  UrlFetchApp: { fetch: () => {
    if (++httpCalls === 1) {
      now = 121000;
      return response(Array.from({ length: 1000 }, () => ({ nmId: 99, quantity: 1 })));
    }
    return response([{ nmId: 99, quantity: 2 }]);
  } },
  retryAfterDelayMs_: () => null, mainSheet: () => dataSheet,
  columnByHeader_: () => 15, WB_ANALYTICS_BASE_URL: () => '', wbAnalyticsHeaders: () => ({})
};
vm.createContext(ctx);
vm.runInContext(source('Shared_WB__Продолжение.js'), ctx);
vm.runInContext(source('List_ТЕСТ__O__Остатки_WB_FBO.js'), ctx);
ctx.wbMainContext_ = { deadline: 180000, state: {}, step: 1 };
assert.throws(() => ctx.updateWBStocksFromStatisticsAPI(), error => error.wbMainYield);
assert.equal(ctx.wbMainContext_.state.fbo.offset, 1000);
ctx.saveWbMainState_(ctx.wbMainContext_.state);
const restored = ctx.loadWbMainState_(1);
assert.equal(restored.fbo.stockMap['99'], 1000);
ctx.wbMainContext_ = { deadline: now + 180000, state: restored, step: 1 };
ctx.updateWBStocksFromStatisticsAPI();
assert.equal(httpCalls, 2);
assert.equal(written[0][0], 1002);
assert.throws(() => ctx.loadWbMainState_(2), /другому шагу/);
ctx.clearWbMainState_(); assert.equal(checkpoint.length, 0);
ctx.UrlFetchApp.fetch = () => ({ getResponseCode: () => 429 });
assert.throws(() => ctx.wbMainFetch_('url', {}), error => error.wbMainYield && error.delayMs >= 60000);

let bulkCalls = 0;
const mixedSheet = { getRange: () => ({ getValues: () => [[1], [2], [3]],
  getFormulas: () => [[''], ['=A2'], ['']],
  setValues: values => { written = values; bulkCalls++; }
}) };
ctx.wbMainWriteMasked_(mixedSheet, 15, [[9], [0], [0]], [true, false, false]);
assert.equal(bulkCalls, 1);
assert.deepEqual(JSON.parse(JSON.stringify(written)), [[9], ['=A2'], [3]]);

// Drive the public flow with stub writers, including trigger quota exhaustion.
let props = {}, calls = [], saved = [], released = 0, quota = false, flowNow = 0;
const flow = {
  Date: { now: () => flowNow },
  Logger: { log() {} }, PropertiesService: { getScriptProperties: () => ({
    getProperty: key => props[key] || null, setProperty: (key, value) => { props[key] = value; },
    deleteProperty: key => { delete props[key]; }
  }) }, SpreadsheetApp: { getActiveSpreadsheet: () => ({ toast() {} }) },
  LockService: { getScriptLock: () => ({ tryLock: () => true, releaseLock: () => { released++; } }) },
  ScriptApp: { getProjectTriggers: () => [], newTrigger: () => ({
    timeBased() { return this; }, after() { return this; },
    create() { if (quota) throw new Error('This script has too many triggers.'); }
  }) }, wbMainContext_: null, loadWbMainState_: () => ({}),
  saveWbMainState_: state => saved.push(state), clearWbMainState_() {},
  runWithTelegramAlertGAS_: (name, callback) => callback()
};
['updateWBStocksFromStatisticsAPI', 'updateOrdersSummaryV2', 'updatePricesAndImages',
  'main', 'updateWBAnalytics', 'updateWBWarehousesByName'].forEach((name, index) => {
  flow[name] = () => calls.push(index + 1);
});
vm.createContext(flow); vm.runInContext(source('Flow_Триггеры__Основные.js'), flow);
for (let step = 1; step <= 6; step++) { flowNow += 61000; flow.processWbStep(step); }
assert.deepEqual(calls, [1, 2, 3, 4, 5, 6]);
assert.equal(props.wb_main_step, undefined); assert.equal(released, 6);
quota = true; flow.processWbStep(1);
assert.equal(props.wb_main_step, '2'); assert.equal(saved.length, 0);
const beforeEarly = calls.length;
flow.processWbStep(2); assert.equal(calls.length, beforeEarly);
flowNow += 61000; flow.WbMainCore_();
assert.equal(calls.at(-1), 2); assert.equal(props.wb_main_step, '3');
flow.updatePricesAndImages = () => {
  flow.wbMainContext_.state = { prices: { offset: 1000 } };
  const error = new Error('budget'); error.wbMainYield = true; throw error;
};
flowNow += 61000; flow.processWbStep(3);
assert.equal(props.wb_main_step, '3'); assert.equal(saved.at(-1).prices.offset, 1000);
console.log('WB continuation checks passed: cursor/sums, checkpoint, transient HTTP, bulk masks, six steps, quota fallback.');
