'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { claimAppendInitializations: claim, seedAppendInitializationBaselines: seed, inspectAppendEligibility: inspect, destination } = require('../append_initialization_ledger');
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'checksheets-append-ledger-'));
const stateFile = path.join(directory, 'state.json');
const baseline = [['Артикул'], ['old']];
const appended = [...baseline, ['new']];
const options = { stateFile, scope: 'stream-formulas', sheetName: 'StreamSupps' };
const change = (row, offer, column = 6) => ({ row, offer, column, valueToWrite: '=FORMULA()' });
const observation = (row, offer, column = 6, value = '', formula = '') => ({ row, offer, column, value, formula });
try {
  // Migration protects every present row, including unfinished historic onboarding offers.
  let result = claim({ ...options, keys: baseline, changes: [change(2, 'old')], observedCells: [observation(2, 'old')] });
  assert.equal(result.seeded, true); assert.equal(result.authorized.length, 0);
  claim({ ...options, keys: baseline, changes: [], observedCells: [observation(2, 'old', 9, '=MANUAL()')] });
  assert.equal(Object.keys(Object.values(JSON.parse(fs.readFileSync(stateFile)).scopes)[0].cells).length, 0); // Baseline row protection needs no per-cell ledger bloat.
  result = claim({ ...options, keys: appended, changes: [change(3, 'new')], observedCells: [observation(3, 'new')] });
  assert.equal(result.authorized.length, 1);
  const persisted = JSON.parse(fs.readFileSync(stateFile));
  assert.equal(Object.values(persisted.scopes)[0].cells['3:6'].status, 'issued'); // Written before caller's mutation.
  // Simulate lost remote reply, or a user deleting the successfully initialized formula.
  result = claim({ ...options, keys: appended, changes: [change(3, 'new')], observedCells: [observation(3, 'new')] });
  assert.equal(result.authorized.length, 0); assert.equal(result.blocked[0].reason, 'initialization_already_issued');
  // A nonblank destination seen at admission is protected forever if later cleared.
  const next = [...appended, ['new2']];
  claim({ ...options, keys: next, changes: [], observedCells: [observation(4, 'new2', 7, 0)] });
  result = claim({ ...options, keys: next, changes: [change(4, 'new2', 7)], observedCells: [observation(4, 'new2', 7)] });
  assert.equal(result.authorized.length, 0); assert.equal(result.blocked[0].reason, 'destination_protected');
  // Prerequisite not ready on first observation: an unissued blank cell may initialize later.
  result = claim({ ...options, keys: next, changes: [change(4, 'new2', 8)], observedCells: [observation(4, 'new2', 8)] });
  assert.equal(result.authorized.length, 1);
  // Interior replacements, moved old offers, duplicates, and shrinking row count do not admit.
  result = claim({ ...options, keys: [['Артикул'], ['inserted'], ['new'], ['new2'], ['old']], changes: [change(2, 'inserted'), change(5, 'old')], observedCells: [observation(2, 'inserted'), observation(5, 'old')] });
  assert.equal(result.authorized.length, 0);
  claim({ ...options, keys: baseline, changes: [], observedCells: [] });
  result = claim({ ...options, keys: [['Артикул'], ['old'], ['dup'], ['dup']], changes: [change(3, 'dup')], observedCells: [observation(3, 'dup')] });
  assert.equal(result.authorized.length, 0);
  // Even a wholly new offer under the historical high-water mark is protected.
  result = claim({ ...options, keys: [['Артикул'], ['old'], ['fresh']], changes: [change(3, 'fresh')], observedCells: [observation(3, 'fresh')] });
  assert.equal(result.authorized.length, 0);
  assert.throws(() => claim({ ...options, keys: next, changes: [], observedCells: [{ row: 4, offer: 'new2', column: 9 }] }), /requires value/);
  assert.throws(() => destination({ row: 4, offer: 'new2', column: 9, range: 'J4' }, 'StreamSupps'), /Conflicting/);
  const beforePreview = fs.readFileSync(stateFile, 'utf8');
  const preview = inspect({ ...options, keys: [...next, ['skip-known'], ['preview-new']], columns: [6] });
  assert.deepEqual(preview.eligibleOffers, ['new2', 'preview-new']);
  assert.equal(fs.readFileSync(stateFile, 'utf8'), beforePreview);
  // Dry run cannot issue a destination or advance durable high water.
  const future = [...next, ['skip-known'], ['future']];
  result = claim({ ...options, dryRun: true, keys: future, changes: [change(6, 'future')], observedCells: [observation(6, 'future')] });
  assert.equal(result.authorized.length, 1);
  result = claim({ ...options, keys: future, changes: [change(6, 'future')], observedCells: [observation(6, 'future')] });
  assert.equal(result.authorized.length, 1);
  const second = { stateFile, scope: 'catalog-formulas', sheetName: 'ТЗ', keys: baseline };
  seed([second], { stateFile });
  assert.throws(() => seed([second], { stateFile }), /already established/);
  // First run of another helper/sheet is its own migration, never historical repair.
  assert.equal(claim({ ...second, changes: [change(2, 'old')], observedCells: [observation(2, 'old')] }).authorized.length, 0);
  const stateText = fs.readFileSync(stateFile, 'utf8');
  fs.writeFileSync(stateFile, '{}');
  assert.throws(() => claim({ ...options, keys: future }), /Invalid/);
  fs.writeFileSync(stateFile, stateText);
  fs.unlinkSync(stateFile);
  assert.throws(() => claim({ ...options, keys: future }), /Established.*missing/);
  console.log('append_initialization_ledger: all checks passed');
} finally { fs.rmSync(directory, { recursive: true, force: true }); }
