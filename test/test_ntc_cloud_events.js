'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const context = vm.createContext({Date, JSON, Number, Math});
['Shared_Engine.js', 'List_НТЦ__FBS__Журнал.js'].forEach(file => vm.runInContext(fs.readFileSync(path.resolve(__dirname, '../ntc-cloud', file), 'utf8'), context));
const clone = value => JSON.parse(JSON.stringify(value));
const articles = [{offer_id: 'M-3', model: 'M', H: 3}];
const book = {getSheetByName: () => null, getSheets: () => [{getSheetId: () => 1}, {getSheetId: () => 3}]};
function advance(previous, postings = [], returns = []) {
  return context.ntcAdvance_({articles, stock_by_model: previous ? previous.last_f_by_model : {M: 30}, postings, returns}, previous).state;
}
function posting(status, quantity, handed, number = 'OZ-1') {
  return {posting_number: number, status, ever_handed_over: handed, items: [{offer_id: 'M-3', quantity}]};
}
function accepted(id, quantity) {
  return {id, posting_number: 'OZ-1', schema: 'fbs', visual: {status: {sys_name: 'ReceivedBySeller'}}, product: {offer_id: 'M-3', quantity}};
}
function events(before, after, target = book) {
  return clone(context.ntcFbsEventRequests_(before, after, {rows: articles}, target, 'run-1'));
}
let base = advance();
let ordered = advance(base, [posting('awaiting_packaging', 4, false)]);
let result = events(base, ordered);
assert.equal(result.events.length, 1);
assert.equal(result.events[0].accountingDelta, -12);
assert.equal(result.events[0].stockBefore, 30);
assert.equal(result.events[0].stockAfter, 18);
assert.equal(result.requests[0].addSheet.properties.sheetId, 2);
assert.equal(result.requests[0].addSheet.properties.title, 'События FBS');
assert.equal(result.requests[1].appendCells.rows.length, 2);
assert.deepEqual(events(ordered, ordered), {requests: [], events: []});

let cancelled = advance(ordered, [posting('cancelled', 4, false)]);
assert.equal(events(ordered, cancelled).events[0].accountingDelta, 12);
assert.equal(cancelled.last_f_by_model.M, 30);
let alreadyCancelled = advance(base, [posting('cancelled', 4, false)]);
assert.equal(events(base, alreadyCancelled).events[0].accountingDelta, 0);

let shipped = advance(ordered, [posting('delivering', 4, true)]);
assert.equal(events(ordered, shipped).events[0].accountingDelta, 0);
let shippedCancel = advance(shipped, [posting('cancelled', 4, false)]);
assert.equal(events(shipped, shippedCancel).events[0].accountingDelta, 0);
assert.match(events(shipped, shippedCancel).events[0].note, /Передача/);
let unknownCancel = advance(ordered, [{posting_number: 'OZ-1', status: 'cancelled', items: [{offer_id: 'M-3', quantity: 4}]}]);
assert.equal(events(ordered, unknownCancel).events[0].accountingDelta, 0);

let returned = advance(shippedCancel, [], [accepted('r1', 1)]);
assert.equal(events(shippedCancel, returned).events[0].accountingDelta, 3);
assert.equal(events(shippedCancel, returned).events[0].returnId, 'r1');
let secondReturn = advance(returned, [], [accepted('r1', 1), accepted('r2', 2)]);
assert.equal(events(returned, secondReturn).events.length, 1);
assert.equal(events(returned, secondReturn).events[0].accountingDelta, 6);
assert.equal(events(secondReturn, advance(secondReturn, [], [accepted('r1', 1), accepted('r2', 2)])).events.length, 0);

let changed = advance(ordered, [posting('awaiting_packaging', 2, false)]);
assert.equal(events(ordered, changed).events[0].accountingDelta, 6);
assert.equal(events(ordered, changed).events[0].kind, 'Изменение количества FBS');
let increased = advance(changed, [posting('awaiting_packaging', 5, false)]);
assert.equal(events(changed, increased).events[0].accountingDelta, -9);

let short = advance(base, [posting('awaiting_packaging', 15, false)]);
assert.equal(events(base, short).events[0].accountingDelta, -45);
assert.equal(events(base, short).events[0].stockAfter, 0);
let shortReturn = advance(short, [], [accepted('r1', 1)]);
assert.equal(events(short, shortReturn).events[0].accountingDelta, 3);
assert.equal(events(short, shortReturn).events[0].stockAfter, 0);

let wb = advance(base, [posting('awaiting_packaging', 1, false, 'WB:123')]);
assert.equal(events(base, wb).events[0].platform, 'WB');
assert.equal(events(base, ordered).events[0].platform, 'Ozon');

// Existing sheets get only events; creating a sheet never mutates the book.
result = events(base, ordered, {getSheetByName: () => ({getSheetId: () => 77, getLastRow: () => 12})});
assert.equal(result.requests.length, 1);
assert.equal(result.requests[0].appendCells.sheetId, 77);
assert.equal(result.requests[0].appendCells.rows.length, 1);

// Preserve legacy manual debit without generating synthetic FBS orders.
let legacy = clone(base); legacy.manual_k = {'M-3': 1};
let manual = advance(legacy);
assert.equal(events(legacy, manual).events.length, 0);
console.log('NTC FBS events: order, cancellation, handover, partial return, replay, quantity and shortage checks passed');
