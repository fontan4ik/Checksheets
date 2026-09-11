function getOzonPricesOptimized() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();
  const minPriceColumn = 70; // BR — Цена для минимального бустинга Ozon

  sheet.getRange(1, minPriceColumn).setValue("Цена мин. бустинга Ozon");

  if (lastRow < 2) {
    Logger.log("Ozon цены: в листе нет строк товаров");
    return;
  }

  // ИСПРАВЛЕНО: читаем product_id из U (21), а не из R (18)
  const productIdRange = sheet.getRange("U2:U" + lastRow).getValues();
  const productIds = productIdRange.map(r => r[0]).filter(id => id !== '' && id !== null && id !== undefined && id > 0 && !isNaN(id));
  const rowIndexes = productIdRange.map((r, i) => [r[0], i + 2]); // [product_id, rowNumber]

  const priceMap = {};
  const chunkSize = 1000;
  let apiErrorCount = 0;
  let ozonProductsCount = 0;
  let requestCount = 0;
  let completeSuccess = true;

  let lastRequestTime = Date.now() - 1000 / RPS();

  // Итерации
  for (let i = 0; i < productIds.length; i += chunkSize) {
    const chunk = productIds.slice(i, i + chunkSize);
    let cursor = "";
    let pageNumber = 0;
    const seenCursors = {};

    do {
      lastRequestTime = rateLimitRPS(lastRequestTime, RPS());
      const payload = JSON.stringify({
        cursor: cursor,
        filter: { product_id: chunk.map(Number), visibility: "ALL" },
        limit: chunkSize
      });

      const options = {
        method: "post",
        contentType: "application/json",
        headers: ozonHeaders(),
        payload: payload,
        muteHttpExceptions: true
      };

      requestCount++;
      const response = retryFetch(ozonPricesApiURL(), options);

      if (!response) {
        apiErrorCount++;
        completeSuccess = false;
        Logger.log("❌ Не удалось получить цены Ozon для батча " + (Math.floor(i / chunkSize) + 1));
        break;
      }

      const responseCode = response.getResponseCode();
      if (responseCode < 200 || responseCode >= 300) {
        apiErrorCount++;
        completeSuccess = false;
        Logger.log("❌ Ozon /v5/product/info/prices: HTTP " + responseCode + " " + response.getContentText().substring(0, 500));
        break;
      }

      let data;
      try {
        data = JSON.parse(response.getContentText());
      } catch (error) {
        apiErrorCount++;
        completeSuccess = false;
        Logger.log("❌ Ozon /v5/product/info/prices вернул некорректный JSON: " + error);
        break;
      }

      const items = data.items || (data.result && data.result.items) || [];
      ozonProductsCount += items.length;
      items.forEach(item => {
        const productId = item.product_id;
        if (productId === null || productId === undefined || productId === "") return;

        const p = item.price || {};
        let price = "";
        if (p.marketing_seller_price !== null && p.marketing_seller_price !== undefined && p.marketing_seller_price !== "") {
          price = p.marketing_seller_price;
        } else if (p.price_before !== null && p.price_before !== undefined && p.price_before !== "") {
          price = p.price_before;
        } else if (p.price !== null && p.price !== undefined && p.price !== "") {
          price = p.price;
        }

        priceMap[productId] = price;
      });

      pageNumber++;
      const nextCursor = String(data.cursor || "");
      if (nextCursor && nextCursor === cursor) {
        apiErrorCount++;
        completeSuccess = false;
        Logger.log("❌ Ozon pagination не продвигается для батча " + (Math.floor(i / chunkSize) + 1));
        break;
      }
      if (nextCursor && seenCursors[nextCursor]) {
        apiErrorCount++;
        completeSuccess = false;
        Logger.log("❌ Ozon pagination зациклилась для батча " + (Math.floor(i / chunkSize) + 1));
        break;
      }
      if (nextCursor) seenCursors[nextCursor] = true;
      cursor = nextCursor;
    } while (cursor);

    if (!completeSuccess) break;
    Logger.log("Обработан батч " + (Math.floor(i / chunkSize) + 1) + ", страниц: " + pageNumber);
  }

  // Собираем массив значений для записи
  const pricesToWrite = rowIndexes.map(([pid]) => [priceMap[pid] !== undefined ? priceMap[pid] : ""]);

  // Запись цен в столбец K (11) - ЦЕНА ОЗОН
  const startRow = 2;
  const numRows = pricesToWrite.length;
  if (numRows > 0) {
    sheet.getRange(startRow, 11, numRows, 1).setValues(pricesToWrite); // K (11): ЦЕНА ОЗОН
  }

  let elasticBoostResult = null;
  if (completeSuccess && productIds.length > 0) {
    try {
      elasticBoostResult = fetchOzonMinElasticBoostPrices_(productIds);
      const elasticBoostPricesToWrite = rowIndexes.map(([pid]) => [
        elasticBoostResult.priceMap[pid] !== undefined ? elasticBoostResult.priceMap[pid] : ""
      ]);
      // BR обновляем только после полной успешной выгрузки: при ошибке Ozon
      // ранее корректные значения должны остаться нетронутыми.
      sheet.getRange(2, minPriceColumn, elasticBoostPricesToWrite.length, 1).setValues(elasticBoostPricesToWrite);
    } catch (error) {
      apiErrorCount++;
      completeSuccess = false;
      Logger.log("❌ Ozon min elastic boost: " + error);
    }
  }

  const elasticPriceMap = elasticBoostResult ? elasticBoostResult.priceMap : {};
  const matchedCount = rowIndexes.filter(([pid]) => elasticPriceMap[pid] !== undefined).length;
  const filledMinPriceCount = rowIndexes.filter(([pid]) => elasticPriceMap[pid] > 0).length;
  Logger.log("Ozon min elastic boost sync: " + JSON.stringify({
    rows: rowIndexes.length,
    ozon_products: ozonProductsCount,
    elastic_action_id: elasticBoostResult ? elasticBoostResult.actionId : null,
    elastic_action_products: elasticBoostResult ? elasticBoostResult.actionProductsCount : 0,
    matched: matchedCount,
    with_min_elastic_price: filledMinPriceCount,
    without_min_elastic_price: matchedCount - filledMinPriceCount,
    not_matched: rowIndexes.length - matchedCount,
    api_requests: requestCount,
    api_errors: apiErrorCount,
    status: completeSuccess ? "SUCCESS" : "ERROR"
  }));
}

