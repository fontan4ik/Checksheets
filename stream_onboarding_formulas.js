/** Missing-only StreamSupps preparation. Never writes spill ranges or source stocks. */
const fs = require('node:fs');
const path = require('node:path');
const { STREAM_SUPPS_HEADERS: H, resolveStreamSuppsColumns } = require('./stream_supps_schema');
const BOOK = '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
const SCHEMA = {
  offer: H.offerId, model: H.model, brand: H.brand, pack: 'Х', samaraTotal: 'СМР САМ',
  feronMsk: H.feronMsk, feronSmr: H.feronSmr, feronNsb: H.feronNsb, feronEkb: H.feronEkb,
  moscow: H.podorozhnikFbs, samara: H.feronFbs, nsb: H.feronNsbFbs, ekb: H.feronEkbFbs,
  etmSource: 'ETM SMR', etm: H.etmSmr, rsSource: H.rsSmr, rs: H.reserve,
  rsMoscow: 'РУССКИЙ СВЕТ МОСКВА', wbSamara: H.wbVoltmirTotal,
  wbMoscow: H.wbFeronMoscowTotal, total: 'СУММА ВСЕХ ПОСТАВЩИКОВ',
};
const CABLE_MODELS = new Set(['LC1-C5E04-121-T-R','LC1-C5E04-121-T-P-R','LC1-C5E04-321-T-P-R','LC1-C5E04-311','LC1-C5E04-111-T-R']);
const blank = v => v === '' || v === null || v === undefined;
const positive = v => !blank(v) && Number.isFinite(Number(v)) && Number(v) > 0;
const numeric = v => !blank(v) && typeof v === 'number' && Number.isFinite(v) && v >= 0;
const text = v => String(v ?? '').trim();
const cell = (rows, r, c) => rows[r - 1]?.[c - 1] ?? '';
function letter(col) { let s = ''; for (; col; col = Math.floor((col - 1) / 26)) s = String.fromCharCode(65 + (col - 1) % 26) + s; return s; }
function normalizeFormula(f) { return text(f).replace(/\s+/g, '').toUpperCase().replace(/(\$?[A-Z]+)\$?\d+/g, '$1#'); }
// Replace only the template's row references, never numeric constants (e.g. 305).
function relocateFormula(f, from, to) { return f.replace(/(\$?[A-Z]+)(\$?)(\d+)/g, (all, col, absolute, row) => absolute ? all : col + (Number(row) === from ? to : row)); }
function templateInventory(values, formulas, columns, field) {
  const inventory = [];
  for (let r = 2; r <= values.length; r++) {
    const f = cell(formulas, r, columns[field]);
    if (typeof f === 'string' && f.startsWith('=')) inventory.push({ row: r, formula: f,
      normalized: normalizeFormula(f), brand: text(cell(values, r, columns.brand)).toLowerCase(), model: text(cell(values, r, columns.model)) });
  }
  return inventory;
}
function chooseTemplate(inventory, model, brand) {
  const sameModel = inventory.filter(t => t.model === model && t.brand === brand);
  const candidates = sameModel.length ? sameModel : inventory.filter(t => t.brand === brand);
  const rules = new Map();
  for (const t of candidates) { const v = rules.get(t.normalized) || { ...t, count: 0 }; v.count++; rules.set(t.normalized, v); }
  if (rules.size === 1) return [...rules.values()][0];
  // The verified M allocation formula is the common established rule across
  // Feron and Arlight; simple /1.5 and /2 remain per-product overrides.
  const canonical = [...rules.values()].filter(t => t.normalized.includes('LET(BASE;REGEXREPLACE(') && t.normalized.includes('ARL_TR;'));
  if (!sameModel.length && canonical.length === 1 && canonical[0].count >= 5) return canonical[0];
  return null;
}
function canonicalAllocation(inventory) {
  const rules = new Map();
  for (const t of inventory) {
    if (!t.normalized.includes('LET(BASE;REGEXREPLACE(') || !t.normalized.includes('ARL_TR;')) continue;
    const entry = rules.get(t.normalized) || { ...t, count: 0 }; entry.count++; rules.set(t.normalized, entry);
  }
  const candidates = [...rules.values()];
  return candidates.length === 1 && candidates[0].count >= 5 ? candidates[0] : null;
}
function planStreamSupps({ values, formulas, txoz, targetOffers, offers, packMap }) {
  const requested = targetOffers || offers;
  if (!Array.isArray(requested) && !(requested instanceof Set)) throw new Error("StreamSupps: explicit targetOffers required; historical blanks are protected");
  const columns = resolveStreamSuppsColumns(values[0] || [], SCHEMA);
  // Templates reference fixed source letters; moved columns require an explicit
  // migration rather than silently adopting formulas pointed at the old layout.
  const established = { offer:1, model:2, brand:4, pack:6, samaraTotal:8, feronMsk:9, feronSmr:10,
    feronNsb:11, feronEkb:12, moscow:13, samara:14, nsb:15, ekb:16, etmSource:17,
    etm:19, rsSource:21, rs:22, rsMoscow:24, wbSamara:28, wbMoscow:29, total:31 };
  for (const [k, c] of Object.entries(established)) if (columns[k] !== c) throw new Error(`StreamSupps: moved ${k}; formula migration required`);
  const txColumns = resolveStreamSuppsColumns(txoz[0] || [], { offer:'Артикул', pack:'Кратность нтц' }, 'TXOZ');
  const packs = new Map();
  for (const r of txoz.slice(1)) { const key = text(r[txColumns.offer - 1]); if (key) { const a = packs.get(key) || []; a.push(r[txColumns.pack - 1]); packs.set(key, a); } }
  const inventories = Object.fromEntries(['moscow', 'total'].map(f => [f, templateInventory(values, formulas, columns, f)]));
  const selected = requested ? new Set(requested) : null;
  const defaultMoscowTemplate = canonicalAllocation(inventories.moscow);
  const changes = [], pending = [], touched = new Set();
  const report = { counts: {}, inactiveFields: ['nsb', 'ekb'], rowCount: values.length - 1, moscowNonzero: [] };
  for (let row = 2; row <= values.length; row++) {
    const offer = text(cell(values, row, columns.offer));
    if (!offer || selected && !selected.has(offer)) continue;
    const missing = field => blank(cell(values, row, columns[field])) && blank(cell(formulas, row, columns[field]));
    const add = (field, value) => { if (!missing(field)) return; const range = `'StreamSupps'!${letter(columns[field])}${row}`;
      changes.push({ range, values: [[value]], offer, field, row }); touched.add(offer); report.counts[field] = (report.counts[field] || 0) + 1; };
    const reason = (field, why) => pending.push({ offer, row, field, reason: why });
    const model = text(cell(values, row, columns.model)), brand = text(cell(values, row, columns.brand)).toLowerCase();
    const supplied = packMap instanceof Map ? packMap.get(offer) : packMap?.[offer];
    if (supplied && typeof supplied === 'object' && supplied.unitReview) {
      reason('pack', 'unit review required before stock formulas');
      if (missing('rsMoscow')) add('rsMoscow', 0);
      continue;
    }
    let pack = cell(values, row, columns.pack);
    if (missing('pack')) {
      const candidates = packs.get(offer) || [];
      if (candidates.length === 1 && positive(candidates[0])) {
        pack = Number(candidates[0]); add('pack', `=VLOOKUP(A${row};TXOZ!A:C;3;0)`);
      } else if (candidates.length === 0 && packMap) {
        // Only the caller's authoritative, exact-offer pack resolver may supply
        // missing TXOZ identities. No model fuzzy-match or suffix inference here.
        const suppliedPack = supplied && typeof supplied === 'object' ? supplied.pack : supplied;
        if (positive(suppliedPack)) { pack = Number(suppliedPack); add('pack', pack); }
        else reason('pack', 'missing valid exact TXOZ or authoritative pack');
      } else reason('pack', candidates.length > 1 ? 'duplicate TXOZ offer' : 'missing valid exact TXOZ pack');
    }
    if (missing('rsMoscow')) add('rsMoscow', 0);
    if (Number(cell(values, row, columns.rsMoscow))) report.moscowNonzero.push({ offer, row });
    if (!positive(pack)) { reason('pack', 'pack is not positive numeric; stock formulas postponed'); continue; }
    const guarded = (source, expression) => `=IF(OR(NOT(ISNUMBER(${source}${row}));NOT(ISNUMBER(F${row}));F${row}<=0);"";${expression})`;
    add('samaraTotal', `=IF(COUNT(J${row};Q${row};U${row})<>3;"";J${row}+Q${row}+U${row})`);
    add('samara', guarded('J', `ROUND(J${row}/F${row}/1,5;0)`));
    add('etm', guarded('Q', CABLE_MODELS.has(model) ? `ROUND(TRUNC(Q${row}/305)/F${row}/1,5;0)` : `ROUND(Q${row}/F${row}/1,5;0)`));
    add('rs', guarded('U', `ROUND(U${row}/F${row}/1,5;0)`));
    if (missing('moscow')) {
      const template = chooseTemplate(inventories.moscow, model, brand) || defaultMoscowTemplate;
      if (template) add('moscow', guarded('I', relocateFormula(template.formula, template.row, row).slice(1)));
      else reason('moscow', 'no unambiguous verified product/brand formula');
    }
    add('wbSamara', `=IF(OR(A${row}="";COUNT(N${row};S${row};V${row})<>3);"";ROUND(N${row}+S${row}+V${row};0))`);
    add('wbMoscow', `=IF(OR(A${row}="";COUNT(M${row};X${row})<>2);"";ROUND(M${row}+X${row};0))`);
    if (missing('total')) {
      const template = chooseTemplate(inventories.total, model, brand);
      if (template) add('total', relocateFormula(template.formula, template.row, row));
      // Diagnostic fallback for new manufacturer brands: sum only literal
      // Feron source lanes. Marketplace totals above remain authoritative.
      else add('total', `=IF(COUNT(I${row};J${row};K${row};L${row})<>4;"";I${row}+J${row}+K${row}+L${row})`);
    }
    for (const field of ['feronMsk', 'feronSmr', 'etmSource', 'rsSource']) {
      if (!numeric(cell(values, row, columns[field]))) reason(field, 'source snapshot not populated with nonnegative number');
    }
    // O/P are inactive in the verified sheet (no formulas anywhere). Preserve.
  }
  return { changes, changed: changes.length, offers: [...touched], pending, report, columns };
}
function targetBlocks(keys, targetOffers) {
  const wanted = new Set(targetOffers), blocks = [];
  for (let index = 1; index < keys.length; index++) {
    if (!wanted.has(text(keys[index]?.[0]))) continue;
    const row = index + 1, previous = blocks[blocks.length - 1];
    if (previous && row === previous.end + 1 && row - previous.start < 200) previous.end = row;
    else blocks.push({ start: row, end: row });
  }
  return blocks;
}
async function readStreamSnapshot(sheets, { spreadsheetId = BOOK, targetOffers, readRetryDelayMs = 1000 } = {}) {
  if (!targetOffers) throw new Error('StreamSupps: explicit targetOffers required');
  const request = async params => {
    for (let attempt = 0; ; attempt++) {
      try { return await sheets.spreadsheets.values.batchGet({ spreadsheetId, ...params }, { timeout:90000, retry:false }); }
      catch (error) {
        const status = Number(error.response?.status || error.code);
        const transient = [408, 429, 500, 502, 503, 504].includes(status) ||
          ['ECONNRESET','ETIMEDOUT','ECONNABORTED','EAI_AGAIN','ENOTFOUND','EPIPE'].includes(error.code) ||
          /socket hang up/i.test(error.message || '');
        if (!transient || attempt >= 3) throw error;
        await new Promise(resolve => setTimeout(resolve, readRetryDelayMs * 2 ** attempt));
      }
    }
  };
  const keys = await request({ ranges:["'StreamSupps'!1:1", "'StreamSupps'!A:A", 'TXOZ!A:A'], valueRenderOption:'UNFORMATTED_VALUE' });
  const offerKeys = keys.data.valueRanges[1].values || [];
  const last = Math.max(1, offerKeys.length), txLast = Math.max(1, keys.data.valueRanges[2].values?.length || 1);
  // FORMULA reads return entered formulas without evaluating every expensive M
  // allocation and unrelated Y/Z/AA lookup in the 22k+ historical rows.
  const entered = await request({ ranges:[`'StreamSupps'!A1:AE${last}`, `TXOZ!A1:C${txLast}`], valueRenderOption:'FORMULA' });
  const formulas = entered.data.valueRanges[0].values || [];
  const values = Array.from({ length:last }, (_, i) => (formulas[i] || []).map(v => typeof v === 'string' && v.startsWith('=') ? '' : v));
  values[0] = keys.data.valueRanges[0].values?.[0] || [];
  const identity = await request({ ranges:[`'StreamSupps'!B2:B${Math.max(2,last)}`, `'StreamSupps'!D2:D${Math.max(2,last)}`], valueRenderOption:'UNFORMATTED_VALUE' });
  for (const [index, column] of [[0,1],[1,3]]) {
    (identity.data.valueRanges[index].values || []).forEach((r, i) => { if (values[i + 1]) values[i + 1][column] = r[0] ?? ''; });
  }
  // Effective output is required only for the durable target set. Exclude the
  // unrelated picture/sales/design/Arlight spill lanes beyond X.
  const reads = targetBlocks(offerKeys, targetOffers).flatMap(block => [
    { ...block, column:0, endColumn:23, range:`'StreamSupps'!A${block.start}:X${block.end}` },
    { ...block, column:27, endColumn:28, range:`'StreamSupps'!AB${block.start}:AC${block.end}` },
    { ...block, column:30, endColumn:30, range:`'StreamSupps'!AE${block.start}:AE${block.end}` },
  ]);
  for (let offset = 0; offset < reads.length; offset += 12) {
    const batch = reads.slice(offset, offset + 12);
    const result = await request({ ranges:batch.map(r => r.range), valueRenderOption:'UNFORMATTED_VALUE' });
    batch.forEach((read, i) => {
      const rows = result.data.valueRanges[i].values || [];
      for (let row = read.start; row <= read.end; row++) for (let c = read.column; c <= read.endColumn; c++) {
        values[row - 1][c] = rows[row - read.start]?.[c - read.column] ?? '';
      }
    });
  }
  return { values, formulas, offerKeys, txoz:entered.data.valueRanges[1].values || [], request };
}
async function prepareStreamSupps(sheets, { dryRun = false, spreadsheetId = BOOK,
  backupDir = path.join(__dirname, 'test', 'runtime'), targetOffers, offers, packMap, readRetryDelayMs,
  ledgerStateFile } = {}) {
  if (!targetOffers && !offers) throw new Error('StreamSupps: explicit targetOffers required');
  const { request, ...snapshot } = await readStreamSnapshot(sheets, { spreadsheetId, targetOffers:targetOffers || offers, readRetryDelayMs });
  const proposed = planStreamSupps({ ...snapshot, targetOffers: targetOffers || offers, packMap });
  // The durable append ledger protects both historical gaps and cells a person
  // clears later. Claim before the first remote attempt; ambiguous failures must
  // never cause an automatic second write into a subsequently edited cell.
  const managedFields = ['pack', 'samaraTotal', 'samara', 'etm', 'rs', 'moscow', 'wbSamara', 'wbMoscow', 'total', 'rsMoscow'];
  const observedCells = [];
  for (let row = 2; row <= snapshot.values.length; row++) {
    const offer = text(snapshot.offerKeys[row - 1]?.[0]);
    if (!offer) continue;
    for (const field of managedFields) {
      const column = proposed.columns[field];
      observedCells.push({ row, offer, column, value: cell(snapshot.values, row, column), formula: cell(snapshot.formulas, row, column) });
    }
  }
  const { claimAppendInitializations } = require('./append_initialization_ledger');
  const claims = claimAppendInitializations({ scope:'stream-formulas', sheetName:'StreamSupps',
    keys:snapshot.offerKeys,
    changes:proposed.changes.map(change => ({ ...change, column:proposed.columns[change.field] })),
    observedCells, stateFile:ledgerStateFile, dryRun });
  const counts = {};
  for (const change of claims.authorized) counts[change.field] = (counts[change.field] || 0) + 1;
  const plan = { ...proposed, changes:claims.authorized, changed:claims.authorized.length,
    offers:[...new Set(claims.authorized.map(change => change.offer))],
    report:{ ...proposed.report, counts, appendInitialization:{ seeded:claims.seeded,
      admittedRows:claims.admittedRows, blocked:claims.blocked.length } } };
  if (!dryRun && plan.changes.length) {
    fs.mkdirSync(backupDir, { recursive:true });
    fs.writeFileSync(path.join(backupDir, `stream-formulas-before-${Date.now()}-${process.pid}.json`), JSON.stringify({ at:new Date().toISOString(), ...snapshot, changes:plan.changes }), { mode:0o600 });
    for (let start = 0; start < plan.changes.length; start += 100) {
      const batch = plan.changes.slice(start, start + 100);
      // Re-read destinations and their offer keys immediately before mutation.
      const checks = await request({ ranges:batch.flatMap(c => [c.range, `'StreamSupps'!A${c.row}`]), valueRenderOption:'FORMULA' });
      batch.forEach((c, i) => {
        if (!blank(checks.data.valueRanges[i * 2].values?.[0]?.[0]) || text(checks.data.valueRanges[i * 2 + 1].values?.[0]?.[0]) !== c.offer) throw new Error(`StreamSupps concurrent edit at ${c.range}`);
      });
      await sheets.spreadsheets.values.batchUpdate({ spreadsheetId, requestBody:{ valueInputOption:'USER_ENTERED', data:batch.map(({range,values}) => ({range,values})) } }, { timeout:90000, retry:false });
      const verified = await request({ ranges:batch.map(c => c.range), valueRenderOption:'FORMULA' });
      batch.forEach((c, i) => { if (verified.data.valueRanges[i].values?.[0]?.[0] !== c.values[0][0]) throw new Error(`StreamSupps formula read-back mismatch at ${c.range}`); });
    }
  }
  return { ...plan, dryRun, values: snapshot.values, headers: snapshot.values[0], snapshot };
}
module.exports = { planStreamSupps, prepareStreamSupps, normalizeFormula, relocateFormula, CABLE_MODELS, SCHEMA, readStreamSnapshot, targetBlocks };
