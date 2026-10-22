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

// The sole numeric exception reads the documented unnamed StreamSupps key.
assert.deepStrictEqual(resolveStreamSuppsColumns(['', 'brand'], {
  offer_id: 'Артикул продавца', brand: 'brand',
}), { offer_id: 1, brand: 2 });
assert.deepStrictEqual(resolveStreamSuppsColumns(['', 'Артикул продавца'], {
  offerId: 'Артикул продавца',
}), { offerId: 2 }, 'visible header always wins over the unnamed A1');
for (const wrong of ['Other', ' ', 'Артикул производителя']) {
  assert.throws(() => resolveStreamSuppsColumns([wrong, 'brand'], {
    offerId: 'Артикул продавца',
  }), /не найден заголовок/);
}
assert.throws(() => resolveStreamSuppsColumns([], { offerId: 'Артикул продавца' }), /не найден заголовок/);
assert.throws(() => resolveStreamSuppsColumns(['', 'brand'], {
  offerId: 'Артикул продавца',
}, 'Other'), /не найден заголовок/);
assert.throws(() => resolveStreamSuppsColumns(['', 'brand'], {
  stock: 'WB ВОЛЬТМИР ИТОГ',
}), /не найден заголовок/);
assert.throws(() => resolveStreamSuppsColumns(['', 'Артикул продавца', 'Артикул продавца'], {
  offerId: 'Артикул продавца',
}), /дублируется/);
assert.throws(() => resolveStreamSuppsColumns(['', 'brand'], {
  offerId: { header: 'Артикул продавца', occurrence: 1 },
}), /не найден заголовок/);

// Sanitized read-only header snapshot confirms all current stock writer keys.
const liveHeaders = ['', 'Артикул производителя', 'PIC', 'brand', 'SKU OZON', 'Х', 'chrlid',
  'СМР САМ', 'FER MSK', 'FER SMR', 'FER NSB', 'FER EKB', 'ПОДОРОЖНИК ФБС', 'ФЕРОН ФБС',
  'НОВОСИБИРСК ФЕРОН', 'ЕКБ Ферон', 'ETM SMR', 'ETM MSK', 'ЭТМ САМАРА', 'CODES',
  'RS SMR', 'РЕЗЕРВ', 'RS MSK', 'РУССКИЙ СВЕТ МОСКВА\r', 'ПРОДАЖ', 'ДИЗАЙН', 'АРЛАЙТ МСК',
  'WB ВОЛЬТМИР ИТОГ', 'ФБС ФЕРОН МОСКВА', 'Цена продажи', 'СУММА ВСЕХ ПОСТАВЩИКОВ',
  'АРЛАЙТ МСК', 'ЦЕЛЕВАЯ НАЦЕНКА'];
const fs = require('node:fs');
const vm = require('node:vm');
const { STREAM_SUPPS_HEADERS } = require('../stream_supps_schema');
for (const [file, symbol] of [
  ['sync-etm-stocks.js', 'ETM_TR_SCHEMA'],
  ['sync-feron-stocks.js', 'FERON_TR_SCHEMA'],
  ['sync-rs-stocks.js', 'RS_COLUMNS'],
]) {
  const source = fs.readFileSync(file, 'utf8');
  const expression = source.match(new RegExp('const ' + symbol + ' = (\\{[\\s\\S]*?\\n\\});'));
  assert(expression, symbol + ' schema found without executing marketplace code');
  const schema = vm.runInNewContext('(' + expression[1] + ')', { STREAM_SUPPS_HEADERS });
  const columns = resolveStreamSuppsColumns(liveHeaders, schema);
  const key = columns.articul || columns.vendor_code || columns.offer_id;
  assert.equal(key, 1, file + ' unnamed offer key resolved');
  assert.equal(columns.wbStock || columns.wb_voltmir_stock || columns.wb_stock, 28, 'AB WB source preserved');
  if (file === 'sync-feron-stocks.js') assert.equal(columns.wb_feron_moscow_stock, 29, 'AC Feron Moscow preserved');
}
console.log('PASS StreamSupps header resolver and three live stock writer schemas');
