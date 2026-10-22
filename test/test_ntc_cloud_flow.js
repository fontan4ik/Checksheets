'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../ntc-cloud');
const clone = value => JSON.parse(JSON.stringify(value));
const headers = ['Артикул продавца', 'Артикул производителя', 'ФОТО', 'SKU OZON', 'SKU WB', 'Остаток склад по моделям',
  'Виртуальный остаток', 'Х', 'Округлённое+прогруз на мп', 'chrlid'];

function harness() {
  const stats = {batches: [], notifications: 0, published: 0, uuid: 0, toasts: [], triggers: []};
  const sheets = new Map();
  function sheet(name, id, data) {
    const result = {
      name, id, data: clone(data), maxRows: 100,
      getSheetId() { return id; }, getLastRow() { return this.data.length; }, getMaxRows() { return this.maxRows; }, hideSheet() {},
      getImages() { return []; }, setFrozenRows(rows) { this.frozenRows = rows; },
      getDataRange() { return {getValues: () => { if (stats.catalogRead && name === 'НТЦ списания') stats.catalogRead(this); return clone(this.data); }, getFormulas: () => this.data.map(r => r.map(() => ""))}; },
      getRange(row, col, rows = 1, cols = 1) {
        if (typeof row === 'string') {
          const match = /^([A-Z]+)(\d+):([A-Z]+)(\d+)$/.exec(row);
          assert.ok(match, 'unsupported mock A1 range: ' + row);
          const column = name => [...name].reduce((n, char) => n * 26 + char.charCodeAt(0) - 64, 0);
          row = Number(match[2]); col = column(match[1]);
          rows = Number(match[4]) - row + 1; cols = column(match[3]) - col + 1;
        }
        return {
          getDisplayValues: () => Array.from({length: rows}, (_, i) => Array.from({length: cols}, (_, j) => String((this.data[row - 1 + i] || [])[col - 1 + j] ?? ''))),
          getValues: () => Array.from({length: rows}, (_, i) => Array.from({length: cols}, (_, j) => (this.data[row - 1 + i] || [])[col - 1 + j] ?? '')),
          setValues: values => { values.forEach((r, i) => r.forEach((v, j) => { if (!this.data[row - 1 + i]) this.data[row - 1 + i] = []; this.data[row - 1 + i][col - 1 + j] = v; })); }
        };
      },
      appendRow(row) { this.data.push(row); }
    };
    sheets.set(name, result); return result;
  }
  const catalog = sheet('НТЦ списания', 1, [headers, ...[3, 5, 10].map(H => ['M-' + H, 'M', '', 100 + H, 200 + H, 100, 0, H, H === 10 ? 5 : 6, 300 + H])]);
  const operator = sheet('Склад НТЦ', 2, [[], [], [], [], [], ['МОДЕЛЬ','КОЛИЧЕСТВО, ШТ','ПОСТАВКА, ШТ','СПИСАНИЕ, ШТ'], ['M', 100, '', '']]);
  const journal = sheet('_НТЦ облако журнал', 3, [['Часть', 'JSON']]);
  const book = {getSheetByName: name => sheets.get(name), getSheets: () => [...sheets.values()], insertSheet: name => sheet(name, sheets.size + 1, []), toast(message) { stats.toasts.push(message); }};
  const properties = {NTC_LIVE: 'true', NTC_OZON_ENABLED: 'true', TELEGRAM_TOKEN: 'mock-token', TELEGRAM_CHAT: 'mock-chat'};
  const context = vm.createContext({console, Date, Set, Map, JSON, Number, Math,
    Logger: {log() {}},
    Session: {getEffectiveUser: () => ({getEmail: () => 'vladimir.romanovich.grebennikov@gmail.com'})},
    SpreadsheetApp: {openById: () => book, flush() {}},
    PropertiesService: {getScriptProperties: () => ({getProperty: key => properties[key] || null, setProperties: values => Object.assign(properties,values), setProperty: (key,value) => { properties[key]=value; }, deleteProperty: key => { delete properties[key]; }})},
    ScriptApp: {getProjectTriggers: () => stats.triggers, deleteTrigger: trigger => { stats.triggers = stats.triggers.filter(t => t !== trigger); }, newTrigger: name => ({timeBased() { return this; }, everyMinutes(value) { this.minutes = value; return this; }, after(value) { this.delay = value; return this; }, create() { const trigger = {getHandlerFunction: () => name, minutes: this.minutes, delay: this.delay}; stats.triggers.push(trigger); return trigger; }})},
    LockService: {getScriptLock: () => ({tryLock: () => true, releaseLock() {}})},
    Utilities: {getUuid: () => 'sheet-uuid-' + (++stats.uuid), formatDate: date => date.toISOString()},
    UrlFetchApp: {fetch: () => { stats.notifications++; return {}; }},
    Sheets: {Spreadsheets: {batchUpdate: request => {
      if (stats.beforeBatch) stats.beforeBatch(request);
      // Sheets validates and applies every request together: no partial mutation on failure.
      if (stats.failBatch) { stats.failBatch = false; throw new Error('mock atomic commit failure'); }
      stats.batches.push(clone(request));
      request.requests.forEach(r => {
        if (r.addSheet) { sheet(r.addSheet.properties.title, r.addSheet.properties.sheetId, []); return; }
        if (r.appendDimension) { const s = [...sheets.values()].find(s => s.id === r.appendDimension.sheetId); s.maxRows += r.appendDimension.length; return; }
        if (r.appendCells) {
          const s = [...sheets.values()].find(s => s.id === r.appendCells.sheetId);
          s.data.push(...r.appendCells.rows.map(row => row.values.map(cell => {
            const value = cell.userEnteredValue;
            return value.numberValue ?? value.stringValue ?? value.boolValue;
          })));
          return;
        }
        const update = r.updateCells, target = update.range || update.start;
        const s = [...sheets.values()].find(s => s.id === target.sheetId);
        const startRow = update.range ? target.startRowIndex : target.rowIndex;
        const startCol = update.range ? target.startColumnIndex : target.columnIndex;
        if (update.range) {
          for (let i = startRow; i < target.endRowIndex; i++) for (let j = startCol; j < target.endColumnIndex; j++) {
            if (!s.data[i]) s.data[i] = []; s.data[i][j] = '';
          }
        }
        update.rows.forEach((row, i) => row.values.forEach((cell, j) => {
          if (!s.data[startRow + i]) s.data[startRow + i] = [];
          const value = cell.userEnteredValue;
          s.data[startRow + i][startCol + j] = value.numberValue ?? value.stringValue ?? value.boolValue;
        }));
      });
    }}}
  });
  vm.runInContext(fs.readFileSync(path.join(root, 'Shared_Operator.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(path.join(root, 'Shared_Engine.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(path.join(root, 'Flow_НТЦ__Облако.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(path.join(root, 'List_НТЦ__FBS__Журнал.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(path.join(root, 'Flow_НТЦ__Трансляция.js'), 'utf8'), context);
  const initial = context.ntcReadCatalog_();
  journal.data.push(['0', JSON.stringify({engine: context.ntcAdvance_({stock_by_model: initial.stock_by_model, articles: initial.rows, manual_k: initial.manual_k}).state, revision: 0})]);
  context.ntcPublish_ = () => {
    stats.published++;
    assert.ok(context.ntcReadState_().publish_pending, 'publication must have durable pending state before remote call');
    if (stats.publishFailure) throw new Error('mock marketplace unavailable');
    return {confirmed: 6};
  };
  context.ntcFetchOrders_ = () => [];
  context.ntcFetchReturns_ = () => [];
  return {context, catalog, operator, journal, stats, properties, sheets, state: () => clone(context.ntcReadState_())};
}
let count = 0;
function test(name, action) { action(); count++; console.log('ok - ' + name); }
test('sheet supply commits journal, all stock outputs and input clear in one transaction', () => {
  const h = harness(); h.operator.data[6][2] = 7;
  h.context.ntcSupply();
  const first = h.stats.batches[0].requests;
  assert.ok(first.some(r => r.updateCells?.range?.sheetId === 3));
  assert.ok(first.some(r => r.updateCells?.start?.sheetId === 1));
  assert.ok(first.some(r => r.updateCells?.start?.sheetId === 2 && r.updateCells.start.columnIndex === 2 && r.updateCells.rows[0].values[0].userEnteredValue.stringValue === ''));
  const history = h.sheets.get('История склада');
  assert.ok(first.some(r => r.appendCells?.sheetId === history.id), 'human-readable history is in inventory transaction');
  assert.equal(history.data.length, 2);
  assert.equal(history.data[1][2], 'Поставка');
  assert.equal(history.data[1][4], 7);
  assert.equal(h.operator.data[6][2], '');
  assert.equal(h.catalog.data[1][5], 107);
  assert.equal(h.state().engine.last_f_by_model.M, 107);
  assert.ok(h.state().publish_pending);
  assert.equal(h.stats.published, 0, 'manual supply never sends marketplace stocks');
  const batches = h.stats.batches.length;
  h.context.ntcSupply();
  assert.equal(h.stats.batches.length, batches, 'double click with cleared input performs no second movement');
  assert.equal(history.data.length, 2, 'double click never appends duplicate history');
});
test('sheet writeoff is physical pieces, double click does not debit twice', () => {
  const h = harness(); h.operator.data[6][3] = 4;
  h.context.ntcWriteOff(); h.context.ntcWriteOff();
  assert.equal(h.state().engine.last_f_by_model.M, 96);
  assert.equal(h.catalog.data[1][5], 96);
  assert.equal(Object.keys(h.state().engine.movements).length, 1);
  assert.equal(h.sheets.get('История склада').data.length, 2);
});
test('scanner same UUID retry never repeats committed movement; changed content rejects', () => {
  const h = harness();
  const payload = {id: 'scanner-operation-uuid-1', type: 'writeoff', items: [{model: 'M', quantity: 8}], comment: 'scan'};
  h.context.ntcScannerSubmit(payload);
  const revision = h.state().revision;
  h.context.ntcScannerSubmit(payload);
  assert.equal(h.state().engine.last_f_by_model.M, 92);
  assert.equal(h.state().revision, revision);
  assert.equal(Object.keys(h.state().engine.movements).length, 1);
  assert.equal(h.sheets.get('История склада').data.length, 2, 'same UUID replay must not duplicate human-readable history');
  assert.throws(() => h.context.ntcScannerSubmit({...payload, items: [{model: 'M', quantity: 9}]}), /ID операции/);
});
test('failure before atomic commit leaves input and inventory available for safe retry', () => {
  const h = harness(); h.operator.data[6][3] = 8; h.stats.failBatch = true;
  assert.throws(() => h.context.ntcWriteOff(), /atomic commit failure/);
  assert.equal(h.operator.data[6][3], 8);
  assert.equal(h.state().engine.last_f_by_model.M, 100);
  assert.equal(h.catalog.data[1][5], 100);
  assert.equal(h.sheets.get('История склада').data.length, 1, 'failed atomic commit never appends a movement');
  h.context.ntcWriteOff();
  assert.equal(h.state().engine.last_f_by_model.M, 92);
  assert.equal(Object.keys(h.state().engine.movements).length, 1);
  assert.equal(h.sheets.get('История склада').data.length, 2);
});
test('background transmitter retries committed inventory and alerts once until recovery', () => {
  const h = harness(); h.stats.publishFailure = true; h.operator.data[6][3] = 8;
  const movement = h.context.ntcWriteOff();
  assert.equal(movement.ok, true); assert.equal(h.stats.published, 0);
  h.properties.NTC_TRANSMISSION_RUNNING = 'true';
  const result = h.context.ntcTransmitterTick();
  assert.equal(result.pending, true);
  assert.equal(h.state().engine.last_f_by_model.M, 92);
  assert.equal(h.operator.data[6][3], '');
  assert.ok(h.state().publish_pending.last_error);
  assert.equal(h.stats.notifications, 1);
  h.context.ntcTransmitterTick(); h.context.ntcTransmitterTick();
  assert.equal(h.state().engine.last_f_by_model.M, 92);
  assert.equal(h.stats.notifications, 1);
  h.stats.publishFailure = false; h.context.ntcTransmitterTick();
  assert.equal(h.state().publish_pending, undefined);
  assert.equal(h.state().engine.last_f_by_model.M, 92);
});
test('same scanner UUID remains accounting only, transmitter publishes separately', () => {
  const h = harness(); h.stats.publishFailure = true;
  const payload = {id: 'scanner-operation-uuid-2', type: 'supply', items: [{model: 'M', quantity: 8}]};
  h.context.ntcScannerSubmit(payload);
  h.stats.publishFailure = false; h.context.ntcScannerSubmit(payload);
  assert.equal(h.state().engine.last_f_by_model.M, 108);
  assert.equal(Object.keys(h.state().engine.movements).length, 1);
  assert.equal(h.stats.published, 0);
  assert.ok(h.state().publish_pending);
  h.properties.NTC_TRANSMISSION_RUNNING = 'true'; h.context.ntcTransmitterTick();
  assert.equal(h.state().publish_pending, undefined);
});
test('acknowledgement journal failure preserves pending retry without repeating movement', () => {
  const h = harness(); h.operator.data[6][3] = 8;
  h.context.ntcWriteOff();
  h.properties.NTC_TRANSMISSION_RUNNING = 'true';
  h.stats.beforeBatch = () => { h.stats.beforeBatch = null; h.stats.failBatch = true; };
  const result = h.context.ntcTransmitterTick();
  assert.equal(result.pending, true);
  assert.equal(h.state().engine.last_f_by_model.M, 92);
  assert.ok(h.state().publish_pending);
  h.context.ntcTransmitterTick();
  assert.equal(h.state().publish_pending, undefined);
  assert.equal(h.state().engine.last_f_by_model.M, 92);
  assert.equal(Object.keys(h.state().engine.movements).length, 1);
});
test('fresh catalog compares offer/H identities before commit, not only aggregate stock', () => {
  for (const edit of [s => { s.data[1][0] = 'M-3-new'; }, s => { s.data[1][7] = 4; }, s => { [s.data[1], s.data[2]] = [s.data[2], s.data[1]]; }]) {
    const h = harness(); h.operator.data[6][3] = 8;
    let reads = 0;
    h.stats.catalogRead = s => { if (++reads === 2) edit(s); };
    assert.throws(() => h.context.ntcWriteOff(), /таблица изменена/);
    assert.equal(h.state().engine.last_f_by_model.M, 100);
    assert.equal(h.operator.data[6][3], 8);
    assert.equal(h.stats.batches.length, 0);
  }
});
test('operator input/model edited during calculation rejects before clearing or applying', () => {
  for (const edit of [r => { r[3] = 9; }, r => { r[0] = 'changed-model'; }]) {
    const h = harness(); h.operator.data[6][3] = 8;
    let reads = 0;
    h.stats.catalogRead = () => { if (++reads === 2) edit(h.operator.data[6]); };
    assert.throws(() => h.context.ntcWriteOff(), /изменены во время операции/);
    assert.equal(h.state().engine.last_f_by_model.M, 100);
    assert.equal(h.stats.batches.length, 0);
  }
});
test('unchanged tick writes journal only and leaves derived cells untouched', () => {
  const h = harness(); h.context.ntcCloudTick();
  assert.ok(h.stats.batches.length > 0);
  h.stats.batches.forEach(batch => batch.requests.forEach(request => {
    const update = request.updateCells;
    assert.equal((update.range || update.start).sheetId, 3);
  }));
});
test('blank or boolean physical stock rejects before movement or input clearing', () => {
  for (const invalid of ['', ' ', true, false]) {
    const h = harness(); h.catalog.data.slice(1).forEach(row => { row[5] = invalid; });
    h.operator.data[6][3] = 8;
    assert.throws(() => h.context.ntcReadCatalog_(), /данные|остаток/);
    assert.throws(() => h.context.ntcWriteOff(), /данные|остаток/);
    assert.equal(h.operator.data[6][3], 8);
    assert.equal(h.state().engine.last_f_by_model.M, 100);
    assert.equal(h.stats.batches.length, 0);
  }
});

test('platform toggle never starts transmission or publishes synchronously', () => {
  const h=harness(); h.properties.NTC_WB_ENABLED='true';h.properties.WB_NTC_WAREHOUSE='22';
  h.properties['NTC_MP_wb_22_303']='6';h.properties['NTC_MP_wb_22_305']='6';h.properties['NTC_MP_wb_22_310']='5';h.properties['NTC_MP_ozon_11_M-3']='6';
  let cycles=0;h.context.ntcCloudTickUnlocked_=()=>{cycles++;assert.equal(h.properties['NTC_MP_wb_22_303'],undefined);};
  h.context.ntcToggleWb();assert.equal(h.properties.NTC_WB_ENABLED,'false');assert.equal(cycles,0);assert.equal(h.properties['NTC_MP_wb_22_303'],'6');
  h.context.ntcToggleWb();assert.equal(h.properties.NTC_WB_ENABLED,'true');assert.equal(cycles,0);assert.equal(h.stats.published,0);assert.notEqual(h.properties.NTC_TRANSMISSION_RUNNING,'true');assert.equal(h.properties['NTC_MP_ozon_11_M-3'],'6');
});

test('new product preparation preserves existing model pool and imports new model initial count once', () => {
  const h=harness();
  h.catalog.data.push(['M-20','M','',120,220,'','',20,'',320]);
  h.catalog.data.push(['NEW-20','NEW','',121,221,'','',20,'',321]);
  h.operator.data.push(['NEW',150,'','']);
  assert.equal(h.context.ntcPrepareNewProducts_(h.catalog),2);
  assert.equal(h.catalog.data[4][5],100);
  assert.equal(h.catalog.data[5][5],150);
  assert.equal(h.context.ntcPrepareNewProducts_(h.catalog),0);
  assert.equal(h.catalog.data[1][5],100);
});
test('new product without initial stock starts at zero', () => {
  const h=harness(); h.catalog.data.push(['NEW-20','NEW','',121,221,'','',20,'',321]);
  h.context.ntcPrepareNewProducts_(h.catalog); assert.equal(h.catalog.data[4][5],0);
});

test('orders tick and inactive transmitter never publish', () => {
  const h = harness(); h.context.ntcCloudTick(); h.context.ntcTransmitterTick();
  assert.equal(h.stats.published, 0);
  assert.ok(h.state().publish_pending);
});
test('either stock button applies both columns atomically, supplies before writeoffs', () => {
  for (const button of ['ntcSupply', 'ntcWriteOff']) {
    const h = harness(); h.operator.data[6][2] = 10; h.operator.data[6][3] = 4;
    h.context[button]();
    assert.equal(h.operator.data[6][2], ''); assert.equal(h.operator.data[6][3], '');
    assert.equal(h.state().engine.last_f_by_model.M, 106);
    assert.equal(h.sheets.get('История склада').data.length, 3);
    assert.equal(h.stats.published, 0);
    const revision = h.state().revision; h.context[button]();
    assert.equal(h.state().revision, revision, 'cleared columns cannot replay movements');
  }
});
test('same-operation supply is applied first and excess writeoff clamps to zero atomically', () => {
  const financed = harness(); financed.operator.data[6][2] = 20; financed.operator.data[6][3] = 110;
  financed.context.ntcWriteOff(); assert.equal(financed.state().engine.last_f_by_model.M, 10);
  assert.equal(financed.operator.data[6][2], ''); assert.equal(financed.operator.data[6][3], '');
  const h = harness(); h.operator.data[6][2] = 2; h.operator.data[6][3] = 200;
  h.context.ntcWriteOff();
  assert.equal(h.operator.data[6][2], ''); assert.equal(h.operator.data[6][3], '');
  assert.equal(h.state().engine.last_f_by_model.M, 0);
  const movement = Object.values(h.state().engine.movements).find(m => m.type === 'writeoff');
  assert.equal(movement.quantity, 200); assert.equal(movement.applied_quantity, 102);
  const revision = h.state().revision; h.context.ntcWriteOff();
  assert.equal(h.state().revision, revision);
  h.operator.data[6][2] = 7; h.context.ntcSupply();
  assert.equal(h.state().engine.last_f_by_model.M, 7);
});
test('start installs persistent transmitter and one-off kick without sending; restart does not duplicate', () => {
  const h = harness(); h.context.ntcStartTransmission(); h.context.ntcStartTransmission();
  assert.equal(h.properties.NTC_TRANSMISSION_RUNNING, 'true');
  assert.equal(h.stats.published, 0);
  assert.equal(h.stats.triggers.filter(t => t.getHandlerFunction() === 'ntcTransmitterTick').length, 1);
  assert.equal(h.stats.triggers.find(t => t.getHandlerFunction() === 'ntcTransmitterTick').minutes, 5);
  assert.equal(h.stats.triggers.filter(t => t.getHandlerFunction() === 'ntcCloudTick').length, 1);
  assert.equal(h.stats.triggers.filter(t => t.getHandlerFunction() === 'ntcTransmissionOnce').length, 1);
  h.context.ntcTransmissionOnce();
  assert.equal(h.stats.published, 1);
  assert.equal(h.stats.triggers.filter(t => t.getHandlerFunction() === 'ntcTransmissionOnce').length, 0);
  assert.equal(h.stats.triggers.filter(t => t.getHandlerFunction() === 'ntcTransmitterTick').length, 1);
  h.context.ntcStopTransmission(); h.context.ntcTransmitterTick();
  assert.equal(h.properties.NTC_TRANSMISSION_RUNNING, 'false'); assert.equal(h.stats.published, 1);
  assert.equal(h.stats.triggers.filter(t => t.getHandlerFunction() === 'ntcTransmitterTick').length, 0);
  assert.equal(h.stats.triggers.filter(t => t.getHandlerFunction() === 'ntcCloudTick').length, 1, 'stop keeps FBS order accounting');
});
console.log(`${count} NTC cloud flow scenarios passed.`);

test("active transmitter with both platforms off skips catalog and publication", () => { const h=harness(); h.properties.NTC_TRANSMISSION_RUNNING="true"; h.properties.NTC_OZON_ENABLED="false"; h.properties.NTC_WB_ENABLED="false"; h.context.ntcReadCatalog_=()=>{throw Error("must not read catalog");}; assert.equal(h.context.ntcTransmitterTick().ok,true); assert.equal(h.stats.published,0); });

test('three tables match movements by model rather than shared row number', () => {
 const h=harness(); h.catalog.data.push(['N-3','N','',121,221,50,0,3,16,321]);
 h.operator.data[5]=['МОДЕЛЬ','КОЛИЧЕСТВО, ШТ','','МОДЕЛЬ','ПОСТАВКА, ШТ','','МОДЕЛЬ','СПИСАНИЕ, ШТ'];
 h.operator.data[6]=['M',100,'','N',2,'','M',''];
 h.operator.data[7]=['N',50,'','M','','','N',1];
 h.context.ntcSupply(); assert.equal(h.state().engine.last_f_by_model.N,51); assert.equal(h.state().engine.last_f_by_model.M,100);
 assert.equal(h.operator.data[7][1],51); assert.equal(h.operator.data[6][4],''); assert.equal(h.operator.data[7][7],'');
});
test('G affects publication quantities but manual stock movement changes only F', () => {
 const h=harness(); h.catalog.data[3][6]=20; h.operator.data[6][2]=1; h.context.ntcSupply();
 assert.equal(h.catalog.data[3][5],101); assert.equal(h.catalog.data[3][6],20); assert.equal(h.catalog.data[3][8],6);
 assert.equal(h.state().engine.last_f_by_model.M,101);
});

test('FBS cancellation forces publication reconciliation even when rounded target is unchanged', () => {
 const h=harness(); h.context.ntcFetchOrders_=()=>[{posting_number:'CANCEL',status:'cancelled',ever_handed_over:true,items:[{offer_id:'M-3',quantity:1}]}];
 h.context.ntcCloudTick(); assert.equal(h.state().publication_reconcile_offers.ozon['M-3'],true);
 h.properties.NTC_TRANSMISSION_RUNNING='true'; h.properties.NTC_MP_ozon_11_M3='unused';
 h.context.ntcTransmitterTick(); assert.equal(h.state().publication_reconcile_offers.ozon,undefined);
});

test('owner FBS pause removes only FBS schedules and blocks API work before catalog reads', () => {
  const h=harness(); h.context.ntcStartTransmission();
  const result=h.context.ntcPauseFbs();
  assert.equal(result.fbsPaused,true);
  assert.equal(h.properties.NTC_FBS_PAUSED,'true');
  assert.equal(h.properties.NTC_TRANSMISSION_RUNNING,'false');
  assert.equal(h.properties.NTC_OZON_ENABLED,'false');
  assert.equal(h.properties.NTC_WB_ENABLED,'false');
  assert.equal(h.stats.triggers.filter(t=>['ntcCloudTick','ntcTransmitterTick','ntcTransmissionOnce'].includes(t.getHandlerFunction())).length,0);
  h.context.ntcReadCatalog_=()=>{throw new Error('catalog must not be read');};
  h.context.ntcCloudTick(); h.context.ntcTransmitterTick();
  assert.throws(()=>h.context.ntcStartTransmission(),/приостановлен/);
  assert.equal(h.stats.published,0);
});

test('deployed emergency flag disables FBS even without writable runtime properties', () => {
  const h=harness(); h.context.NTC_FBS_TEMPORARILY_PAUSED=true;
  h.context.ntcReadCatalog_=()=>{throw new Error('catalog must not be read');};
  h.context.ntcCloudTick(); h.context.ntcTransmitterTick();
  h.context.ntcInstallOrderTrigger_();
  assert.equal(h.stats.triggers.length,0);
  assert.throws(()=>h.context.ntcStartTransmission(),/приостановлен/);
  assert.equal(h.stats.published,0);
});
