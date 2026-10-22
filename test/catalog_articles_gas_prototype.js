/**
 * Append exact seller articles only. Existing rows and columns B onward are untouched.
 * Дизайн контент!A has an intentionally empty header (verified 2026-10-15).
 * A five-minute dispatcher resumes scans; completed scans wait 50 minutes.
 */
const CATALOG_ARTICLES_BOOK = '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
const CATALOG_ARTICLES_TARGETS = {
  ozon: [['ТЗ', 'Артикул'], ['ОБОР', 'Артикул'], ['Дизайн контент', null], ['StreamSupps', 'Артикул продавца']],
  wb: [['UNIT WB', 'Артикул']]
};

function installCatalogArticlesTrigger() {
  return runWithTelegramAlertGAS_('installCatalogArticlesTrigger', function() {
    // Create before removing duplicates so a trigger-quota failure preserves the old schedule.
    const old = ScriptApp.getProjectTriggers().filter(t => t.getHandlerFunction() === 'syncCatalogArticles');
    if (!old.length) ScriptApp.newTrigger('syncCatalogArticles').timeBased().everyMinutes(5).create();
    old.slice(1).forEach(t => ScriptApp.deleteTrigger(t));
    Logger.log('Каталог: установлен один диспетчер syncCatalogArticles, каждые 5 минут; полный цикл примерно раз в час.');
    return syncCatalogArticlesCore_();
  });
}

function syncCatalogArticles() {
  return runWithTelegramAlertGAS_('syncCatalogArticles', syncCatalogArticlesCore_);
}

function resumeCatalogArticles() {
  return runWithTelegramAlertGAS_('resumeCatalogArticles', syncCatalogArticlesCore_);
}

function syncCatalogArticlesCore_() {
  const lock = LockService.getDocumentLock();
  if (!lock.tryLock(1000)) { Logger.log('Каталог: обновление артикулов уже выполняется; повтор через 5 минут.'); return; }
  const props = PropertiesService.getScriptProperties();
  const started = Date.now();
  const errors = [];
  let pending = false;
  try {
    ScriptApp.getProjectTriggers().filter(t => t.getHandlerFunction() === 'resumeCatalogArticles')
      .forEach(t => ScriptApp.deleteTrigger(t));
    let book;
    ['ozon', 'wb'].forEach(platform => {
      try {
        const key = 'CATALOG_ARTICLES_' + platform;
        const raw = props.getProperty(key);
        let state = raw ? JSON.parse(raw) : { cursor: null, nextScan: 0, pages: 0, added: {} };
        if (state.nextScan > Date.now()) { if (state.retrying) pending = true; return; }
        if (Date.now() - started > 180000) { pending = true; return; }
        if (!book) book = catalogArticlesBook_();
        const targets = CATALOG_ARTICLES_TARGETS[platform].map(def => catalogArticlesTarget_(book, def));
        const seen = new Set([JSON.stringify(state.cursor)]);
        const articles = new Set();
        let cursor = state.cursor, complete = false, pages = 0, retryMs = 0;
        const fetchDeadline = Math.min(started + 150000, Date.now() + (platform === 'wb' ? 150000 : 80000));
        while (Date.now() < fetchDeadline) {
          const page = catalogArticlesPage_(platform, cursor);
          if (page.retryMs) { retryMs = page.retryMs; break; }
          const cursorKey = JSON.stringify(page.cursor);
          if (!page.complete && seen.has(cursorKey)) throw new Error(platform + ': повтор курсора API');
          page.articles.forEach(article => articles.add(article));
          pages++;
          cursor = page.cursor;
          complete = page.complete;
          seen.add(cursorKey);
          if (complete) break;
          Utilities.sleep(platform === 'wb' ? 650 : 100);
        }
        Logger.log('Каталог ' + platform + ': получено страниц=' + pages + ', артикулов=' + articles.size);
        targets.forEach(target => {
          const added = appendCatalogArticles_(target, Array.from(articles));
          state.added[target.sheet.getName()] = (state.added[target.sheet.getName()] || 0) + added;
        });
        // Advance only after all destinations acknowledge the entire buffered batch.
        // A partially written batch is replayed and deduplicated against fresh A values.
        state.cursor = cursor;
        state.pages += pages;
        state.retrying = !!retryMs;
        state.nextScan = retryMs ? Date.now() + retryMs : complete ? Date.now() + 50 * 60000 : 0;
        props.setProperty(key, JSON.stringify(state));
        if (complete) {
          Logger.log('Каталог ' + platform + ': проход завершён, страниц=' + state.pages + ', добавлено=' + JSON.stringify(state.added));
          props.setProperty('CATALOG_ARTICLES_LAST_' + platform, JSON.stringify({ at: new Date().toISOString(), pages: state.pages, added: state.added }));
          props.setProperty(key, JSON.stringify({ cursor: null, nextScan: state.nextScan, pages: 0, added: {} }));
        } else pending = true;
      } catch (err) {
        errors.push(platform + ': ' + err.message);
      }
    });
    if (pending) {
      try {
        ScriptApp.newTrigger('resumeCatalogArticles').timeBased().after(60000).create();
      } catch (err) {
        if (!/too many triggers|слишком много триггер|maximum number of triggers/i.test(String(err))) throw err;
        Logger.log('Каталог: лимит триггеров; прогресс подхватит диспетчер через 5 минут.');
      }
    }
    if (errors.length) throw new Error(errors.join('; '));
  } finally {
    lock.releaseLock();
  }
}

