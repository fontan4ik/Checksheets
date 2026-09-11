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
  normalizeMarketplaceStock(value, brand) {
    const stock = Math.trunc(Number(value));
    if (!Number.isFinite(stock) || stock < 0) return 0;
    return stock === 1 && String(brand || '').trim().toLowerCase() !== 'arlight' ? 0 : stock;
  },
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

const sourceBrandSheet = {
  getLastRow() { return 3; },
  getRange() {
    return { getDisplayValues() { return [['A', '', '', 'Arlight'], ['B', '', '', 'Feron']]; } };
  },
};
assert.deepStrictEqual(
  JSON.parse(JSON.stringify(sandbox.readSamaraSupplierYnxBrandMap_(sourceBrandSheet))),
  { A: 'Arlight', B: 'Feron' },
);

const stockSheet = {
  getLastRow() { return 5; },
  getLastColumn() { return 2; },
  getRange() {
    return { getDisplayValues() { return [['art', 'TR YA FBS'], ['A', '1'], ['B', '1'], ['C', '0'], ['D', '2']]; } };
  },
};
assert.deepStrictEqual(
  JSON.parse(JSON.stringify(sandbox.readSamaraSupplierYnxStockEntries_(stockSheet, { A: 'Arlight', B: 'Feron' }))),
  [
    { sku: 'A', brand: 'Arlight', count: 1 },
    { sku: 'B', brand: 'Feron', count: 0 },
    { sku: 'C', brand: '', count: 0 },
    { sku: 'D', brand: '', count: 2 },
  ],
);

assert(source.includes("{ sheetName: 'StreamSupps', keyColumn: 1, stockColumn: 14 }"));
assert(source.includes("{ sheetName: 'StreamSupps', keyColumn: 1, stockColumn: 19 }"));
assert(source.includes("{ sheetName: 'StreamSupps', keyColumn: 1, stockColumn: 23 }"));
assert(source.includes('SAMARA_SUPPLIER_YNX_YANDEX_CAMPAIGN_NAME'));
assert(!source.includes('SAMARA_SUPPLIER_YNX_CAMPAIGN_NAME_FOR_LOG_'));
assert(source.includes('58480133'));
assert(source.includes("'/offers/stocks'"));
assert(source.includes("const SAMARA_SUPPLIER_YNX_TARGET_STOCK_HEADER = 'TR YA FBS';"));
assert(source.includes('readSamaraSupplierYnxFormulaSummary_'));
assert(source.includes('SpreadsheetApp.flush();'));
assert(!source.includes('targetSheet.getRange(2, targetStockColumn, values.length, 1).setValues(values);'));

console.log('PASS node_check');
console.log('PASS overlapping_supplier_stocks_are_summed');
console.log('PASS blank_target_rows_are_zero');
console.log('PASS stock_parser_guards');
console.log('PASS StreamSupps Arlight single-unit exception');
console.log('PASS live_sheet_headers_and_yandex_campaign_contract');
