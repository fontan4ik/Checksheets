'use strict';

const fs = require('node:fs');
const path = require('node:path');
const BOOK = '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
const HEADER = 'Артикул WB';
const OLD_ARRAY = '={ "Артикул WB"; ARRAYFORMULA(IFERROR(VLOOKUP(A2:A & "";\'ТЕХ данные wb\'!A:C;3;0)))}';
const text = value => String(value ?? '');
const normalized = value => text(value).trim().toLowerCase().replace(/\s+/g, ' ');

function nmId(value) {
  const string = text(value);
  return /^[1-9]\d*$/.test(string) && Number.isSafeInteger(Number(string)) ? string : null;
}

function planWbArticleIds(keys, current, tech) {
  // Explicit service layout: T is the established nmID field written by
  // updateWBArticles(). AN has a second visible "Артикул WB" header.
  const anchor = text(current[0]?.[0]).trim();
  if (anchor !== OLD_ARRAY && normalized(anchor) !== normalized(HEADER)) {
    throw new Error('ТЕСТ: unexpected T1 nmID header/formula');
  }
  const sourceHeaders = tech[0] || [];
  for (const [index, expected] of [[0, 'Артикул продавца'], [2, HEADER]]) {
    const matches = sourceHeaders.flatMap((h, i) => normalized(h) === normalized(expected) ? [i] : []);
    if (matches.length !== 1 || matches[0] !== index) throw new Error('ТЕХ данные wb: changed/duplicate ' + expected);
  }
  const mapping = new Map();
  for (const row of tech.slice(1)) {
    const offer = text(row[0]);
    if (!offer) continue;
    const id = nmId(row[2]);
    if (!id) throw new Error('ТЕХ данные wb: invalid nmID for ' + offer);
    if (mapping.has(offer) && mapping.get(offer) !== id) throw new Error('ТЕХ данные wb: ambiguous nmID for ' + offer);
    mapping.set(offer, id);
  }
  if (!mapping.size) throw new Error('ТЕХ данные wb: empty nmID source');

  const changes = [], conflicts = [], sourceUnavailable = [];
  let existing = 0, matching = 0;
  for (let index = 1; index < Math.max(keys.length, current.length); index++) {
    const offer = text(keys[index]?.[0]);
    const before = current[index]?.[0];
    const expected = mapping.get(offer);
    if (before !== '' && before !== undefined && before !== null) {
      existing++;
      if (!expected) sourceUnavailable.push({ row: index + 1, offer, before });
      else if (nmId(before) === expected) matching++;
      else conflicts.push({ row: index + 1, offer, before, expected });
    } else if (expected) changes.push({ row: index + 1, offer, value: expected });
  }
  return { headerChange: anchor !== HEADER, sourceOffers: mapping.size, existing, matching, conflicts, sourceUnavailable, changes };
}

function requestsFor(plan, sheetId) {
  const requests = [];
  if (plan.headerChange) requests.push({ updateCells: {
    range: { sheetId, startRowIndex: 0, endRowIndex: 1, startColumnIndex: 19, endColumnIndex: 20 },
    rows: [{ values: [{ userEnteredValue: { stringValue: HEADER } }] }], fields: 'userEnteredValue',
  } });
  let group = [];
  const flush = () => {
    if (!group.length) return;
    requests.push({ updateCells: {
      range: { sheetId, startRowIndex: group[0].row - 1, endRowIndex: group.at(-1).row, startColumnIndex: 19, endColumnIndex: 20 },
      rows: group.map(change => ({ values: [{ userEnteredValue: { stringValue: change.value } }] })), fields: 'userEnteredValue',
    } });
    group = [];
  };
  for (const change of plan.changes) {
    if (group.length && change.row !== group.at(-1).row + 1) flush();
    group.push(change);
  }
  flush();
  return requests;
}

