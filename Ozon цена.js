function getOzonPricesOptimized() {
  const sheet = mainSheet();

  // ИСПРАВЛЕНО: читаем product_id из U (21), а не из R (18)
  const productIdRange = sheet.getRange("U2:U" + sheet.getLastRow()).getValues();
  const productIds = productIdRange.map(r => r[0]).filter(id => id !== '' && id !== null && id !== undefined && id > 0 && !isNaN(id));
  const rowIndexes = productIdRange.map((r, i) => [r[0], i + 2]); // [product_id, rowNumber]

  const priceMap = {};
  const chunkSize = 1000;

  let lastRequestTime = Date.now() - 1000 / RPS();

  // Итерации
  for (let i = 0; i < productIds.length; i += chunkSize) {
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

    const chunk = productIds.slice(i, i + chunkSize);
    const payload = JSON.stringify({
      filter: { product_id: chunk.map(Number) },
      limit: chunk.length
    });

    const options = {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: payload
    };

    const response = retryFetch(ozonPricesApiURL(), options);

    if (!response) {
      Logger.log(`❌ Не удалось получить цены для продукта ${productId}`);
      continue;
    }

    const data = JSON.parse(response.getContentText());

    if (data.items && data.items.length) {
      data.items.forEach(item => {
        // ИСПРАВЛЕНО (2026-02-03): правильный выбор цены из нескольких полей
        // Приоритет полей цены:
        // 1. price.marketing_seller_price - цена продавца с учетом маркетинговых действий
        // 2. price.price_before - базовая цена продавца
        // 3. price.price - полная цена с маркетплейсом (включает наценку Ozon)
        //
        // Валидные значения: число (включая 0), непустая строка
        // Невалидные значения: null, undefined, пустая строка ""

        const p = item.price;
        let price = "";

        // Проверяем каждое поле с точной валидацией (работает в старых версиях JS)
        // marketing_seller_price имеет приоритет
        if (p && p.marketing_seller_price !== null && p.marketing_seller_price !== undefined && p.marketing_seller_price !== "") {
          price = p.marketing_seller_price;
        }
        // Если marketing_seller_price нет, проверяем price_before
        else if (p && p.price_before !== null && p.price_before !== undefined && p.price_before !== "") {
          price = p.price_before;
        }
        // Если нет price_before, берем price (может быть пустым)
        else {
          price = p.price || "";
        }

        priceMap[item.product_id] = price;
      });
    };
  }

  // Собираем массив значений для записи
  const pricesToWrite = rowIndexes.map(([pid]) => [priceMap[pid] !== undefined ? priceMap[pid] : ""]);

  // Запись цен в столбец K (11) - ЦЕНА ОЗОН
  const startRow = 2;
  const numRows = pricesToWrite.length;
  if (numRows > 0) {
    sheet.getRange(startRow, 11, numRows, 1).setValues(pricesToWrite); // K (11): ЦЕНА ОЗОН
  }
}
