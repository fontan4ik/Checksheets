/** Full WB Content catalog, staged across bounded trigger executions.
 * A:C is a fixed service layout used by existing StreamSupps lookup formulas.
 * Publish only after the API cursor explicitly confirms the end of the catalog.
 */
const WB_TECH_DATA_SHEET_NAME = 'ТЕХ данные wb';
const WB_TECH_CATALOG_STATE_ = 'wb_tech_catalog_v2';
const WB_TECH_CATALOG_STAGE_ = '_WB_TECH_CATALOG_STAGE';
const WB_TECH_STAGE_SPREADSHEET_ID_ = 'wb_tech_stage_spreadsheet_id';
const WB_TECH_CATALOG_HEADERS_ = ['Артикул продавца', 'Код размера (chrt_id)', 'Артикул WB'];

function updateWBTechDataSheet() {
  return runWithTelegramAlertGAS_('updateWBTechDataSheet', function() { return wbTechDataCatalogSlice_(); });
}

function continueWBTechDataSheet() {
  return runWithTelegramAlertGAS_('continueWBTechDataSheet', function() {
    if (!wbTechDataCatalogPending_()) {
      wbTechDataCatalogClearTriggers_();
      return { complete: true };
    }
    return wbTechDataCatalogSlice_();
  });
}

function wbTechDataCatalogPending_() {
  return !!PropertiesService.getScriptProperties().getProperty(WB_TECH_CATALOG_STATE_);
}

function wbTechDataCatalogClearTriggers_() {
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (trigger.getHandlerFunction() === 'continueWBTechDataSheet') ScriptApp.deleteTrigger(trigger);
  });
}

function wbTechDataCatalogSchedule_() {
  wbTechDataCatalogClearTriggers_();
  ScriptApp.newTrigger('continueWBTechDataSheet').timeBased().after(180000).create();
}

function wbTechDataCatalogSave_(props, state) {
  props.setProperty(WB_TECH_CATALOG_STATE_, JSON.stringify(state));
}

/** Private staging book isolates API page writes from StreamSupps recalculation. */
function wbTechDataCatalogCreateStage_() {
  const props = PropertiesService.getScriptProperties();
  const id = props.getProperty(WB_TECH_STAGE_SPREADSHEET_ID_);
  const book = id ? SpreadsheetApp.openById(id) : SpreadsheetApp.create('Checksheets WB catalog staging');
  const sheet = book.getSheetByName(WB_TECH_CATALOG_STAGE_) || book.getSheets()[0];
  sheet.setName(WB_TECH_CATALOG_STAGE_);
  if (sheet.getMaxColumns() > 3) sheet.deleteColumns(4, sheet.getMaxColumns() - 3);
  sheet.clearContents();
  // Keep the only sheet visible. This private book is reused across full scans.
  SpreadsheetApp.flush();
  if (!id) props.setProperty(WB_TECH_STAGE_SPREADSHEET_ID_, book.getId());
  return { book: book, sheet: sheet };
}

