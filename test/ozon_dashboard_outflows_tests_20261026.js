'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const context = vm.createContext({
  Utilities: {
    formatDate: () => '2026-10-26'
  }
});
vm.runInContext(fs.readFileSync('ozon-dashboard/Shared_Ozon_Настройки.js', 'utf8'), context);
vm.runInContext(fs.readFileSync('ozon-dashboard/List_Основная__УходыПоСкладам__Ozon.js', 'utf8'), context);

const period = context.ozonDashboardOutflowPeriod_();
assert.equal(period.from, '2026-09-25T20:00:00.000Z');
assert.equal(period.to, '2026-10-26T19:59:59.999Z');
context.Utilities.formatDate = () => '2026-03-31';
assert.equal(context.ozonDashboardOutflowPeriod_().from, '2026-02-27T20:00:00.000Z');

const aggregated = context.ozonDashboardAggregateOutflowPostings_([
  {
    status: 'delivered',
    analytics_data: {warehouse_id: 101},
    products: [{sku: 3001, quantity: 2}, {sku: 3001, quantity: 1}, {sku: 3002, quantity: 4}]
  },
  {
    status: 'awaiting_deliver',
    analytics_data: {warehouse_id: 202},
    products: [{sku: 3001, quantity: 5}]
  },
  {
    status: 'cancelled',
    analytics_data: {warehouse_id: 101},
    products: [{sku: 3001, quantity: 99}]
  }
], {101: 'МО УХ', 202: 'СПБ УХ'});
assert.deepEqual(JSON.parse(JSON.stringify(aggregated)), {
  '3001': {'МО УХ': 3, 'СПБ УХ': 5},
  '3002': {'МО УХ': 4}
});

assert.throws(() => context.ozonDashboardAggregateOutflowPostings_([
  {status: 'delivered', analytics_data: {warehouse_id: 303}, products: [{sku: 3001, quantity: 1}]}
], {101: 'МО УХ'}), /склады не сопоставлены/);

const outflowHeaders = vm.runInContext('Object.values(OZON_DASHBOARD_OUTFLOW_HEADERS_)', context);
assert.equal(outflowHeaders.length, 16);
assert.equal(new Set(outflowHeaders).size, 16);

const clusterNames = [
  'Беларусь', 'Дальний Восток', 'Калининград', 'Санкт-Петербург и СЗО', 'Армения',
  'Узбекистан', 'Воронеж', 'Москва, МО и Дальние регионы', 'Уфа', 'Казань', 'Красноярск',
  'Тюмень', 'Саратов', 'Ярославль', 'Краснодар', 'Екатеринбург', 'Новосибирск', 'Омск',
  'Оренбург', 'Пермь', 'Ростов', 'Тверь', 'Алматы', 'Астана', 'Невинномысск'
];
const clusterResponse = {
  result: clusterNames.map((name, index) => ({
    data: {
      macrolocal_cluster: {name},
      fulfillments: [{warehouse_id: 10000 + index, name: 'ТЕСТОВЫЙ СКЛАД'}]
    }
  }))
};
context.ozonDashboardPostJson_ = () => clusterResponse;
const warehouseHeaders = context.ozonDashboardFetchFboWarehouseHeaders_({});
assert.equal(Object.keys(warehouseHeaders).length, clusterNames.length);
assert.ok(Object.values(warehouseHeaders).every(header => outflowHeaders.includes(header)));

function makeButtonHarness() {
  const properties = new Map();
  const triggers = [];
  const events = [];
  const sheet = {getLastRow: () => 3, getName: () => 'Основная'};
  const spreadsheet = {getSheetByName: name => name === 'Основная' ? sheet : null};
  const context = vm.createContext({
    Utilities: {getUuid: () => 'test-run-id'},
    Logger: {log: () => {}},
    SpreadsheetApp: {getActiveSpreadsheet: () => spreadsheet},
    PropertiesService: {getScriptProperties: () => ({
      getProperty: key => properties.get(key) || null,
      setProperty: (key, value) => properties.set(key, value),
      deleteProperty: key => properties.delete(key)
    })},
    LockService: {getScriptLock: () => ({tryLock: () => true, releaseLock: () => {}})},
    ScriptApp: {
      getProjectTriggers: () => triggers.slice(),
      deleteTrigger: trigger => { const index = triggers.indexOf(trigger); if (index >= 0) triggers.splice(index, 1); },
      newTrigger: handler => ({
        after: milliseconds => ({create: () => {
          triggers.push({handler, milliseconds, getHandlerFunction: () => handler});
        }}),
        timeBased: function() { return this; }
      })
    },
    runWithTelegramAlertGAS_: (_name, callback) => callback()
  });
  vm.runInContext(fs.readFileSync('ozon-dashboard/Flow_Основная__Дашборд_Ozon.js', 'utf8'), context);
  context.ozonDashboardFetchTargetWarehouseIds_ = () => ({});
  context.ozonDashboardSyncPrices_ = () => events.push('prices');
  context.ozonDashboardSyncStockSlice_ = (_sheet, state) => {
    events.push('stocks');
    state.rowOffset = state.lastRow + 1;
  };
  context.ozonDashboardBeginOutflows_ = (_sheet, state) => {
    events.push('begin-outflows');
    state.phase = 'outflows';
    properties.set('ozonDashboardSyncState', JSON.stringify(state));
  };
  context.ozonDashboardSyncOutflowPages_ = (_sheet, state) => {
    events.push('outflows');
    state.phase = 'outflowCommit';
  };
  context.ozonDashboardCommitOutflows_ = () => {
    events.push('commit-outflows');
    return {cellsWritten: 16};
  };
  context.ozonDashboardClearSync_ = () => {
    events.push('clear');
    properties.delete('ozonDashboardSyncState');
    triggers.splice(0, triggers.length);
  };
  return {context, events, properties, triggers};
}

const stocksRun = makeButtonHarness();
stocksRun.context.ozonDashboardLoadStocks();
assert.deepEqual(stocksRun.events, ['stocks', 'begin-outflows']);
assert.equal(JSON.parse(stocksRun.properties.get('ozonDashboardSyncState')).phase, 'outflows');
assert.deepEqual(stocksRun.triggers.map(trigger => trigger.handler), ['continueOzonDashboardSync']);
stocksRun.context.continueOzonDashboardSync();
assert.equal(JSON.parse(stocksRun.properties.get('ozonDashboardSyncState')).phase, 'outflowCommit');
stocksRun.context.continueOzonDashboardSync();
assert.deepEqual(stocksRun.events, ['stocks', 'begin-outflows', 'outflows', 'commit-outflows', 'clear']);

const combinedRun = makeButtonHarness();
combinedRun.context.ozonDashboardLoadPricesAndStocks();
assert.deepEqual(combinedRun.events, ['prices']);
assert.equal(JSON.parse(combinedRun.properties.get('ozonDashboardSyncState')).phase, 'stocks');
combinedRun.context.continueOzonDashboardSync();
assert.deepEqual(combinedRun.events, ['prices', 'stocks', 'begin-outflows']);

const pricesRun = makeButtonHarness();
pricesRun.context.ozonDashboardLoadPrices();
assert.deepEqual(pricesRun.events, ['prices', 'clear']);

console.log('Ozon dashboard outflow unit checks passed.');