/**
 * Возвращает цены для минимального бустинга из конкретной акции
 * «Эластичный бустинг». Это не price.min_price: последнее поле является
 * общим ограничением цены товара для акций и стратегий.
 */
function fetchOzonMinElasticBoostPrices_(productIds) {
  const action = getOzonElasticBoostAction_();
  const requestedIds = {};
  productIds.forEach(function(productId) {
    requestedIds[String(productId)] = true;
  });

  const priceMap = {};
  let lastId = "";
  let pageCount = 0;
  let actionProductsCount = 0;
  const seenLastIds = {};
  let lastRequestTime = Date.now() - 1000 / RPS();

  do {
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());
    const response = retryFetch(ozonActionCandidatesApiURL(), {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify({
        action_id: action.id,
        limit: 1000,
        last_id: lastId
      }),
      muteHttpExceptions: true
    });

    if (!response) {
      throw new Error("не удалось получить candidates акции " + action.id);
    }
    if (response.getResponseCode() < 200 || response.getResponseCode() >= 300) {
      throw new Error("candidates акции " + action.id + ": HTTP " + response.getResponseCode() + " " + response.getContentText().substring(0, 500));
    }

    let data;
    try {
      data = JSON.parse(response.getContentText());
    } catch (error) {
      throw new Error("candidates акции " + action.id + " вернул некорректный JSON: " + error);
    }

    const result = data.result || {};
    const products = result.products || [];
    actionProductsCount += products.length;
    products.forEach(function(product) {
      const productId = String(product.id === undefined ? product.product_id : product.id);
      if (!requestedIds[productId]) return;

      const price = Number(product.price_min_elastic);
      priceMap[productId] = isFinite(price) && price > 0 ? price : "";
    });

    pageCount++;
    // Ozon завершает выдачу пустой страницей и повторяет в ней последний
    // last_id. Это штатный конец пагинации, не цикл.
    if (!products.length) {
      break;
    }

    const nextLastId = String(result.last_id || "");
    if (nextLastId && nextLastId === lastId) {
      throw new Error("pagination candidates не продвигается для акции " + action.id);
    }
    if (nextLastId && seenLastIds[nextLastId]) {
      throw new Error("pagination candidates зациклилась для акции " + action.id);
    }
    if (nextLastId) seenLastIds[nextLastId] = true;
    lastId = nextLastId;
  } while (lastId);

  Logger.log("Эластичный бустинг: акция " + action.id + ", страниц: " + pageCount + ", товаров: " + actionProductsCount);
  return {
    actionId: action.id,
    actionProductsCount: actionProductsCount,
    priceMap: priceMap
  };
}

function getOzonElasticBoostAction_() {
  const response = retryFetch(ozonActionsApiURL(), {
    method: "get",
    headers: ozonHeaders(),
    muteHttpExceptions: true
  });

  if (!response) {
    throw new Error("не удалось получить список акций Ozon");
  }
  if (response.getResponseCode() < 200 || response.getResponseCode() >= 300) {
    throw new Error("список акций Ozon: HTTP " + response.getResponseCode() + " " + response.getContentText().substring(0, 500));
  }

  let data;
  try {
    data = JSON.parse(response.getContentText());
  } catch (error) {
    throw new Error("список акций Ozon вернул некорректный JSON: " + error);
  }

  const actions = data.result || data.actions || [];
  const action = actions.find(function(item) {
    return /^Эластичный бустинг/i.test(String(item.title || "").trim());
  });
  if (!action || !action.id) {
    throw new Error("в кабинете не найдена активная акция «Эластичный бустинг»");
  }
  return action;
}