function wbTechDataCatalogSlice_(scheduleContinuation) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return { complete: false, busy: true };
  const started = Date.now();
  const props = PropertiesService.getScriptProperties();
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    let state = JSON.parse(props.getProperty(WB_TECH_CATALOG_STATE_) || 'null');
    let stage;
    if (!state || started - state.startedAt > 12 * 60 * 60 * 1000) {
      state = { startedAt: started, cursor: null, rows: 0, cards: 0, pages: 0, retries: 0, ready: false };
      const staging = wbTechDataCatalogCreateStage_();
      state.stageSpreadsheetId = staging.book.getId();
      stage = staging.sheet;
      wbTechDataCatalogSave_(props, state);
    } else if (!state.stageSpreadsheetId) {
      // Migrate an existing local checkpoint without touching either live lookup
      // data or the original staging backup. The saved cursor remains unchanged.
      const previousStage = ss.getSheetByName(WB_TECH_CATALOG_STAGE_);
      if (!previousStage && state.rows) throw new Error('WB catalog staging sheet missing; published data preserved');
      const staging = wbTechDataCatalogCreateStage_();
      stage = staging.sheet;
      if (state.rows) {
        wbTechDataCatalogEnsureRows_(stage, state.rows, 10000);
        stage.getRange(1, 1, state.rows, 3).setNumberFormat('@')
          .setValues(previousStage.getRange(1, 1, state.rows, 3).getValues());
        SpreadsheetApp.flush();
      }
      state.stageSpreadsheetId = staging.book.getId();
      wbTechDataCatalogSave_(props, state);
    } else {
      stage = SpreadsheetApp.openById(state.stageSpreadsheetId).getSheetByName(WB_TECH_CATALOG_STAGE_);
    }
    if (!stage) throw new Error('WB catalog staging sheet missing; published data preserved');
    let bufferedRows = [];
    let bufferedPages = 0;
    function flushPages() {
      if (!bufferedPages) return;
      if (bufferedRows.length) {
        wbTechDataCatalogEnsureRows_(stage, state.rows, 10000);
        stage.getRange(state.rows - bufferedRows.length + 1, 1, bufferedRows.length, 3)
          .setNumberFormat('@').setValues(bufferedRows);
        // Commit sheet writes before advancing the durable cursor. If this fails,
        // the next execution replays this batch over the same staging range.
        SpreadsheetApp.flush();
      }
      wbTechDataCatalogSave_(props, state);
      bufferedRows = [];
      bufferedPages = 0;
    }
    // Watchdog is installed before requests, so a hard runtime stop can resume.
    if (scheduleContinuation !== false) wbTechDataCatalogSchedule_();
    while (!state.ready && Date.now() - started < 140000) {
      if (state.pages >= 10000) throw new Error('WB catalog exceeded 10000 pages; published data preserved');
      // WB Content API has a stricter 600ms interval than the generic WB 2 RPS.
      Utilities.sleep(600);
      let response;
      try {
        response = UrlFetchApp.fetch('https://content-api.wildberries.ru/content/v2/get/cards/list', {
          method: 'post', contentType: 'application/json', headers: wbHeaders(),
          payload: JSON.stringify({ settings: {
            sort: { ascending: true }, filter: { withPhoto: -1 },
            cursor: Object.assign({ limit: 100 }, state.cursor || {})
          }}), muteHttpExceptions: true
        });
      } catch (error) {
        flushPages();
        return wbTechDataCatalogRetry_(props, state, 'network: ' + error.message);
      }
      const status = response.getResponseCode();
      if (status === 429 || status >= 500) {
        flushPages();
        return wbTechDataCatalogRetry_(props, state, 'HTTP ' + status);
      }
      if (status !== 200) throw new Error('WB catalog HTTP ' + status + '; published data preserved');
      let data;
      try { data = JSON.parse(response.getContentText()); }
      catch (error) { throw new Error('WB catalog invalid JSON; published data preserved'); }
      const page = wbTechDataCatalogPage_(data, state.cursor);
      const rows = wbTechDataCatalogRows_(page.cards);
      bufferedRows = bufferedRows.concat(rows);
      bufferedPages++;
      // This is the in-memory cursor; flushPages persists it only after the rows.
      state.rows += rows.length;
      state.cards += page.cards.length;
      state.pages++;
      state.cursor = page.cursor;
      state.ready = page.complete;
      state.retries = 0;
      if (bufferedRows.length >= 1000 || bufferedPages >= 10 || state.ready) flushPages();
    }
    flushPages();
    if (!state.ready) return { complete: false, cards: state.cards, pages: state.pages, stageSpreadsheetId: state.stageSpreadsheetId };
    if (!state.rows) throw new Error('WB catalog is empty; published data preserved');
    const rows = wbTechDataCatalogDedupe_(stage.getRange(1, 1, state.rows, 3).getValues());
    const sheet = ss.getSheetByName(WB_TECH_DATA_SHEET_NAME) || ss.insertSheet(WB_TECH_DATA_SHEET_NAME);
    const published = prepareWBTechDataSheet_(sheet, rows);
    if (published) SpreadsheetApp.flush();
    props.setProperty('wb_tech_catalog_last_success', JSON.stringify({ at: Date.now(), cards: state.cards, rows: rows.length, pages: state.pages }));
    props.deleteProperty(WB_TECH_CATALOG_STATE_);
    wbTechDataCatalogClearTriggers_();
    Logger.log('WB catalog complete: ' + state.cards + ' cards, ' + rows.length + ' rows; StreamSupps formulas can recalculate');
    return { complete: true, cards: state.cards, rows: rows.length };
  } catch (error) {
    // A terminal failure must alert once and retain the last checkpoint for repair.
    wbTechDataCatalogClearTriggers_();
    throw error;
  } finally {
    lock.releaseLock();
  }
}

