const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const { execFileSync } = require('child_process');

const path = require('path');
const sourcePath = path.join(__dirname, '..', 'Синхронизация остатков поставщиков в Яндекс.js');
const source = fs.readFileSync(sourcePath, 'utf8');

execFileSync(process.execPath, ['--check', sourcePath], { stdio: 'inherit' });

const sandbox = {
  console,
  isFinite,
  SpreadsheetApp: {},
  LockService: {},
  Logger: {},
  JSON,
  Math,
  String,
  Number,
};
vm.runInNewContext(source, sandbox, { filename: sourcePath });

assert.strictEqual(
  JSON.stringify(sandbox.aggregateSamaraSupplierMaps_(
    ['A', 'B', '', 'C'],
    { A: 2, B: 1 },
    { A: 3, B: 0 },
    { A: 4, B: 7 },
  )),
  JSON.stringify([[9], [8], [0], [0]]),
);

assert.strictEqual(sandbox.parseSamaraSupplierYnxStock_('', 'TEST', 'A'), 0);
assert.strictEqual(sandbox.parseSamaraSupplierYnxStock_('1 000', 'TEST', 'A'), 1000);
assert.throws(() => sandbox.parseSamaraSupplierYnxStock_('-1', 'TEST', 'A'));
assert.throws(() => sandbox.parseSamaraSupplierYnxStock_('1.5', 'TEST', 'A'));

assert(source.includes("{ sheetName: 'FERON TR', keyHeader: 'art', stockHeader: 'SMR' }"));
assert(source.includes("{ sheetName: 'ETM TR', keyHeader: 'art', stockHeader: 'SMR' }"));
assert(source.includes("{ sheetName: 'РуСВ TR', keyHeader: 'Артикул', stockHeader: 'Округлённое' }"));
assert(source.includes('SAMARA_SUPPLIER_YNX_YANDEX_CAMPAIGN_NAME'));
assert(!source.includes('SAMARA_SUPPLIER_YNX_CAMPAIGN_NAME_FOR_LOG_'));
assert(source.includes('58480133'));
assert(source.includes("'/offers/stocks'"));
assert(source.includes("const SAMARA_SUPPLIER_YNX_TARGET_STOCK_HEADER = 'TR YA FBS';"));

console.log('PASS node_check');
console.log('PASS overlapping_supplier_stocks_are_summed');
console.log('PASS blank_target_rows_are_zero');
console.log('PASS stock_parser_guards');
console.log('PASS live_sheet_headers_and_yandex_campaign_contract');
