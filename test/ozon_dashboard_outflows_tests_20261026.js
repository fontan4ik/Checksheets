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
    analytics_data: {warehouse_name: 'МОСКВА_РФЦ'},
    products: [{sku: 3001, quantity: 2}, {sku: 3001, quantity: 1}, {sku: 3002, quantity: 4}]
  },
  {
    status: 'awaiting_deliver',
    analytics_data: {warehouse_name: 'САНКТ-ПЕТЕРБУРГ_РФЦ'},
    products: [{sku: 3001, quantity: 5}]
  },
  {
    status: 'cancelled',
    analytics_data: {warehouse_name: 'МОСКВА_РФЦ'},
    products: [{sku: 3001, quantity: 99}]
  }
], {'москва_рфц': 'МО УХ', 'санкт-петербург_рфц': 'СПБ УХ'});
assert.deepEqual(JSON.parse(JSON.stringify(aggregated)), {
  '3001': {'МО УХ': 3, 'СПБ УХ': 5},
  '3002': {'МО УХ': 4}
});

assert.throws(() => context.ozonDashboardAggregateOutflowPostings_([
  {status: 'delivered', analytics_data: {warehouse_id: 101}, products: [{sku: 3001, quantity: 1}]}
], {'москва_рфц': 'МО УХ'}), /склады не сопоставлены/);

assert.deepEqual(JSON.parse(JSON.stringify(context.ozonDashboardAggregateOutflowPostings_([
  {status: 'delivered', analytics_data: {warehouse_name: 'НАЛЬЧИК_95'}, products: [{sku: 3001, quantity: 2}]}
], {}))), {'3001': {'КАВ УХ': 2}});

const outflowHeaders = vm.runInContext('Object.values(OZON_DASHBOARD_OUTFLOW_HEADERS_)', context);
assert.equal(outflowHeaders.length, 16);
assert.equal(new Set(outflowHeaders).size, 16);
const headerSheet = {
  getName: () => 'Основная',
  getLastColumn: () => 3,
  getRange: () => ({getDisplayValues: () => [['Артикул', 'Цена продажи', 'МО УХ']]})
};
assert.equal(context.ozonDashboardColumnByHeader_(headerSheet, 'Цена продажи'), 2);
assert.throws(() => context.ozonDashboardColumnByHeader_({
  getName: () => 'Основная',
  getLastColumn: () => 3,
  getRange: () => ({getDisplayValues: () => [['Цена продажи', 'Цена продажи', 'МО УХ']]})
}, 'Цена продажи'), /найден 2 раз/);
assert.throws(() => context.ozonDashboardColumnByHeader_(headerSheet, 'Неизвестный заголовок'), /найден 0 раз/);

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
      fulfillments: [{warehouse_id: 10000 + index, name: 'СКЛАД-' + index}]
    }
  }))
};
context.ozonDashboardPostJson_ = () => clusterResponse;
const warehouseHeaders = context.ozonDashboardFetchFboWarehouseHeaders_({});
assert.equal(Object.keys(warehouseHeaders).length, clusterNames.length);
assert.ok(Object.values(warehouseHeaders).every(header => outflowHeaders.includes(header)));
assert.equal(warehouseHeaders['склад-7'], 'МО УХ');

