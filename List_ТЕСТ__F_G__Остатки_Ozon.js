/**
 * Агрегирует значение Ozon Seller UI «Доступно к продаже» по offer_id.
 * /v1/analytics/stocks возвращает отдельную строку на склад, поэтому один
 * offer_id может встречаться несколько раз в одном ответе.
 */
function aggregateFBOAvailableStocksByOffer(items) {
  const stockMap = {};

  if (!Array.isArray(items)) throw new Error("В ответе Ozon отсутствует массив items");
  items.forEach(item => {
    const offerId = item?.offer_id === null || item?.offer_id === undefined
      ? ""
      : String(item.offer_id).trim();
    if (!offerId) throw new Error("Ozon FBO вернул товар без offer_id");

    const availableRaw = item?.available_stock_count;
    const available = Number(availableRaw);
    if (availableRaw === null || availableRaw === undefined || availableRaw === "" ||
        !Number.isSafeInteger(available) || available < 0) {
      throw new Error(`Ozon FBO вернул некорректный available_stock_count для ${offerId}`);
    }
    if (!Object.prototype.hasOwnProperty.call(stockMap, offerId)) {
      stockMap[offerId] = 0;
    }
    stockMap[offerId] += available;
  });

  return stockMap;
}

function updateStockFBO() {
  return runWithTelegramAlertGAS_('updateStockFBO', updateStockFBO_);
}

function updateStockFBO_() {
  const startedAt = Date.now();
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) return;

  // A = offer_id, F = текущий FBO, V = seller SKU для /v1/analytics/stocks.
  const rows = sheet.getRange(2, 1, lastRow - 1, 22).getValues();
  const rowData = rows.map(row => {
    const offerId = row[0] === null || row[0] === undefined
      ? ""
      : String(row[0]).trim();
    const skuNumber = Number(row[21]);

    return {
      offerId,
      sku: Number.isFinite(skuNumber) && skuNumber > 0 ? skuNumber : null
    };
  });

  const validRows = rowData.filter(row => row.offerId && row.sku);
  const skus = [...new Set(validRows.map(row => row.sku))];
  const cursorKey = 'OZON_FBO_STOCK_NEXT_SKU';
  const props = PropertiesService.getScriptProperties();
  const savedCursor = Number(props.getProperty(cursorKey)) || 0;
  const startIndex = savedCursor >= 0 && savedCursor < skus.length ? savedCursor : 0;
  let nextIndex = startIndex;
  const batchSize = 100;
  const apiItems = [];
  const failedSkus = new Set();
  const processedSkus = new Set();
  let lastRequestTime = Date.now() - 1000 / RPS();

  Logger.log("=== ОБНОВЛЕНИЕ FBO: ДОСТУПНО К ПРОДАЖЕ (F, 6) ===");
  Logger.log(`Строк с offer_id: ${rowData.filter(row => row.offerId).length}`);
  Logger.log(`Уникальных SKU для Ozon Analytics: ${skus.length}`);

  for (let i = startIndex; i < skus.length; i += batchSize) {
    // Штатный повторный запуск продолжит работу без дополнительного триггера.
    if (Date.now() - startedAt >= 3 * 60 * 1000) break;
    const batch = skus.slice(i, i + batchSize);
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

    const options = {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify({ skus: batch })
    };

    try {
      const response = retryFetch(ozonFBOAvailableStocksApiURL(), options);

      if (!response) {
        Logger.log(`❌ Не удалось получить FBO available_stock_count для батча ${i + 1}-${i + batch.length}`);
        batch.forEach(sku => failedSkus.add(sku));
        break;
      }

      const responseCode = response.getResponseCode();
      if (responseCode < 200 || responseCode >= 300) {
        throw new Error(`Ozon FBO HTTP ${responseCode}: ${response.getContentText().substring(0, 300)}`);
      }
      const json = JSON.parse(response.getContentText());
      if (!Array.isArray(json.items)) {
        throw new Error("В ответе Ozon отсутствует массив items");
      }
      const requested = new Set(batch.map(String));
      json.items.forEach(item => {
        const sku = Number(item?.sku);
        const offerId = String(item?.offer_id ?? "").trim();
      const availableRaw = item?.available_stock_count;
      const available = Number(availableRaw);
      if (!Number.isFinite(sku) || !requested.has(String(sku)) || !offerId ||
          availableRaw === null || availableRaw === undefined || availableRaw === "" ||
          !Number.isSafeInteger(available) || available < 0) {
          throw new Error("Ozon FBO вернул неполную или неожиданную запись товара");
        }
      });
      apiItems.push(...json.items);
      batch.forEach(sku => processedSkus.add(sku));
      nextIndex = i + batch.length;
    } catch (error) {
      Logger.log(`❌ Ошибка FBO Analytics для батча ${i + 1}-${i + batch.length}: ${error.message}`);
      batch.forEach(sku => failedSkus.add(sku));
      break;
    }
  }

  const stockMap = aggregateFBOAvailableStocksByOffer(apiItems);
  const writeMask = rowData.map(row => Boolean(
    row.offerId && row.sku && processedSkus.has(row.sku) &&
    Object.prototype.hasOwnProperty.call(stockMap, row.offerId)
  ));
  const valuesToWrite = rowData.map((row, index) => [writeMask[index] ? stockMap[row.offerId] : ""]);
  const written = writeMaskedColumnValues_(
    sheet,
    columnByHeader_(sheet, 'Остаток ФБО ОЗОН'),
    valuesToWrite,
    writeMask,
  );
  if (nextIndex < skus.length) props.setProperty(cursorKey, String(nextIndex));
  else props.deleteProperty(cursorKey);

  Logger.log(`Ответов по складским строкам: ${apiItems.length}`);
  Logger.log(`Offer_id с доступным остатком: ${Object.keys(stockMap).length}`);
  Logger.log(`Неуспешных SKU-батчей: ${failedSkus.size ? "есть" : "нет"}`);
  Logger.log(`✅ Колонка F обновлена значением Ozon «Доступно к продаже»: записано ${written} полных строк.`);

  // G обновляет собственный существующий триггер updateAllFBSStocks.
  if (failedSkus.size) {
    throw new Error(`Ozon FBO: не получены остатки для ${failedSkus.size} SKU; прежние значения сохранены`);
  }
}

