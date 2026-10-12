function syncOfferIdWithProductId() {
  return runWithTelegramAlertGAS_("syncOfferIdWithProductId", syncOfferIdWithProductIdAlertCore_);
}

function syncOfferIdWithProductIdAlertCore_() {
  return runWithOzonProductSyncLock_("syncOfferIdWithProductId", function() {
    return syncOfferIdWithProductIdCore_();
  });
}

/**
 * Общий lock для существующих триггеров товарной синхронизации Ozon.
 * Если другой товарный процесс уже выполняется, дублирующий запуск пропускается.
 */
function runWithOzonProductSyncLock_(sourceName, callback) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) {
    Logger.log(`⚠️ ${sourceName}: товарная синхронизация уже выполняется, повторный запуск пропущен.`);
    return false;
  }

  try {
    callback();
    return true;
  } finally {
    lock.releaseLock();
  }
}

// Both legacy OzonMain and the dedicated trigger continue this same catalog scan.
const OZON_PRODUCT_LIST_CURSOR_KEY = "OZON_PRODUCT_LIST_CURSOR";
const OZON_PRODUCT_LIST_MAX_RUN_MS = 3 * 60 * 1000;

function syncOfferIdWithProductIdCore_() {
  const startedAt = Date.now();
  const sheet = mainSheet();
  const productColumn = columnByHeader_(sheet, "Product_id Ozon");
  const rowCount = Math.max(0, sheet.getLastRow() - 1);
  const offerIds = rowCount ? sheet.getRange(2, 1, rowCount, 1).getValues().flat() : [];
  const productIds = rowCount ? sheet.getRange(2, productColumn, rowCount, 1).getValues().flat() : [];
  const offerMap = new Map();
  offerIds.forEach((value, index) => {
    const offerId = String(value == null ? "" : value).trim();
    if (!offerId) return;
    if (!offerMap.has(offerId)) offerMap.set(offerId, []);
    offerMap.get(offerId).push(index);
  });
  let lastOfferIndex = offerIds.length - 1;
  while (lastOfferIndex >= 0 && !String(offerIds[lastOfferIndex] || "").trim()) lastOfferIndex--;

  const props = PropertiesService.getScriptProperties();
  const scope = sheet.getParent().getId() + ":" + sheet.getSheetId();
  const savedRaw = props.getProperty(OZON_PRODUCT_LIST_CURSOR_KEY);
  const saved = savedRaw ? JSON.parse(savedRaw) : null;
  let cursor = saved && saved.scope === scope ? String(saved.cursor || "") : "";
  const seenCursors = new Set([cursor]);
  const limit = 1000;
  let pages = 0;
  let added = 0;
  let updated = 0;
  let lastRequestTime = Date.now() - 1000 / RPS();

  // Commit every page before advancing the cursor. A retry can repair A/U
  // after a partial write without adding the same offer_id a second time.
  while (Date.now() - startedAt < OZON_PRODUCT_LIST_MAX_RUN_MS) {
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());
    const response = retryFetch(ozonProductsApiURL(), {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify({ filter: {}, limit: limit, last_id: cursor }),
      muteHttpExceptions: true
    }, 1);
    if (!response || response.getResponseCode() === 429 || response.getResponseCode() >= 500) {
      props.setProperty(OZON_PRODUCT_LIST_CURSOR_KEY, JSON.stringify({ scope: scope, cursor: cursor }));
      Logger.log("Ozon A/U: временная ошибка API; следующий штатный запуск продолжит тот же пакет.");
      return { complete: false, added: added, updated: updated };
    }
    const code = response.getResponseCode();
    if (code < 200 || code >= 300) throw new Error("Ozon A/U: HTTP " + code);
    const json = JSON.parse(response.getContentText());
    if (!json.result || !Array.isArray(json.result.items)) {
      throw new Error("Ozon A/U: ответ не содержит result.items; курсор сохранён.");
    }
    const items = json.result.items;
    const nextCursor = String(json.result.last_id || "");
    const complete = items.length < limit;
    if (!complete && (!nextCursor || seenCursors.has(nextCursor))) {
      throw new Error("Ozon A/U: пагинация не продвигается; повторная страница не записана.");
    }
    const validated = items.map(product => {
      const offerId = String(product.offer_id == null ? "" : product.offer_id).trim();
      const productId = Number(product.product_id);
      if (!offerId || !Number.isSafeInteger(productId) || productId <= 0) {
        throw new Error("Ozon A/U: товар без корректных offer_id/product_id; пакет не записан.");
      }
      return { offerId: offerId, productId: productId };
    });
    const newRows = [];
    const newOffers = new Map();
    let existingChanged = false;
    validated.forEach(product => {
      if (offerMap.has(product.offerId)) {
        offerMap.get(product.offerId).forEach(index => {
          if (String(productIds[index]) !== String(product.productId)) {
            productIds[index] = product.productId;
            existingChanged = true;
            updated++;
          }
        });
      } else if (newOffers.has(product.offerId)) {
        if (newOffers.get(product.offerId) !== product.productId) {
          throw new Error("Ozon A/U: разные product_id для одного offer_id.");
        }
      } else {
        newOffers.set(product.offerId, product.productId);
        newRows.push(product);
      }
    });
    if (existingChanged && productIds.length) {
      sheet.getRange(2, productColumn, productIds.length, 1).setValues(productIds.map(value => [value]));
    }
    if (newRows.length) {
      const startRow = lastOfferIndex + 3;
      const requiredLastRow = startRow + newRows.length - 1;
      if (requiredLastRow > sheet.getMaxRows()) {
        sheet.insertRowsAfter(sheet.getMaxRows(), requiredLastRow - sheet.getMaxRows());
      }
      sheet.getRange(startRow, 1, newRows.length, 1).setNumberFormat('@');
      sheet.getRange(startRow, 1, newRows.length, 1).setValues(newRows.map(product => [product.offerId]));
      sheet.getRange(startRow, productColumn, newRows.length, 1).setValues(newRows.map(product => [product.productId]));
      newRows.forEach(product => {
        lastOfferIndex++;
        offerIds[lastOfferIndex] = product.offerId;
        productIds[lastOfferIndex] = product.productId;
        offerMap.set(product.offerId, [lastOfferIndex]);
      });
      added += newRows.length;
    }
    pages++;
    if (complete) {
      props.deleteProperty(OZON_PRODUCT_LIST_CURSOR_KEY);
      Logger.log(`Ozon A/U: полный проход завершён; страниц ${pages}, добавлено ${added}, обновлено ${updated}.`);
      return { complete: true, added: added, updated: updated };
    }
    cursor = nextCursor;
    seenCursors.add(cursor);
    props.setProperty(OZON_PRODUCT_LIST_CURSOR_KEY, JSON.stringify({ scope: scope, cursor: cursor }));
  }
  Logger.log(`Ozon A/U: бюджет времени исчерпан; добавлено ${added}, обновлено ${updated}. Следующий штатный запуск продолжит проход.`);
  return { complete: false, added: added, updated: updated };
}

