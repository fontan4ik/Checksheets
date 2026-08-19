/**
 * Агрегирует значение Ozon Seller UI «Доступно к продаже» по offer_id.
 * /v1/analytics/stocks возвращает отдельную строку на склад, поэтому один
 * offer_id может встречаться несколько раз в одном ответе.
 */
function aggregateFBOAvailableStocksByOffer(items) {
  const stockMap = {};

  (items || []).forEach(item => {
    const offerId = item?.offer_id === null || item?.offer_id === undefined
      ? ""
      : String(item.offer_id).trim();
    if (!offerId) return;

    const available = Number(item.available_stock_count);
    if (!Object.prototype.hasOwnProperty.call(stockMap, offerId)) {
      stockMap[offerId] = 0;
    }
    if (Number.isFinite(available)) {
      stockMap[offerId] += available;
    }
  });

  return stockMap;
}

function updateStockFBO() {
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
      previousFbo: row[5],
      sku: Number.isFinite(skuNumber) && skuNumber > 0 ? skuNumber : null
    };
  });

  const validRows = rowData.filter(row => row.offerId && row.sku);
  const skus = [...new Set(validRows.map(row => row.sku))];
  const batchSize = 100;
  const apiItems = [];
  const failedSkus = new Set();
  let lastRequestTime = Date.now() - 1000 / RPS();

  Logger.log("=== ОБНОВЛЕНИЕ FBO: ДОСТУПНО К ПРОДАЖЕ (F, 6) ===");
  Logger.log(`Строк с offer_id: ${rowData.filter(row => row.offerId).length}`);
  Logger.log(`Уникальных SKU для Ozon Analytics: ${skus.length}`);

  for (let i = 0; i < skus.length; i += batchSize) {
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
        continue;
      }

      const json = JSON.parse(response.getContentText());
      if (!Array.isArray(json.items)) {
        throw new Error("В ответе Ozon отсутствует массив items");
      }
      apiItems.push(...json.items);
    } catch (error) {
      Logger.log(`❌ Ошибка FBO Analytics для батча ${i + 1}-${i + batch.length}: ${error.message}`);
      batch.forEach(sku => failedSkus.add(sku));
    }
  }

  const stockMap = aggregateFBOAvailableStocksByOffer(apiItems);
  const valuesToWrite = rowData.map(row => {
    if (!row.offerId) return [""];
    if (!row.sku || failedSkus.has(row.sku)) return [row.previousFbo];
    return [stockMap[row.offerId] ?? 0];
  });

  sheet.getRange(2, 6, valuesToWrite.length, 1).setValues(valuesToWrite);

  Logger.log(`Ответов по складским строкам: ${apiItems.length}`);
  Logger.log(`Offer_id с доступным остатком: ${Object.keys(stockMap).length}`);
  Logger.log(`Неуспешных SKU-батчей: ${failedSkus.size ? "есть" : "нет"}`);
  Logger.log("✅ Колонка F обновлена значением Ozon «Доступно к продаже».");

  // Обновляем G отдельным FBS-контуром, как и раньше.
  updateAllFBSStocks();
}

/**
 * ИСПРАВЛЕНИЕ: Обновляет G (7) - сумму ВСЕХ FBS складов
 * Не только конкретного склада Москва
 */
function updateAllFBSStocks() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) return;

  // Читаем product_id из U (21)
  const fullProductIds = sheet.getRange(2, 21, lastRow - 1).getValues().flat();
  const validProductIds = fullProductIds
    .filter(id => id !== '' && id !== null && id !== undefined && id > 0);

  const batchSize = 1000;
  const fbsMap = {};
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
      const json = JSON.parse(response.getContentText());
      const items = json.items || [];

      items.forEach(item => {
        const pid = item.product_id;
        // СУММИРУЕМ ВСЕ FBS остатки (не только по конкретному складу)
        const fbsStocks = item.stocks?.filter(s => s.type === 'fbs') || [];
        const totalFbs = fbsStocks.reduce((sum, s) => sum + (s.present || 0), 0);
        if (pid) fbsMap[pid] = totalFbs;
      });
    } catch (e) {
      Logger.log("Ошибка при получении FBS: " + e.message);
    }
  }

  // Записываем в G (7) - ИСПРАВЛЕНО: пишем для ВСЕХ строк
  const valuesToWrite = fullProductIds.map(pid => {
    const key = pid?.toString();
    // Проверяем: ключ есть в fbsMap И product_id валидный
    if (key && key !== "" && pid !== '' && pid !== null && pid !== undefined && pid > 0) {
      return [fbsMap[key] ?? 0];
    }
    return [0];
  });

  sheet.getRange(2, 7, valuesToWrite.length, 1).setValues(valuesToWrite);
  Logger.log("Остатки FBS (G, 7) обновлены - сумма всех FBS складов.");
}