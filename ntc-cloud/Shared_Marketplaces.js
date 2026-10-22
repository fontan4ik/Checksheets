/** Cloud marketplace adapter. Credentials are Script Properties; never log HTTP bodies. */
function ntcApi_(platform, path, payload, config, method) {
  if (typeof ntcFbsPaused_ === 'function' && ntcFbsPaused_() && (/\/(posting|returns|warehouse|warehouses|orders|stocks)(\/|\?|$)/.test(path) || path === '/v2/products/stocks')) throw new Error('НТЦ: обращения к FBS временно отключены пользователем');
  const wb = platform.indexOf('wb') === 0;
  const host = platform === 'wbContent' ? 'https://content-api.wildberries.ru' : wb ? 'https://marketplace-api.wildberries.ru' : 'https://api-seller.ozon.ru';
  if (wb ? !config.wbToken : !config.ozonClientId || !config.ozonApiKey) throw new Error('НТЦ: отсутствуют ключи ' + platform);
  const options = {method: method || 'post', muteHttpExceptions: true, contentType: 'application/json',
    headers: wb ? {Authorization: config.wbToken} : {'Client-Id': String(config.ozonClientId), 'Api-Key': config.ozonApiKey}};
  if (payload !== undefined && options.method !== 'get') options.payload = JSON.stringify(payload);
  for (let attempt = 0; attempt < 4; attempt++) {
    ntcDeadline_(config.deadline);
    Utilities.sleep(wb ? 550 : 100);
    const response = UrlFetchApp.fetch(host + path, options), code = response.getResponseCode();
    if (code >= 200 && code < 300) {
      const raw = response.getContentText();
      if (!raw) return {};
      try { return ntcParseApiJson_(raw); } catch (_) { throw new Error('НТЦ: некорректный JSON ' + platform + ' ' + path); }
    }
    if ((code === 429 || code >= 500) && attempt < 3) {
      const delay = Math.min(30000, Math.max(1000 * Math.pow(2, attempt), Number(response.getHeaders()['Retry-After'] || 0) * 1000));
      ntcDeadline_(config.deadline, delay + 15000); Utilities.sleep(delay); continue;
    }
    const error = new Error('НТЦ API ' + platform + ' ' + path.split('?')[0] + ': HTTP ' + code);
    error.httpCode = code; throw error;
  }
}
function ntcDeadline_(deadline, margin) {
  if (deadline && Date.now() + (margin || 15000) >= Number(deadline)) throw new Error('НТЦ: достигнут лимит времени; продолжение в следующем облачном запуске');
}
function ntcPositiveId_(value) { const n = Number(value); return Number.isSafeInteger(n) && n > 0; }
function ntcFetchOrders_(articles, state, config) {
  const offers = new Set(articles.map(function(r) { return String(r.offer_id); }));
  const known = (state || {}).postings || {}, updates = {}, now = new Date().toISOString();
  if (!config.start || !Number.isFinite(Date.parse(config.start))) throw new Error('НТЦ: не задана дата начала учёта');
  if (!ntcPositiveId_(config.ozonWarehouseId) || !ntcPositiveId_(config.wbWarehouseId)) throw new Error('НТЦ: явно задайте оба склада');
  // Ozon has a one-year list window. Cursor overlap catches status transitions.
  const since = new Date(Date.parse(now) - 364 * 86400000).toISOString();
  const pendingStatuses = ['acceptance_in_progress', 'awaiting_registration', 'awaiting_approve', 'awaiting_packaging', 'awaiting_deliver'];
  const filter = {since: since, to: now, warehouse_ids: [Number(config.ozonWarehouseId)]};
  if (config.cursor) filter.last_changed_status_date = {from: new Date(Math.max(Date.parse(since), Date.parse(config.cursor) - 600000)).toISOString(), to: now};
  const filters = [filter, {since: since, to: now, warehouse_ids: [Number(config.ozonWarehouseId)], statuses: pendingStatuses}];
  filters.forEach(function(queryFilter) {
  let cursor = '';
  const seenCursors = new Set();
  do {
    const result = ntcApi_('ozon', '/v4/posting/fbs/list', {sort_dir: 'ASC', filter: queryFilter, limit: 100, cursor: cursor, with: {analytics_data: false, financial_data: false}}, config);
    if (!result || !Array.isArray(result.postings)) throw new Error('НТЦ: отсутствует список отправлений Ozon');
    result.postings.forEach(function(p) {
      const warehouse = p.delivery_method && p.delivery_method.warehouse_id;
      if (!warehouse) throw new Error('НТЦ: Ozon не вернул склад отправления ' + p.posting_number);
      if (String(warehouse) !== String(config.ozonWarehouseId)) return;
      const number = String(p.posting_number || ''), status = String(p.status || '');
      if (!number || !status || !Array.isArray(p.products)) throw new Error('НТЦ: неполное отправление Ozon');
      const created = Date.parse(p.in_process_at || p.created_at || '');
      if (!Number.isFinite(created) && !known[number]) throw new Error('НТЦ: Ozon не вернул дату отправления');
      if (!known[number] && created < Date.parse(config.start) && pendingStatuses.indexOf(status) < 0) return;
      const items = p.products.filter(function(item) { return offers.has(String(item.offer_id)); }).map(function(item) {
        if (!Number.isSafeInteger(item.quantity) || item.quantity < 0) throw new Error('НТЦ: некорректное количество Ozon');
        return {offer_id: String(item.offer_id), quantity: item.quantity};
      });
      if (!items.length && !known[number]) return;
      const item = {posting_number: number, status: status}; if (items.length) item.items = items;
      // A completed handoff timestamp is additional evidence even when delivery
      // status happened entirely between polls. Never use the planned shipment_date.
      const deliveredAt = Date.parse(p.delivering_date || '');
      if (Number.isFinite(deliveredAt)) item.ever_handed_over = true;
      if (status === 'cancelled' || status === 'not_accepted') {
        const flag = p.cancellation && p.cancellation.cancelled_after_ship;
        item.ever_handed_over = Number.isFinite(deliveredAt) || (typeof flag === 'boolean' ? flag : true);
      }
      updates[number] = item;
    });
    if (!result.has_next) break;
    if (!result.postings.length || typeof result.cursor !== 'string' || !result.cursor || result.cursor === cursor || seenCursors.has(result.cursor)) throw new Error('НТЦ: Ozon пагинация не продвигается');
    seenCursors.add(result.cursor);
    cursor = result.cursor;
  } while (true);
  });
  // WB orders/history includes tasks already assembled; /orders/new alone loses orders between polls.
  const wbOrders = {}, wbStart = Math.max(Date.parse(config.start), Date.now() - 29 * 86400000, config.cursor ? Date.parse(config.cursor) - 600000 : 0);
  function collectWb(o) {
    if (String(o.warehouseId) !== String(config.wbWarehouseId)) return;
    const number = 'WB:' + o.id;
    if (!ntcPositiveId_(o.id)) throw new Error('НТЦ: некорректный идентификатор WB');
    if (!known[number] && !Number.isFinite(Date.parse(o.createdAt || ''))) throw new Error('НТЦ: WB не вернул дату заказа');
    if (offers.has(String(o.article))) wbOrders[String(o.id)] = o;
  }
  let next = 0;
  do {
    const data = ntcApi_('wb', '/api/v3/orders?limit=1000&next=' + next + '&dateFrom=' + Math.floor(wbStart / 1000) + '&dateTo=' + Math.floor(Date.now() / 1000), undefined, config, 'get');
    if (!Array.isArray(data.orders)) throw new Error('НТЦ: отсутствует список WB');
    data.orders.forEach(function(o) {
      if (!known['WB:' + o.id] && Date.parse(o.createdAt || '') < Date.parse(config.start)) return;
      collectWb(o);
    });
    if (data.orders.length < 1000 || !data.next || String(data.next) === '0') break;
    if (String(data.next) === String(next)) throw new Error('НТЦ: WB пагинация не продвигается');
    next = data.next;
  } while (true);
  const newWb = ntcApi_('wb', '/api/v3/orders/new', undefined, config, 'get');
  if (!Array.isArray(newWb.orders)) throw new Error('НТЦ: отсутствуют новые задания WB');
  newWb.orders.forEach(collectWb);
  // Recheck tracked orders outside history window, retaining their original article.
  Object.keys(known).filter(function(k) { return k.indexOf('WB:') === 0; }).forEach(function(k) {
    const id = k.slice(3); if (!wbOrders[id]) wbOrders[id] = {id: Number(id), tracked: known[k]};
  });
  const ids = Object.keys(wbOrders);
  for (let i = 0; i < ids.length; i += 1000) {
    const group = ids.slice(i, i + 1000), data = ntcApi_('wb', '/api/v3/orders/status', {orders: group.map(Number)}, config);
    if (!Array.isArray(data.orders)) throw new Error('НТЦ: отсутствуют статусы WB');
    const seen = new Set();
    data.orders.forEach(function(s) {
      const id = String(s.id), o = wbOrders[id]; if (!o) throw new Error('НТЦ: неожиданный статус WB'); seen.add(id);
      if (!s.supplierStatus || !s.wbStatus) throw new Error('НТЦ: неполный статус WB ' + id);
      const cancelled = s.supplierStatus === 'cancel' || ['canceled', 'canceled_by_client', 'declined'].indexOf(s.wbStatus) >= 0;
      const handed = ['complete', 'receive'].indexOf(s.supplierStatus) >= 0 || ['sold', 'sorted', 'ready_for_pickup'].indexOf(s.wbStatus) >= 0;
      const number = 'WB:' + id, item = {posting_number: number, status: cancelled ? 'cancelled' : handed ? 'delivering' : 'awaiting_packaging'};
      if (o.article) item.items = [{offer_id: String(o.article), quantity: 1}];
      // Cancellation can happen after physical shipment: without receipt proof keep reservation.
      if (cancelled) item.ever_handed_over = true;
      updates[number] = item;
    });
    if (seen.size !== group.length) throw new Error('НТЦ: WB вернул не все статусы');
  }
  return Object.keys(updates).map(function(k) { return updates[k]; });
}
function ntcFetchReturns_(state, config) {
  const numbers = Object.keys((state || {}).postings || {}).filter(function(k) { return k.indexOf('WB:') !== 0; }).sort(), found = [];
  // One group per scheduled run keeps old return history from exhausting daily quotas.
  const offset = numbers.length ? Math.floor(Number(config.returnCursor) || 0) % Math.ceil(numbers.length / 50) * 50 : 0;
  found.nextCursor = numbers.length ? (offset / 50 + 1) % Math.ceil(numbers.length / 50) : 0;
  for (let i = offset; i < Math.min(numbers.length, offset + 50); i += 50) {
    let last = 0;
    do {
      const data = ntcApi_('ozon', '/v1/returns/list', {filter: {posting_numbers: numbers.slice(i, i + 50)}, limit: 500, last_id: last}, config);
      if (!Array.isArray(data.returns)) throw new Error('НТЦ: отсутствует список возвратов');
      data.returns.forEach(function(r) {
        if (String(r.schema).toLowerCase() === 'fbs' && r.visual && r.visual.status && r.visual.status.sys_name === 'ReceivedBySeller') found.push(r);
      });
      if (!data.has_next) break;
      const id = data.returns.length && Number(data.returns[data.returns.length - 1].id);
      if (!id || id <= last) throw new Error('НТЦ: возвраты пагинация не продвигается'); last = id;
    } while (true);
  }
  return found;
}
function ntcChecksum_(value) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, JSON.stringify(value), Utilities.Charset.UTF_8)
    .map(function(b) { return ('0' + ((b + 256) % 256).toString(16)).slice(-2); }).join('');
}
function ntcPublish_(rows, config, deadline) {
  config = Object.assign({}, config, {deadline: deadline || config.deadline});
  const enabled = {ozon: config.ozonEnabled !== false, wb: config.wbEnabled !== false};
  if (enabled.ozon && !ntcPositiveId_(config.ozonWarehouseId) || enabled.wb && !ntcPositiveId_(config.wbWarehouseId)) throw new Error('НТЦ: склады для публикации не заданы');
  const offers = new Set(), chrts = new Set();
  rows.forEach(function(r) {
    if (!r.offer_id || enabled.ozon && !ntcPositiveId_(r.ozonSku) || enabled.wb && (!ntcPositiveId_(r.chrtId) || !ntcPositiveId_(r.wbSku)) || !Number.isSafeInteger(r.amount) || r.amount < 0 || offers.has(String(r.offer_id)) || enabled.wb && chrts.has(String(r.chrtId))) throw new Error('НТЦ: неполная/неоднозначная привязка или остаток, строка ' + r.row);
    offers.add(String(r.offer_id)); chrts.add(String(r.chrtId));
  });
  const props = PropertiesService.getScriptProperties(), runId = Utilities.getUuid(), failures = []; let confirmed = 0;
  ['ozon', 'wb'].forEach(function(platform) {
    if (!enabled[platform]) return;
    const warehouse = platform === 'ozon' ? config.ozonWarehouseId : config.wbWarehouseId;
    function key(r) { return 'NTC_MP_' + platform + '_' + warehouse + '_' + (platform === 'ozon' ? r.offer_id : r.chrtId); }
    const pending = rows.filter(function(r) { return props.getProperty(key(r)) !== String(r.amount); });
    const limit = platform === 'ozon' ? 100 : 1000;
    for (let i = 0; i < pending.length; i += limit) {
      ntcDeadline_(config.deadline); const batch = pending.slice(i, i + limit);
      const items = batch.map(function(r) { return {offerId: r.offer_id, chrtId: Number(r.chrtId), amount: r.amount}; });
      const checksum = ntcChecksum_({platform: platform, warehouseId: warehouse, items: items});
      const snapshotTimestamp = config.snapshotTimestamp || new Date().toISOString();
      const snapshotAgeMs = Date.now() - Date.parse(snapshotTimestamp);
      if (!Number.isFinite(snapshotAgeMs) || snapshotAgeMs < 0) throw new Error('НТЦ: некорректное время снимка остатков');
      const common = {runId: runId, script: 'ntc-cloud', platform: platform, warehouseId: warehouse, warehouseName: platform === 'ozon' ? config.ozonWarehouseName || 'НТЦ' : config.wbWarehouseName || 'НТЦ', batch: i / limit + 1, checksum: checksum, sourceColumn: 'Округлённое+прогруз на мп', snapshotTimestamp: snapshotTimestamp, snapshotAgeMs: snapshotAgeMs, items: items};
      if (platform === 'wb' && snapshotAgeMs > 900000) ntcAudit_(Object.assign({event: 'WB STALE SNAPSHOT'}, common));
      ntcAudit_(Object.assign({event: 'prepared'}, common));
      let response;
      try {
        response = platform === 'ozon' ? ntcApi_('ozon', '/v2/products/stocks', {stocks: batch.map(function(r) { return {offer_id: String(r.offer_id), stock: r.amount, warehouse_id: Number(warehouse)}; })}, config) : ntcApi_('wb', '/api/v3/stocks/' + warehouse, {stocks: items.map(function(r) { return {chrtId: r.chrtId, amount: r.amount}; })}, config, 'put');
        if (platform === 'ozon') {
          if (!Array.isArray(response.result)) throw new Error('НТЦ: Ozon не подтвердил результаты записи');
          batch.forEach(function(r) {
            const result = response.result.filter(function(x) { return String(x.offer_id) === String(r.offer_id); });
            const ok = result.length === 1 && result[0].updated === true && (!result[0].errors || !result[0].errors.length);
            ntcAudit_(Object.assign({}, common, {event: 'item_result', offerId: r.offer_id, success: ok}));
            if (ok) { props.setProperty(key(r), String(r.amount)); confirmed++; } else failures.push(platform + '/' + r.offer_id);
          });
        } else { batch.forEach(function(r) { props.setProperty(key(r), String(r.amount)); confirmed++; }); }
        ntcAudit_(Object.assign({event: 'result', success: platform === 'wb' || batch.every(function(r) { return props.getProperty(key(r)) === String(r.amount); })}, common));
      } catch (error) {
        ntcAudit_(Object.assign({event: 'result', success: false, httpCode: error.httpCode || null}, common));
        if (platform === 'wb' && error.httpCode === 409) {
          batch.forEach(function(r) {
            let ok = false, code = null;
            try {
              ntcDeadline_(config.deadline);
              ntcApi_('wb', '/api/v3/stocks/' + warehouse, {stocks: [{chrtId: Number(r.chrtId), amount: r.amount}]}, config, 'put');
              ok = true; props.setProperty(key(r), String(r.amount)); confirmed++;
            } catch (singleError) { code = singleError.httpCode || null; failures.push(platform + '/' + r.offer_id); }
            ntcAudit_(Object.assign({}, common, {event: 'item_result', offerId: r.offer_id, chrtId: Number(r.chrtId), amount: r.amount, success: ok, httpCode: code}));
          });
          continue;
        }
        batch.forEach(function(r) { failures.push(platform + '/' + r.offer_id); });
      }
    }
  });
  if (failures.length) throw new Error('НТЦ: не подтверждена публикация ' + failures.length + ' позиций; повтор в следующем запуске: ' + failures.slice(0, 5).join(', '));
  return {confirmed: confirmed, enabled: Object.keys(enabled).filter(function(p) { return enabled[p]; }), disabled: Object.keys(enabled).filter(function(p) { return !enabled[p]; })};
}
function ntcDiscoverWarehouses_(config) {
  const ozon = []; let cursor = '';
  do {
    const data = ntcApi_('ozon', '/v2/warehouse/list', {limit: 100, cursor: cursor}, config);
    if (!Array.isArray(data.warehouses)) throw new Error('НТЦ: некорректный список складов Ozon');
    data.warehouses.forEach(function(w) { if (ntcPositiveId_(w.warehouse_id)) ozon.push({id: Number(w.warehouse_id), name: String(w.name || '')}); });
    if (!data.has_next) break;
    const next = data.next_cursor || data.cursor || data.last_id;
    if (!next || next === cursor) throw new Error('НТЦ: пагинация складов не продвигается'); cursor = next;
  } while (true);
  const wb = ntcApi_('wb', '/api/v3/warehouses', undefined, config, 'get');
  if (!Array.isArray(wb)) throw new Error('НТЦ: некорректный список складов WB');
  const ozonMatches = ozon.filter(function(w) { return w.name.trim().toUpperCase() === 'НТЦ СКЛАД'; });
  if (ozonMatches.length !== 1) throw new Error('НТЦ: требуется единственный склад Ozon «НТЦ СКЛАД»');
  const wbMatches = wb.filter(function(w) {
    return config.wbWarehouseId ? String(w.id) === String(config.wbWarehouseId) : /^НТЦ(?:\s+СКЛАД)?$/i.test(String(w.name || '').trim());
  });
  if (wbMatches.length > 1) throw new Error('НТЦ: неоднозначный склад WB');
  return {ozon: ozonMatches[0], wb: wbMatches.length ? {id: Number(wbMatches[0].id), name: String(wbMatches[0].name)} : null};
}
/** Source service layouts are documented exceptions: ТЕСТ A key/E photo/V SKU;
 * TXOZ A offer/C multiplicity; ТЕХ данные wb A offer/B chrtID/C nmID.
 * Never imports physical stocks or formulas from the source workbook. */