/** Sheets REST calls avoid SpreadsheetApp waiting for workbook-wide recalculation. */
function catalogArticlesGoogle_(path, payload) {
  // The Sheets service supplies Apps Script authorization without distributing credentials.
  // Sheets API is enabled in Cloud project 175784251448.
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      if (path === ':batchUpdate') return Sheets.Spreadsheets.batchUpdate(payload, CATALOG_ARTICLES_BOOK);
      if (path === '/values:batchUpdate') return Sheets.Spreadsheets.Values.batchUpdate(payload, CATALOG_ARTICLES_BOOK);
      if (path.indexOf('/values:batchGet?') === 0) {
        const options = { ranges: [] };
        path.split('?')[1].split('&').forEach(part => {
          const pieces = part.split('=');
          if (pieces[0] === 'ranges') options.ranges.push(decodeURIComponent(pieces[1]));
          else options[pieces[0]] = decodeURIComponent(pieces[1]);
        });
        return Sheets.Spreadsheets.Values.batchGet(CATALOG_ARTICLES_BOOK, options);
      }
      return Sheets.Spreadsheets.get(CATALOG_ARTICLES_BOOK, { fields: 'sheets(properties(sheetId,title,gridProperties))' });
    } catch (err) {
      if (attempt === 2 || !/429|500|502|503|quota|rate limit|internal error|service unavailable/i.test(String(err))) throw err;
      Utilities.sleep((attempt + 1) * 10000);
    }
  }
}

