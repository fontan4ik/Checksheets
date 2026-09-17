const assert = require('assert');

const {
  resolveStreamSuppsColumns,
} = require('../stream_supps_schema');

const headers = ['Артикул продавца', 'brand', 'chrlid', 'РЕЗЕРВ'];
assert.deepStrictEqual(
  resolveStreamSuppsColumns(headers, {
    offerId: 'Артикул продавца',
    brand: 'brand',
    chrtId: ['chrtid', 'chrlid'],
    reserve: 'РЕЗЕРВ',
  }),
  { offerId: 1, brand: 2, chrtId: 3, reserve: 4 },
);

assert.throws(
  () => resolveStreamSuppsColumns(
    ['Артикул продавца', 'РЕЗЕРВ', 'РЕЗЕРВ'],
    { reserve: 'РЕЗЕРВ' },
    'StreamSupps',
  ),
  /дублируется.*2, 3/,
);

assert.throws(
  () => resolveStreamSuppsColumns(['Артикул продавца'], { reserve: 'РЕЗЕРВ' }, 'StreamSupps'),
  /не найден заголовок/,
);

console.log('PASS StreamSupps header resolver');
