const NTC_FBS_EVENT_HEADERS_ = ['ID запуска','Время','Площадка','Заказ FBS','Событие','Статус до','Статус после','Артикул','Модель','Количество упаковок','Кратность','Изменение учётного запаса, шт','Остаток модели до запуска, шт','Остаток модели после запуска, шт','Примечание','ID возврата'];
/** Build the visible FBS audit in the same transaction as inventory/journal.
 * Stock columns are the model's aggregate snapshot for this run, repeated on
 * each item; accounting delta remains visible even when shortage clamps F=0. */
function ntcFbsEventRequests_(previousEngine, nextEngine, catalog, book, runId) {
  var before = previousEngine || {}, after = nextEngine || {}, events = [], requests = [];
  var articles = {};
  (catalog.rows || catalog || []).forEach(function(row) { articles[row.offer_id] = {model: row.model, H: row.H}; });
  Object.keys(before.article_schema_by_offer || {}).forEach(function(offer) {
    if (!articles[offer]) articles[offer] = before.article_schema_by_offer[offer];
  });
  function active(posting) {
    return !!posting && !(['cancelled', 'not_accepted'].indexOf(posting.status) >= 0 && !posting.ever_handed_over);
  }
  function returned(number, offer, state) {
    return Object.keys(state.returns || {}).reduce(function(sum, id) {
      var entry = state.returns[id];
      return sum + (entry.posting_number === number && entry.offer_id === offer ? entry.quantity : 0);
    }, 0);
  }
  function outstanding(posting, offer, number) {
    return active(posting) ? Math.max(0, ((posting.items || {})[offer] || 0) - returned(number, offer, before)) : 0;
  }
  function event(number, offer, oldPosting, posting, kind, quantity, delta, note, returnId) {
    var article = articles[offer];
    if (!article) throw new Error('НТЦ FBS журнал: неизвестный артикул ' + offer);
    events.push({runId: String(runId), timestamp: new Date().toISOString(), platform: number.indexOf('WB:') === 0 ? 'WB' : 'Ozon',
      posting: number, kind: kind, statusBefore: oldPosting ? oldPosting.status : '', statusAfter: posting ? posting.status : '',
      offer: offer, model: article.model, packs: quantity, H: article.H, accountingDelta: delta * article.H,
      stockBefore: (before.last_f_by_model || {})[article.model] || 0,
      stockAfter: (after.last_f_by_model || {})[article.model] || 0,
      note: note || '', returnId: returnId || ''});
  }
  Object.keys(after.postings || {}).sort().forEach(function(number) {
    var posting = after.postings[number], oldPosting = (before.postings || {})[number];
    if (ntcEqual_(oldPosting, posting)) return;
    var offers = {};
    Object.keys((oldPosting || {}).items || {}).concat(Object.keys(posting.items || {})).forEach(function(offer) { offers[offer] = true; });
    Object.keys(offers).sort().forEach(function(offer) {
      var oldQty = ((oldPosting || {}).items || {})[offer] || 0, qty = (posting.items || {})[offer] || 0;
      if (oldPosting && oldQty === qty && oldPosting.status === posting.status && oldPosting.ever_handed_over === posting.ever_handed_over) return;
      var delta = outstanding(oldPosting, offer, number) - outstanding(posting, offer, number);
      var cancelled = ['cancelled', 'not_accepted'].indexOf(posting.status) >= 0;
      event(number, offer, oldPosting, posting, cancelled ? 'Отмена FBS' : !oldPosting ? 'Заказ FBS' : oldQty !== qty ? 'Изменение количества FBS' : 'Статус FBS',
        qty, delta, cancelled && posting.ever_handed_over ? 'Передача подтверждена или неизвестна: возврат запаса только после приёмки' : '');
    });
  });
  Object.keys(after.returns || {}).sort().forEach(function(id) {
    var entry = after.returns[id], prior = (before.returns || {})[id];
    if (ntcEqual_(prior, entry)) return;
    if (prior) throw new Error('НТЦ FBS журнал: изменён принятый возврат ' + id);
    var posting = (after.postings || {})[entry.posting_number];
    event(entry.posting_number, entry.offer_id, (before.postings || {})[entry.posting_number], posting,
      'Принятый возврат FBS', entry.quantity, active(posting) ? entry.quantity : 0,
      active(posting) ? 'Получен продавцом' : 'Запас уже восстановлен отменой: повторного прихода нет', id);
  });
  if (!events.length) return {requests: requests, events: events};
  var name = 'События FBS', sheet = book.getSheetByName(name), sheetId;
  var headers = NTC_FBS_EVENT_HEADERS_;
  function cells(values) { return {values: values.map(function(value) {
    return {userEnteredValue: typeof value === 'number' ? {numberValue: value} : {stringValue: String(value)}};
  })}; }
  if (!sheet) {
    var used = book.getSheets().map(function(s) { return s.getSheetId(); });
    sheetId = 1; while (used.indexOf(sheetId) >= 0) sheetId++;
    requests.push({addSheet: {properties: {sheetId: sheetId, title: name, gridProperties: {rowCount: 1000, columnCount: headers.length, frozenRowCount: 1}}}});
  } else sheetId = sheet.getSheetId();
  var rows = !sheet || sheet.getLastRow() === 0 ? [cells(headers)] : [];
  events.forEach(function(e) { rows.push(cells([e.runId,e.timestamp,e.platform,e.posting,e.kind,e.statusBefore,e.statusAfter,e.offer,e.model,e.packs,e.H,e.accountingDelta,e.stockBefore,e.stockAfter,e.note,e.returnId])); });
  requests.push({appendCells: {sheetId: sheetId, rows: rows, fields: 'userEnteredValue'}});
  return {requests: requests, events: events};
}