function makeButtonHarness() {
  const properties = new Map();
  const triggers = [];
  const events = [];
  const notices = [];
  let lockAvailable = true;
  const sheet = {getLastRow: () => 3, getName: () => 'Основная'};
  const spreadsheet = {
    getSheetByName: name => name === 'Основная' ? sheet : null,
    toast: message => notices.push(message)
  };
  const context = vm.createContext({
    Utilities: {getUuid: () => 'test-run-id'},
    Logger: {log: () => {}},
    SpreadsheetApp: {getActiveSpreadsheet: () => spreadsheet},
    PropertiesService: {getScriptProperties: () => ({
      getProperty: key => properties.get(key) || null,
      setProperty: (key, value) => properties.set(key, value),
      deleteProperty: key => properties.delete(key)
    })},
    LockService: {getScriptLock: () => ({tryLock: () => lockAvailable, releaseLock: () => {}})},
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
  return {context, events, properties, triggers, notices, setLockAvailable: value => { lockAvailable = value; }};
}

const stocksRun = makeButtonHarness();
stocksRun.context.ozonDashboardLoadStocks();
assert.deepEqual(stocksRun.events, []);
assert.equal(JSON.parse(stocksRun.properties.get('ozonDashboardSyncState')).phase, 'stocks');
assert.deepEqual(stocksRun.triggers.map(trigger => trigger.handler), ['continueOzonDashboardSync']);
assert.equal(stocksRun.triggers[0].milliseconds, 60000);
assert.doesNotThrow(() => stocksRun.context.ozonDashboardLoadStocks());
assert.match(stocksRun.notices[1], /уже выполняется/);
assert.equal(stocksRun.triggers.length, 1);
stocksRun.context.continueOzonDashboardSync();
assert.deepEqual(stocksRun.events, ['stocks', 'begin-outflows']);
assert.equal(JSON.parse(stocksRun.properties.get('ozonDashboardSyncState')).phase, 'outflows');
stocksRun.context.continueOzonDashboardSync();
assert.deepEqual(stocksRun.events, ['stocks', 'begin-outflows', 'outflows']);
assert.equal(JSON.parse(stocksRun.properties.get('ozonDashboardSyncState')).phase, 'outflowCommit');
stocksRun.context.continueOzonDashboardSync();
assert.deepEqual(stocksRun.events, ['stocks', 'begin-outflows', 'outflows', 'commit-outflows', 'clear']);

const busyStartRun = makeButtonHarness();
busyStartRun.setLockAvailable(false);
assert.doesNotThrow(() => busyStartRun.context.ozonDashboardLoadPrices());
assert.equal(busyStartRun.properties.has('ozonDashboardSyncState'), false);
assert.match(busyStartRun.notices[0], /уже запускается/);

const busyContinuationRun = makeButtonHarness();
busyContinuationRun.context.ozonDashboardLoadStocks();
busyContinuationRun.setLockAvailable(false);
assert.doesNotThrow(() => busyContinuationRun.context.continueOzonDashboardSync());
assert.equal(JSON.parse(busyContinuationRun.properties.get('ozonDashboardSyncState')).phase, 'stocks');
assert.equal(busyContinuationRun.triggers.length, 1);

const combinedRun = makeButtonHarness();
combinedRun.context.ozonDashboardLoadPricesAndStocks();
assert.deepEqual(combinedRun.events, []);
assert.equal(JSON.parse(combinedRun.properties.get('ozonDashboardSyncState')).phase, 'prices');
combinedRun.context.continueOzonDashboardSync();
assert.deepEqual(combinedRun.events, ['prices']);
assert.equal(JSON.parse(combinedRun.properties.get('ozonDashboardSyncState')).phase, 'stocks');
combinedRun.context.continueOzonDashboardSync();
assert.deepEqual(combinedRun.events, ['prices', 'stocks', 'begin-outflows']);
assert.equal(JSON.parse(combinedRun.properties.get('ozonDashboardSyncState')).phase, 'outflows');

const pricesRun = makeButtonHarness();
pricesRun.context.ozonDashboardLoadPrices();
assert.deepEqual(pricesRun.events, []);
pricesRun.context.continueOzonDashboardSync();
assert.deepEqual(pricesRun.events, ['prices', 'clear']);

const retryRun = makeButtonHarness();
retryRun.context.ozonDashboardLoadStocks();
retryRun.context.ozonDashboardContinueCore_ = () => {
  const error = new Error('Ozon API HTTP 429');
  error.ozonRetryable = true;
  error.retryAfterMs = 120000;
  throw error;
};
assert.doesNotThrow(() => retryRun.context.continueOzonDashboardSync());
const retryState = JSON.parse(retryRun.properties.get('ozonDashboardSyncState'));
assert.equal(retryState.transientRetryCount, 1);
assert.match(retryState.lastTransientError, /HTTP 429/);
assert.equal(retryRun.events.includes('clear'), false);
assert.equal(retryRun.triggers.length, 1);
assert.equal(retryRun.triggers[0].milliseconds, 120000);

let apiAttempts = 0;
const apiSleeps = [];
const apiContext = vm.createContext({
  Utilities: {sleep: milliseconds => apiSleeps.push(milliseconds)},
  UrlFetchApp: {fetch: () => {
    apiAttempts++;
    return {
      getResponseCode: () => 429,
      getContentText: () => '{"code":8}',
      getAllHeaders: () => ({'Retry-After': '3'})
    };
  }},
  PropertiesService: {getScriptProperties: () => ({setProperty: () => {}})}
});
vm.runInContext(fs.readFileSync('ozon-dashboard/Shared_Ozon_Настройки.js', 'utf8'), apiContext);
vm.runInContext(fs.readFileSync('ozon-dashboard/Flow_Основная__Дашборд_Ozon.js', 'utf8'), apiContext);
vm.runInContext(fs.readFileSync('ozon-dashboard/List_Основная__ЦенаПродажи__Ozon.js', 'utf8'), apiContext);
let apiError;
try {
  apiContext.ozonDashboardPostJson_('https://example.test', {}, {}, 0);
} catch (error) {
  apiError = error;
}
assert.equal(apiAttempts, 3);
assert.equal(apiError.ozonRetryable, true);
assert.equal(apiError.retryAfterMs, 3000);
assert.deepEqual(apiSleeps, [5000, 10000]);

console.log('Ozon dashboard outflow unit checks passed.');
