'use strict';
const assert = require('node:assert/strict');
const {ntcAdvance_: advance, ntcApplyMovements_: move, ntcAllocate_: allocate} = require('../ntc-cloud/Shared_Engine');
const articles = [3, 5, 10].map(H => ({offer_id: 'M-' + H, model: 'M', H}));
function snapshot(stock = 100, postings = [], returns = [], manual_k = {}) {
  return {stock_by_model: {M: stock}, articles, postings, returns, manual_k};
}
function posting(status, quantity = 1, handoff = false) {
  const row = {posting_number: 'P', status, items: [{offer_id: 'M-10', quantity}]};
  if (handoff !== null) row.ever_handed_over = handoff;
  return row;
}
function returned(quantity = 1, id = 'R', status = 'ReceivedBySeller') {
  return {id, schema: 'Fbs', posting_number: 'P', product: {offer_id: 'M-10', quantity}, visual: {status: {sys_name: status}}};
}
let count = 0;
function test(name, fn) { fn(); count++; console.log('ok - ' + name); }

test('orders debit once; omitted snapshots retain history and input state is immutable', () => {
  const first = advance(snapshot(100, [posting('awaiting_packaging', 2)]));
  const previous = JSON.stringify(first.state);
  assert.deepEqual(first.F_by_model, {M: 80});
  const retry = advance(snapshot(80, [posting('awaiting_packaging', 2)]), first.state);
  assert.deepEqual(retry.delta_physical_by_model, {M: 0});
  assert.deepEqual(advance(snapshot(80), retry.state).F_by_model, {M: 80});
  assert.equal(JSON.stringify(first.state), previous);
});
test('duplicate item rows aggregate while duplicate posting snapshot does not double debit', () => {
  const p = posting('awaiting_packaging');
  p.items.push({offer_id: 'M-10', quantity: 2});
  assert.deepEqual(advance(snapshot(100, [p, p])).F_by_model, {M: 70});
});
test('cancel before handover credits once; unknown cancellation history fails closed', () => {
  const first = advance(snapshot(100, [posting('awaiting_packaging')]));
  const unknown = advance(snapshot(90, [posting('cancelled', 1, null)]), first.state);
  assert.equal(unknown.F_by_model.M, 90);
  const cancel = advance(snapshot(90, [posting('cancelled')]), first.state);
  assert.equal(cancel.F_by_model.M, 100);
  assert.equal(advance(snapshot(100, [posting('cancelled')]), cancel.state).F_by_model.M, 100);
});
test('handover is sticky; cancellation cannot erase shipped items', () => {
  const first = advance(snapshot(100, [posting('delivering', 2, true)]));
  const emptyCancel = posting('cancelled', 0, false);
  const cancelled = advance(snapshot(80, [emptyCancel]), first.state);
  assert.equal(cancelled.F_by_model.M, 80);
  assert.equal(cancelled.state.postings.P.items['M-10'], 2);
  const omitted = {posting_number: 'P', status: 'not_accepted', ever_handed_over: false};
  assert.equal(advance(snapshot(80, [omitted]), cancelled.state).F_by_model.M, 80);
});
test('partial accepted returns credit once; in-transit and FBO returns do not credit', () => {
  const first = advance(snapshot(100, [posting('delivered', 3, true)]));
  const fbo = returned(); fbo.schema = 'Fbo';
  const ignored = advance(snapshot(70, [], [returned(1, 'T', 'ArrivedAtReturnPlace'), fbo]), first.state);
  assert.equal(ignored.F_by_model.M, 70);
  const accepted = advance(snapshot(70, [], [returned(), returned()]), ignored.state);
  assert.equal(accepted.F_by_model.M, 80);
  assert.deepEqual(accepted.applied_units_by_offer, {'M-10': 2});
  assert.equal(advance(snapshot(80, [], [returned()]), accepted.state).F_by_model.M, 80);
  assert.throws(() => advance(snapshot(80, [], [returned(2)]), accepted.state), /changed after acceptance/);
  assert.throws(() => advance(snapshot(80, [], [returned(3, 'R2')]), accepted.state), /returns exceed ordered/);
});
test('partial cancellation updates debit; manual K is a complete snapshot', () => {
  const first = advance(snapshot(100, [posting('awaiting_packaging', 2)], [], {'M-5': 2}));
  assert.equal(first.F_by_model.M, 70);
  const reduced = advance(snapshot(70, [posting('awaiting_packaging', 1)], [], {'M-5': 1}), first.state);
  assert.equal(reduced.F_by_model.M, 85);
  const manualCleared = advance(snapshot(85), reduced.state);
  assert.equal(manualCleared.F_by_model.M, 90);
});
test('shortage clamps F and cancellation restores original pool without overcredit', () => {
  const first = advance(snapshot(5, [posting('awaiting_packaging')]));
  assert.deepEqual(first.F_by_model, {M: 0});
  assert.deepEqual(first.shortage_physical_by_model, {M: 5});
  assert.equal(advance(snapshot(0), first.state).F_by_model.M, 0);
  const restored = advance(snapshot(0, [posting('cancelled')]), first.state);
  assert.equal(restored.F_by_model.M, 5);
  const manualShort = advance(snapshot(5, [], [], {'M-5': 25}), restored.state);
  assert.equal(manualShort.shortage_physical_by_model.M, 120);
  assert.equal(advance(snapshot(0), manualShort.state).F_by_model.M, 5);
});
test('external F change and unsafe quantities are rejected', () => {
  const state = advance(snapshot(100, [posting('awaiting_packaging')])).state;
  assert.throws(() => advance(snapshot(100), state), /F changed outside/);
  assert.throws(() => advance(snapshot(-1)), /nonnegative/);
  assert.throws(() => advance(snapshot(1.2)), /integer/);
  assert.throws(() => advance(snapshot(Number.MAX_SAFE_INTEGER + 1)), /integer/);
  const malformed = snapshot(); malformed.articles = [{offer_id: 'M', model: 'M', H: true}];
  assert.throws(() => advance(malformed), /integer/);
});
test('safe model addition preserves existing ledger; outstanding multiplicity edits reject', () => {
  const first = advance(snapshot(100, [posting('awaiting_packaging')]));
  const added = snapshot(90); added.stock_by_model.N = 20;
  added.articles = articles.concat([{offer_id: 'N-2', model: 'N', H: 2}]);
  const second = advance(added, first.state);
  assert.deepEqual(second.F_by_model, {M: 90, N: 20});
  const changed = snapshot(90); changed.articles = articles.map(a => ({...a, H: a.H === 10 ? 11 : a.H}));
  assert.throws(() => advance(changed, first.state), /outstanding history/);
  changed.articles = articles.map(a => ({...a, model: a.H === 10 ? 'N' : 'M'}));
  changed.stock_by_model.N = 20;
  assert.throws(() => advance(changed, first.state), /outstanding history/);
});
test('legacy ledger upgrade reconstructs physical baseline', () => {
  const first = advance(snapshot(100, [posting('awaiting_packaging')]));
  delete first.state.base_physical_by_model;
  delete first.state.article_schema_by_offer;
  const next = advance(snapshot(90, [posting('cancelled')]), first.state);
  assert.equal(next.F_by_model.M, 100);
});
test('supply and writeoff are physical pieces and survive later order reconciliation', () => {
  const first = advance(snapshot(100, [posting('awaiting_packaging')])).state;
  const supply = {id: 'S', model: 'M', quantity: 7, type: 'supply', timestamp: '2026-10-13T00:00:00Z', comment: 'arrival'};
  const writeoff = {id: 'W', model: 'M', quantity: 4, type: 'writeoff', timestamp: '2026-10-13T00:00:01Z'};
  const updated = move(first, articles, [supply, writeoff]);
  assert.equal(updated.last_f_by_model.M, 93);
  assert.equal(updated.base_physical_by_model.M, 103);
  assert.equal(updated.applied_physical_by_model.M, 10);
  assert.equal(updated.manual_movement_physical_by_model.M, 3);
  assert.equal(first.last_f_by_model.M, 90);
  assert.deepEqual(move(updated, articles, [supply, writeoff]), updated);
  assert.throws(() => move(updated, articles, [{...writeoff, quantity: 5}]), /movement id changed/);
  const reconciled = advance(snapshot(93, [posting('cancelled')]), updated);
  assert.equal(reconciled.F_by_model.M, 103);
});
test('writeoff at zero creates no debt; supply first fills existing order shortage', () => {
  const first = advance(snapshot(5, [posting('awaiting_packaging')])).state;
  const before = JSON.stringify(first);
  const empty = move(first, articles, [{id: 'W', model: 'M', quantity: 1, type: 'writeoff'}]);
  assert.equal(empty.last_f_by_model.M, 0);
  assert.equal(empty.base_physical_by_model.M, first.base_physical_by_model.M);
  assert.equal(empty.movements.W.applied_quantity, 0);
  assert.equal(JSON.stringify(first), before);
  const partial = move(first, articles, [{id: 'S', model: 'M', quantity: 3, type: 'supply'}]);
  assert.equal(partial.last_f_by_model.M, 0);
  const filled = move(partial, articles, [{id: 'S2', model: 'M', quantity: 4, type: 'supply'}]);
  assert.equal(filled.last_f_by_model.M, 2);
  assert.equal(advance(snapshot(2), filled).shortage_physical_by_model.M, 0);
});
test('excess writeoff caps actual debit; retry, next supply and order cancellation remain correct', () => {
  const first = advance(snapshot(15, [posting('awaiting_packaging')])).state;
  const request = {id:'cap-W',model:'M',quantity:100,type:'writeoff'};
  const capped = move(first, articles, [request]);
  assert.equal(capped.last_f_by_model.M,0);
  assert.equal(capped.movements['cap-W'].quantity,100);
  assert.equal(capped.movements['cap-W'].applied_quantity,5);
  assert.equal(capped.base_physical_by_model.M,10);
  assert.deepEqual(move(capped,articles,[request]),capped);
  assert.throws(()=>move(capped,articles,[{...request,quantity:101}]),/movement id changed/);
  assert.equal(move(capped,articles,[{id:'new-supply',model:'M',quantity:7,type:'supply'}]).last_f_by_model.M,7);
  assert.equal(advance(snapshot(0,[posting('cancelled')]),capped).F_by_model.M,10);
});
test('balanced allocation matches full cycles and never oversells physical pool', () => {
  assert.deepEqual(allocate({M: 100}, articles), {'M-10': 5, 'M-5': 6, 'M-3': 6});
  assert.deepEqual(allocate({M: 18}, articles), {'M-10': 1, 'M-5': 1, 'M-3': 1});
  assert.deepEqual(allocate({M: 17}, articles), {'M-10': 0, 'M-5': 2, 'M-3': 2});
  for (let physical = 0; physical < 1000; physical++) {
    const result = allocate({M: physical}, articles);
    const used = articles.reduce((sum, a) => sum + result[a.offer_id] * a.H, 0);
    assert.ok(used <= physical && physical - used < 3);
    assert.ok(result['M-3'] >= result['M-5'] && result['M-5'] >= result['M-10']);
  }
  assert.throws(() => allocate({M: 100}, articles.concat([{offer_id: 'M-3-alt', model: 'M', H: 3}])), /repeated multiplicity/);
});
console.log(`${count} NTC engine scenarios passed.`);

const legacy = advance(snapshot(100, [], [], {"M-10": 2}));
const withoutColumn = snapshot(80); delete withoutColumn.manual_k;
const retained = advance(withoutColumn, legacy.state);
assert.equal(retained.F_by_model.M, 80);
assert.equal(retained.state.manual_k["M-10"], 2);
assert.equal(retained.delta_physical_by_model.M, 0);
console.log("Legacy writeoff column removal preserves accounted stock and journal");
