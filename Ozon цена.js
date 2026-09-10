function getOzonPricesOptimized() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();
  const minPriceColumn = 70; // BR — Минимальная цена Ozon

  sheet.getRange(1, minPriceColumn).setValue("Минимальная цена Ozon");

  if (lastRow < 2) {
    Logger.log("Ozon цены: в листе нет строк товаров");
    return;
  }

  // ИСПРАВЛЕНО: читаем product_id из U (21), а не из R (18)
  const productIdRange = sheet.getRange("U2:U" + lastRow).getValues();
  const productIds = productIdRange.map(r => r[0]).filter(id => id !== '' && id !== null && id !== undefined && id > 0 && !isNaN(id));
  const rowIndexes = productIdRange.map((r, i) => [r[0], i + 2]); // [product_id, rowNumber]

  const priceMap = {};
  const minPriceMap = {};
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

        // Существующая выгрузка сопоставляется по product_id, поэтому min_price
        // берём из того же ответа и сохраняем по тому же ключу.
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
        const minPrice = Number(p.min_price);
        minPriceMap[productId] = isFinite(minPrice) && minPrice > 0 ? minPrice : "";
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

  // BR обновляем только после полной успешной выгрузки: при ошибке Ozon
  // ранее корректные значения должны остаться нетронутыми.
  if (completeSuccess && productIds.length > 0) {
    const minPricesToWrite = rowIndexes.map(([pid]) => [
      minPriceMap[pid] !== undefined ? minPriceMap[pid] : ""
    ]);
    sheet.getRange(2, minPriceColumn, minPricesToWrite.length, 1).setValues(minPricesToWrite);
  }

  const matchedCount = rowIndexes.filter(([pid]) => minPriceMap[pid] !== undefined).length;
  const filledMinPriceCount = rowIndexes.filter(([pid]) => minPriceMap[pid] > 0).length;
  Logger.log("Ozon min_price sync: " + JSON.stringify({
    rows: rowIndexes.length,
    ozon_products: ozonProductsCount,
    matched: matchedCount,
    with_min_price: filledMinPriceCount,
    without_min_price: matchedCount - filledMinPriceCount,
    not_matched: rowIndexes.length - matchedCount,
    api_requests: requestCount,
    api_errors: apiErrorCount,
    status: completeSuccess ? "SUCCESS" : "ERROR"
  }));
}
