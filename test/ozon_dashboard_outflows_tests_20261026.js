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

console.log('Ozon dashboard outflow unit checks passed.');