function ntcEnrichCatalog_(sheet, config) {
  const grid = sheet.getDataRange().getValues(), headers = grid[0];
  const fields = {offer: ntcColumn_(headers, 'Артикул продавца'), photo: ntcColumn_(headers, 'ФОТО'), ozon: ntcColumn_(headers, 'SKU OZON'), wb: ntcColumn_(headers, 'SKU WB'), chrt: ntcColumn_(headers, 'chrlid'), size: ntcColumn_(headers, 'Х')};
  const catalog = {}, conflicts = [], targetOffers = new Set(grid.slice(1).map(function(r) { return String(r[fields.offer] || '').trim(); }).filter(Boolean));
  function add(offer, field, value) {
    offer = String(offer || '').trim(); if (!targetOffers.has(offer) || value === '' || value == null) return;
    if (field === 'photo') {
      if (typeof value !== 'string') return;
      value = ntcPhotoUrl_(value);
    }
    const item = catalog[offer] || (catalog[offer] = {});
    if (item[field] !== undefined && String(item[field]) !== String(value)) conflicts.push(offer + '/' + field);
    else item[field] = value;
  }
  if (config.sourceSpreadsheetId) {
    const source = SpreadsheetApp.openById(config.sourceSpreadsheetId);
    const main = source.getSheetByName('ТЕСТ') || source.getSheetByName('тест');
    if (main) {
      const range = main.getDataRange(), sourceRows = range.getValues(), formulas = range.getFormulas();
      sourceRows.slice(1).forEach(function(r, i) {
        const image = String((formulas[i + 1] || [])[4] || '').match(/^\s*=\s*IMAGE\s*\(\s*"((?:[^"]|"")*)"/i);
        const photo = image ? image[1].replace(/""/g, '"') : typeof r[4] === 'string' && /^https?:\/\//i.test(r[4]) ? r[4] : '';
        add(r[0], 'photo', photo); add(r[0], 'ozon', r[21]);
      });
    }
    const packs = source.getSheetByName('TXOZ');
    if (packs) packs.getDataRange().getValues().slice(1).forEach(function(r) { add(r[0], 'size', r[2]); });
    const wb = source.getSheetByName('ТЕХ данные wb');
    if (wb) wb.getDataRange().getValues().slice(1).forEach(function(r) { add(r[0], 'chrt', r[1]); add(r[0], 'wb', r[2]); });
  }
  if (conflicts.length) throw new Error('НТЦ: неоднозначная привязка источника: ' + conflicts.slice(0, 10).join(', '));
  const missingOzon = grid.slice(1).filter(function(r) { const c = catalog[String(r[fields.offer])] || {}; return r[fields.offer] && (!r[fields.ozon] && !c.ozon || !r[fields.photo] && !c.photo); }).map(function(r) { return String(r[fields.offer]); });
  for (let i = 0; i < missingOzon.length; i += 100) {
    const data = ntcApi_('ozon', '/v3/product/info/list', {offer_id: missingOzon.slice(i, i + 100)}, config);
    if (!Array.isArray(data.items)) throw new Error('НТЦ: неполный каталог Ozon');
    data.items.forEach(function(p) {
      const ids = Array.from(new Set((p.sources || []).map(function(s) { return Number(s.sku); }).filter(ntcPositiveId_)));
      if (ntcPositiveId_(p.sku)) add(p.offer_id, 'ozon', p.sku);
      else if (ids.length === 1) add(p.offer_id, 'ozon', ids[0]);
      else if (ids.length > 1) throw new Error('НТЦ: несколько SKU Ozon у ' + p.offer_id);
      const photo = Array.isArray(p.primary_image) ? p.primary_image[0] : p.primary_image;
      if (photo) add(p.offer_id, 'photo', photo);
    });
  }
  const missingWb = new Set(grid.slice(1).filter(function(r) { const c = catalog[String(r[fields.offer])] || {}; return r[fields.offer] && (!r[fields.wb] && !c.wb || !r[fields.chrt] && !c.chrt); }).map(function(r) { return String(r[fields.offer]); }));
  if (missingWb.size) {
    let cursor = {limit: 100}, previous = '';
    do {
      const data = ntcApi_('wbContent', '/content/v2/get/cards/list', {settings: {cursor: cursor, filter: {withPhoto: -1}}}, config);
      if (!Array.isArray(data.cards) || !data.cursor) throw new Error('НТЦ: неполный каталог WB');
      data.cards.filter(function(c) { return missingWb.has(String(c.vendorCode)); }).forEach(function(c) {
        const sizes = c.sizes || [];
        if (sizes.length !== 1 || !ntcPositiveId_(sizes[0].chrtID)) throw new Error('НТЦ: неоднозначный размер WB ' + c.vendorCode);
        add(c.vendorCode, 'chrt', sizes[0].chrtID); add(c.vendorCode, 'wb', c.nmID);
      });
      if (Number(data.cursor.total) < 100) break;
      cursor = {limit: 100, updatedAt: data.cursor.updatedAt, nmID: data.cursor.nmID};
      const signature = JSON.stringify(cursor); if (signature === previous || !data.cards.length) throw new Error('НТЦ: каталог WB пагинация не продвигается'); previous = signature;
    } while (true);
  }
  if (conflicts.length) throw new Error('НТЦ: неоднозначная привязка API: ' + conflicts.slice(0, 10).join(', '));
  const changes = [];
  grid.slice(1).forEach(function(r, index) {
    const offer = String(r[fields.offer] || '').trim(), item = catalog[offer]; if (!item) return;
    ['photo', 'ozon', 'wb', 'chrt', 'size'].forEach(function(field) {
      const value = item[field]; if (value === undefined || r[fields[field]] !== '') return;
      if (field !== 'photo' && !ntcPositiveId_(value)) throw new Error('НТЦ: некорректная привязка ' + offer + '/' + field);
      changes.push({row: index + 2, col: fields[field] + 1, value: value, photo: field === 'photo'});
    });
  });
  // All source/API ambiguity is checked before the first write; stock/formula fields untouched.
  changes.forEach(function(c) {
    const range = sheet.getRange(c.row, c.col);
    if (c.photo) range.setFormula('=IMAGE("' + c.value.replace(/"/g, '""') + '")');
    else range.setValue(c.value);
  });
  return {updated: changes.length};
}
function ntcPhotoUrl_(value) {
  if (typeof value !== 'string' || !/^https:\/\/[a-z0-9.-]+(?::\d+)?(?:\/|$)/i.test(value) || /[\s<>\u0000-\u001f]/.test(value)) throw new Error('НТЦ: фото должно быть HTTPS URL');
  return value;
}

/** WB order cursors are nanosecond int64 values. Keep their exact JSON digits. */
function ntcParseApiJson_(raw) {
  return JSON.parse(String(raw).replace(/("next"\s*:\s*)(\d{16,})(?=\s*[,}])/g, '$1"$2"'));
}
