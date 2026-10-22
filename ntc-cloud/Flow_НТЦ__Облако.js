/** Independent, bound NTC workbook; never starts a local process. */
const NTC_BOOK_ID = '1i35SfWZljNR63GEkPuwgU2zVSU_Y2CWoxcRK-LcpjUo';
const NTC_OWNER = 'vladimir.romanovich.grebennikov@gmail.com';
const NTC_CATALOG = 'НТЦ списания';
const NTC_OPERATOR = 'Склад НТЦ';
const NTC_STATE = '_НТЦ облако журнал';
function ntcBook_() { return SpreadsheetApp.openById(NTC_BOOK_ID); }
function ntcColumn_(headers, name) {
  const matches = []; headers.forEach(function(h, i) { if (String(h).trim() === name) matches.push(i); });
  if (matches.length !== 1) throw new Error('НТЦ: заголовок «' + name + '» отсутствует или повторяется');
  return matches[0];
}
function ntcConfig_() {
  const p = PropertiesService.getScriptProperties();
  return {spreadsheetId: NTC_BOOK_ID, sourceSpreadsheetId: '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI',
    ozonClientId: p.getProperty('OZON_CLIENT_ID'), ozonApiKey: p.getProperty('OZON_API_KEY'), wbToken: p.getProperty('WB_TOKEN'),
    ozonWarehouseId: p.getProperty('OZON_NTC_WAREHOUSE'), wbWarehouseId: p.getProperty('WB_NTC_WAREHOUSE'),
    ozonEnabled: p.getProperty('NTC_OZON_ENABLED') === 'true', wbEnabled: p.getProperty('NTC_WB_ENABLED') === 'true',
    start: p.getProperty('NTC_START'), cursor: p.getProperty('NTC_CURSOR'), snapshotTimestamp: new Date().toISOString(), deadline: Date.now() + 270000};
}
function onOpen() {
  SpreadsheetApp.getUi().createMenu('Склад НТЦ').addItem('Открыть сканер и кнопки', 'ntcOpenScanner')
    .addItem('Поставить на остаток (колонка C)', 'ntcSupply').addItem('Списать (колонка D)', 'ntcWriteOff')
    .addSeparator().addItem('Обновить заказы и остатки МП', 'ntcCloudTick').addItem('Обновить карточки товаров', 'ntcRefreshCatalog').addItem('Запустить трансляцию МП','ntcStartTransmission').addItem('Остановить трансляцию МП','ntcStopTransmission')
    .addItem('Диагностика', 'ntcDiagnostics').addSeparator().addItem('Установка / проверка системы', 'ntcInstall').addItem('Запустить облачную работу', 'ntcEnableCloud').addToUi();
}
function ntcOpenScanner() {
  ntcBook_().setActiveSheet(ntcBook_().getSheetByName(NTC_OPERATOR));
  SpreadsheetApp.getUi().showSidebar(HtmlService.createHtmlOutputFromFile('Scanner').setTitle('Склад НТЦ · сканер'));
}
function ntcLocked_(label, action) {
  return runWithTelegramAlertGAS_(label, function() {
    const lock = LockService.getScriptLock(); if (!lock.tryLock(5000)) throw new Error('НТЦ: обработка уже идёт, повторите через несколько секунд');
    try { return action(); } finally { lock.releaseLock(); }
  });
}
function ntcBackgroundLocked_(label, action) {
  const lock=LockService.getScriptLock();
  if (!lock.tryLock(1000)) { Logger.log(JSON.stringify({event:'background_overlap_skipped',handler:label})); return {ok:true,skipped:true,message:'Другой облачный обработчик выполняется; продолжим по расписанию'}; }
  try { return runWithTelegramAlertGAS_(label,action); } finally { lock.releaseLock(); }
}
function runWithTelegramAlertGAS_(label, action) {
  try { return action(); } catch (error) {
    const p = PropertiesService.getScriptProperties(), token = p.getProperty('TELEGRAM_TOKEN'), chat = p.getProperty('TELEGRAM_CHAT');
    // Expected overlap/deadline continuations are retried without notification storms.
    if (!/обработка уже идёт|лимит времени/.test(String(error.message)) && token && chat) {
      try { UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/sendMessage', {method: 'post', contentType: 'application/json',
        payload: JSON.stringify({chat_id: chat, text: 'НТЦ · ' + label + '\n' + String(error.message).slice(0, 1500)}), muteHttpExceptions: true}); } catch (_) {}
    }
    throw error;
  }
}
function ntcServiceSheet_(name, headers) {
  const book = ntcBook_(); let sheet = book.getSheetByName(name);
  if (!sheet) { sheet = book.insertSheet(name); sheet.getRange(1, 1, 1, headers.length).setValues([headers]); sheet.hideSheet(); }
  return sheet;
}
function ntcReadState_() {
  const sheet = ntcBook_().getSheetByName(NTC_STATE); if (!sheet || sheet.getLastRow() < 2) throw new Error('Сначала выполните ntcInstall()');
  return JSON.parse(sheet.getRange(2, 2, sheet.getLastRow() - 1, 1).getValues().map(function(r) { return r[0]; }).join(''));
}
function ntcReadCatalog_() {
  const sheet = ntcBook_().getSheetByName(NTC_CATALOG), values = sheet.getDataRange().getValues(), formulas = sheet.getDataRange().getFormulas(), h = values[0];
  const columns = {}; ['Артикул продавца', 'Артикул производителя', 'ФОТО', 'SKU OZON', 'SKU WB', 'Остаток склад по моделям',
    'Виртуальный остаток', 'Х', 'Округлённое+прогруз на мп', 'chrlid'].forEach(function(n) { columns[n] = ntcColumn_(h, n); });
  const rows = [], stock = {}, seen = {};
  values.slice(1).forEach(function(r, i) {
    const offer = String(r[columns['Артикул продавца']] || '').trim(); if (!offer) return;
    const model = String(r[columns['Артикул производителя']] || '').trim();
    const rawStock = r[columns['Остаток склад по моделям']], rawSize = r[columns['Х']];
    if (rawStock == null || typeof rawStock === 'boolean' || String(rawStock).trim() === '' || rawSize == null || typeof rawSize === 'boolean' || String(rawSize).trim() === '') throw new Error('НТЦ: пустые или некорректные данные остатка/кратности строки ' + (i + 2));
    const amount = Number(rawStock), size = Number(rawSize);
    if (!model || seen[offer] || !Number.isSafeInteger(amount) || amount < 0 || !Number.isSafeInteger(size) || size <= 0) throw new Error('НТЦ: неверные данные/кратность строки ' + (i + 2));
    if (Object.prototype.hasOwnProperty.call(stock, model) && stock[model] !== amount) throw new Error('НТЦ: разные физические остатки модели ' + model);
    const rawExtra = r[columns['Виртуальный остаток']], extra = rawExtra === '' || rawExtra == null ? 0 : Number(rawExtra);
    if (typeof rawExtra === 'boolean' || !Number.isSafeInteger(extra) || extra < 0 || !Number.isSafeInteger(amount + extra)) throw new Error('НТЦ: неверная добавка G строки ' + (i+2));
    seen[offer] = true; stock[model] = amount;
    rows.push({offer_id: offer, model: model, H: size, row: i + 2, photo: ntcCatalogPhotoUrl_((formulas[i + 1] || [])[columns['ФОТО']], r[columns['ФОТО']]),
      ozonSku: r[columns['SKU OZON']], wbSku: r[columns['SKU WB']], chrtId: r[columns['chrlid']], amount: r[columns['Округлённое+прогруз на мп']],
      publicationExtra: extra});
  });
  if (!rows.length) throw new Error('НТЦ: нет товаров');
  return {sheet: sheet, rows: rows, stock_by_model: stock, columns: columns};
}
function ntcPublicationAmounts_(catalog, physicalStock) {
  const result = ntcAllocate_(physicalStock,catalog.rows);
  catalog.rows.forEach(function(r) {
    if (!r.publicationExtra) return;
    const pool = Object.assign({},physicalStock); pool[r.model] += r.publicationExtra;
    result[r.offer_id] = ntcAllocate_(pool,catalog.rows)[r.offer_id];
  });
  return result;
}
function ntcCell_(sheet, row, col, value) {
  const entered = typeof value === 'number' ? {numberValue: value} : typeof value === 'boolean' ? {boolValue: value} : {stringValue: String(value)};
  return {updateCells: {start: {sheetId: sheet.getSheetId(), rowIndex: row - 1, columnIndex: col - 1}, rows: [{values: [{userEnteredValue: entered}]}], fields: 'userEnteredValue'}};
}
function ntcJournalRequests_(envelope) {
  const ledger = ntcServiceSheet_(NTC_STATE, ['Часть', 'JSON']);
  const serialized = JSON.stringify(envelope), chunks = []; for (let i = 0; i < serialized.length; i += 40000) chunks.push([String(i / 40000), serialized.slice(i, i + 40000)]);
  const requests = [], needed = chunks.length + 1;
  if (ledger.getMaxRows() < needed) requests.push({appendDimension: {sheetId: ledger.getSheetId(), dimension: 'ROWS', length: needed - ledger.getMaxRows()}});
  const stateRange = {sheetId: ledger.getSheetId(), startRowIndex: 1, endRowIndex: Math.max(needed, ledger.getLastRow()), startColumnIndex: 0, endColumnIndex: 2};
  requests.push({updateCells: {range: stateRange, rows: chunks.map(function(r) { return {values: r.map(function(v) { return {userEnteredValue: {stringValue: v}}; })}; }), fields: 'userEnteredValue'}});
  return requests;
}
function ntcCommitJournal_(envelope) {
  Sheets.Spreadsheets.batchUpdate({requests: ntcJournalRequests_(envelope)}, NTC_BOOK_ID);
  SpreadsheetApp.flush();
}
function ntcCatalogIdentity_(catalog) {
  return catalog.rows.map(function(r) { return {row: r.row, offer_id: r.offer_id, model: r.model, H: r.H,
    ozonSku: r.ozonSku, wbSku: r.wbSku, chrtId: r.chrtId, publicationExtra:r.publicationExtra}; });
}
/** One Sheets transaction commits inventory, input clear and crash recovery journal.
 * Script lock serializes scripts. Sheets has no compare-and-swap for human edits:
 * re-read the exact rows immediately before batchUpdate, and protect catalog F/H.
 * A pending absolute-stock publication is durable before the first remote call. */
