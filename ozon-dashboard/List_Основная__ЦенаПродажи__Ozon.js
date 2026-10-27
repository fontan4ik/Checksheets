function ozonDashboardSyncPrices_(sheet, state) {
  const offerColumn = ozonDashboardColumnByHeader_(sheet, OZON_DASHBOARD_TARGET_HEADERS_.offerId);
  const priceColumn = ozonDashboardColumnByHeader_(sheet, OZON_DASHBOARD_TARGET_HEADERS_.price);
  const rowCount = Math.max(0, state.lastRow - 1);
  if (!rowCount) {
    Logger.log('Лист «' + sheet.getName() + '» не содержит строк товаров для цен.');
    return;
  }

  const offerIds = sheet.getRange(2, offerColumn, rowCount, 1).getValues()
    .map(function(row) { return ozonDashboardValidOfferId_(row[0]); });
  const uniqueOffers = [];
  const seen = Object.create(null);
  offerIds.forEach(function(offerId) {
    if (offerId && !seen[offerId]) {
      seen[offerId] = true;
      uniqueOffers.push(offerId);
    }
  });

  const priceByOffer = Object.create(null);
  const batchSize = 1000;
  let requestCount = 0;
  for (let offset = 0; offset < uniqueOffers.length; offset += batchSize) {
    const batch = uniqueOffers.slice(offset, offset + batchSize);
    let cursor = '';
    const seenCursors = Object.create(null);
    let pageCount = 0;
    do {
      const data = ozonDashboardPostJson_(
        OZON_DASHBOARD_API_.prices,
        {
          cursor: cursor,
          filter: {offer_id: batch, visibility: 'ALL'},
          limit: batchSize
        },
        state,
        250
      );
      const items = Array.isArray(data.items) ? data.items :
        (data.result && Array.isArray(data.result.items) ? data.result.items : null);
      if (!items) throw new Error('Ozon prices API: в ответе нет массива items');

      items.forEach(function(item) {
        const offerId = ozonDashboardValidOfferId_(item && item.offer_id);
        const amount = Number(item && item.price && item.price.price);
        if (!offerId || !isFinite(amount) || amount < 0) return;
        priceByOffer[offerId] = amount;
      });

      pageCount++;
      if (pageCount > 20) throw new Error('Ozon prices API: слишком много страниц для одного набора offer_id');
      const nextCursor = String(data.cursor || '').trim();
      if (nextCursor && (nextCursor === cursor || seenCursors[nextCursor])) {
        throw new Error('Ozon prices API: курсор пагинации не продвигается');
      }
      if (nextCursor) seenCursors[nextCursor] = true;
      cursor = nextCursor;
      requestCount++;
    } while (cursor);
  }

  const existingValues = sheet.getRange(2, priceColumn, rowCount, 1).getValues();
  const writeValues = [];
  const selected = [];
  let matched = 0;
  for (let index = 0; index < rowCount; index++) {
    const offerId = offerIds[index];
    const hasPrice = offerId && Object.prototype.hasOwnProperty.call(priceByOffer, offerId);
    writeValues.push(hasPrice ? priceByOffer[offerId] : existingValues[index][0]);
    selected.push(Boolean(hasPrice));
    if (hasPrice) matched++;
  }

  const written = ozonDashboardWriteColumn_(sheet, priceColumn, 2, writeValues, selected);
  Logger.log(JSON.stringify({
    service: 'Ozon prices',
    runId: state.runId,
    offers: uniqueOffers.length,
    matched: matched,
    cellsWritten: written,
    requests: requestCount
  }));
}

function ozonDashboardPostJson_(url, payload, state, minimumIntervalMs) {
  const maxAttempts = 3;
  let lastError = null;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    const previousAt = Number(state.lastOzonRequestAt || 0);
    const waitMs = minimumIntervalMs - (Date.now() - previousAt);
    if (waitMs > 0) Utilities.sleep(waitMs);

    let response = null;
    try {
      response = UrlFetchApp.fetch(url, {
        method: 'post',
        contentType: 'application/json',
        headers: ozonDashboardHeaders_(),
        payload: JSON.stringify(payload),
        muteHttpExceptions: true
      });
    } catch (error) {
      state.lastOzonRequestAt = Date.now();
      PropertiesService.getScriptProperties().setProperty(
        OZON_DASHBOARD_STATE_KEY_, JSON.stringify(state)
      );
      lastError = error;
      lastError.ozonTransient = true;
      if (attempt + 1 >= maxAttempts) break;
      Utilities.sleep(Math.max(2000 * Math.pow(2, attempt), minimumIntervalMs));
      continue;
    }

    state.lastOzonRequestAt = Date.now();
    PropertiesService.getScriptProperties().setProperty(
      OZON_DASHBOARD_STATE_KEY_, JSON.stringify(state)
    );
    const status = response.getResponseCode();
    const body = response.getContentText();
    if (status >= 200 && status < 300) {
      try {
        return JSON.parse(body);
      } catch (error) {
        throw new Error('Ozon API вернул некорректный JSON (' + status + ')');
      }
    }

    lastError = new Error('Ozon API HTTP ' + status + ': ' + body.substring(0, 400));
    if (status === 408 || status === 429 || status >= 500) {
      lastError.ozonRetryable = true;
      lastError.retryAfterMs = ozonDashboardRetryAfterMs_(response);
    }
    if (!(status === 408 || status === 429 || status >= 500) || attempt + 1 >= maxAttempts) break;
    Utilities.sleep(Math.max(5000 * Math.pow(2, attempt), minimumIntervalMs, lastError.retryAfterMs || 0));
  }
  throw lastError || new Error('Не удалось выполнить запрос Ozon API');
}

function ozonDashboardRetryAfterMs_(response) {
  let headers = {};
  try {
    headers = response.getAllHeaders ? response.getAllHeaders() :
      (response.getHeaders ? response.getHeaders() : {});
  } catch (error) {
    return 0;
  }
  const retryAfter = Object.keys(headers || {}).reduce(function(value, key) {
    return String(key).toLowerCase() === 'retry-after' ? headers[key] : value;
  }, null);
  if (retryAfter === null || retryAfter === undefined) return 0;
  const seconds = Number(retryAfter);
  if (isFinite(seconds) && seconds >= 0) return seconds * 1000;
  const dateMs = Date.parse(String(retryAfter));
  return isFinite(dateMs) ? Math.max(0, dateMs - Date.now()) : 0;
}
