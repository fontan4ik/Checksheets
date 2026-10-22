'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { parseCatalog, ensureCatalogFallback, resolveOnboardingCatalog, fallbackFormula, ORIGINAL_ANCHORS, AUX, AUX_HEADERS } = require('../stream_onboarding_catalog');
const attrs = (offer, pack = '3', extra = []) => ({ offer_id: offer, sku: 123, attributes: [{ id: 85, values: [{ value: 'Brand' }] }, { id: 8962, values: [{ value: pack }] }, ...extra] });
const info = offer => ({ offer_id: offer, sku: 123 });
function mockSheets() {
  const state = { anchors: [null, null, null, ORIGINAL_ANCHORS.brand, ORIGINAL_ANCHORS.sku], aux: [AUX_HEADERS, ['older-1', 'Preserved', 999, 1, 'old']], mutations: [], fault: false };
  const sheets = { spreadsheets: {
    get: async () => ({ data: { sheets: [{ properties: { title: AUX, sheetId: 90, hidden: true, gridProperties: { rowCount: 100 } } }] } }),
    batchUpdate: async arg => { state.mutations.push(arg); return { data: {} }; },
    values: {
      batchGet: async ({ ranges, valueRenderOption }) => ({ data: { valueRanges: ranges.map(range => ({ values: range.includes(AUX) ? state.aux : range.endsWith('1:1') ? [valueRenderOption === 'FORMULA' ? state.anchors : ['', 'Артикул производителя', 'PIC', 'brand', 'SKU OZON']] : [[state.anchors[range.includes('D1') ? 3 : 4]]] })) } }),
      update: async arg => { state.mutations.push(arg); if (state.fault) throw new Error('write failed'); state.aux = arg.requestBody.values; return { data: {} }; },
      batchUpdate: async arg => { state.mutations.push(arg); for (const value of arg.requestBody.data) state.anchors[value.range.includes('D1') ? 3 : 4] = value.values[0][0]; return { data: {} }; },
    },
  } };
  return { sheets, state };
}
(async () => {
  let result = parseCatalog(['0001-99'], [info('0001-99')], [attrs('0001-99')]);
  assert.equal(result.packMap.get('0001-99'), 3); // Explicit attribute wins; never infer suffix 99.
  assert.equal(result.identities.get('0001-99').brand, 'Brand');
  for (const value of ['0', '-1', '1.5', '', 'x']) assert.equal(parseCatalog(['x'], [info('x')], [attrs('x', value)]).packMap.size, 0);
  result = parseCatalog(['x'], [info('x')], [attrs('x', '1', [{ id: 4678, values: [{ value: '305' }] }])]);
  assert.equal(result.packMap.size, 0); assert.equal(result.pending[0].reason, 'supplier_unit_review');
  assert.throws(() => parseCatalog(['x'], [info('x'), info('x')], [attrs('x')]), /duplicate/);
  assert.throws(() => parseCatalog(['x'], [info('other')], []), /unexpected/);
  assert.equal(parseCatalog(['x'], [], []).pending[0].reason, 'catalog_missing');
  assert.equal(parseCatalog(['x'], [{ ...info('x'), sku: 321 }], [attrs('x')]).identities.size, 0);
  const duplicateUnits = attrs('x'); duplicateUnits.attributes.push({ id: 8962, values: [{ value: '8' }] });
  assert.equal(parseCatalog(['x'], [info('x')], [duplicateUnits]).packMap.size, 0);
  const identity = new Map([['new-3', { brand: 'Brand', sku: 123, pack: 3 }]]);
  let mock = mockSheets();
  await ensureCatalogFallback(mock.sheets, identity, { dryRun: true });
  assert.equal(mock.state.mutations.length, 0);
  const backupDir = fs.mkdtempSync(path.join(os.tmpdir(), 'checksheets-catalog-test-'));
  try {
    await ensureCatalogFallback(mock.sheets, identity, { backupDir, now: () => 'now' });
    assert.deepEqual(mock.state.aux[1], ['older-1', 'Preserved', 999, 1, 'old']);
    assert.deepEqual(mock.state.aux[2], ['new-3', 'Brand', 123, 3, 'now']);
    assert.equal(mock.state.anchors[3], ORIGINAL_ANCHORS.brand);
    assert.equal(mock.state.anchors[4], ORIGINAL_ANCHORS.sku);
    assert.ok(fallbackFormula('brand').includes('<>"0"'), 'blank lookup returned as 0 must use the auxiliary brand');
    assert.ok(fallbackFormula('sku').includes('VALUE(') && fallbackFormula('sku').includes('MOD('), 'SKU primary must be a positive integer, not LEN(0)');
    assert.equal(fs.readdirSync(backupDir).length, 1);
    // Subsequent calls accept their own formula; old auxiliary identities survive.
    await ensureCatalogFallback(mock.sheets, identity, { backupDir });
    mock = mockSheets(); mock.state.anchors[3] = '=CUSTOM()';
    await assert.rejects(ensureCatalogFallback(mock.sheets, identity, { backupDir }), /Unknown/);
    assert.equal(mock.state.mutations.length, 0);
    mock = mockSheets(); mock.state.fault = true;
    await assert.rejects(ensureCatalogFallback(mock.sheets, identity, { backupDir }), /write failed/);
    assert.equal(mock.state.anchors[3], ORIGINAL_ANCHORS.brand);
    mock = mockSheets();
    result = await resolveOnboardingCatalog(mock.sheets, ['new-3'], { dryRun: true, request: async endpoint => endpoint.startsWith('/v3') ? { items: [info('new-3')] } : { result: [attrs('new-3')] } });
    assert.equal(result.packMap.get('new-3'), 3); assert.equal(mock.state.mutations.length, 0);
  } finally { fs.rmSync(backupDir, { recursive: true }); }
  console.log('stream_onboarding_catalog: all checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