function ntcCommit_(catalog, envelope, extras) {
  const book = ntcBook_();
  envelope.publish_pending = envelope.publish_pending || {since: new Date().toISOString(), alert_attempted: false};
  envelope.publish_pending.revision = envelope.revision || 0;
  const requests = [];
  const prior = book.getSheetByName(NTC_STATE) && book.getSheetByName(NTC_STATE).getLastRow() > 1 ? ntcReadState_() : {engine: {movements: {}}};
  let history = book.getSheetByName('История склада');
  if (!history) { history = book.insertSheet('История склада'); history.getRange('A1:F1').setValues([['ID','Время','Тип','Модель','Количество, шт','Комментарий']]); history.setFrozenRows(1); }
  const newMovements = Object.keys(envelope.engine.movements || {}).filter(function(id) { return !(prior.engine.movements || {})[id]; });
  if (newMovements.length) requests.push({appendCells: {sheetId: history.getSheetId(), rows: newMovements.map(function(id) { const m = envelope.engine.movements[id]; return {values: [m.id,m.timestamp,m.type === 'supply' ? 'Поставка' : 'Списание',m.model,m.applied_quantity === undefined ? m.quantity : m.applied_quantity,m.applied_quantity !== undefined && m.applied_quantity !== m.quantity ? m.comment + ' · Запрошено: ' + m.quantity + ', списано: ' + m.applied_quantity + ' (остаток 0)' : m.comment].map(function(v) { return {userEnteredValue: typeof v === 'number' ? {numberValue: v} : {stringValue: String(v)}}; })}; }), fields: 'userEnteredValue'}});
  const fbsEvents = ntcFbsEventRequests_(prior.engine, envelope.engine, catalog, book, String(envelope.revision || 0));
  requests.push.apply(requests, fbsEvents.requests);
  // Ozon/WB can release their own digital reserve on cancellation. Reconcile
  // affected listings even when the physical pool and rounded target did not change.
  envelope.publication_reconcile_offers = envelope.publication_reconcile_offers || {};
  fbsEvents.events.forEach(function(event) { const platform=event.platform==='Ozon'?'ozon':'wb'; const pending=envelope.publication_reconcile_offers[platform] || (envelope.publication_reconcile_offers[platform]={}); pending[event.offer]=true; });
  const allocated = ntcPublicationAmounts_(catalog, envelope.engine.last_f_by_model);
  catalog.rows.forEach(function(r) {
    const physical = envelope.engine.last_f_by_model[r.model];
    if (catalog.stock_by_model[r.model] !== physical) requests.push(ntcCell_(catalog.sheet, r.row, catalog.columns['Остаток склад по моделям'] + 1, physical));
    if (r.amount !== allocated[r.offer_id]) requests.push(ntcCell_(catalog.sheet, r.row, catalog.columns['Округлённое+прогруз на мп'] + 1, allocated[r.offer_id]));
  });
  const operator = book.getSheetByName(NTC_OPERATOR);
  if (operator) operator.getRange(7, 1, Math.max(1, operator.getLastRow() - 6), 2).getValues().forEach(function(r, index) {
    const model = String(r[0] || ''); if (Object.prototype.hasOwnProperty.call(envelope.engine.last_f_by_model, model) && r[1] !== envelope.engine.last_f_by_model[model]) requests.push(ntcCell_(operator, index + 7, 2, envelope.engine.last_f_by_model[model]));
  });
  (extras || []).forEach(function(extra) { requests.push(extra.request || extra); });
  requests.unshift.apply(requests,ntcJournalRequests_(envelope));
  // Reject edits made while API reads were in flight before changing F.
  const fresh = ntcReadCatalog_(); if (!ntcEqual_(fresh.stock_by_model, catalog.stock_by_model) ||
    !ntcEqual_(fresh.columns, catalog.columns) || !ntcEqual_(ntcCatalogIdentity_(fresh), ntcCatalogIdentity_(catalog))) throw new Error('НТЦ: таблица изменена во время расчёта, повторите');
  (extras || []).forEach(function(extra) {
    if (!extra.expected) return;
    const e = extra.expected, current = operator.getRange(e.row, 1, 1, Math.max(e.col, e.modelCol || 1)).getValues()[0];
    if (current[(e.modelCol || 1)-1] !== e.model || current[e.col - 1] !== e.quantity) throw new Error('НТЦ: количество/модель изменены во время операции, повторите');
  });
  Sheets.Spreadsheets.batchUpdate({requests: requests}, NTC_BOOK_ID);
  SpreadsheetApp.flush();
  fbsEvents.events.forEach(function(event) { Logger.log(JSON.stringify({event:'fbs_stock_event',data:event})); });
}
function ntcPublishCurrent_() {
  const c = ntcReadCatalog_(), cfg = ntcConfig_(), envelope = ntcReadState_();
  if (PropertiesService.getScriptProperties().getProperty('NTC_TRANSMISSION_RUNNING') !== 'true') return {ok: true, message: 'Операция записана; передача в МП выключена до завершения установки.'};
  if (!envelope.publish_pending) {
    envelope.publish_pending = {since: new Date().toISOString(), revision: envelope.revision || 0, alert_attempted: false};
    ntcCommitJournal_(envelope);
  }
  const pending = envelope.publish_pending;
  try {
    const p=PropertiesService.getScriptProperties();
    ['ozon','wb'].forEach(function(platform) {
      if (!(platform==='ozon'?cfg.ozonEnabled:cfg.wbEnabled)) return;
      const dirty=(envelope.publication_reconcile_offers || {})[platform] || {}, warehouse=platform==='ozon'?cfg.ozonWarehouseId:cfg.wbWarehouseId;
      c.rows.forEach(function(r) { if(dirty[r.offer_id]) p.deleteProperty('NTC_MP_'+platform+'_'+warehouse+'_'+(platform==='ozon'?r.offer_id:r.chrtId)); });
    });
    const result = ntcPublish_(c.rows, cfg, cfg.deadline);
    (result.enabled || ['ozon','wb']).forEach(function(platform) { if(envelope.publication_reconcile_offers) delete envelope.publication_reconcile_offers[platform]; });
    delete envelope.publish_pending; ntcCommitJournal_(envelope);
    const targets = result.enabled || ['ozon','wb'];
    return {ok: true, message: targets.length ? 'Операция записана. Остатки переданы: ' + targets.map(function(t) { return t === 'ozon' ? 'Ozon' : 'WB'; }).join(', ') + '.' : 'Операция записана. Трансляция Ozon и WB выключена.', result: result};
  } catch (error) {
    envelope.publish_pending = envelope.publish_pending || pending;
    envelope.publish_pending.last_error = String(error.message);
    const p = PropertiesService.getScriptProperties(), token = p.getProperty('TELEGRAM_TOKEN'), chat = p.getProperty('TELEGRAM_CHAT');
    const notify = !envelope.publish_pending.alert_attempted && !/лимит времени/.test(String(error.message)) && token && chat;
    if (notify) envelope.publish_pending.alert_attempted = true;
    ntcCommitJournal_(envelope);
    if (notify) {
      try { UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/sendMessage', {method: 'post', contentType: 'application/json', muteHttpExceptions: true,
        payload: JSON.stringify({chat_id: chat, text: 'НТЦ · остатки ожидают передачи в МП\n' + String(error.message).slice(0, 1500)})}); } catch (_) {}
    }
    ntcAudit_({event: 'publish_pending', revision: envelope.revision, message: String(error.message)});
    return {ok: true, pending: true, message: 'Операция записана. Передача в МП ожидает повторного запуска: ' + error.message};
  }
}
function ntcSupply() { return ntcSheetMovement_('supply'); }
function ntcWriteOff() { return ntcSheetMovement_('writeoff'); }
function ntcSheetMovement_(type) {
  return ntcLocked_('Поставка и списание', function() {
    const operator = ntcBook_().getSheetByName(NTC_OPERATOR), c = ntcReadCatalog_(), state = ntcReadState_();
    const id = Utilities.getUuid(), now = new Date().toISOString(), inputs = ntcReadOperatorMovements_(operator);
    function entries(drafts) { return drafts.map(function(m,index) { return {id:id+':'+m.type+':'+index, model:m.model, quantity:m.quantity, type:m.type, timestamp:now, comment:'Лист '+NTC_OPERATOR}; }); }
    const supplies = entries(inputs.supplies), writeoffs = entries(inputs.writeoffs);
    const clear = inputs.extras.map(function(e) { return {request:ntcCell_(operator,e.row,e.col,''),expected:e}; });
    if (!clear.length) return {ok: true, message: 'Нет количества для обработки'};
    const advanced = ntcAdvance_({articles: c.rows, stock_by_model: c.stock_by_model}, state.engine);
    state.engine = ntcApplyMovements_(advanced.state, c.rows, supplies.concat(writeoffs)); state.revision = (state.revision || 0) + 1;
    ntcCommit_(c, state, clear);
    const result = {ok: true, message: 'Запас обновлён: поставок ' + supplies.length + ', списаний ' + writeoffs.length + '. Передача МП выполняется отдельным облачным обработчиком.'};
    ntcBook_().toast(result.message, 'Склад НТЦ', 10); return result;
  });
}
function ntcScannerCatalog() {
  const c = ntcReadCatalog_(), products = {}, barcodes = ntcBook_().getSheetByName('Штрихкоды');
  c.rows.forEach(function(r) { if (!products[r.model]) products[r.model] = {model: r.model, name: r.model, stock: c.stock_by_model[r.model], photo: r.photo, barcodes: [r.model]}; });
  if (barcodes && barcodes.getLastRow() > 1) barcodes.getRange(2, 1, barcodes.getLastRow() - 1, 3).getDisplayValues().forEach(function(r) {
    if (!r[0]) return; if (!products[r[1]]) throw new Error('Неизвестная модель в штрихкодах: ' + r[1]);
    products[r[1]].barcodes.push(r[0]); if (r[2]) products[r[1]].name = r[2];
  });
  return {products: Object.keys(products).map(function(m) { return products[m]; }), version: ntcReadState_().revision || 0};
}
function ntcScannerSubmit(payload) {
  return ntcLocked_('Сканер', function() {
    if (!payload || !/^[\w-]{16,100}$/.test(String(payload.id)) || ['supply', 'writeoff'].indexOf(payload.type) < 0 || !Array.isArray(payload.items) || !payload.items.length) throw new Error('Некорректная операция сканера');
    const c = ntcReadCatalog_(), envelope = ntcReadState_(); envelope.scanner_operations = envelope.scanner_operations || {};
    const items = payload.items.map(function(item) { return {model: String(item.model || '').trim(), quantity: item.quantity}; });
    const canonical = JSON.stringify({type: payload.type, items: items, comment: String(payload.comment || '')});
    if (envelope.scanner_operations[payload.id]) {
      if (envelope.scanner_operations[payload.id] !== canonical) throw new Error('ID операции уже использован для другого количества');
      return {ok: true, message: 'Операция уже учтена. Запас повторно не изменён.'};
    }
    const now = new Date().toISOString(), movements = items.map(function(item, i) { return {id: payload.id + ':' + i,
      model: String(item.model), quantity: item.quantity, type: payload.type, timestamp: now, comment: String(payload.comment || '').slice(0, 1000)}; });
    const advanced = ntcAdvance_({articles: c.rows, stock_by_model: c.stock_by_model}, envelope.engine);
    envelope.engine = ntcApplyMovements_(advanced.state, c.rows, movements); envelope.scanner_operations[payload.id] = canonical; envelope.revision = (envelope.revision || 0) + 1;
    ntcCommit_(c, envelope); return {ok: true, message: 'Операция записана. Передача МП выполняется отдельным облачным обработчиком.'};
  });
}
function ntcCloudTick() { return ntcBackgroundLocked_('Заказы и остатки', ntcCloudTickUnlocked_); }
function ntcCloudTickUnlocked_() {
  if (ntcFbsPaused_()) return {ok:true,message:'Учёт FBS приостановлен'};
  return (function() {
    const c = ntcReadCatalog_(), envelope = ntcReadState_(), cfg = ntcConfig_(); cfg.start = envelope.start; cfg.cursor = envelope.cursor; cfg.returnCursor = envelope.returnCursor || 0;
    const cursor = new Date().toISOString(), postings = ntcFetchOrders_(c.rows, envelope.engine, cfg);
    const interim = ntcAdvance_({articles: c.rows, stock_by_model: c.stock_by_model, postings: postings}, envelope.engine);
    const returns = ntcFetchReturns_(interim.state, cfg);
    const advanced = ntcAdvance_({articles: c.rows, stock_by_model: c.stock_by_model, postings: postings, returns: returns}, envelope.engine);
    envelope.engine = advanced.state; envelope.returnCursor = returns.nextCursor || 0; envelope.cursor = cursor; envelope.revision = (envelope.revision || 0) + 1;
    ntcCommit_(c, envelope);
    PropertiesService.getScriptProperties().setProperty('NTC_LAST_ORDER_SYNC', cursor); ntcSetToggleStatus_();
    Logger.log(JSON.stringify({event:'fbs_tick_complete',revision:envelope.revision,postings:postings.length,returns:returns.length,shortage:advanced.shortage_physical_by_model}));
    return {ok:true,message:'Заказы и возвраты учтены. Трансляция выполняется отдельно.'};
  })();
}
function ntcRefreshCatalog() { return ntcLocked_('Каталог', function() {
  const sheet = ntcBook_().getSheetByName(NTC_CATALOG), enriched = ntcEnrichCatalog_(sheet, ntcConfig_());
  const initialized = ntcPrepareNewProducts_(sheet), c = ntcReadCatalog_(), envelope = ntcReadState_();
  const advanced = ntcAdvance_({articles: c.rows, stock_by_model: c.stock_by_model}, envelope.engine);
  envelope.engine = advanced.state; envelope.revision = (envelope.revision || 0) + 1;
  ntcCommit_(c, envelope); ntcFormatOperator_(ntcBook_().getSheetByName(NTC_OPERATOR), ntcReadCatalog_()); ntcSetToggleStatus_();
  const missing = c.rows.filter(function(r) { return !r.ozonSku || !r.wbSku || !r.chrtId || !r.photo; }).map(function(r) { return r.offer_id; });
  const message = 'Данные загружены: ' + c.rows.length + ' товаров. Новых строк: ' + initialized +
    (missing.length ? '. Не найдены все данные: ' + missing.join(', ') : '. Все привязки заполнены.');
  ntcBook_().toast(message, 'Склад НТЦ', 15); return {updated: enriched.updated, initialized: initialized, missing: missing};
}); }
/** Enrol blank-stock rows without resetting existing model inventories. */
function ntcPrepareNewProducts_(sheet) {
  const range = sheet.getDataRange(), grid = range.getValues(), formulas = range.getFormulas(), h = grid[0];
  const offerCol = ntcColumn_(h, 'Артикул продавца'), modelCol = ntcColumn_(h, 'Артикул производителя'), sizeCol = ntcColumn_(h, 'Х'), stockCol = ntcColumn_(h, 'Остаток склад по моделям');
  const envelope = ntcReadState_(), stocks = Object.assign({}, envelope.engine.last_f_by_model), operator = ntcBook_().getSheetByName(NTC_OPERATOR), initial = {}, seen = {}, changes = [];
  if (operator && operator.getLastRow() >= 7) operator.getRange(7,1,operator.getLastRow()-6,2).getValues().forEach(function(r) {
    if (!r[0] || r[1] === '') return; const model = String(r[0]);
    if (!Number.isSafeInteger(r[1]) || r[1] < 0 || (initial[model] !== undefined && initial[model] !== r[1])) throw new Error('НТЦ: неверный стартовый остаток модели ' + model);
    initial[model] = r[1];
  });
  let initialized = 0;
  grid.slice(1).forEach(function(r,index) {
    const offer = String(r[offerCol] || '').trim(); if (!offer) return;
    if (seen[offer]) throw new Error('НТЦ: повтор артикула ' + offer); seen[offer] = true;
    const match = /^(.*)-(\d+)$/.exec(offer), model = String(r[modelCol] || (match && match[1]) || '').trim(), size = Number(r[sizeCol] || (match && match[2]));
    if (!model || !Number.isSafeInteger(size) || size <= 0) throw new Error('Укажите модель и кратность для ' + offer);
    if (r[modelCol] === '') { if (formulas[0][modelCol]) throw new Error('Формула модели не рассчитана для ' + offer); changes.push(ntcCell_(sheet,index+2,modelCol+1,model)); }
    if (r[sizeCol] === '') { if (formulas[0][sizeCol]) throw new Error('Формула кратности не рассчитана для ' + offer); changes.push(ntcCell_(sheet,index+2,sizeCol+1,size)); }
    if (r[stockCol] === '') {
      if (stocks[model] === undefined) stocks[model] = initial[model] === undefined ? 0 : initial[model];
      changes.push(ntcCell_(sheet,index+2,stockCol+1,stocks[model])); initialized++;
    } else if (stocks[model] !== undefined && stocks[model] !== r[stockCol]) throw new Error('Остаток модели ' + model + ' отличается от журнала');
    else stocks[model] = r[stockCol];
  });
  if (changes.length) Sheets.Spreadsheets.batchUpdate({requests: changes}, NTC_BOOK_ID);
  SpreadsheetApp.flush(); return initialized;
}
function ntcAudit_(event) { ntcServiceSheet_('_НТЦ MP аудит', ['Время', 'Событие']).appendRow([new Date().toISOString(), JSON.stringify(event).slice(0, 49000)]); }
function ntcDiagnostics() {
  const c = ntcReadCatalog_(), e = ntcReadState_(), cfg = ntcConfig_();
  const result = {account: Session.getEffectiveUser().getEmail(), products: c.rows.length, models: Object.keys(c.stock_by_model).length,
    ledgerMatches: ntcEqual_(c.stock_by_model, e.engine.last_f_by_model), warehouses: {ozon: cfg.ozonWarehouseId, wb: cfg.wbWarehouseId},
    live: PropertiesService.getScriptProperties().getProperty('NTC_LIVE'), triggers: ScriptApp.getProjectTriggers().map(function(t) { return t.getHandlerFunction(); })};
  Logger.log(JSON.stringify(result)); return result;
}

