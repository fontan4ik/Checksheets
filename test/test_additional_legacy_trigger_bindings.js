const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const calls = [], alerts = [];
const ctx = {
  runWithTelegramAlertGAS_: (name, callback) => { alerts.push(name); return callback(); },
  updateProductsV2AlertCore_: () => { calls.push('cards'); return 'cards-progress'; },
  startFetchAndWriteAnalytics_: () => { calls.push('analytics'); return 'analytics-progress'; },
  Logger: {log() {}}
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('Flow_Триггеры__Основные.js', 'utf8'), ctx);
assert.equal(ctx.maintainArticleColumn(), 'cards-progress');
assert.equal(ctx.OzonSKUAndAnalytic(), 'analytics-progress');
assert.deepEqual(calls, ['cards', 'analytics']);
assert.deepEqual(alerts, ['maintainArticleColumn', 'OzonSKUAndAnalytic']);
assert.equal(typeof ctx.auditArticleColumn, 'function');
ctx.startFetchAndWriteAnalytics_ = () => { throw new Error('terminal failure'); };
assert.throws(() => ctx.OzonSKUAndAnalytic(), /terminal failure/);
console.log('PASS existing legacy names delegate to bounded card/analytics cores, preserve alerts and terminal failures');
// Retry waits must fit the invocation budget; otherwise preserve the batch for a later run.
let now = 0, attempts = 0, sleeps = 0;
const http = {
  Date: {now: () => now}, Logger: {log() {}},
  UrlFetchApp: {fetch: () => { attempts++; return {getResponseCode: () => 429, getContentText: () => 'rate limit'}; }},
  Utilities: {sleep: ms => { now += ms; sleeps++; }}
};
vm.createContext(http);
vm.runInContext(fs.readFileSync('List_ТЕСТ__I_J_L_AO__Заказы_Ozon.js','utf8'), http);
assert.equal(http.fetchOzonAnalyticsResponse_('url', {}, 3, 80000), null);
assert.equal(attempts, 1); assert.equal(sleeps, 0);
now = 75000;
assert.equal(http.fetchOzonAnalyticsResponse_('url', {}, 3, 80000), null);
assert.equal(attempts, 1);
console.log('PASS analytics retry deadline reserves time for checkpoint');
let deletes = 0, continued = 0, activeRun = null;
http.deleteOzonAnalyticsContinuationTriggers_ = () => deletes++;
http.PropertiesService = {getScriptProperties: () => ({getProperty: () => activeRun})};
http.fetchAndWriteAnalytics = () => continued++;
http.continueFetchAndWriteAnalytics_();
assert.equal(deletes, 1); assert.equal(continued, 0);
activeRun = 'active'; http.continueFetchAndWriteAnalytics_();
assert.equal(deletes, 2); assert.equal(continued, 1);
console.log('PASS stale cross-owner continuation cannot start another analytics cycle');
