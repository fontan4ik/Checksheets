'use strict';
/** At-most-once admission of new tail rows. Claims are durable BEFORE any Sheets write. */
const fs = require('node:fs');
const path = require('node:path');
const DEFAULT_STATE = path.join(__dirname, 'logs', 'append-initialization-state.json');
const text = value => String(value ?? '').trim();
const blank = value => value === '' || value === null || value === undefined;
function atomicJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temporary = `${file}.${process.pid}.tmp`;
  const fd = fs.openSync(temporary, 'w', 0o600);
  try { fs.writeFileSync(fd, JSON.stringify(value, null, 2)); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
  fs.renameSync(temporary, file);
  const parent = fs.openSync(path.dirname(file), 'r');
  try { fs.fsyncSync(parent); } finally { fs.closeSync(parent); }
}
function acquire(file) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const lock = `${file}.lock`;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      fs.mkdirSync(lock);
      fs.writeFileSync(path.join(lock, 'pid'), String(process.pid));
      return () => { if (fs.existsSync(path.join(lock, 'pid')) && fs.readFileSync(path.join(lock, 'pid'), 'utf8') === String(process.pid)) { fs.unlinkSync(path.join(lock, 'pid')); fs.rmdirSync(lock); } };
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      const pidFile = path.join(lock, 'pid');
      const pid = fs.existsSync(pidFile) ? Number(fs.readFileSync(pidFile, 'utf8')) : null;
      if (!Number.isSafeInteger(pid) || pid <= 0) throw new Error('Append initialization ledger busy');
      try { process.kill(pid, 0); throw new Error('Append initialization ledger busy'); }
      catch (probe) { if (probe.code !== 'ESRCH') throw probe; }
      fs.unlinkSync(pidFile); fs.rmdirSync(lock);
    }
  }
  throw new Error('Append initialization ledger unavailable');
}
function load(file) {
  if (!fs.existsSync(file)) {
    if (fs.existsSync(`${file}.initialized`)) throw new Error('Established append ledger missing; automatic initialization denied');
    return { version: 1, scopes: {} };
  }
  const state = JSON.parse(fs.readFileSync(file, 'utf8'));
  if (state.version !== 1 || !state.scopes || typeof state.scopes !== 'object' || Array.isArray(state.scopes)) throw new Error('Invalid append initialization ledger');
  return state;
}
function persist(file, state) {
  atomicJson(file, state);
  if (!fs.existsSync(`${file}.initialized`)) fs.writeFileSync(`${file}.initialized`, '1\n', { mode: 0o600, flag: 'wx' });
}
function indexKeys(keys) {
  if (!Array.isArray(keys)) throw new Error('Append admission requires full A keys including header');
  const rows = [], counts = new Map();
  for (let index = 1; index < keys.length; index++) {
    if (!Array.isArray(keys[index])) throw new Error('Invalid full A keys');
    const offer = text(keys[index][0]);
    if (!offer) continue;
    rows.push({ row: index + 1, offer }); counts.set(offer, (counts.get(offer) || 0) + 1);
  }
  return { rows, counts, lastRow: rows.length ? rows[rows.length - 1].row : 1 };
}
function scopeKey({ scope, sheetName, spreadsheetId = 'checksheets' }) {
  if (!text(scope) || !text(sheetName)) throw new Error('Append admission requires scope and sheetName');
  return JSON.stringify([spreadsheetId, scope, sheetName]);
}
function observe(state, options) {
  const key = scopeKey(options), current = indexKeys(options.keys);
  let record = state.scopes[key];
  if (!record) {
    record = state.scopes[key] = { highWaterRow: current.lastRow, seen: Object.fromEntries(current.rows.map(row => [row.offer, true])), admitted: {}, cells: {}, seededAt: new Date().toISOString() };
    return { record, current, seeded: true };
  }
  if (!Number.isSafeInteger(record.highWaterRow) || record.highWaterRow < 1 || !record.seen || !record.admitted || !record.cells || typeof record.seen !== 'object' || typeof record.admitted !== 'object' || typeof record.cells !== 'object') throw new Error('Invalid append scope record');
  const previousTail = record.highWaterRow;
  for (const entry of current.rows) {
    const rowKey = `${entry.row}:${entry.offer}`;
    if (!record.seen[entry.offer] && entry.row > previousTail && current.counts.get(entry.offer) === 1) record.admitted[rowKey] = { admittedAt: new Date().toISOString() };
  }
  for (const entry of current.rows) record.seen[entry.offer] = true;
  record.highWaterRow = Math.max(record.highWaterRow, current.lastRow);
  return { record, current, seeded: false };
}
function columnNumber(value) {
  if (Number.isSafeInteger(value) && value > 0) return value;
  if (typeof value === 'string' && /^[A-Za-z]+$/.test(value)) return [...value.toUpperCase()].reduce((number, letter) => number * 26 + letter.charCodeAt(0) - 64, 0);
  return null;
}
function destination(item, sheetName) {
  let row = item.row, column = columnNumber(item.column);
  if (item.range) {
    const match = String(item.range).match(/^(?:(?:'((?:[^']|'')+)'|([^!]+))!)?\$?([A-Za-z]+)\$?(\d+)(?::\$?([A-Za-z]+)\$?(\d+))?$/);
    if (!match || (match[1] || match[2]) && (match[1] || match[2]).replace(/''/g, "'") !== sheetName || match[5] && (match[5].toUpperCase() !== match[3].toUpperCase() || match[6] !== match[4])) throw new Error('Append ledger requires exact single-cell destination');
    if (row && row !== Number(match[4]) || column && column !== columnNumber(match[3])) throw new Error('Conflicting append destination coordinates');
    row ||= Number(match[4]); column ||= columnNumber(match[3]);
  }
  if (!Number.isSafeInteger(row) || row < 2 || !column) throw new Error('Invalid append destination');
  const offer = text(item.offer ?? item.offer_id);
  if (!offer) throw new Error('Append destination requires exact offer');
  return { row, column, offer, key: `${row}:${column}`, rowKey: `${row}:${offer}` };
}
function authorize(state, options) {
  const { record, current, seeded } = observe(state, options);
  const byRow = new Map(current.rows.map(row => [row.row, row.offer]));
  const observed = new Map();
  for (const item of options.observedCells || []) {
    const cell = destination(item, options.sheetName);
    if (!Object.hasOwn(item, 'value') && !Object.hasOwn(item, 'formula')) throw new Error('Observed destination requires value or formula');
    if (observed.has(cell.key)) throw new Error('Duplicate observed initialization destination');
    if (byRow.get(cell.row) !== cell.offer) throw new Error('Append observed row identity mismatch');
    observed.set(cell.key, item);
    if (record.admitted[cell.rowKey] && (!blank(item.value) || !blank(item.formula))) record.cells[cell.key] ||= { status: 'protected', offer: cell.offer, observedAt: new Date().toISOString() };
  }
  const authorized = [], blocked = [];
  for (const item of options.changes || []) {
    const cell = destination(item, options.sheetName);
    let reason;
    if (seeded || !record.admitted[cell.rowKey]) reason = 'existing_row_protected';
    else if (byRow.get(cell.row) !== cell.offer || current.counts.get(cell.offer) !== 1) reason = 'row_identity_changed';
    else if (!observed.has(cell.key)) reason = 'destination_not_observed';
    else if (record.cells[cell.key]) reason = record.cells[cell.key].status === 'issued' ? 'initialization_already_issued' : 'destination_protected';
    if (reason) { blocked.push({ change: item, reason }); continue; }
    // Never resend an issued destination: a lost reply may already be a successful write.
    record.cells[cell.key] = { status: 'issued', offer: cell.offer, issuedAt: new Date().toISOString() };
    authorized.push(item);
  }
  return { authorized, blocked, seeded, admittedRows: current.rows.filter(entry => record.admitted[`${entry.row}:${entry.offer}`]) };
}
function claimAppendInitializations(options) {
  const file = options.stateFile || DEFAULT_STATE;
  const release = acquire(file);
  try {
    const state = load(file), result = authorize(state, options);
    if (!options.dryRun) persist(file, state);
    return result;
  } finally { release(); }
}
function inspectAppendEligibility(options) {
  const file = options.stateFile || DEFAULT_STATE;
  // A preview never advances the durable tail, records observations, or claims cells.
  const state = load(file), { record, current, seeded } = observe(state, options);
  const columns = (options.columns || []).map(columnNumber);
  if (columns.some(column => !column)) throw new Error('Invalid append eligibility columns');
  const admittedRows = current.rows.filter(entry => current.counts.get(entry.offer) === 1 && record.admitted[`${entry.row}:${entry.offer}`]
    && (!columns.length || columns.some(column => !record.cells[`${entry.row}:${column}`])));
  return { seeded, admittedRows, eligibleOffers: [...new Set(admittedRows.map(entry => entry.offer))] };
}

function seedAppendInitializationBaselines(sheets, options = {}) {
  const file = options.stateFile || DEFAULT_STATE, release = acquire(file);
  try {
    const state = load(file), results = [];
    for (const sheet of sheets) {
      const key = scopeKey(sheet);
      if (state.scopes[key]) throw new Error('Append baseline already established; refusing to reset');
      const result = observe(state, sheet);
      results.push({ scope: sheet.scope, sheetName: sheet.sheetName, highWaterRow: result.record.highWaterRow });
    }
    if (!options.dryRun) persist(file, state);
    return results;
  } finally { release(); }
}
module.exports = { claimAppendInitializations, seedAppendInitializationBaselines, inspectAppendEligibility, DEFAULT_STATE, destination };