function wbTechDataCatalogRetry_(props, state, reason) {
  state.retries++;
  wbTechDataCatalogSave_(props, state);
  if (state.retries >= 5) throw new Error('WB catalog failed 5 consecutive attempts: ' + reason);
  Logger.log('WB catalog transient ' + reason + '; continuation scheduled, published data preserved');
  return { complete: false, retry: true, reason: reason, stageSpreadsheetId: state.stageSpreadsheetId };
}

function wbTechDataCatalogPage_(data, previousCursor) {
  if (!data || data.error || !Array.isArray(data.cards) || !data.cursor ||
      typeof data.cursor.total !== 'number' || !Number.isInteger(data.cursor.total) || data.cursor.total < 0) {
    throw new Error('WB catalog malformed cards/cursor response; published data preserved');
  }
  const total = data.cursor.total;
  if (data.cards.length > 100 || (!data.cards.length && total !== 0) ||
      (data.cards.length < 100 && total >= 100)) {
    throw new Error('WB catalog inconsistent page size; published data preserved');
  }
  const complete = total < 100;
  let cursor = null;
  if (!complete) {
    const nmID = data.cursor.nmID || data.cursor.nmId;
    if (!data.cursor.updatedAt || !nmID || !Number.isFinite(Number(nmID)) || Number(nmID) <= 0) {
      throw new Error('WB catalog missing pagination cursor; published data preserved');
    }
    cursor = { updatedAt: data.cursor.updatedAt, nmID: nmID };
    if (previousCursor && String(previousCursor.updatedAt) === String(cursor.updatedAt) &&
        String(previousCursor.nmID) === String(cursor.nmID)) {
      throw new Error('WB catalog repeated pagination cursor; published data preserved');
    }
  }
  return { cards: data.cards, cursor: cursor, complete: complete };
}

function wbTechDataCatalogRows_(cards) {
  const rows = [];
  cards.forEach(function(card) {
    const vendor = String(card.vendorCode || '').trim();
    const nm = card.nmID || card.nmId;
    // Error drafts have no assigned marketplace IDs and cannot fill a chrtID lookup.
    if (!vendor || !Number.isFinite(Number(nm)) || Number(nm) <= 0) return;
    const sizes = Array.isArray(card.sizes) && card.sizes.length ? card.sizes : [{}];
    sizes.forEach(function(size) {
      const id = size.chrtID || size.chrtId;
      rows.push([vendor, Number(id) > 0 ? String(id) : '', String(nm)]);
    });
  });
  return rows;
}

function wbTechDataCatalogDedupe_(rows) {
  const seen = new Set();
  return rows.filter(function(row) {
    const key = JSON.stringify(row);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function wbTechDataCatalogEnsureRows_(sheet, count, growthBlock) {
  const current = sheet.getMaxRows();
  if (current < count) {
    // Structural changes recalculate this large workbook: amortize staging growth.
    // Keep the live table's final allocation exact (no growthBlock argument).
    const target = growthBlock ? Math.ceil(count / growthBlock) * growthBlock : count;
    sheet.insertRowsAfter(current, target - current);
  }
}

function prepareWBTechDataSheet_(sheet, rows) {
  const values = [WB_TECH_CATALOG_HEADERS_].concat(rows);
  // A single write replaces the complete table and removes an obsolete tail.
  // No clearContents() on the live lookup table before a successful full scan.
  const length = Math.max(values.length, sheet.getLastRow());
  while (values.length < length) values.push(['', '', '']);
  const existingRows = sheet.getLastRow();
  const existing = existingRows ? sheet.getRange(1, 1, existingRows, 3).getValues() : [];
  const equal = values.every(function(row, index) {
    return row.every(function(value, column) {
      const current = existing[index] ? existing[index][column] : '';
      return String(current === null || current === undefined ? '' : current) ===
        String(value === null || value === undefined ? '' : value);
    });
  });
  // A previous native write can become durable before its execution times out.
  // Recognize it without writing/recalculating the same large lookup table again.
  if (equal) return false;
  wbTechDataCatalogEnsureRows_(sheet, length);
  sheet.getRange(1, 1, length, 3).setNumberFormat('@').setValues(values);
  sheet.setFrozenRows(1);
  return true;
}
