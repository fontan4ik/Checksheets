const assert = require('assert');
const { periods, resultRows, verifySheetHeaders } = require('../ozon_fbo_fbs_sales_local');

const range = periods(new Date(2026, 8, 17));
assert.deepStrictEqual(range.month, ['2026-08-16', '2026-09-16']);
assert.deepStrictEqual(range.quarter, ['2026-06-17', '2026-09-17']);

assert.deepStrictEqual(resultRows(
  ['1', '2', ''],
  new Map([['1', 8], ['2', 1]]),
  new Map([['1', 3], ['2', 5]]),
  new Map([['1', 18]]),
  new Map([['1', 4]]),
), [[5, 3, 14, 4], [0, 5, 0, 0], ['', '', '', '']]);
const headers = Array(46).fill('');
headers[21] = 'SKU Ozon';
headers[42] = 'Продажи штуки месяц FBO';
headers[43] = 'Продажи штуки месяц FBS\n';
headers[44] = 'Продажи штуки квартал FBO\n';
headers[45] = 'Продажи штуки квартал FBS\n';
verifySheetHeaders(headers);
headers[43] = 'другая колонка';
assert.throws(() => verifySheetHeaders(headers), /запись AQ:AT остановлена/);
console.log('PASS local Ozon FBO/FBS sales ranges and split');
