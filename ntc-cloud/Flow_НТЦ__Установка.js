/** Run in the bound project under NTC_OWNER. No marketplace writes during install. */
function ntcInstall() {
  if (Session.getEffectiveUser().getEmail().toLowerCase() !== NTC_OWNER) throw new Error('Установка должна выполняться от ' + NTC_OWNER);
  return ntcLocked_('Установка', function() {
    const p = PropertiesService.getScriptProperties();
    if (typeof NTC_BOOTSTRAP !== 'undefined') p.setProperties(NTC_BOOTSTRAP, false);
    if (!p.getProperty('NTC_LIVE')) p.setProperty('NTC_LIVE', 'false');
    if (!p.getProperty('WB_NTC_WAREHOUSE')) p.setProperty('WB_NTC_WAREHOUSE', '798761');
    ['NTC_OZON_ENABLED','NTC_WB_ENABLED'].forEach(function(key) { if (!p.getProperty(key)) p.setProperty(key,'false'); });
    const book = ntcBook_(), sheet = book.getSheetByName(NTC_CATALOG);
    // Copied ARRAYFORMULA headers reference absent source tabs. Replace only those
    // documented catalog columns; keep physical F and seller/model identity.
    const names = ['Артикул продавца','Артикул производителя','ФОТО','SKU OZON','SKU WB','Остаток склад по моделям','Виртуальный остаток','Х','Округлённое+прогруз на мп','chrlid'];
    const existing = sheet.getRange(1, 1, 1, names.length).getDisplayValues()[0];
    names.forEach(function(name, i) { if (existing[i] !== name) throw new Error('НТЦ: изменена структура колонки ' + (i + 1)); });
    [2,3,4,7,9].forEach(function(index) {
      if (sheet.getRange(1,index+1).getFormula()) { sheet.getRange(1,index+1,sheet.getMaxRows(),1).clearContent(); sheet.getRange(1,index+1).setValue(names[index]); }
    });
    const offers = sheet.getRange(2,1,sheet.getLastRow()-1,1).getDisplayValues();
    const seedArticles = (NTC_SEED.engine.article_schema_by_offer || {});
    offers.forEach(function(r,index) {
      const offer = r[0], historical = seedArticles[offer], suffix = /-(\d+)$/.exec(offer);
      if (!historical && !suffix) throw new Error('Неизвестная кратность артикула ' + offer);
      if (!sheet.getRange(index+2,ntcColumn_(names, 'Х') + 1).getValue()) sheet.getRange(index+2,ntcColumn_(names, 'Х') + 1).setValue(historical ? historical.H : Number(suffix[1]));
    });
    ntcEnrichCatalog_(sheet, ntcConfig_());
    const c = ntcReadCatalog_();
    let operator = book.getSheetByName(NTC_OPERATOR);
    if (!operator) { operator = book.getSheetByName('Лист76'); if (operator) operator.setName(NTC_OPERATOR); else operator = book.insertSheet(NTC_OPERATOR); }
    if (operator.getLastRow() > 0 && operator.getRange('A1').getDisplayValue() !== 'СКЛАД НТЦ') throw new Error('Второй лист содержит данные; установка остановлена');
    ntcFormatOperator_(operator, c);
    const barcodeSheet = book.getSheetByName('Штрихкоды') || book.insertSheet('Штрихкоды');
    if (!barcodeSheet.getLastRow()) { barcodeSheet.getRange('A1:C1').setValues([['Штрихкод','Модель','Название']]); barcodeSheet.setFrozenRows(1); barcodeSheet.getRange('A:A').setNumberFormat('@'); }
    ntcImportBarcodes_(barcodeSheet, c);
    if (!book.getSheetByName(NTC_STATE)) {
      if (!ntcEqual_(c.stock_by_model, NTC_SEED.engine.last_f_by_model)) throw new Error('Текущие остатки отличаются от журнала миграции; требуется сверка');
      ntcCommit_(c, ntcCopy_(NTC_SEED));
    }
    const envelope = ntcReadState_(); p.setProperties({NTC_START: envelope.start, NTC_CURSOR: envelope.cursor}, false);
    const warehouses = ntcDiscoverWarehouses_(ntcConfig_());
    p.setProperty('OZON_NTC_WAREHOUSE', String(warehouses.ozon.id));
    if (warehouses.wb) p.setProperty('WB_NTC_WAREHOUSE', String(warehouses.wb.id));
    book.setActiveSheet(sheet); book.moveActiveSheet(1);
    book.setActiveSheet(operator); book.moveActiveSheet(2);
    const history = book.getSheetByName('История склада'); if (history) { book.setActiveSheet(history); book.moveActiveSheet(3); }
    book.setActiveSheet(barcodeSheet); book.moveActiveSheet(4);
    ntcSetToggleStatus_(); book.setActiveSheet(operator); return ntcDiagnostics();
  });
}
function ntcFormatOperator_(sheet, c) {
  const layout = ntcOperatorLayout_(sheet), last = Math.max(13, sheet.getLastRow());
  const existingStocks = last >= 7 ? sheet.getRange(7, 1, last - 6, 2).getValues().filter(function(r) { return r[0] !== ''; }) : [];
  const modelSet = {}; Object.keys(c.stock_by_model).forEach(function(model) { modelSet[model] = true; });
  const oldStocks = {}; existingStocks.forEach(function(r) { const model = String(r[0]).trim(); modelSet[model] = true; oldStocks[model] = r[1]; });
  const models = Object.keys(modelSet).sort();
  const supplies = ntcOperatorDrafts_(sheet, layout, models, 'supply'), writeoffs = ntcOperatorDrafts_(sheet, layout, models, 'writeoff');
  // Read every draft before clearing legacy columns. New tables keep their independent ordering.
  if (layout === 'legacy') { sheet.getRange(7, 3, last - 6, 2).clearContent().clearDataValidations(); sheet.getRange('F2:G15').clearContent().clearDataValidations(); }
  else sheet.getRange('F2:F15').clearContent().clearDataValidations();
  sheet.setFrozenRows(1); sheet.setHiddenGridlines(true);
  sheet.getRange(1, 1, Math.max(last, models.length + 6, supplies.length + 6, writeoffs.length + 6), 11).setFontFamily('Arial');
  sheet.getRange('A1:H3').breakApart();
  sheet.getRange('A1:H1').merge().setValue('СКЛАД НТЦ').setFontSize(20).setFontWeight('bold').setBackground('#163547').setFontColor('#ffffff');
  sheet.getRange('A2:H2').merge().setValue('Остатки, поставки и списания — физические штуки модели').setFontSize(11);
  sheet.getRange('A3:H3').merge().setValue('Любая складская кнопка применяет обе таблицы: сначала поставку, затем списание. Модели сопоставляются по коду.').setWrap(true);
  sheet.getRange('A6:H6').clearContent().clearDataValidations();
  const tables = [{col: 1, header: 'КОЛИЧЕСТВО, ШТ', color: '#dce9f1', rows: models.map(function(model) { return [model, Object.prototype.hasOwnProperty.call(c.stock_by_model, model) ? c.stock_by_model[model] : oldStocks[model]]; })}, {col: 4, header: 'ПОСТАВКА, ШТ', color: '#e3efda', rows: supplies}, {col: 7, header: 'СПИСАНИЕ, ШТ', color: '#fbe4e5', rows: writeoffs}];
  tables.forEach(function(table) {
    sheet.getRange(6, table.col, 1, 2).setValues([['МОДЕЛЬ', table.header]]).setFontWeight('bold').setBackground(table.color).setWrap(true);
    const count = Math.max(1, table.rows.length);
    sheet.getRange(7, table.col, count, 1).setNumberFormat('@').setBackground('#ffffff');
    if (table.rows.length) sheet.getRange(7, table.col, table.rows.length, 2).setValues(table.rows);
    sheet.getRange(7, table.col + 1, count, 1).setBackground(table.color).setNumberFormat('0');
    if (table.col !== 1) sheet.getRange(7, table.col + 1, Math.max(count, 100), 1).setDataValidation(SpreadsheetApp.newDataValidation().requireFormulaSatisfied('=OR(ISBLANK(' + (table.col === 4 ? 'E' : 'H') + '7);AND(ISNUMBER(' + (table.col === 4 ? 'E' : 'H') + '7);' + (table.col === 4 ? 'E' : 'H') + '7>0;MOD(' + (table.col === 4 ? 'E' : 'H') + '7;1)=0))').setAllowInvalid(false).build());
    sheet.getRange(6, table.col, count + 1, 2).setBorder(true, true, true, true, true, true, '#8da1ac', SpreadsheetApp.BorderStyle.SOLID);
  });
  const controls = {}; sheet.getImages().forEach(function(image) { const title = image.getAltTextTitle(); if (title.indexOf('NTC_BUTTON:') === 0) controls[title] = image; });
  NTC_BUTTONS.forEach(function(button, index) {
    const image = controls['NTC_BUTTON:' + button.handler] || sheet.insertImage(Utilities.newBlob(Utilities.base64Decode(button.png), 'image/png', button.handler + '.png'), 10, 2 + index);
    image.setAnchorCell(sheet.getRange(index + 2, 10)).setAnchorCellXOffset(0).setAnchorCellYOffset(0).setAltTextTitle('NTC_BUTTON:' + button.handler).setAltTextDescription(button.label).assignScript(button.handler).setWidth(250).setHeight(38);
    sheet.setRowHeight(index + 2, 44);
  });
  [1,2,4,5,7,8].forEach(function(col) { sheet.setColumnWidth(col, 150); });
  [3,6,9].forEach(function(col) { sheet.setColumnWidth(col, 30); sheet.getRange(6, col, last - 5, 1).setBackground('#ffffff').setBorder(false, false, false, false, false, false); });
  sheet.setColumnWidth(10, 260); sheet.setColumnWidth(11, 65); sheet.setRowHeight(1, 40); sheet.setRowHeight(3, 44); sheet.setRowHeight(6, 44);
}
function ntcImportBarcodes_(target, catalog) {
  if (target.getLastRow() > 1) return;
  const source = SpreadsheetApp.openById(ntcConfig_().sourceSpreadsheetId).getSheetByName('Grocy — товары'); if (!source || source.getLastRow() < 2) return;
  const data = source.getDataRange().getDisplayValues(), h = data[0];
  // Grocy export schema varies; accept only uniquely named exact model/barcode fields.
  const model = h.indexOf('Модель'), barcode = h.indexOf('Штрихкоды'), name = h.indexOf('Название');
  if (model < 0 || barcode < 0) return;
  const rows = [], seen = {}; data.slice(1).forEach(function(r) {
    if (!Object.prototype.hasOwnProperty.call(catalog.stock_by_model,r[model])) return;
    String(r[barcode]).split(/[;,\n]/).map(function(v) { return v.trim(); }).filter(Boolean).forEach(function(code) {
      if (seen[code] && seen[code] !== r[model]) throw new Error('Штрихкод относится к разным моделям: ' + code); seen[code] = r[model]; rows.push([code,r[model],name >= 0 ? r[name] : r[model]]);
    });
  });
  if (rows.length) target.getRange(2,1,rows.length,3).setValues(rows);
}
function ntcEnableCloud() {
  if (ntcFbsPaused_()) throw new Error('FBS приостановлен пользователем');
  if (Session.getEffectiveUser().getEmail().toLowerCase() !== NTC_OWNER) throw new Error('Запустите от ' + NTC_OWNER);
  const diagnostics = ntcDiagnostics(); if (!diagnostics.ledgerMatches) throw new Error('Журнал и остатки не совпадают');
  const config = ntcConfig_(); if (!config.ozonWarehouseId || !config.wbWarehouseId) throw new Error('Склады не настроены');
  const handlers = ['ntcCloudTick','ntcOperatorEdit','ntcRefreshCatalog'];
  ScriptApp.getProjectTriggers().forEach(function(t) { if (handlers.indexOf(t.getHandlerFunction()) >= 0) ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('ntcCloudTick').timeBased().everyMinutes(5).create();
  ScriptApp.newTrigger('ntcRefreshCatalog').timeBased().everyDays(1).atHour(5).create();
  const p = PropertiesService.getScriptProperties();
  if (p.getProperty('NTC_CLOUD_INITIALIZED') !== 'true') p.setProperty('NTC_CLOUD_INITIALIZED','true');
  p.setProperty('NTC_LIVE','true'); ntcSetToggleStatus_(); return ntcCloudTick();
}