function ntcToggleOzon() { return ntcTogglePlatform_('ozon'); }
function ntcToggleWb() { return ntcTogglePlatform_('wb'); }
function ntcTogglePlatform_(platform) {
  return ntcLocked_('Переключение ' + platform, function() {
    const p = PropertiesService.getScriptProperties(), key = platform === 'ozon' ? 'NTC_OZON_ENABLED' : 'NTC_WB_ENABLED';
    const enabled = p.getProperty(key) !== 'true'; p.setProperty(key,String(enabled));
    ntcSetToggleStatus_();
    const result = {ok: true, message: (platform === 'ozon' ? 'Ozon' : 'WB') + ': трансляция ' + (enabled ? 'включена' : 'выключена')};
    ntcBook_().toast(result.message, 'Склад НТЦ', 8);
    if (enabled) {
      const cfg = ntcConfig_(), catalog = ntcReadCatalog_(), warehouse = platform === 'ozon' ? cfg.ozonWarehouseId : cfg.wbWarehouseId;
      catalog.rows.forEach(function(r) { p.deleteProperty('NTC_MP_' + platform + '_' + warehouse + '_' + (platform === 'ozon' ? r.offer_id : r.chrtId)); });
      // Publication resumes only if the separate transmitter is running.
    }
    return result;
  });
}
function ntcSetToggleStatus_() {
  const p = PropertiesService.getScriptProperties(), sheet = ntcBook_().getSheetByName(NTC_OPERATOR);
  const lastSync = p.getProperty('NTC_LAST_ORDER_SYNC');
  const lastSyncDisplay = lastSync ? Utilities.formatDate(new Date(lastSync), 'Europe/Samara', 'dd.MM.yyyy HH:mm:ss') + ' (Самара)' : 'ещё не выполнен';
  if (sheet) sheet.getRange('J12:J16').setValues([['Ozon: ' + (p.getProperty('NTC_OZON_ENABLED') === 'true' ? 'ВКЛ' : 'ВЫКЛ')],['WB: ' + (p.getProperty('NTC_WB_ENABLED') === 'true' ? 'ВКЛ' : 'ВЫКЛ')],['Автотрансляция: ' + (p.getProperty('NTC_TRANSMISSION_RUNNING') === 'true' ? 'РАБОТАЕТ' : 'ОСТАНОВЛЕНА')],[ntcFbsPaused_() ? 'Учёт FBS: ОСТАНОВЛЕН' : 'Учёт FBS: каждые 5 минут'],['Последний учёт FBS: ' + lastSyncDisplay]]);
}

function ntcCatalogPhotoUrl_(formula, value) {
  const match = /^=IMAGE\(\s*"((?:[^"]|"")*)"/i.exec(String(formula || ''));
  if (match) return match[1].replace(/""/g, '"');
  return typeof value === 'string' && /^https:\/\//i.test(value) ? value : '';
}
