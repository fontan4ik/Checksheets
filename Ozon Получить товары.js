function syncOfferIdWithProductId() {
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

function syncOfferIdWithProductIdCore_() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) return; // nothing to process

  // Read existing data into memory
  const offerIds = sheet.getRange(2, 1, lastRow - 1).getValues().flat(); // column A
  const productIds = sheet.getRange(2, 21, lastRow - 1).getValues().flat(); // column U (21) - Product_id Ozon

  // Map offerId -> row index in the sheet
  const offerMap = new Map();
  const sheetData = [];
  offerIds.forEach((id, index) => {
    const trimmedId = id.toString().trim();
    if (trimmedId) {
      offerMap.set(trimmedId, index); // 0-based index in sheetData
      sheetData.push({ offerId: trimmedId, productId: productIds[index] || "" });
    } else {
      sheetData.push({ offerId: "", productId: productIds[index] || "" });
    }
  });

  const limit = 1000;
  let last_id = "";
  let processedCount = 0;
  let lastRequestTime = Date.now() - 1000 / RPS();

  const newRowsToAdd = []; // store new rows to add at the end

  while (true) {
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

    const payload = { filter: {}, limit: limit, last_id: last_id };
    const options = {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify(payload),
    };

    const response = retryFetch(ozonProductsApiURL(), options);

    if (!response) {
      Logger.log(`❌ Не удалось получить данные с Ozon API (last_id: ${last_id})`);
      break;
    }

    const json = JSON.parse(response.getContentText());
    const items = json?.result?.items || [];

    if (!items.length) break;

    items.forEach(product => {
      const offerId = (product.offer_id || "").trim();
      const productId = product.product_id;

      if (!offerId || !productId) return;

      if (offerMap.has(offerId)) {
        // update existing row in memory
        const index = offerMap.get(offerId);
        if (sheetData[index].productId !== productId) {
          sheetData[index].productId = productId;
          processedCount++;
        }
      } else {
        // schedule new row
        newRowsToAdd.push({ offerId, productId });
        processedCount++;
      }
    });

    if (items.length < limit) break;
    last_id = json.result.last_id || "";
  }

  // Write updates back to sheet in batch
  const productColumnRange = sheet.getRange(2, 21, sheetData.length, 1); // U (21): Product_id Ozon
  const updatedProductIds = sheetData.map(row => [row.productId]);
  productColumnRange.setValues(updatedProductIds);

  // Добавляем новые товары сразу после последнего артикула в A. getLastRow()
  // здесь использовать нельзя: формулы в других колонках могут создать
  // большой пустой разрыв перед новыми товарами.
  if (newRowsToAdd.length > 0) {
    let lastOfferIndex = -1;
    for (let i = offerIds.length - 1; i >= 0; i--) {
      if (String(offerIds[i] || "").trim()) {
        lastOfferIndex = i;
        break;
      }
    }
    const startRow = lastOfferIndex >= 0 ? lastOfferIndex + 3 : 2;
    const newOfferIds = newRowsToAdd.map(row => [row.offerId]);
    const newProductIds = newRowsToAdd.map(row => [row.productId]);
    const requiredLastRow = startRow + newRowsToAdd.length - 1;

    if (requiredLastRow > sheet.getMaxRows()) {
      sheet.insertRowsAfter(sheet.getMaxRows(), requiredLastRow - sheet.getMaxRows());
    }

    // Insert new offerIds in column A
    sheet.getRange(startRow, 1, newOfferIds.length, 1).setValues(newOfferIds);
    // Insert corresponding productIds in column U (21)
    sheet.getRange(startRow, 21, newProductIds.length, 1).setValues(newProductIds);
  }

  Logger.log(`Синхронизация завершена. Обработано строк: ${processedCount}`);
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