function catalogArticlesBook_() {
  const definitions = CATALOG_ARTICLES_TARGETS.ozon.concat(CATALOG_ARTICLES_TARGETS.wb);
  const ranges = definitions.map(d => "'" + d[0].replace(/'/g, "''") + "'");
  const query = ranges.map(r => 'ranges=' + encodeURIComponent(r + '!A:A')).join('&');
  const headers = ranges.map(r => 'ranges=' + encodeURIComponent(r + '!1:1')).join('&');
  return {
    metadata: catalogArticlesGoogle_('?fields=sheets(properties(sheetId,title,gridProperties))').sheets,
    values: catalogArticlesGoogle_('/values:batchGet?valueRenderOption=UNFORMATTED_VALUE&' + query).valueRanges,
    formulas: catalogArticlesGoogle_('/values:batchGet?valueRenderOption=FORMULA&' + query).valueRanges,
    headers: catalogArticlesGoogle_('/values:batchGet?valueRenderOption=FORMATTED_VALUE&' + headers).valueRanges
  };
}

function catalogArticlesTarget_(book, definition) {
  const definitions = CATALOG_ARTICLES_TARGETS.ozon.concat(CATALOG_ARTICLES_TARGETS.wb);
  const index = definitions.findIndex(d => d[0] === definition[0]);
  const metadata = book.metadata.find(s => s.properties.title === definition[0]);
  if (!metadata) throw new Error('Нет листа ' + definition[0]);
  const headers = (book.headers[index].values || [[]])[0];
  if (definition[1] === null) {
    if (String(headers[0] || '').trim() !== '') throw new Error(definition[0] + ': изменился пустой заголовок A');
  } else {
    const normalize = v => String(v || '').trim().toLowerCase().replace(/ё/g, 'е').replace(/\s+/g, ' ');
    const matches = headers.reduce((a, v, i) => normalize(v) === normalize(definition[1]) ? a.concat(i) : a, []);
    if (matches.length !== 1 || matches[0] !== 0) throw new Error(definition[0] + ': заголовок артикула должен однозначно указывать на A');
  }
  const values = book.values[index].values || [];
  const formulas = book.formulas[index].values || [];
  let last = 1;
  const existing = new Set();
  for (let i = 1; i < Math.max(values.length, formulas.length); i++) {
    const value = values[i] && values[i][0];
    const article = String(value == null ? '' : value).trim();
    if (article) existing.add(article);
    if (article || (formulas[i] && formulas[i][0])) last = i + 1;
  }
  return { sheet: { getName: () => definition[0] }, sheetId: metadata.properties.sheetId,
    capacity: metadata.properties.gridProperties.rowCount, existing: existing, last: last };
}

function appendCatalogArticles_(target, articles) {
  const missing = [];
  const seen = new Set(target.existing);
  articles.forEach(article => {
    if (!seen.has(article)) { missing.push(article); seen.add(article); }
  });
  if (!missing.length) return 0;
  const end = target.last + missing.length;
  const requests = [];
  if (end > target.capacity) requests.push({ appendDimension: { sheetId: target.sheetId, dimension: 'ROWS', length: end - target.capacity } });
  // Explicit stringValue preserves zeros and '=' literally. The grid extension
  // and A values are committed atomically, without a separate formatting write.
  requests.push({ updateCells: { range: { sheetId: target.sheetId, startRowIndex: target.last,
    endRowIndex: end, startColumnIndex: 0, endColumnIndex: 1 },
    rows: missing.map(article => ({ values: [{ userEnteredValue: { stringValue: article } }] })), fields: 'userEnteredValue' } });
  catalogArticlesGoogle_(':batchUpdate', { requests: requests });
  target.capacity = Math.max(target.capacity, end);
  const range = target.sheet.getName() + '!A' + (target.last + 1) + ':A' + end;
  target.last = end;
  target.existing = seen;
  Logger.log('Каталог: ' + target.sheet.getName() + ' +' + missing.length + ', ' + range);
  return missing.length;
}

function catalogArticlesPage_(platform, cursor) {
  const wb = platform === 'wb';
  const limit = wb ? 100 : 1000;
  const url = wb ? 'https://content-api.wildberries.ru/content/v2/get/cards/list' : ozonProductsApiURL();
  const payload = wb
    ? { settings: { sort: { ascending: true }, cursor: Object.assign({ limit: limit }, cursor || {}), filter: { withPhoto: -1 } } }
    : { filter: { visibility: 'ALL' }, limit: limit, last_id: cursor || '' };
  const response = retryFetch(url, {
    method: 'post', contentType: 'application/json', headers: wb ? wbHeaders() : ozonHeaders(),
    payload: JSON.stringify(payload), muteHttpExceptions: true
  }, 1);
  if (!response || response.getResponseCode() === 429 || response.getResponseCode() >= 500) {
    return { retryMs: Math.max(60000, response ? (retryAfterDelayMs_(response) || 60000) : 60000) };
  }
  if (response.getResponseCode() !== 200) throw new Error(platform + ': HTTP ' + response.getResponseCode());
  const body = JSON.parse(response.getContentText());
  const items = wb ? body.cards : body.result && body.result.items;
  if (!Array.isArray(items)) throw new Error(platform + ': некорректный ответ каталога');
  const articles = items.map(item => {
    const value = wb ? item.vendorCode : item.offer_id;
    if (typeof value !== 'string' || !value.trim()) throw new Error(platform + ': пустой артикул в API');
    return value.trim();
  });
  const complete = items.length < limit;
  const next = wb ? body.cursor && { updatedAt: body.cursor.updatedAt, nmID: body.cursor.nmID } : body.result.last_id;
  if (!complete && (wb ? !next || !next.updatedAt || !next.nmID : !next)) throw new Error(platform + ': нет курсора следующей страницы');
  return { articles: articles, complete: complete, cursor: complete ? null : next };
}
