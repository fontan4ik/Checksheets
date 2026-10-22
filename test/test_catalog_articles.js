const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('test/catalog_articles_gas_prototype.js', 'utf8');
const writes = [];
const rows = [['Артикул'], ['001-1'], [''], [''], ['']];
const formulas = ['', '', '', '=""', ''];
let capacity = 5;
let response;
let sent;
const context = vm.createContext({
  Logger: {log() {}},
  retryFetch: (_, options) => { sent = JSON.parse(options.payload); return response; },
  wbHeaders: () => ({}), ozonHeaders: () => ({}), ozonProductsApiURL: () => 'ozon', retryAfterDelayMs_: () => 120000
});
vm.runInContext(source, context);
const book = {
 metadata: [{properties:{title:'ТЗ',sheetId:7,gridProperties:{rowCount:5}}}, {properties:{title:'Дизайн контент',sheetId:8,gridProperties:{rowCount:5}}}],
 headers: [{values:[['Артикул']]}, {}, {values:[['BAD']]}],
 values:[{values:rows}], formulas:[{values:formulas.map(x=>[x])}]
};
context.catalogArticlesGoogle_ = (path, payload) => {
 assert.equal(path, ':batchUpdate');
 payload.requests.forEach(req => {
  if (req.appendDimension) {
   capacity += req.appendDimension.length;
   book.metadata[0].properties.gridProperties.rowCount=capacity;
  } else {
   const r=req.updateCells.range.startRowIndex+1;
   assert.equal(req.updateCells.range.startColumnIndex,0);
   assert.equal(req.updateCells.range.endColumnIndex,1);
   assert.equal(req.updateCells.fields,'userEnteredValue');
   const values=req.updateCells.rows.map(row=>[row.values[0].userEnteredValue.stringValue]);
   writes.push({r,values});values.forEach((v,i)=>rows[r-1+i]=v);
  }
 });
};
let target = context.catalogArticlesTarget_(book, ['ТЗ', 'Артикул']);
assert.equal(target.last, 4); // Blank formula at row 4 is occupied.
assert.equal(context.appendCatalogArticles_(target, ['001-1', '001-5', '001-5', '0002']), 2);
assert.equal(writes[0].r, 5);
assert.equal(capacity, 6);
assert.equal(rows[4][0], '001-5');
assert.equal(rows[5][0], '0002');
// Reload after a partial multi-sheet commit: same API page adds nothing twice.

target = context.catalogArticlesTarget_(book, ['ТЗ', 'Артикул']);
assert.equal(context.appendCatalogArticles_(target, ['001-1', '001-5', '0002']), 0);
book.headers[0].values=[['Other', 'Артикул']];
assert.throws(() => context.catalogArticlesTarget_(book, ['ТЗ', 'Артикул']), /однозначно указывать на A/);
assert.throws(() => context.catalogArticlesTarget_(book, ['Дизайн контент', null]), /пустой заголовок/);
response = {getResponseCode: () => 200, getContentText: () => JSON.stringify({result: {items: [{offer_id: '0003-10'}], last_id: ''}})};
assert.equal(context.catalogArticlesPage_('ozon', null).articles[0], '0003-10');
assert.equal(sent.filter.visibility, 'ALL');
response = {getResponseCode: () => 200, getContentText: () => JSON.stringify({cards: [{vendorCode: 'WB-1'}]})};
assert.equal(context.catalogArticlesPage_('wb', {updatedAt:'date',nmID:2}).articles[0], 'WB-1');
assert.equal(sent.settings.filter.withPhoto, -1);
assert.equal(sent.settings.cursor.limit, 100);
assert.equal(sent.settings.cursor.nmID, 2);
response = {getResponseCode: () => 429};
assert.equal(context.catalogArticlesPage_('wb', null).retryMs, 120000);
response = {getResponseCode: () => 200, getContentText: () => JSON.stringify({cards: Array.from({length:100}, () => ({vendorCode:'WB-1'}))})};
assert.throws(() => context.catalogArticlesPage_('wb', null), /нет курсора/);
console.log('PASS append-only A, blank formulas, exact suffixes/zeros, dedup on restart, schema guard, API filters, 429 and invalid pagination');

// A failure on the second destination must not advance Ozon's cursor.
// WB still runs; replay repairs remaining destinations without duplicating the first.
const props = new Map();
const inventories = new Map();
let failSecond = true, released = 0;
Object.assign(context, {
  LockService: {getDocumentLock: () => ({tryLock: () => true, releaseLock: () => released++})},
  PropertiesService: {getScriptProperties: () => ({getProperty: k => props.get(k), setProperty: (k,v) => props.set(k,v)})},
  ScriptApp: {getProjectTriggers: () => []},
  catalogArticlesBook_: () => ({}),
  Utilities: {sleep() {}},
  catalogArticlesTarget_: (_, def) => {
    if (!inventories.has(def[0])) inventories.set(def[0], new Set());
    return {name: def[0], sheet: {getName: () => def[0]}};
  },
  catalogArticlesPage_: platform => ({articles: [platform + '-0001-5'], complete: true, cursor: null}),
  appendCatalogArticles_: (target, articles) => {
    if (target.name === 'ОБОР' && failSecond) { failSecond = false; throw Error('interrupted sheet write'); }
    const set = inventories.get(target.name), before = set.size;
    articles.forEach(a => set.add(a));
    return set.size - before;
  }
});
assert.throws(() => context.syncCatalogArticlesCore_(), /interrupted sheet write/);
assert.equal(props.has('CATALOG_ARTICLES_ozon'), false);
assert.equal(inventories.get('ТЗ').size, 1);
assert.equal(inventories.get('UNIT WB').size, 1);
context.syncCatalogArticlesCore_();
assert.equal(inventories.get('ТЗ').size, 1);
assert.equal(inventories.get('StreamSupps').size, 1);
assert.equal(JSON.parse(props.get('CATALOG_ARTICLES_ozon')).cursor, null);
assert.equal(released, 2);
console.log('PASS multi-sheet partial failure recovery, independent WB run, cursor commit and lock release');

props.clear();
let now = 1000000, continuations = 0, requestedCursor;
context.Date = class extends Date { static now() { return now; } };
context.ScriptApp.newTrigger = name => {
  assert.equal(name, 'resumeCatalogArticles');
  return {timeBased: () => ({after: () => ({create: () => continuations++})})};
};
context.catalogArticlesPage_ = (platform, cursor) => {
  requestedCursor = cursor;
  now += 180001;
  return {articles: ['NEXT-1'], complete: false, cursor: 'next-page'};
};
context.syncCatalogArticlesCore_();
assert.equal(JSON.parse(props.get('CATALOG_ARTICLES_ozon')).cursor, 'next-page');
assert.equal(continuations, 1);
context.catalogArticlesPage_ = (platform, cursor) => {
  if (platform === 'ozon') assert.equal(cursor, 'next-page');
  return {articles: ['NEXT-1'], complete: true, cursor: null};
};
context.syncCatalogArticlesCore_();
assert.equal(JSON.parse(props.get('CATALOG_ARTICLES_ozon')).cursor, null);
assert.equal(inventories.get('ТЗ').size, 2);
console.log('PASS timed continuation resumes saved API cursor without duplicate rows');
