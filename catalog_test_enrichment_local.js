'use strict';
/** Targeted new-catalog enrichment of TEST. B is owned by its existing array formula. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const axios = require('axios');
const BOOK = '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
const FIELD_HEADERS = { brand: 'Бренд', model: 'Связка', image: 'Картинка', productId: 'Product_id Ozon', sku: 'SKU Ozon', name: 'Название модели', category: 'Категория товара', price: 'ЦЕНА ОЗОН', fbo: 'Остаток ФБО ОЗОН', fbs: 'Остаток ФБС ОЗОН' };
const text = value => String(value ?? '').trim();
const normalized = value => text(value).toLowerCase().replace(/ё/g, 'е').replace(/\s+/g, ' ');
function resolveColumns(headers) {
  const result = { offer: 1 };
  // Explicit fixed-A exception: TEST A1 is blank; AM is an unrelated seller-article column.
  if (text(headers[0]) && normalized(headers[0]) !== 'артикул') throw new Error('ТЕСТ: changed primary A header');
  for (const [field, header] of Object.entries(FIELD_HEADERS)) {
    const matches = headers.flatMap((value, i) => normalized(value) === normalized(header) ? [i + 1] : []);
    if (matches.length !== 1) throw new Error(`ТЕСТ: missing/duplicate ${header}`);
    result[field] = matches[0];
  }
  return result;
}
function indexRows(rows) {
  const result = new Map();
  for (let i = 1; i < rows.length; i++) {
    const offer = text(rows[i]?.[0]);
    if (!offer) continue;
    const target = { row: i + 1, values: rows[i] };
    if (result.has(offer)) result.get(offer).matches.push(target);
    else result.set(offer, { ...target, matches: [target] });
  }
  return result;
}
function attr(item, id) {
  const matches = (item?.attributes || []).filter(a => a.id === id);
  return matches.length === 1 && matches[0].values?.length === 1 ? text(matches[0].values[0].value) : '';
}
function unique(items, allowed, label) {
  if (!Array.isArray(items)) throw new Error(`Ozon ${label}: invalid result`);
  const result = new Map();
  for (const item of items) {
    const offer = text(item.offer_id);
    if (!allowed.has(offer) || result.has(offer)) throw new Error(`Ozon ${label}: unexpected/duplicate offer`);
    result.set(offer, item);
  }
  return result;
}
function firstImage(value) { return typeof value === 'string' ? value : Array.isArray(value) ? value.find(x => typeof x === 'string' && x) || '' : ''; }
function metadataFor(info, attributes, categories, price) {
  const positiveId = value => Number.isSafeInteger(Number(value)) && Number(value) > 0 ? Number(value) : '';
  const image = firstImage(info.primary_image) || firstImage(info.images) || firstImage(attributes?.primary_image);
  return {
    brand: attr(attributes, 85), model: attr(attributes, 9048) || attr(attributes, 22390),
    image: /^https:\/\//.test(image) ? `=IMAGE("${image.replace(/"/g, '""')}")` : '',
    productId: positiveId(info.id), sku: positiveId(info.sku || (info.sources || []).map(s => s.sku).find(Boolean)),
    name: text(info.name || attributes?.name), category: categories.get(Number(attributes?.description_category_id || info.description_category_id)) || '',
    price: Number.isFinite(Number(price)) && Number(price) > 0 ? Number(price) : '',
  };
}
async function retry(operation) {
  for (let attempt = 0; ; attempt++) {
    try { return await operation(); } catch (error) {
      const status = Number(error.response?.status || error.code);
      if (attempt >= 3 || !([408, 429, 500, 502, 503, 504].includes(status) || /ECONNRESET|ETIMEDOUT|ECONNABORTED|EAI_AGAIN/.test(error.code || ''))) throw error;
      await new Promise(resolve => setTimeout(resolve, 2000 * 2 ** attempt));
    }
  }
}
function requestClient() {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(path.join(__dirname, 'Shared_Настройки.js'), 'utf8') + ';this.h=ozonHeaders();', context);
  return async (endpoint, payload) => retry(async () => (await axios.post(`https://api-seller.ozon.ru${endpoint}`, payload, { headers: context.h, timeout: 45000 })).data);
}
function stockMetadata(info, fbsItems, fboItems) {
  const byId = new Map([...info.values()].map(card => [String(card.id), card]));
  const bySku = new Map([...info.values()].filter(card => Number(card.sku) > 0).map(card => [String(card.sku), card]));
  const result = new Map();
  if (!Array.isArray(fbsItems) || !Array.isArray(fboItems)) throw new Error('Ozon: invalid stock response');
  const seen = new Set();
  for (const item of fbsItems) {
    const id = String(item.product_id), card = byId.get(id);
    if (!card || seen.has(id) || !Array.isArray(item.stocks)) throw new Error('Ozon: invalid FBS product');
    seen.add(id);
    let total = 0;
    for (const stock of item.stocks) {
      if (typeof stock.type !== 'string' || stock.present === '' || stock.present === null || stock.present === undefined || !Number.isSafeInteger(Number(stock.present)) || Number(stock.present) < 0) throw new Error('Ozon: invalid FBS present');
      if (stock.type === 'fbs') total += Number(stock.present);
    }
    result.set(text(card.offer_id), { fbs: total });
  }
  for (const item of fboItems) {
    const card = bySku.get(String(item.sku));
    if (!card || text(item.offer_id) !== text(card.offer_id) || item.available_stock_count === '' || item.available_stock_count === null || item.available_stock_count === undefined || !Number.isSafeInteger(Number(item.available_stock_count)) || Number(item.available_stock_count) < 0) throw new Error('Ozon: invalid FBO available stock');
    const value = result.get(text(card.offer_id)) || {};
    value.fbo = (value.fbo || 0) + Number(item.available_stock_count);
    result.set(text(card.offer_id), value);
  }
  return result;
}
async function fetchMetadata(offers, options = {}) {
  const request = options.request || requestClient();
  const categoryResult = await request('/v1/description-category/tree', {});
  if (!Array.isArray(categoryResult.result)) throw new Error('Ozon: invalid category tree');
  const categories = new Map();
  function visit(nodes) { for (const node of nodes) { if (node.description_category_id && node.category_name) categories.set(Number(node.description_category_id), node.category_name); if (node.children) visit(node.children); } }
  visit(categoryResult.result);
  const metadata = new Map(), pending = [];
  for (let start = 0; start < offers.length; start += 100) {
    const batch = offers.slice(start, start + 100), allowed = new Set(batch);
    const info = unique((await request('/v3/product/info/list', { offer_id: batch })).items, allowed, 'v3');
    const attributes = unique((await request('/v4/product/info/attributes', { filter: { offer_id: batch, visibility: 'ALL' }, limit: batch.length })).result, allowed, 'v4');
    const prices = new Map();
    if (info.size) {
      let cursor = '', seen = new Set();
      do {
        const response = await request('/v5/product/info/prices', { cursor, filter: { product_id: [...info.values()].map(item => item.id), visibility: 'ALL' }, limit: 1000 });
        if (!Array.isArray(response.items)) throw new Error('Ozon: invalid prices');
        for (const item of response.items) {
          const id = Number(item.product_id);
          if (![...info.values()].some(card => Number(card.id) === id) || prices.has(id)) throw new Error('Ozon: unexpected/duplicate price product');
          const p = item.price || {};
          prices.set(id, [p.marketing_seller_price, p.price_before, p.price].find(value => value !== null && value !== undefined && value !== '') ?? '');
        }
        cursor = text(response.cursor);
        if (cursor && seen.has(cursor)) throw new Error('Ozon: repeated prices cursor');
        seen.add(cursor);
      } while (cursor);
    }
    let stocks = new Map();
    if (info.size && options.includeStocks !== false) {
      const fbs = await request('/v4/product/info/stocks', { filter: { product_id: [...info.values()].map(item => item.id) }, limit: info.size });
      const skus = [...info.values()].map(item => Number(item.sku)).filter(value => Number.isSafeInteger(value) && value > 0);
      // Analytics endpoint's strict shared limit: space reads across consecutive batches.
      if (start > 0 && !options.request) await new Promise(resolve => setTimeout(resolve, 7000));
      const fbo = skus.length ? await request('/v1/analytics/stocks', { skus }) : { items: [] };
      stocks = stockMetadata(info, fbs.items, fbo.items);
    }
    for (const offer of batch) {
      const detail = info.get(offer);
      if (!detail) { pending.push({ offer_id: offer, reason: 'ozon_info_missing' }); continue; }
      const value = { ...metadataFor(detail, attributes.get(offer), categories, prices.get(Number(detail.id))), ...(stocks.get(offer) || {}) };
      metadata.set(offer, value);
      const missing = Object.keys(FIELD_HEADERS).filter(field => value[field] === '' || value[field] === undefined);
      if (missing.length) pending.push({ offer_id: offer, reason: 'ozon_fields_missing', fields: missing, errors: detail.errors || [], statuses: detail.statuses || {} });
    }
  }
  return { metadata, pending };
}
function planWrites(rows, columns, metadata) {
  const indexed = indexRows(rows), updates = [];
  for (const [offer, values] of metadata) {
    const target = indexed.get(offer);
    if (!target) continue;
    for (const match of target.matches) for (const field of Object.keys(FIELD_HEADERS)) {
      if (text(match.values[columns[field] - 1]) || values[field] === '' || values[field] === undefined) continue;
      updates.push({ offer, field, row: match.row, column: columns[field], value: values[field] });
    }
  }
  return updates;
}
function updateRequest(sheetId, updates) {
  const sorted = [...updates].sort((a, b) => a.column - b.column || a.row - b.row);
  const groups = [];
  for (const item of sorted) {
    const previous = groups[groups.length - 1];
    if (previous && previous.column === item.column && previous.items.at(-1).row + 1 === item.row) previous.items.push(item);
    else groups.push({ column: item.column, items: [item] });
  }
  return groups.map(group => ({ updateCells: {
    range: { sheetId, startRowIndex: group.items[0].row - 1, endRowIndex: group.items.at(-1).row, startColumnIndex: group.column - 1, endColumnIndex: group.column },
    rows: group.items.map(item => ({ values: [{ userEnteredValue: typeof item.value === 'number' ? { numberValue: item.value } : item.field === 'image' ? { formulaValue: item.value } : { stringValue: item.value } }] })),
    fields: 'userEnteredValue',
  } }));
}

async function enrichTestCatalog(sheets, offers, options = {}) {
  const spreadsheetId = options.spreadsheetId || BOOK, dryRun = options.dryRun === true;
  const requested = [...new Set(offers.map(text).filter(Boolean))];
  if (!requested.length) return { added: 0, enriched: 0, pending: [] };
  const getRows = async () => {
    const response = await retry(() => sheets.spreadsheets.values.get({ spreadsheetId, range: "'ТЕСТ'!A:Y", valueRenderOption: 'FORMULA' }, { timeout: 120000 }));
    const rows = response.data.values || [];
    if (!rows.length) throw new Error('ТЕСТ empty');
    return { rows, columns: resolveColumns(rows[0]), indexed: indexRows(rows) };
  };
  let snapshot = await getRows();
  const ledger=require('./append_initialization_ledger');
  const admissionOptions=snap=>({scope:'test-enrichment',sheetName:'ТЕСТ',keys:snap.rows.map(r=>[r[0]??'']),columns:Object.keys(FIELD_HEADERS).map(f=>snap.columns[f]),stateFile:options.ledgerStateFile});
  // Establish/protect the current rows before appending. Occupied fields are
  // remembered too: clearing a manual value later is not a request to restore it.
  const observe=snap=>snap.rows.slice(1).flatMap((r,i)=>text(r[0])?Object.keys(FIELD_HEADERS).map(f=>({row:i+2,offer:text(r[0]),column:snap.columns[f],value:r[snap.columns[f]-1]??''})):[]);
  ledger.claimAppendInitializations({...admissionOptions(snapshot),changes:[],observedCells:observe(snapshot),dryRun});
  const eligible=new Set(ledger.inspectAppendEligibility(admissionOptions(snapshot)).eligibleOffers);
  const needed = requested.filter(offer => !snapshot.indexed.has(offer) || eligible.has(offer)&&snapshot.indexed.get(offer).matches.some(match => Object.keys(FIELD_HEADERS).some(field => !text(match.values[snapshot.columns[field] - 1]))));
  if (!needed.length) return { added: 0, enriched: 0, pending: [] };
  const result = await (options.fetchMetadata || fetchMetadata)(needed, options);
  // Re-read after Ozon requests: a cloud catalog run or manual fill may have completed.
  snapshot = await getRows();
  const missing = needed.filter(offer => !snapshot.indexed.has(offer));
  if (options.appendMissing === false && missing.length) throw new Error('ТЕСТ: requested offers absent after catalog append');
  const report = { added: missing.length, enriched: 0, byField: {}, pending: result.pending };
  if (dryRun) {
    report.enriched = planWrites(snapshot.rows, snapshot.columns, result.metadata).length;
    report.wouldAppend = missing;
    return report;
  }
  const book = (await retry(() => sheets.spreadsheets.get({ spreadsheetId, fields: 'sheets.properties' }))).data;
  const properties = book.sheets.find(sheet => normalized(sheet.properties.title) === 'тест')?.properties;
  if (!properties) throw new Error('ТЕСТ metadata missing');
  const backupDir = options.backupDir || path.join(__dirname, 'test', 'runtime');
  fs.mkdirSync(backupDir, { recursive: true });
  const backup = path.join(backupDir, `test-enrichment-before-${Date.now()}-${process.pid}.json`);
  fs.writeFileSync(backup, JSON.stringify({ at: new Date().toISOString(), requested, rows: snapshot.rows, properties }), { mode: 0o600 });
  report.backup = backup;
  if (missing.length) {
    let last = snapshot.rows.length;
    while (last > 1 && !text(snapshot.rows[last - 1]?.[0])) last--;
    const end = last + missing.length, requests = [];
    if (end > properties.gridProperties.rowCount) requests.push({ appendDimension: { sheetId: properties.sheetId, dimension: 'ROWS', length: end - properties.gridProperties.rowCount } });
    requests.push({ updateCells: { range: { sheetId: properties.sheetId, startRowIndex: last, endRowIndex: end, startColumnIndex: 0, endColumnIndex: 1 }, rows: missing.map(offer => ({ values: [{ userEnteredValue: { stringValue: offer } }] })), fields: 'userEnteredValue' } });
    await sheets.spreadsheets.batchUpdate({ spreadsheetId, requestBody: { requests } }, { timeout: 120000, retry: false });
    snapshot = await getRows();
    if (missing.some(offer => !snapshot.indexed.has(offer))) throw new Error('ТЕСТ append read-back mismatch');
  }
  // Re-read immediately before admission; metadata/backup/append may have taken time.
  snapshot = await getRows();
  const proposed = planWrites(snapshot.rows, snapshot.columns, result.metadata);
  const admission=ledger.claimAppendInitializations({...admissionOptions(snapshot),changes:proposed,observedCells:observe(snapshot),dryRun});
  const updates=admission.authorized;report.blocked=admission.blocked.length;
  const requests = updateRequest(properties.sheetId, updates);
  const destinations=new Map(updates.map(u=>[`${u.row}:${u.column}`,u]));
  for (let i = 0; i < requests.length; i += 100) {
    const batch=requests.slice(i,i+100),fresh=await getRows();
    for(const request of batch){const range=request.updateCells.range;for(let row=range.startRowIndex+1;row<=range.endRowIndex;row++){
      const column=range.startColumnIndex+1,update=destinations.get(`${row}:${column}`);
      if(!update||text(fresh.rows[row-1]?.[0])!==update.offer||text(fresh.rows[row-1]?.[column-1]))throw Error(`ТЕСТ concurrent edit before enrichment ${row}:${column}`);
    }}
    await sheets.spreadsheets.batchUpdate({ spreadsheetId, requestBody: { requests: batch } }, { timeout: 120000, retry: false });
  }
  const checked = await getRows();
  for (const update of updates) {
    if (text(checked.rows[update.row - 1]?.[0]) !== update.offer || String(checked.rows[update.row - 1]?.[checked.columns[update.field] - 1] ?? '') !== String(update.value)) throw new Error(`ТЕСТ enrichment read-back mismatch ${update.offer}/${update.field}`);
    report.byField[update.field] = (report.byField[update.field] || 0) + 1;
  }
  report.enriched = updates.length;
  return report;
}
module.exports = { enrichTestCatalog, fetchMetadata, metadataFor, stockMetadata, resolveColumns, planWrites, updateRequest };
