const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const props = new Map();
let triggers = [];
let status = 429;
let writes = 0;
const sheet = { getLastRow: () => 2, getRange: () => ({
  getDisplayValues: () => [['123']],
  setValues: () => { writes++; }, setNumberFormat: () => {},
}) };
const context = {
  Logger: { log() {} },
  LockService: { getScriptLock: () => ({ tryLock: () => true, releaseLock() {} }) },
  PropertiesService: { getScriptProperties: () => ({
    getProperty: key => props.get(key) || null,
    setProperty: (key, value) => props.set(key, value),
    deleteProperty: key => props.delete(key),
  }) },
  ScriptApp: {
    getProjectTriggers: () => [...triggers],
    deleteTrigger: trigger => { triggers = triggers.filter(item => item !== trigger); },
    newTrigger: handler => ({ timeBased: () => ({ after: delay => ({ create: () => {
      triggers.push({ getHandlerFunction: () => handler, delay });
    } }) }) }),
  },
  runWithTelegramAlertGAS_: (_, run) => run(),
  ozonHeaders: () => ({}),
  retryFetch: () => ({ getResponseCode: () => status,
    getContentText: () => JSON.stringify({ products: [{ sku: '123', amount: 10, quantity: 2 }] }) }),
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'List_UNIT_API__УПД__Ozon.js'), 'utf8'), context);
context.getOzonBuyoutOrdersUnitApiSheet_ = () => sheet;
context.getOzonBuyoutOrdersHeaderMap_ = () => ({ 'ску oz': 1 });
context.ensureOzonBuyoutOrdersColumn_ = () => 11;
context.ensureOzonBuyoutOrdersQuantityColumn_ = () => 36;
context.splitOzonBuyoutOrdersPeriods_ = (from, to) => [{ from, to }];
context.updateOzonBuyoutOrdersUnitApiForDates('2026-09-01', '2026-09-30', 0);
assert.equal(writes, 0, '429 must preserve existing values');
assert.equal(triggers.length, 1);
assert.equal(triggers[0].delay, 300000);
assert.deepEqual(JSON.parse(props.get('ozonBuyoutUnitApiRetry')), { from: '2026-09-01', to: '2026-09-30', attempt: 1 });
context.retryOzonBuyoutOrdersUnitApi();
assert.equal(triggers.length, 1, 'continuations must not accumulate triggers');
assert.equal(JSON.parse(props.get('ozonBuyoutUnitApiRetry')).attempt, 2);
status = 200;
context.retryOzonBuyoutOrdersUnitApi();
assert.equal(writes, 2);
assert.equal(props.size, 0);
assert.equal(triggers.length, 0);
status = 429;
assert.throws(() => context.updateOzonBuyoutOrdersUnitApiForDates('2026-09-01', '2026-09-30', 4), /429/);
assert.equal(props.size, 0);
status = 401;
assert.throws(() => context.updateOzonBuyoutOrdersUnitApiForDates('2026-09-01', '2026-09-30', 0), /401/);
assert.equal(triggers.length, 0);
assert.throws(() => { status = 429; context.updateOzonBuyoutOrdersUnitApiForDates('2026-09-01', '2026-09-30'); }, /429/);
context.retryAfterDelayMs_ = () => 1800000;
context.updateOzonBuyoutOrdersUnitApiForDates('2026-09-01', '2026-09-30', 0);
assert.equal(triggers[0].delay, 1800000, 'deferred retry respects server cooldown');
context.clearOzonBuyoutOrdersRetry_();
context.retryFetch = () => null;
context.updateOzonBuyoutOrdersUnitApiForDates('2026-09-01', '2026-09-30', 0);
assert.equal(triggers.length, 1, 'exhausted network outage also defers');
console.log('PASS buyout deferred retry preserves values, original dates, bounded retries and terminal alerts');
