const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const sourcePath = path.join(__dirname, '..', 'Ozon остатки FBO.js');
const source = fs.readFileSync(sourcePath, 'utf8');
const context = {};
vm.createContext(context);
vm.runInContext(source, context, { filename: sourcePath });

assert.equal(typeof context.aggregateFBOAvailableStocksByOffer, 'function');

const responseItems = [
  { offer_id: '25487-10', available_stock_count: 1 },
  { offer_id: '29493', available_stock_count: 7 },
  { offer_id: '29493', available_stock_count: 1 },
  { offer_id: '29493', available_stock_count: 2 },
  { offer_id: '27999-1', available_stock_count: 0 },
  { offer_id: '27999-1', available_stock_count: 2 },
  { offer_id: '', available_stock_count: 999 },
  { offer_id: 'invalid-count', available_stock_count: 'not-a-number' },
];

assert.deepEqual(
  context.aggregateFBOAvailableStocksByOffer(responseItems),
  {
    '25487-10': 1,
    '29493': 10,
    '27999-1': 2,
    'invalid-count': 0,
  },
);

console.log('✅ Ozon FBO available-stock aggregation test passed');
