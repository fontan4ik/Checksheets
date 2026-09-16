const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('НТЦ списания.js', 'utf8');
const stockRows = [
  ['2851987-3', '2851987', '', '', '', 100, 33, 3],
  ['2851987-5', '2851987', '', '', '', 100, 20, 5]
];
const ledgerRows = [['posting_number', 'status', 'products_json']];
const reserveRows = [];
let postings = [];
let failFetch = false;
let fetchCalls = 0;
const properties = {NTC_FBS_RESERVE_START_UTC: '2026-09-01T00:00:00.000Z'};

const stock = {
  getLastRow: () => 3,
  getRange(row, col, count) {
    if (row === 1) return {getDisplayValues: () => [[
      'Артикул продавца', '', '', '', '', 'Остаток склад по моделям', '', '', '', '', 'Ручное списание штук'
    ]]};
    if (col === 1) return {getValues: () => stockRows};
    if (col === 13) return {setValues(values) { reserveRows.splice(0, reserveRows.length, ...values); }};
    throw Error('Unexpected stock range ' + row + '/' + col + '/' + count);
  }
};
const ledger = {
  getLastRow: () => ledgerRows.length,
  getRange(row, col, count) {
    if (row !== 2 || col !== 1) throw Error('Unexpected ledger range');
    return {
      getValues: () => ledgerRows.slice(1, 1 + count),
      setValues(values) { ledgerRows.splice(1, values.length, ...values); },
      clearContent() { ledgerRows.splice(1); }
    };
  }
};
const ss = {getSheetByName(name) {
  if (name === 'НТЦ списания') return stock;
  if (name === '_НТЦ FBS резерв') return ledger;
  return null;
}};
const context = vm.createContext({
  SpreadsheetApp: {getActiveSpreadsheet: () => ss},
  PropertiesService: {getDocumentProperties: () => ({
    getProperty: key => properties[key], setProperty: (key, value) => { properties[key] = value; }
  })},
  LockService: {getDocumentLock: () => ({tryLock: () => true, releaseLock() {}})},
  Logger: {log() {}},
  ozonNTCFindWarehouseId: () => 123,
  ozonNTCPost: (path, body) => {
    assert.equal(path, '/v3/posting/fbs/list');
    assert.deepEqual(Array.from(body.filter.warehouse_id), [123]);
    fetchCalls++;
    if (failFetch) throw Error('API failed');
    return {result: {postings: body.filter.status ? postings.filter(p => p.status === body.filter.status) : postings,
      has_next: false}};
  }
});
vm.runInContext(source, context);
const formula = context.ntcOutboundFormula_(2, 1000);
assert.match(formula, /\$N2/, 'outbound stock uses net model stock');
assert.doesNotMatch(formula, /\$G2|\$I2/, 'reference columns do not drive outbound stock');
const availableFormula = context.ntcAvailableFormula_(2, 1000);
assert.match(availableFormula, /\$K\$2:\$K\$1000/, 'manual write-off reads K');
assert.doesNotMatch(availableFormula, /\$J\$2:\$J\$1000/, 'chrlid in J is never subtracted');

function posting(status, quantity = 2) {
  return {posting_number: '123-1', status, in_process_at: '2026-09-15T00:00:00Z',
    products: [{offer_id: '2851987-3', quantity}]};
}
postings = [posting('awaiting_packaging')];
context.syncNtcFbsWriteOffs();
assert.equal(JSON.stringify(reserveRows), '[[6],[6]]', '2 packs of 3 reserve 6 model units');
assert.equal(ledgerRows.length, 2);
context.syncNtcFbsWriteOffs();
assert.equal(JSON.stringify(reserveRows), '[[6],[6]]', 'repeat is idempotent');

postings = [posting('cancelled')];
context.syncNtcFbsWriteOffs();
assert.equal(JSON.stringify(reserveRows), '[[0],[0]]', 'pre-shipment cancellation releases reserve');

postings = [posting('awaiting_packaging')];
context.syncNtcFbsWriteOffs();
postings = [posting('delivering')];
context.syncNtcFbsWriteOffs();
postings = [posting('cancelled')];
context.syncNtcFbsWriteOffs();
assert.equal(JSON.stringify(reserveRows), '[[6],[6]]', 'post-shipment cancellation does not invent a physical return');

postings = [posting('awaiting_packaging'), {posting_number: 'bad', status: 'awaiting_packaging',
  in_process_at: '2026-09-15T00:00:00Z', products: [{offer_id: 'missing', quantity: 1}]}];
context.syncNtcFbsWriteOffs();
assert.equal(JSON.stringify(reserveRows), '[[6],[6]]', 'unlisted warehouse products are ignored');
const before = JSON.stringify(ledgerRows);

postings = [{posting_number: 'broken', status: 'awaiting_packaging',
  in_process_at: '2026-09-15T00:00:00Z', products: [{offer_id: '2851987-3', quantity: -1}]}];
assert.throws(() => context.syncNtcFbsWriteOffs(), /Некорректные товары/);
assert.equal(JSON.stringify(ledgerRows), before, 'validation failure preserves ledger');

failFetch = true;
assert.throws(() => context.syncNtcFbsWriteOffs(), /API failed/);
assert.equal(JSON.stringify(ledgerRows), before, 'API failure preserves ledger');
assert.ok(fetchCalls >= 7);
console.log('NTC write-off tests passed');