/**
 * Одноразовое исправление уже существующих пустых разрывов между товарами.
 * Удаляет целые строки, где первичный ключ A пуст, но ниже ещё есть товары.
 * Все остальные колонки сдвигаются вместе, поэтому данные остаются выровнены.
 */
function removeEmptyProductRowGaps() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();
  if (lastRow < 3) {
    Logger.log("Пустых разрывов нет.");
    return;
  }

  const offerIds = sheet.getRange(2, 1, lastRow - 1, 1).getValues().flat();
  let lastOfferIndex = -1;
  for (let i = offerIds.length - 1; i >= 0; i--) {
    if (String(offerIds[i] || "").trim()) {
      lastOfferIndex = i;
      break;
    }
  }

  if (lastOfferIndex < 0) {
    Logger.log("В колонке A нет товаров.");
    return;
  }

  const blocks = [];
  let blockStart = -1;
  for (let i = 0; i <= lastOfferIndex; i++) {
    const isEmpty = !String(offerIds[i] || "").trim();
    if (isEmpty && blockStart < 0) blockStart = i;
    if (!isEmpty && blockStart >= 0) {
      blocks.push({ startRow: blockStart + 2, count: i - blockStart });
      blockStart = -1;
    }
  }

  let deletedCount = 0;
  for (let i = blocks.length - 1; i >= 0; i--) {
    sheet.deleteRows(blocks[i].startRow, blocks[i].count);
    deletedCount += blocks[i].count;
  }

  Logger.log(`✅ Удалено пустых строк внутри таблицы: ${deletedCount}`);
}
