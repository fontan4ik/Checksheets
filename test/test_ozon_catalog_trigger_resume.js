const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('List_ТЕСТ__A_U__ProductId_Ozon.js', 'utf8');
function setup(responses) {
  const rows = [['OLD', 1]], props = new Map(), requests = [];
  let clock = 0, failNewU = false;
  const sheet = {
    getLastRow: () => rows.length + 1, getMaxRows: () => 10000,
    getParent: () => ({ getId: () => 'sheet' }), getSheetId: () => 1,
    getRange: (row, col, count) => ({
      getValues: () => Array.from({length: count}, (_, i) => [rows[row - 2 + i]?.[col === 1 ? 0 : 1] ?? '']),
      setNumberFormat: () => {},
      setValues: values => {
        if (failNewU && col === 21 && row === 3) { failNewU = false; throw Error('interrupted U write'); }
        values.forEach((v, i) => { rows[row - 2 + i] ||= ['', '']; rows[row - 2 + i][col === 1 ? 0 : 1] = v[0]; });
      }
    })
  };
  const context = {
    Date: {now: () => clock}, Logger: {log() {}}, mainSheet: () => sheet,
    columnByHeader_: () => 21, RPS: () => 20, rateLimitRPS: () => clock,
    ozonHeaders: () => ({}), ozonProductsApiURL: () => 'ozon',
    PropertiesService: {getScriptProperties: () => ({getProperty: k => props.get(k), setProperty: (k,v) => props.set(k,v), deleteProperty: k => props.delete(k)})},
    retryFetch: (_, opts) => {
      requests.push(JSON.parse(opts.payload));
      const r = responses.shift();
      clock += r.elapsed || 0;
      return {getResponseCode: () => r.code || 200, getContentText: () => JSON.stringify(r.body)};
    }
  };
  vm.createContext(context); vm.runInContext(source, context);
  return {context, rows, props, requests, resetClock: () => clock = 0, interruptNewU: () => failNewU = true};
}
const fullPage = [{offer_id:'OLD',product_id:2}, ...Array.from({length:999}, () => ({offer_id:'NEW',product_id:3}))];
let run = setup([
  {body:{result:{items:fullPage,last_id:'next'}},elapsed:180001},
  {body:{result:{items:[{offer_id:'LAST',product_id:4}],last_id:''}}}
]);
assert.equal(run.context.syncOfferIdWithProductIdCore_().complete, false);
assert.deepEqual(run.rows, [['OLD',2],['NEW',3]]);
assert.equal(JSON.parse(run.props.get('OZON_PRODUCT_LIST_CURSOR')).cursor, 'next');
run.resetClock();
assert.equal(run.context.syncOfferIdWithProductIdCore_().complete, true);
assert.equal(run.requests[1].last_id, 'next');
assert.deepEqual(run.rows, [['OLD',2],['NEW',3],['LAST',4]]);
assert.equal(run.props.has('OZON_PRODUCT_LIST_CURSOR'), false);
// Retry after A committed but U write failed must repair U without duplicate A.
run = setup([{body:{result:{items:[{offer_id:'NEW',product_id:3}]}}},{body:{result:{items:[{offer_id:'NEW',product_id:3}]}}}]);
run.interruptNewU();
assert.throws(() => run.context.syncOfferIdWithProductIdCore_(), /interrupted/);
run.context.syncOfferIdWithProductIdCore_();
assert.deepEqual(run.rows, [['OLD',1],['NEW',3]]);
// A full page with a missing cursor is an error, not a repeated first page.
run = setup([{body:{result:{items:fullPage}}}]);
assert.throws(() => run.context.syncOfferIdWithProductIdCore_(), /пагинация/);
assert.deepEqual(run.rows, [['OLD',1]]);
run = setup([{code:429,body:{error:'limit'}}]);
assert.equal(run.context.syncOfferIdWithProductIdCore_().complete, false);
assert.deepEqual(run.rows, [['OLD',1]]);
let called = 0;
const flow = {runWithTelegramAlertGAS_: (_, fn) => fn(), syncOfferIdWithProductIdAlertCore_: () => ++called};
vm.createContext(flow); vm.runInContext(fs.readFileSync('Flow_Триггеры__Основные.js','utf8'), flow);
flow.OzonMain(); assert.equal(called,1);
console.log('PASS OzonMain binding, catalog resume, per-page commit, partial-write repair, invalid pagination and transient retry');