/**
 * ИСПРАВЛЕНИЕ: Обновляет G (7) - сумму ВСЕХ FBS складов
 * Не только конкретного склада Москва
 */
function updateAllFBSStocks() {
  return runWithTelegramAlertGAS_('updateAllFBSStocks', updateAllFBSStocks_);
}

function updateAllFBSStocks_() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) return;

  // Читаем product_id из U (21)
  const fullProductIds = sheet.getRange(2, 21, lastRow - 1).getValues().flat();
  const validProductIds = fullProductIds
    .filter(id => id !== '' && id !== null && id !== undefined && id > 0);

  const batchSize = 1000;
  const fbsMap = {};
  let failedBatches = 0;
  let lastRequestTime = Date.now() - 1000 / RPS();

  // Получаем данные из v4/product/info/stocks (тот же что для FBO)
  for (let i = 0; i < validProductIds.length; i += batchSize) {
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

    const batch = validProductIds.slice(i, i + batchSize);
    if (batch.length === 0) continue;

    const payload = {
      filter: { product_id: batch },
      limit: batch.length
    };

    const options = {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify(payload)
    };

    try {
      const response = retryFetch(ozonStocksApiURL(), options);
      if (!response) throw new Error("Ozon FBS не вернул ответ");
      const responseCode = response.getResponseCode();
      if (responseCode < 200 || responseCode >= 300) {
        throw new Error(`HTTP ${responseCode}: ${response.getContentText().substring(0, 300)}`);
      }
      const json = JSON.parse(response.getContentText());
      if (!Array.isArray(json.items)) throw new Error("В ответе Ozon FBS отсутствует массив items");
      const requested = new Set(batch.map(String));
      const seen = new Set();

      json.items.forEach(item => {
        const pid = String(item?.product_id ?? "").trim();
        if (!pid || !requested.has(pid) || seen.has(pid)) {
          throw new Error(`Ozon FBS вернул пустой, неожиданный или повторный product_id: ${pid}`);
        }
        if (!Array.isArray(item.stocks)) throw new Error(`Ozon FBS не вернул stocks для product_id ${pid}`);
        seen.add(pid);
        // СУММИРУЕМ ВСЕ FBS остатки (не только по конкретному складу)
        const totalFbs = item.stocks.reduce((sum, stock) => {
          if (!stock || typeof stock.type !== "string") {
            throw new Error(`Ozon FBS вернул неполную складскую запись для product_id ${pid}`);
          }
          const presentRaw = stock.present;
          const present = Number(presentRaw);
          if (presentRaw === null || presentRaw === undefined || presentRaw === "" ||
              !Number.isSafeInteger(present) || present < 0) {
            throw new Error(`Ozon FBS вернул некорректный остаток для product_id ${pid}`);
          }
          return sum + (stock.type === 'fbs' ? present : 0);
        }, 0);
        fbsMap[pid] = totalFbs;
      });
    } catch (e) {
      failedBatches++;
      Logger.log("Ошибка при получении FBS: " + e.message);
    }
  }

  if (failedBatches) {
    throw new Error(`Ozon FBS: не удалось получить ${failedBatches} батчей; прежние остатки сохранены`);
  }

  // Записываем в G (7) - ИСПРАВЛЕНО: пишем для ВСЕХ строк
  const writeMask = fullProductIds.map(pid => Object.prototype.hasOwnProperty.call(fbsMap, String(pid)));
  const valuesToWrite = fullProductIds.map((pid, index) => [writeMask[index] ? fbsMap[String(pid)] : ""]);
  const written = writeMaskedColumnValues_(
    sheet,
    columnByHeader_(sheet, 'Остаток ФБС ОЗОН'),
    valuesToWrite,
    writeMask,
  );
  Logger.log(`Остатки FBS (G, 7) обновлены: записано ${written} полных строк.`);
}
