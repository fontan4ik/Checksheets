/** Один постоянный триггер: полный каталог Ozon → карточки → полный каталог WB.
 * Служебный лист _CATALOG_STATUS имеет фиксированный layout A:B (ключ/значение).
 * Формулы StreamSupps продолжают читать ТЕСТ и ТЕХ данные wb без изменений.
 */
const MARKETPLACE_CATALOG_STATE_KEY = 'MARKETPLACE_CATALOG_CYCLE_V1';
const MARKETPLACE_CATALOG_HANDLER = 'refreshMarketplaceCatalogs';

function installMarketplaceCatalogTriggersAndRefresh() {
  return runWithTelegramAlertGAS_('installMarketplaceCatalogTriggersAndRefresh', function() {
    const owned = ScriptApp.getProjectTriggers();
    const current = owned.filter(t => t.getHandlerFunction() === MARKETPLACE_CATALOG_HANDLER);
    // These two owned triggers are replaced by the ordered pipeline. Foreign
    // triggers are not returned by getProjectTriggers and remain untouched.
    owned.filter(t => ['updateProductsV2', 'syncOfferIdWithProductId'].includes(t.getHandlerFunction()))
      .forEach(t => ScriptApp.deleteTrigger(t));
    current.slice(1).forEach(t => ScriptApp.deleteTrigger(t));
    if (!current.length) ScriptApp.newTrigger(MARKETPLACE_CATALOG_HANDLER).timeBased().everyMinutes(5).create();
    const props = PropertiesService.getScriptProperties();
    if (!props.getProperty(MARKETPLACE_CATALOG_STATE_KEY)) {
      props.setProperty(MARKETPLACE_CATALOG_STATE_KEY, JSON.stringify({ phase: 'catalog', started: new Date().toISOString() }));
    }
    return refreshMarketplaceCatalogsCore_();
  });
}

function refreshMarketplaceCatalogs() {
  return runWithTelegramAlertGAS_('refreshMarketplaceCatalogs', refreshMarketplaceCatalogsCore_);
}

function refreshMarketplaceCatalogsCore_() {
  const props = PropertiesService.getScriptProperties();
  const gate = LockService.getScriptLock();
  if (!gate.tryLock(1000)) return { busy: true };
  let state;
  const lease = String(Date.now()) + ':' + String(Math.random());
  try {
    const raw = props.getProperty(MARKETPLACE_CATALOG_STATE_KEY);
    state = raw ? JSON.parse(raw) : { phase: 'catalog', started: new Date().toISOString() };
    if (Number(state.leaseUntil) > Date.now()) return { busy: true };
    if (state.phase === 'idle') {
      if (Date.now() < Number(state.nextRun)) return state;
      state.phase = 'catalog';
      state.started = new Date().toISOString();
    }
    // A crashed execution expires after the GAS six-minute hard limit.
    state.lease = lease;
    state.leaseUntil = Date.now() + 7 * 60 * 1000;
    props.setProperty(MARKETPLACE_CATALOG_STATE_KEY, JSON.stringify(state));
  } finally { gate.releaseLock(); }
  const phase = state.phase;
  let result;
  try {
    if (phase === 'wb') {
      // WB owns the same script lock internally and stages pages on its sheet.
      result = wbTechDataCatalogSlice_(false);
    } else {
      result = runWithOzonProductSyncLock_(MARKETPLACE_CATALOG_HANDLER, function() {
        return phase === 'catalog' ? syncOfferIdWithProductIdCore_() : updateProductsV2Core_();
      });
    }
    if (result && result.complete) {
      state.phase = phase === 'catalog' ? 'details' : phase === 'details' ? 'wb' : 'idle';
      if (state.phase === 'idle') {
        state.completed = new Date().toISOString();
        // Full catalogs twice a day; five-minute ticks only resume the scan.
        // Hourly full scans would consume the user's shared trigger runtime quota.
        state.nextRun = Date.now() + 12 * 60 * 60 * 1000;
        SpreadsheetApp.flush();
      }
    }
    state.updated = new Date().toISOString();
    state.lastResult = result || { busy: true };
    delete state.error;
    props.setProperty(MARKETPLACE_CATALOG_STATE_KEY, JSON.stringify(state));
    try { writeMarketplaceCatalogStatus_(state); }
    catch (statusError) { Logger.log('Catalog status write delayed: ' + statusError); }
    Logger.log('Catalog pipeline: ' + JSON.stringify(state));
    return state;
  } catch (error) {
    state.error = String(error.message || error);
    state.updated = new Date().toISOString();
    props.setProperty(MARKETPLACE_CATALOG_STATE_KEY, JSON.stringify(state));
    try { writeMarketplaceCatalogStatus_(state); }
    catch (statusError) { Logger.log('Catalog status write delayed: ' + statusError); }
    throw error;
  } finally {
    const latest = JSON.parse(props.getProperty(MARKETPLACE_CATALOG_STATE_KEY) || '{}');
    if (latest.lease === lease) {
      delete latest.lease;
      delete latest.leaseUntil;
      props.setProperty(MARKETPLACE_CATALOG_STATE_KEY, JSON.stringify(latest));
    }
  }
}

function writeMarketplaceCatalogStatus_(state) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName('_CATALOG_STATUS');
  if (!sheet) {
    try { sheet = ss.insertSheet('_CATALOG_STATUS'); }
    catch (error) {
      sheet = SpreadsheetApp.openById(ss.getId()).getSheetByName('_CATALOG_STATUS');
      if (!sheet) throw error;
    }
  }
  const triggers = ScriptApp.getProjectTriggers().map(t => ({ handler: t.getHandlerFunction(), id: t.getUniqueId() }));
  const rows = [
    ['Поле', 'Значение'], ['phase', state.phase], ['started', state.started || ''],
    ['updated', state.updated || ''], ['completed', state.completed || ''],
    ['nextRun', state.nextRun ? new Date(state.nextRun).toISOString() : ''],
    ['lastResult', JSON.stringify(state.lastResult || {})], ['error', state.error || ''],
    ['ownedTriggers', JSON.stringify(triggers)],
    ['wbSuccess', PropertiesService.getScriptProperties().getProperty('wb_tech_catalog_last_success') || '']
  ];
  sheet.getRange(1, 1, rows.length, 2).setValues(rows);
  if (!sheet.isSheetHidden()) sheet.hideSheet();
}
