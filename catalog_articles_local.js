#!/usr/bin/env node
/** Full Ozon/WB seller catalogs → missing articles at the end of A only. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const axios = require('axios');
const { google } = require('googleapis');
const { sendTelegramAlert } = require('./telegram_notifier');
const { STREAM_SUPPS_HEADERS, resolveStreamSuppsColumns } = require('./stream_supps_schema');

const BOOK = '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
const TARGETS = {
  ozon: [['ТЗ', 'Артикул'], ['ОБОР', 'Артикул'], ['Дизайн контент', null], ['StreamSupps', 'Артикул продавца'], ['UNIT API', 'Артикул']],
  wb: [['UNIT WB', 'Артикул']],
};
const LOGS = process.env.CATALOG_ARTICLES_LOG_DIR || path.join(__dirname, 'logs');
const LOCK = path.join(LOGS, 'catalog-articles.lock');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const text = value => String(value ?? '').trim();
const quote = name => `'${name.replace(/'/g, "''")}'`;
const log = message => console.log(`${new Date().toISOString()} ${message}`);

function atomicJson(file, value) {
  const temp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temp, JSON.stringify(value, null, 2), { mode: 0o600 });
  fs.renameSync(temp, file);
}

function acquireLock() {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const fd = fs.openSync(LOCK, 'wx', 0o600);
      fs.writeFileSync(fd, String(process.pid));
      fs.closeSync(fd);
      return true;
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      let pid;
      try { pid = Number(fs.readFileSync(LOCK, 'utf8')); }
      catch (readError) { if (readError.code === 'ENOENT') continue; throw readError; }
      // An empty/new lock belongs to the process currently creating it.
      if (!Number.isSafeInteger(pid) || pid <= 0) return false;
      try { process.kill(pid, 0); return false; }
      catch (probe) { if (probe.code !== 'ESRCH') throw probe; }
      fs.unlinkSync(LOCK);
    }
  }
  return false;
}

async function retry(operation, label) {
  for (let attempt = 0; ; attempt++) {
    try { return await operation(); }
    catch (error) {
      const status = Number(error.response?.status || error.code);
      const transient = [408, 409, 429, 500, 502, 503, 504].includes(status) ||
        ['ECONNRESET', 'ETIMEDOUT', 'ECONNABORTED', 'EAI_AGAIN', 'ENOTFOUND'].includes(error.code);
      if (!transient || attempt >= 4) throw new Error(`${label}: ${status || error.code || error.name}`);
      const retryAfter = Number(error.response?.headers?.['retry-after']);
      const wait = Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter * 1000 : 2000 * 2 ** attempt;
      log(`${label}: временный сбой, повтор через ${Math.ceil(wait / 1000)} с`);
      await sleep(wait);
    }
  }
}

function credentials() {
  // Reuse the agreed project configuration; never print or copy credential values.
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(path.join(__dirname, 'Shared_Настройки.js'), 'utf8') +
    ';this.catalogHeaders={ozon:ozonHeaders(),wb:wbHeaders()};', context);
  return context.catalogHeaders;
}

function parsePage(platform, body, limit) {
  const wb = platform === 'wb';
  const items = wb ? body.cards : body.result?.items;
  if (!Array.isArray(items)) throw new Error(`${platform}: некорректный ответ каталога`);
  const articles = items.map(item => {
    const value = wb ? item.vendorCode : item.offer_id;
    if (typeof value !== 'string' || !value.trim()) throw new Error(`${platform}: пустой артикул API`);
    return value.trim();
  });
  const complete = items.length < limit;
  const cursor = wb ? body.cursor && { updatedAt: body.cursor.updatedAt, nmID: body.cursor.nmID } : body.result.last_id;
  if (!complete && (wb ? !cursor?.updatedAt || !cursor?.nmID : !cursor)) throw new Error(`${platform}: нет курсора`);
  return { articles, complete, cursor };
}

async function fetchCatalog(platform, headers) {
  const wb = platform === 'wb', limit = wb ? 100 : 1000;
  const url = wb ? 'https://content-api.wildberries.ru/content/v2/get/cards/list' : 'https://api-seller.ozon.ru/v3/product/list';
  let cursor = null, pages = 0;
  const seen = new Set(['null']), articles = new Set();
  for (;;) {
    const payload = wb
      ? { settings: { sort: { ascending: true }, cursor: { limit, ...(cursor || {}) }, filter: { withPhoto: -1 } } }
      : { filter: { visibility: 'ALL' }, limit, last_id: cursor || '' };
    const response = await retry(() => axios.post(url, payload, { headers, timeout: 30000 }), platform);
    const page = parsePage(platform, response.data, limit);
    const key = JSON.stringify(page.cursor);
    if (!page.complete && seen.has(key)) throw new Error(`${platform}: повтор курсора`);
    page.articles.forEach(article => articles.add(article));
    pages++;
    if (pages % 25 === 0 || page.complete) log(`${platform}: страниц ${pages}, уникальных артикулов ${articles.size}`);
    if (page.complete) break;
    seen.add(key);
    cursor = page.cursor;
    await sleep(wb ? 900 : 100);
  }
  if (!articles.size) throw new Error(`${platform}: пустой каталог; запись пропущена`);
  return [...articles];
}

function planAppend(name, header, headers, values, formulas, articles) {
  const normalize = value => text(value).toLowerCase().replace(/ё/g, 'е').replace(/\s+/g, ' ');
  // UNIT API used to spill its keys from ТЕСТ. Appending beneath a growing
  // spill would eventually block that formula; its key column must be literal.
  if (name === 'UNIT API' && text(formulas[0]?.[0]).startsWith('=')) {
    throw new Error(`${name}: A1 должна содержать буквальный заголовок, а не формулу`);
  }
  if (name === 'StreamSupps' && header === STREAM_SUPPS_HEADERS.offerId) {
    // Reuse the documented blank-A1 key exception; appends still require A.
    const columns = resolveStreamSuppsColumns(headers, { offerId: header }, name);
    if (columns.offerId !== 1) throw new Error(`${name}: заголовок должен однозначно указывать на A`);
  } else if (header === null) {
    // Explicit fixed-A exception: Дизайн контент!A1 is empty, verified 2026-10-15.
    if (text(headers[0])) throw new Error(`${name}: изменился пустой заголовок A`);
  } else {
    const matches = headers.flatMap((value, i) => normalize(value) === normalize(header) ? [i] : []);
    if (matches.length !== 1 || matches[0] !== 0) throw new Error(`${name}: заголовок должен однозначно указывать на A`);
  }
  const existing = new Set();
  let last = 1;
  for (let i = 1; i < Math.max(values.length, formulas.length); i++) {
    const article = text(values[i]?.[0]);
    if (article) existing.add(article);
    if (article || text(formulas[i]?.[0])) last = i + 1;
  }
  const missing = [];
  for (const article of articles) if (!existing.has(article)) { missing.push(article); existing.add(article); }
  return { last, missing };
}

async function updateTarget(sheets, definition, articles, dryRun) {
  const [name, header] = definition, prefix = quote(name);
  // Read immediately before append, after the full marketplace scan has finished.
  const read = params => retry(() => sheets.spreadsheets.values.batchGet({ spreadsheetId: BOOK, ...params }), `Google ${name}`);
  const [effective, entered] = await Promise.all([
    read({ ranges: [`${prefix}!1:1`, `${prefix}!A:A`], valueRenderOption: 'FORMATTED_VALUE' }),
    read({ ranges: [`${prefix}!A:A`], valueRenderOption: 'FORMULA' }),
  ]);
  const plan = planAppend(name, header, effective.data.valueRanges[0].values?.[0] || [],
    effective.data.valueRanges[1].values || [], entered.data.valueRanges[0].values || [], articles);
  const result = { added: plan.missing.length, startRow: plan.last + 1, endRow: plan.last + plan.missing.length };
  if (!plan.missing.length || dryRun) { log(`${name}: ${dryRun ? 'добавить' : 'добавлено'} ${plan.missing.length}`); return result; }
  const metadata = await retry(() => sheets.spreadsheets.get({ spreadsheetId: BOOK, fields: 'sheets(properties(sheetId,title,gridProperties))' }), 'Google metadata');
  const properties = metadata.data.sheets.find(sheet => sheet.properties.title === name)?.properties;
  if (!properties) throw new Error(`Нет листа ${name}`);
  const requests = [];
  if (result.endRow > properties.gridProperties.rowCount) requests.push({ appendDimension: {
    sheetId: properties.sheetId, dimension: 'ROWS', length: result.endRow - properties.gridProperties.rowCount,
  } });
  requests.push({ updateCells: {
    range: { sheetId: properties.sheetId, startRowIndex: plan.last, endRowIndex: result.endRow, startColumnIndex: 0, endColumnIndex: 1 },
    rows: plan.missing.map(article => ({ values: [{ userEnteredValue: { stringValue: article } }] })), fields: 'userEnteredValue',
  } });
  // A timeout can be an acknowledged write with a lost response. Do not resend this
  // mutation: fail this run; the next run re-reads A and repairs without duplicates.
  atomicJson(path.join(LOGS, 'catalog-articles-pending.json'), { at: new Date().toISOString(), sheet: name, ...result, articles: plan.missing });
  await sheets.spreadsheets.batchUpdate({ spreadsheetId: BOOK, requestBody: { requests } }, { timeout: 90000, retry: false });
  const checked = await read({ ranges: [`${prefix}!A${result.startRow}:A${result.endRow}`], valueRenderOption: 'UNFORMATTED_VALUE' });
  const actual = checked.data.valueRanges[0].values || [];
  if (actual.length !== plan.missing.length || actual.some((row, i) => row[0] !== plan.missing[i])) throw new Error(`${name}: запись не совпала с read-back`);
  fs.rmSync(path.join(LOGS, 'catalog-articles-pending.json'), { force: true });
  log(`${name}: добавлено ${result.added}, A${result.startRow}:A${result.endRow}, read-back OK`);
  return result;
}

async function main() {
  fs.mkdirSync(LOGS, { recursive: true });
  if (!acquireLock()) { log('Другой проход уже выполняется; запуск пропущен'); return; }
  const report = { startedAt: new Date().toISOString(), sources: {}, sheets: {}, errors: [] };
  try {
    const auth = new google.auth.GoogleAuth({ keyFile: process.env.GOOGLE_APPLICATION_CREDENTIALS ||
      path.join(__dirname, 'nomadic-bedrock-485314-b0-d7624dedd83c.json'), scopes: ['https://www.googleapis.com/auth/spreadsheets'] });
    const sheets = google.sheets({ version: 'v4', auth });
    const headers = credentials();
    for (const platform of ['ozon', 'wb']) {
      try {
        const articles = await fetchCatalog(platform, headers[platform]);
        report.sources[platform] = articles.length;
        if (platform === 'ozon') {
          // Dependent sheets look up their product fields from ТЕСТ. Refresh
          // that source first, including blanks left by interrupted earlier runs.
          try {
            const { enrichTestCatalog } = require('./catalog_test_enrichment_local');
            report.sheets['ТЕСТ'] = await enrichTestCatalog(sheets, articles, {
              dryRun: process.argv.includes('--dry-run'), appendMissing: true,
            });
          } catch (error) { report.errors.push(`ТЕСТ: ${error.message}`); }
        }
        for (const definition of TARGETS[platform]) {
          try { report.sheets[definition[0]] = await updateTarget(sheets, definition, articles, process.argv.includes('--dry-run')); }
          catch (error) { report.errors.push(`${definition[0]}: ${error.message}`); }
        }
        if(platform==='ozon'){
          try {
            report.oborFormulas=await require('./obor_formulas_local').prepareOborFormulas(sheets,articles,{dryRun:process.argv.includes('--dry-run')});
          } catch(error){report.errors.push(`ОБОР formulas: ${error.message}`);}
        }
        if (platform === 'wb') {
          try {
            report.wbArticleIds = await require('./wb_article_ids_local').prepareWbArticleIds(sheets, {
              dryRun: process.argv.includes('--dry-run'),
            });
          } catch (error) { report.errors.push(`ТЕСТ WB nmID: ${error.message}`); }
        }
      } catch (error) { report.errors.push(`${platform}: ${error.message}`); }
    }
    report.finishedAt = new Date().toISOString();
    atomicJson(path.join(LOGS, 'catalog-articles-last.json'), report);
    if (report.errors.length) throw new Error(report.errors.join('; '));
    log(`Готово: ${JSON.stringify(report.sheets)}`);
    return report;
  } finally {
    fs.rmSync(LOCK, { force: true });
  }
}

if (require.main === module) main().catch(async error => {
  console.error(`Каталог артикулов: ${error.message}`);
  await sendTelegramAlert('Каталог артикулов Ozon/WB', error.message);
  process.exitCode = 1;
});
module.exports = { TARGETS, planAppend, parsePage, updateTarget, fetchCatalog, main };
