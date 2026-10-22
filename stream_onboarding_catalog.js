'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const axios = require('axios');
const { resolveStreamSuppsColumns, STREAM_SUPPS_HEADERS } = require('./stream_supps_schema');
const BOOK = '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
// Dedicated hidden service layout: A offer / B brand / C SKU / D explicit units / E timestamp.
const AUX = '_STREAM_ONBOARDING_CATALOG';
const AUX_HEADERS = ['offer_id', 'brand', 'sku', 'units_per_product', 'updated_at'];
async function retryRead(operation) {
  for(let attempt=0;;attempt++) {
    try { return await operation(); }
    catch(error) {
      const status=Number(error.response?.status||error.code);
      if(attempt>=3||!([408,429,500,502,503,504].includes(status)||/socket hang up|ECONNRESET|ETIMEDOUT|timeout|ECONNABORTED/i.test(error.message||'')))throw error;
      await new Promise(r=>setTimeout(r,3000*2**attempt));
    }
  }
}
const ORIGINAL_ANCHORS = {
  brand: '={ "brand"; ARRAYFORMULA(IFERROR(VLOOKUP(A2:A;\'ТЕСТ\'!A:AAV;3;0)))}',
  sku: '={ "SKU OZON"; ARRAYFORMULA(IFERROR(VLOOKUP(A2:A & "";\'ТЕСТ\'!A:V;22;0)))}',
};
function legacyFallbackFormula(field) {
  const primary = field === 'brand' ? "VLOOKUP(A2:A;'ТЕСТ'!A:AAV;3;0)" : 'VLOOKUP(A2:A & "";\'ТЕСТ\'!A:V;22;0)';
  const header = field === 'brand' ? 'brand' : 'SKU OZON';
  return `={ "${header}"; ARRAYFORMULA(IF(LEN(IFERROR(${primary};""));IFERROR(${primary};"");IFERROR(VLOOKUP(A2:A & "";'${AUX}'!A:C;${field === 'brand' ? 2 : 3};0);"")))}`;
}
function fallbackFormula(field) {
  const primary=field==='brand'?"VLOOKUP(A2:A;'ТЕСТ'!A:AAV;3;0)":'VLOOKUP(A2:A & "";\'ТЕСТ\'!A:V;22;0)';
  const valid=field==='brand'
    ? `(LEN(IFERROR(${primary};""))>0)*(IFERROR(${primary}&"";"")<>"0")`
    : `IFERROR((VALUE(${primary})>0)*(MOD(VALUE(${primary});1)=0);FALSE)`;
  return `={ "${field==='brand'?'brand':'SKU OZON'}"; ARRAYFORMULA(IF(${valid};IFERROR(${primary};"");IFERROR(VLOOKUP(A2:A & "";'${AUX}'!A:C;${field==='brand'?2:3};0);"")))}`;
}
function credentials() {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(path.join(__dirname, 'Shared_Настройки.js'), 'utf8') + ';this.h=ozonHeaders();', context);
  return context.h;
}
function uniqueByOffer(items, requested, label) {
  if (!Array.isArray(items)) throw new Error(`${label}: invalid catalog response`);
  const result = new Map();
  for (const item of items) {
    const offer = String(item.offer_id ?? '');
    if (!requested.has(offer) || result.has(offer)) throw new Error(`${label}: unexpected or duplicate offer ${offer}`);
    result.set(offer, item);
  }
  return result;
}
function singleAttribute(item, id) {
  const attrs = (item.attributes || []).filter(a => a.id === id);
  if (attrs.length !== 1 || attrs[0].values?.length !== 1) return null;
  return String(attrs[0].values[0].value ?? '').trim() || null;
}
function parseCatalog(offers, info, attributes) {
  const requested = new Set(offers), byInfo = uniqueByOffer(info, requested, 'v3'), byAttrs = uniqueByOffer(attributes, requested, 'v4');
  const packMap = new Map(), identities = new Map(), pending = [];
  for (const offer of offers) {
    const detail = byInfo.get(offer), attrs = byAttrs.get(offer);
    if (!detail || !attrs) { pending.push({ offer, reason: 'catalog_missing' }); continue; }
    const brand = singleAttribute(attrs, 85);
    const sku = Number(detail.sku || attrs.sku);
    if (!brand || !Number.isSafeInteger(sku) || sku <= 0 || (detail.sku && attrs.sku && Number(detail.sku) !== Number(attrs.sku))) {
      pending.push({ offer, reason: 'catalog_identity_incomplete' }); continue;
    }
    const rawUnits = singleAttribute(attrs, 8962), units = Number(rawUnits);
    // A length-bearing product needs supplier-unit review, even if a unit count also exists.
    const unitReview = (attrs.attributes || []).some(a => a.id === 4678);
    const pack = !unitReview && rawUnits !== null && /^\d+$/.test(rawUnits) && Number.isSafeInteger(units) && units > 0 ? units : null;
    identities.set(offer, { offer_id: offer, brand, sku, pack, unitReview, title: String(detail.name || attrs.name || '') });
    if (pack !== null) packMap.set(offer, pack);
    else pending.push({ offer, reason: unitReview ? 'supplier_unit_review' : 'explicit_pack_missing' });
  }
  return { packMap, identities, pending };
}
async function fetchCatalog(offers, { request = null, headers = null } = {}) {
  const authHeaders = headers || (request ? {} : credentials());
  const post = request || (async (endpoint, body) => (await axios.post(`https://api-seller.ozon.ru${endpoint}`, body, { headers: authHeaders, timeout: 30000 })).data);
  let info = [], attrs = [];
  for (let start = 0; start < offers.length; start += 100) {
    const batch = offers.slice(start, start + 100);
    const detail = await post('/v3/product/info/list', { offer_id: batch });
    const attributes = await post('/v4/product/info/attributes', { filter: { offer_id: batch }, limit: batch.length });
    // Validate per-request boundaries as well as the final merged response.
    uniqueByOffer(detail.items, new Set(batch), 'v3');
    uniqueByOffer(attributes.result, new Set(batch), 'v4');
    info.push(...detail.items); attrs.push(...attributes.result);
  }
  return parseCatalog(offers, info, attrs);
}
function letter(column) { let text = ''; while (column) { column--; text = String.fromCharCode(65 + column % 26) + text; column = Math.floor(column / 26); } return text; }
async function ensureCatalogFallback(sheets, identities, options = {}) {
  const spreadsheetId = options.spreadsheetId || BOOK;
  const read = async (ranges, valueRenderOption) => (await retryRead(()=>sheets.spreadsheets.values.batchGet({ spreadsheetId, ranges, valueRenderOption },{timeout:90000,retry:false}))).data.valueRanges;
  const [visible, formulas] = await Promise.all([read(["'StreamSupps'!1:1"], 'UNFORMATTED_VALUE'), read(["'StreamSupps'!1:1"], 'FORMULA')]);
  const columns = resolveStreamSuppsColumns(visible[0].values?.[0] || [], { brand: STREAM_SUPPS_HEADERS.brand, sku: STREAM_SUPPS_HEADERS.ozonSku });
  const current = formulas[0].values?.[0] || [];
  for (const field of ['brand', 'sku']) if (![ORIGINAL_ANCHORS[field], legacyFallbackFormula(field), fallbackFormula(field)].includes(current[columns[field] - 1])) throw new Error(`Unknown StreamSupps ${field} anchor; preserve and review`);
  const metadata = (await retryRead(()=>sheets.spreadsheets.get({ spreadsheetId, fields: 'sheets.properties' },{timeout:90000,retry:false}))).data;
  let aux = metadata.sheets.find(s => s.properties.title === AUX)?.properties;
  let existing = [];
  if (aux) {
    existing = (await read([`'${AUX}'!A:E`], 'UNFORMATTED_VALUE'))[0].values || [];
    if (JSON.stringify(existing[0]) !== JSON.stringify(AUX_HEADERS)) throw new Error('Onboarding auxiliary schema changed');
  }
  const rows = new Map();
  for (const row of existing.slice(1)) {
    if (!row[0]) continue;
    if (rows.has(String(row[0]))) throw new Error('Duplicate onboarding auxiliary offer');
    rows.set(String(row[0]), row);
  }
  const now = (options.now || (() => new Date().toISOString()))();
  for (const [offer, item] of identities) {
    const previous=rows.get(offer);
    const identity=[offer,item.brand,item.sku,item.pack??''];
    rows.set(offer,[...identity,previous&&JSON.stringify(previous.slice(0,4))===JSON.stringify(identity)?previous[4]:now]);
  }
  if (options.dryRun) return { rows: rows.size, columns };
  // Preserve the exact before-image before any structural or formula mutation.
  const backupDir = options.backupDir || path.join(__dirname, 'test', 'runtime');
  fs.mkdirSync(backupDir, { recursive: true });
  fs.writeFileSync(path.join(backupDir, `stream-onboarding-catalog-before-${Date.now()}-${process.pid}.json`), JSON.stringify({ at: now, columns, anchors: current, auxiliary: existing }), { mode: 0o600 });
  if (!aux) {
    const created = await sheets.spreadsheets.batchUpdate({ spreadsheetId, requestBody: { requests: [{ addSheet: { properties: { title: AUX, hidden: true, gridProperties: { rowCount: Math.max(1000, rows.size + 1), columnCount: 5 } } } }] } });
    aux = created.data.replies?.[0]?.addSheet?.properties;
    if (!aux?.sheetId && aux?.sheetId !== 0) throw new Error('Auxiliary creation not acknowledged');
  } else {
    const requests = [];
    if (!aux.hidden) requests.push({ updateSheetProperties: { properties: { sheetId: aux.sheetId, hidden: true }, fields: 'hidden' } });
    if (aux.gridProperties.rowCount < rows.size + 1) requests.push({ appendDimension: { sheetId: aux.sheetId, dimension: 'ROWS', length: rows.size + 1 - aux.gridProperties.rowCount } });
    if (requests.length) await sheets.spreadsheets.batchUpdate({ spreadsheetId, requestBody: { requests } });
  }
  if(JSON.stringify(existing)!==JSON.stringify([AUX_HEADERS,...rows.values()])) {
    await sheets.spreadsheets.values.update({ spreadsheetId, range: `'${AUX}'!A1:E${rows.size + 1}`, valueInputOption: 'RAW', requestBody: { values: [AUX_HEADERS, ...rows.values()] } },{timeout:90000,retry:false});
  }
  const written = (await read([`'${AUX}'!A1:E${rows.size + 1}`], 'UNFORMATTED_VALUE'))[0].values || [];
  if (JSON.stringify(written) !== JSON.stringify([AUX_HEADERS, ...rows.values()])) throw new Error('Onboarding auxiliary read-back mismatch');
  // Header/spill formulas belong to the spreadsheet. Auxiliary source values
  // may refresh, but an ordinary catalog pass never migrates those formulas.
  const checked = await read(['brand', 'sku'].map(field => `'StreamSupps'!${letter(columns[field])}1`), 'FORMULA');
  if (checked.some((range, i) => range.values?.[0]?.[0] !== current[columns[['brand','sku'][i]]-1])) throw new Error('Onboarding anchor changed concurrently; preserved');
  return { rows: rows.size, columns };
}
async function resolveOnboardingCatalog(sheets, offers, options = {}) {
  const exact = [...new Set(offers.map(offer => String(typeof offer === 'object' ? offer.offer_id ?? offer.offer : offer).trim()).filter(Boolean))];
  if (!exact.length) return { packMap: new Map(), identities: new Map(), pending: [] };
  const result = await fetchCatalog(exact, options);
  await ensureCatalogFallback(sheets, result.identities, options);
  return result;
}
module.exports = { resolveOnboardingCatalog, ensureCatalogFallback, fetchCatalog, parseCatalog, fallbackFormula, ORIGINAL_ANCHORS, AUX, AUX_HEADERS };
