'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('List_ТЕХ_данные_wb__Таблица__WB.js', 'utf8');
function fixture(responses, options = {}) {
  let now = 1000;
  const properties = new Map();
  const triggers = [];
  const requests = [];
  const events = [];
  const sheets = new Map();
  const books = new Map();
  function makeSheet(name, collection = sheets) {
    const sheet = { name, setName(next) { collection.delete(this.name); this.name = next; collection.set(next, this); return this; }, values: name === 'ТЕХ данные wb' ? [['old-header'], ['old-data']] : [], max: 1000,
      getMaxColumns() { return 3; }, deleteColumns() {},
      getLastRow() { return this.values.length; }, getMaxRows() { return this.max; },
      insertRowsAfter(_, n) { this.max += n; }, clearContents() { this.values = []; }, hideSheet() {}, setFrozenRows() {},
      getRange(row, col, height, width) { return {
        setNumberFormat() { return this; },
        setValues(values) { events.push({ type: 'write', sheet: sheet.name, rows: values.length });
          if (sheet.name === '_WB_TECH_CATALOG_STAGE' && options.failStageWrite) throw new Error('stage-write-failed');
          values.forEach((v, i) => { sheet.values[row - 1 + i] = Array.from(v); }); return this; },
        getValues() { return sheet.values.slice(row - 1, row - 1 + height).map(r => r.slice(col - 1, col - 1 + width)); }
      }; }
    };
    collection.set(name, sheet);
    return sheet;
  }
  makeSheet('ТЕХ данные wb');
  const context = vm.createContext({ console, Set, Date: { now: () => now },
    Logger: { log() {} }, wbHeaders: () => ({}),
    runWithTelegramAlertGAS_: (_, callback) => callback(),
    LockService: { getScriptLock: () => ({ tryLock: () => true, releaseLock() {} }) },
    PropertiesService: { getScriptProperties: () => ({ getProperty: k => properties.get(k) || null,
      setProperty: (k, v) => { events.push({ type: 'property', key: k, value: v.startsWith('{') ? JSON.parse(v) : v }); return properties.set(k, v); }, deleteProperty: k => properties.delete(k) }) },
    Utilities: { sleep(ms) { now += options.sleep || ms; } },
    SpreadsheetApp: {
      create() {
        const id = 'private-' + (books.size + 1);
        const tabs = new Map();
        makeSheet('Sheet1', tabs);
        const book = { getId: () => id, getSheets: () => [...tabs.values()], getSheetByName: n => tabs.get(n) };
        books.set(id, book);
        events.push({ type: 'create', id });
        return book;
      },
      openById(id) { assert.ok(books.has(id)); return books.get(id); },
      flush() { events.push({ type: 'flush' }); }, getActiveSpreadsheet: () => ({ getSheetByName: n => sheets.get(n), insertSheet: makeSheet }) },
    ScriptApp: { getProjectTriggers: () => triggers.slice(), deleteTrigger(t) { triggers.splice(triggers.indexOf(t), 1); },
      newTrigger(name) { return { timeBased() { return this; }, after() { return this; }, create() { triggers.push({ getHandlerFunction: () => name }); } }; } },
    UrlFetchApp: { fetch(url, request) { requests.push(JSON.parse(request.payload)); const value = responses.shift();
      if (value instanceof Error) throw value;
      assert.ok(value, 'unexpected request');
      return { getResponseCode: () => value.status || 200, getContentText: () => value.raw || JSON.stringify(value.data) };
    } }
  });
  vm.runInContext(source, context);
  return { context, properties, triggers, sheets, requests, events, books, makeSheet };
}
const card = n => ({ vendorCode: 'ART-' + n, nmID: n, sizes: [{ chrtID: n + 1000 }] });
const page = (count, nmID = count) => ({ data: { cards: Array.from({ length: count }, (_, i) => card(i + 1)), cursor: { total: count, nmID, updatedAt: '2026-01-01' } } });
let passed = 0;
function test(name, callback) { callback(); passed++; console.log('PASS ' + name); }
test('full catalog uses cursor and publishes after terminal page', () => {
  const f = fixture([page(100), page(1)]);
  const result = f.context.updateWBTechDataSheet();
  assert.equal(result.complete, true);
  assert.equal(result.rows, 100); // deduplicated across pages
  assert.equal(f.requests[1].settings.cursor.nmID, 100);
  assert.equal(f.requests[0].settings.filter.withPhoto, -1);
  assert.equal(f.triggers.length, 0);
  assert.ok(f.properties.has('wb_tech_catalog_last_success'));
});
test('bounded execution resumes persisted cursor and does not publish partial', () => {
  const f = fixture([page(100), page(1)], { sleep: 150000 });
  assert.equal(f.context.updateWBTechDataSheet().complete, false);
  assert.equal(f.sheets.get('ТЕХ данные wb').values[1][0], 'old-data');
  assert.equal(f.triggers.length, 1);
  assert.equal(f.context.continueWBTechDataSheet().complete, true);
  assert.equal(f.requests[1].settings.cursor.nmID, 100);
});
test('HTTP 401 preserves published table and throws', () => {
  const f = fixture([{ status: 401 }]);
  assert.throws(() => f.context.updateWBTechDataSheet(), /HTTP 401/);
  assert.equal(f.sheets.get('ТЕХ данные wb').values[1][0], 'old-data');
});
test('transient 429 resumes without losing checkpoint', () => {
  const f = fixture([page(100), { status: 429 }, page(1)]);
  assert.equal(f.context.updateWBTechDataSheet().retry, true);
  assert.equal(f.sheets.get('ТЕХ данные wb').values[1][0], 'old-data');
  assert.equal(f.context.continueWBTechDataSheet().complete, true);
  assert.equal(f.requests[1].settings.cursor.nmID, f.requests[2].settings.cursor.nmID);
});
test('repeated and missing cursors reject partial catalog', () => {
  const repeated = fixture([page(100), page(100)]);
  assert.throws(() => repeated.context.updateWBTechDataSheet(), /repeated/);
  const missing = page(100); delete missing.data.cursor.updatedAt;
  assert.throws(() => fixture([missing]).context.updateWBTechDataSheet(), /missing pagination/);
});
test('invalid JSON and missing cards reject publication', () => {
  assert.throws(() => fixture([{ raw: 'bad' }]).context.updateWBTechDataSheet(), /invalid JSON/);
  assert.throws(() => fixture([{ data: { cursor: { total: 0 } } }]).context.updateWBTechDataSheet(), /malformed/);
});
test('empty catalog is never published', () => {
  const f = fixture([page(0)]);
  assert.throws(() => f.context.updateWBTechDataSheet(), /empty/);
  assert.equal(f.sheets.get('ТЕХ данные wb').values[1][0], 'old-data');
});
test('inconsistent pagination rejects instead of publishing a short page', () => {
  const value = page(1); value.data.cursor.total = 100;
  assert.throws(() => fixture([value]).context.updateWBTechDataSheet(), /inconsistent/);
});
test('sizes expand, duplicate rows removed, invalid drafts ignored', () => {
  const f = fixture([]);
  const rows = f.context.wbTechDataCatalogRows_([
    { vendorCode: 'A', nmId: 4, sizes: [{ chrtId: 1 }, { chrtID: 2 }, { chrtId: 1 }] },
    { vendorCode: 'B', nmID: 5 }, { vendorCode: 'draft' }
  ]);
  assert.equal(rows.length, 4);
  assert.equal(f.context.wbTechDataCatalogDedupe_(rows).length, 3);
});
test('obsolete table tail cleared in same successful write', () => {
  const f = fixture([page(1)]);
  f.sheets.get('ТЕХ данные wb').values.push(['obsolete']);
  f.context.updateWBTechDataSheet();
  assert.deepEqual(f.sheets.get('ТЕХ данные wb').values[2], ['', '', '']);
});
test('dispatcher mode yields without consuming or replacing trigger quota', () => {
  const f = fixture([page(100), page(1)], { sleep: 150000 });
  const permanent = { getHandlerFunction: () => 'refreshMarketplaceCatalogs' };
  f.triggers.push(permanent);
  assert.equal(f.context.wbTechDataCatalogSlice_(false).complete, false);
  assert.equal(f.triggers.length, 1);
  assert.equal(f.triggers[0], permanent);
  assert.equal(f.context.wbTechDataCatalogSlice_(false).complete, true);
  assert.equal(f.triggers.length, 1);
  assert.equal(f.triggers[0], permanent);
});
test('staging grows at most twice for 20000 rows while live allocation stays exact', () => {
  const f = fixture([]);
  let allocated = 1000;
  const growth = [];
  const stage = { getMaxRows: () => allocated, insertRowsAfter: (after, extra) => {
    assert.equal(after, allocated);
    allocated += extra;
    growth.push(allocated);
  }};
  for (let rows = 100; rows <= 20000; rows += 100) {
    f.context.wbTechDataCatalogEnsureRows_(stage, rows, 10000);
  }
  assert.deepEqual(growth, [10000, 20000]);
  f.context.wbTechDataCatalogEnsureRows_(stage, 20001);
  assert.equal(allocated, 20001);
});
test('ten API pages use one staging write and cursor commits after sheet flush', () => {
  const responses = Array.from({ length: 10 }, (_, n) => page(100, n + 1));
  responses.push(page(1));
  const f = fixture(responses);
  f.context.updateWBTechDataSheet();
  const writes = f.events.filter(e => e.type === 'write' && e.sheet === '_WB_TECH_CATALOG_STAGE');
  assert.equal(writes.length, 2);
  assert.deepEqual(writes.map(e => e.rows), [1000, 1]);
  const checkpoint = f.events.findIndex(e => e.type === 'property' && e.value.pages === 10);
  assert.equal(f.events[checkpoint - 1].type, 'flush');
  assert.equal(f.events[checkpoint - 2].rows, 1000);
});
test('staging write failure leaves durable cursor before entire buffered batch', () => {
  const f = fixture([page(100), page(1)], { failStageWrite: true });
  assert.throws(() => f.context.updateWBTechDataSheet(), /stage-write-failed/);
  const state = JSON.parse(f.properties.get('wb_tech_catalog_v2'));
  assert.equal(state.pages, 0);
  assert.equal(state.rows, 0);
  assert.equal(state.cursor, null);
  assert.equal(f.sheets.get('ТЕХ данные wb').values[1][0], 'old-data');
});
test('terminal malformed page safely replays preceding uncommitted pages', () => {
  const f = fixture([page(100), { raw: 'invalid-json' }]);
  assert.throws(() => f.context.updateWBTechDataSheet(), /invalid JSON/);
  assert.equal(JSON.parse(f.properties.get('wb_tech_catalog_v2')).pages, 0);
  assert.equal(f.events.filter(e => e.type === 'write').length, 0);
});
test('existing local checkpoint migrates exactly committed rows to private book', () => {
  const f = fixture([page(1)], { sleep: 150000 });
  const old = f.makeSheet('_WB_TECH_CATALOG_STAGE');
  old.values = [['saved', '111', '222'], ['uncommitted-tail', '333', '444']];
  f.properties.set('wb_tech_catalog_v2', JSON.stringify({ startedAt: 1000, rows: 1, cards: 100,
    pages: 1, cursor: { updatedAt: '2026-01-01', nmID: 100 }, retries: 0, ready: false }));
  const result = f.context.wbTechDataCatalogSlice_(false);
  assert.equal(result.complete, true);
  assert.equal(f.requests[0].settings.cursor.nmID, 100);
  const id = f.properties.get('wb_tech_stage_spreadsheet_id');
  const privateStage = f.books.get(id).getSheetByName('_WB_TECH_CATALOG_STAGE');
  assert.equal(privateStage.values[0][0], 'saved');
  assert.equal(privateStage.values[1][0], 'ART-1');
  assert.equal(old.values[1][0], 'uncommitted-tail');
  assert.equal(f.events.filter(e => e.type === 'create').length, 1);
});
test('private staging book reused for continuation and new full scans', () => {
  const f = fixture([page(100), page(1), page(1)], { sleep: 150000 });
  const partial = f.context.wbTechDataCatalogSlice_(false);
  const saved = JSON.parse(f.properties.get('wb_tech_catalog_v2'));
  assert.equal(partial.stageSpreadsheetId, saved.stageSpreadsheetId);
  assert.equal(f.context.wbTechDataCatalogSlice_(false).complete, true);
  assert.equal(f.context.wbTechDataCatalogSlice_(false).complete, true);
  assert.equal(f.events.filter(e => e.type === 'create').length, 1);
  assert.equal(f.sheets.has('_WB_TECH_CATALOG_STAGE'), false);
});
test('unchanged published table skips all native writes', () => {
  const f = fixture([]);
  const sheet = f.sheets.get('ТЕХ данные wb');
  sheet.values = [['Артикул продавца', 'Код размера (chrt_id)', 'Артикул WB'], ['A', 11, 22]];
  assert.equal(f.context.prepareWBTechDataSheet_(sheet, [['A', '11', '22']]), false);
  assert.equal(f.events.filter(e => e.type === 'write').length, 0);
});
test('ready checkpoint recognizes prior durable publication without write or flush', () => {
  const f = fixture([]);
  const staging = f.context.wbTechDataCatalogCreateStage_();
  staging.sheet.values = [['A', '111', '222']];
  f.sheets.get('ТЕХ данные wb').values = [
    ['Артикул продавца', 'Код размера (chrt_id)', 'Артикул WB'], ['A', '111', '222'], ['', '', '']
  ];
  f.properties.set('wb_tech_catalog_v2', JSON.stringify({ startedAt: 1000, rows: 1, cards: 1,
    pages: 1, cursor: null, retries: 0, ready: true, stageSpreadsheetId: staging.book.getId() }));
  f.events.length = 0;
  assert.equal(f.context.wbTechDataCatalogSlice_(false).complete, true);
  assert.equal(f.events.filter(e => e.type === 'write' || e.type === 'flush').length, 0);
  assert.equal(f.properties.has('wb_tech_catalog_v2'), false);
  assert.equal(f.properties.has('wb_tech_catalog_last_success'), true);
  assert.equal(f.requests.length, 0);
});
test('nonempty obsolete published tail still requires replacement', () => {
  const f = fixture([]);
  const sheet = f.sheets.get('ТЕХ данные wb');
  sheet.values = [['Артикул продавца', 'Код размера (chrt_id)', 'Артикул WB'], ['A', '11', '22'], ['obsolete', '', '']];
  assert.equal(f.context.prepareWBTechDataSheet_(sheet, [['A', '11', '22']]), true);
  assert.deepEqual(sheet.values[2], ['', '', '']);
});
console.log(passed + ' WB catalog tests passed');