async function prepareWbArticleIds(sheets, options = {}) {
  const spreadsheetId = options.spreadsheetId || BOOK;
  const read = async () => {
    const [raw, source] = await Promise.all([
      sheets.spreadsheets.values.batchGet({ spreadsheetId, ranges: ["'ТЕСТ'!T:T"], valueRenderOption: 'FORMULA' }, { timeout: 120000 }),
      sheets.spreadsheets.values.batchGet({ spreadsheetId, ranges: ["'ТЕСТ'!A:A", "'ТЕХ данные wb'!A:C"], valueRenderOption: 'FORMATTED_VALUE' }, { timeout: 120000 }),
    ]);
    return { current: raw.data.valueRanges[0].values || [], keys: source.data.valueRanges[0].values || [], tech: source.data.valueRanges[1].values || [] };
  };
  const before = await read();
  const plan = planWbArticleIds(before.keys, before.current, before.tech);
  // An ordinary header is a one-time migration, never a recurring repair of user changes.
  if (plan.headerChange) throw new Error('ТЕСТ T1 changed: automatic header repair denied');
  const observedCells=before.keys.slice(1).flatMap((r,i)=>text(r[0]).trim()?[{row:i+2,offer:text(r[0]).trim(),column:20,value:before.current[i+1]?.[0]??''}]:[]);
  const admission=require('./append_initialization_ledger').claimAppendInitializations({scope:'wb-article-ids',sheetName:'ТЕСТ',keys:before.keys,changes:plan.changes.map(c=>({...c,column:20})),observedCells,stateFile:options.ledgerStateFile,dryRun:!!options.dryRun});
  plan.changes=admission.authorized;
  const report = { sourceOffers: plan.sourceOffers, existing: plan.existing, matching: plan.matching,
    blocked: admission.blocked.length, conflicts: plan.conflicts, sourceUnavailable: plan.sourceUnavailable, planned: plan.changes.length, written: 0, headerChange: plan.headerChange };
  if (options.dryRun || (!plan.headerChange && !plan.changes.length)) return report;

  const metadata = (await sheets.spreadsheets.get({ spreadsheetId, fields: 'sheets.properties' }, { timeout: 120000 })).data;
  const sheetId = metadata.sheets.find(s => s.properties.title.toLowerCase() === 'тест')?.properties.sheetId;
  if (sheetId === undefined) throw new Error('ТЕСТ sheet missing');
  const backupDir = options.backupDir || path.join(__dirname, 'test', 'runtime');
  fs.mkdirSync(backupDir, { recursive: true });
  report.backup = path.join(backupDir, `wb-article-ids-before-${Date.now()}-${process.pid}.json`);
  fs.writeFileSync(report.backup, JSON.stringify({ at: new Date().toISOString(), before, plan }, null, 2));
  if (JSON.stringify(await read()) !== JSON.stringify(before)) throw new Error('TEST/TECH changed during nmID preparation');

  // No mutation retry: a lost response may follow a committed write. The next
  // invocation re-reads T and only fills cells that are still blank.
  const requests = requestsFor(plan, sheetId);
  for (let index = 0; index < requests.length; index += 500) {
    await sheets.spreadsheets.batchUpdate({ spreadsheetId, requestBody: { requests: requests.slice(index, index + 500) } }, { timeout: 120000, retry: false });
  }
  const after = await read();
  if (after.current[0]?.[0] !== HEADER) throw new Error('TEST T1 header read-back mismatch');
  for (let index = 1; index < before.current.length; index++) {
    const value = before.current[index]?.[0];
    if (value !== '' && value !== null && value !== undefined && after.current[index]?.[0] !== value) {
      throw new Error('TEST existing nmID changed at row ' + (index + 1));
    }
  }
  for (const change of plan.changes) {
    if (after.current[change.row - 1]?.[0] !== change.value) throw new Error('TEST nmID read-back mismatch at row ' + change.row);
  }
  report.written = plan.changes.length;
  report.preservedExisting = plan.existing;
  return report;
}

module.exports = { HEADER, OLD_ARRAY, nmId, planWbArticleIds, requestsFor, prepareWbArticleIds };
