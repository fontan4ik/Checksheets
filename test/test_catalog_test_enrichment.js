'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { resolveColumns, planWrites, metadataFor, stockMetadata, fetchMetadata, enrichTestCatalog } = require('../catalog_test_enrichment_local');
const headers = ['', 'МОДЕЛЬ', 'Бренд', 'Связка', 'Картинка', 'Остаток ФБО ОЗОН', 'Остаток ФБС ОЗОН', '', '', '', 'ЦЕНА ОЗОН', '', '', '', '', '', '', '', '', '', 'Product_id\nOzon', 'SKU Ozon', '', 'Название модели', 'Категория товара'];
const fields = { brand: 'Brand', model: 'Group', image: '=IMAGE("https://example.com/image.jpg")', productId: 123, sku: 456, name: '=literal title', category: 'Category', price: 50, fbo: 0, fbs: 3 };
(async () => {
  const columns = resolveColumns(headers);
  assert.equal(columns.productId, 21);
  assert.throws(() => resolveColumns([...headers, 'SKU Ozon']), /duplicate/);
  const kept = ['existing', '=USER_FORMULA()', 'Manual'];
  const updates = planWrites([headers, kept, ['new-1'], ['new-1', '', '', '=MANUAL()']], columns, new Map([['existing', fields], ['new-1', fields]]));
  assert.ok(!updates.some(item => item.column === 2));
  assert.ok(!updates.some(item => item.row === 2 && item.field === 'brand'));
  assert.ok(!updates.some(item => item.row === 4 && item.field === 'model'));
  assert.equal(updates.filter(item => item.offer === 'new-1' && item.field === 'sku').length, 2);
  const value = metadataFor({ id: 123, sku: 456, name: 'Name', primary_image: ['https://example.com/a.jpg'], description_category_id: 7 }, { attributes: [{ id: 85, values: [{ value: 'Brand' }] }] }, new Map([[7, 'Category']]), 50);
  assert.equal(value.brand, 'Brand'); assert.equal(value.model, ''); assert.equal(value.category, 'Category');
  const stockInfo = new Map([['new-1', { offer_id: 'new-1', id: 123, sku: 456 }]]);
  assert.deepEqual(stockMetadata(stockInfo, [{ product_id: 123, stocks: [{ type: 'fbs', present: 9 }, { type: 'fbo', present: 100 }] }], [{ sku: 456, offer_id: 'new-1', available_stock_count: 2 }, { sku: 456, offer_id: 'new-1', available_stock_count: 3 }]).get('new-1'), { fbs: 9, fbo: 5 });
  assert.equal(stockMetadata(stockInfo, [], []).size, 0);
  assert.deepEqual(stockMetadata(stockInfo, [{ product_id: 123, stocks: [{ type: 'fbs', present: 0 }] }], []).get('new-1'), { fbs: 0 }); // Successful FBS-only response does not establish FBO zero.
  assert.throws(() => stockMetadata(stockInfo, [{ product_id: 123, stocks: [{ type: 'fbs', present: '' }] }], []), /invalid/);
  const source = await fetchMetadata(['new-1'], { request: async endpoint => {
    if (endpoint.endsWith('/tree')) return { result: [{ description_category_id: 7, category_name: 'Category' }] };
    if (endpoint === '/v3/product/info/list') return { items: [{ offer_id: 'new-1', id: 123, sku: 456, name: 'Name', description_category_id: 7 }] };
    if (endpoint.endsWith('/attributes')) return { result: [{ offer_id: 'new-1', attributes: [{ id: 85, values: [{ value: 'Brand' }] }] }] };
    if (endpoint.endsWith('/prices')) return { items: [{ product_id: 123, price: { marketing_seller_price: '', price_before: '60', price: '50' } }] };
    if (endpoint === '/v4/product/info/stocks') return { items: [{ product_id: 123, stocks: [{ type: 'fbs', present: 3 }] }] };
    if (endpoint === '/v1/analytics/stocks') return { items: [{ sku: 456, offer_id: 'new-1', available_stock_count: 0 }] };
    throw Error(endpoint);
  } });
  assert.equal(source.metadata.get('new-1').price, 60);
  assert.equal(source.metadata.get('new-1').fbo, 0);
  assert.equal(source.metadata.get('new-1').fbs, 3);
  const rows = [headers, kept]; const writes = []; let getHook=null;
  const sheets = { spreadsheets: {
    values: { get: async () => {if(getHook)getHook();return { data: { values: structuredClone(rows) } };} },
    get: async () => ({ data: { sheets: [{ properties: { title: 'ТЕСТ', sheetId: 10, gridProperties: { rowCount: 100 } } }] } }),
    batchUpdate: async ({ requestBody }) => { for (const request of requestBody.requests) {
      writes.push(request); const update = request.updateCells; if (!update) continue;
      update.rows.forEach((row, index) => {
        const targetIndex = update.range.startRowIndex + index;
        rows[targetIndex] ||= [];
        row.values.forEach((cell, col) => { const entered = cell.userEnteredValue; rows[targetIndex][update.range.startColumnIndex + col] = entered.stringValue ?? entered.numberValue ?? entered.formulaValue; });
      });
    } return { data: {} }; },
  } };
  const backupDir = fs.mkdtempSync(path.join(os.tmpdir(), 'checksheets-test-enrichment-'));
  try {
    const ledgerStateFile=path.join(backupDir,'ledger.json');
    const options={backupDir,ledgerStateFile};
    const fetchMetadata = async () => ({ metadata: new Map([['new-1', fields]]), pending: [] });
    const dry = await enrichTestCatalog(sheets, ['new-1'], { ...options,dryRun: true, fetchMetadata });
    assert.equal(dry.added, 1); assert.equal(writes.length, 0);
    const applied = await enrichTestCatalog(sheets, ['new-1'], { ...options,fetchMetadata });
    assert.equal(applied.added, 1); assert.equal(applied.enriched, 10);
    assert.equal(rows[1][1], '=USER_FORMULA()'); assert.equal(rows[1][2], 'Manual');
    assert.equal(rows[2][23], '=literal title');
    const titleRequest = writes.find(request => request.updateCells?.range.startColumnIndex === 23);
    assert.equal(titleRequest.updateCells.rows[0].values[0].userEnteredValue.stringValue, '=literal title');
    assert.ok(!writes.some(request => request.updateCells?.range.startColumnIndex === 1));
    const repeated = await enrichTestCatalog(sheets, ['new-1'], { ...options,fetchMetadata });
    assert.equal(repeated.enriched, 0); assert.equal(repeated.added, 0);
    rows[2][23]=''; const erased=await enrichTestCatalog(sheets,['new-1'],{...options,fetchMetadata}); assert.equal(erased.enriched,0); assert.equal(rows[2][23],'');
    rows[1][2]=''; const manualErased=await enrichTestCatalog(sheets,['existing'],{...options,fetchMetadata}); assert.equal(manualErased.enriched,0); assert.equal(rows[1][2],'');
    let appendedReads=0;getHook=()=>{if(rows[3]?.[0]==='new-2'&&++appendedReads===3)rows[3][23]='MANUAL LATE';};
    const fetchSecond=async()=>({metadata:new Map([['new-2',fields]]),pending:[]});
    await assert.rejects(enrichTestCatalog(sheets,['new-2'],{...options,fetchMetadata:fetchSecond}),/concurrent edit/);
    assert.equal(rows[3][23],'MANUAL LATE');getHook=null;
  } finally { fs.rmSync(backupDir, { recursive: true }); }
  console.log('catalog_test_enrichment: all checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
