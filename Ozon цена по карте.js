/**
 * getOzonPriceOnCard() — НОВЫЙ СКРИПТ
 *
 * API: /v1/product/prices/details (Premium Pro)
 * Вход: SKU (колонка V, 22)
 * Выход: customer_price.amount — цена товара на сайте (цена по карте)
 * Запись: колонка BG (59) — "Цена Озон по карте"
 *
 * Отличие от getOzonPricesOptimized() в Ozon цена.gs:
 * - Тот пишет в K (11) и использует старый v5 endpoint (цены продавца)
 * - Этот пишет в BG (59) и использует customer_price (цена на витрине)
 */

function getOzonPriceOnCard() {
  const sheet = mainSheet();

  // Читаем SKU из колонки V (22)
  const skuRange = sheet.getRange("V2:V" + sheet.getLastRow()).getValues();

  // Фильтруем только валидные SKU для запроса к API
  const validSkus = skuRange
    .map(r => r[0])
    .filter(sku => sku !== '' && sku !== null && sku !== undefined && sku !== 0 && sku !== "0" && !isNaN(sku));

  // Сохраняем [sku, rowNumber] для ВСЕХ строк
  const rowIndexes = skuRange.map((r, i) => [String(r[0]), i + 2]);

  Logger.log(`=== getOzonPriceOnCard() ===`);
  Logger.log(`Всего строк: ${skuRange.length}, валидных SKU: ${validSkus.length}`);

  const priceMap = {};
  const chunkSize = 1000;
  let lastRequestTime = Date.now() - 1000 / RPS();

  for (let i = 0; i < validSkus.length; i += chunkSize) {
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

    const chunk = validSkus.slice(i, i + chunkSize);
    const payload = JSON.stringify({
      skus: chunk.map(String)
    });

    const options = {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: payload
    };

    const response = retryFetch(ozonPricesDetailsURL(), options);

    if (!response) {
      Logger.log(`❌ Ошибка запроса для батча ${Math.floor(i / chunkSize) + 1}`);
      continue;
    }

    const data = JSON.parse(response.getContentText());

    if (data.prices && data.prices.length) {
      data.prices.forEach(item => {
        const sku = String(item.sku);

        // customer_price — цена товара на сайте (с учётом скидок Ozon)
        let price = "";
        if (
          item.customer_price &&
          item.customer_price.amount !== null &&
          item.customer_price.amount !== undefined &&
          item.customer_price.amount !== ""
        ) {
          price = String(item.customer_price.amount);
        }

        priceMap[sku] = price;
      });
    }

    Logger.log(`Обработано ${Math.min(i + chunkSize, validSkus.length)}/${validSkus.length} SKU`);
  }

  // Собираем массив цен для ВСЕХ строк
  const pricesToWrite = rowIndexes.map(([sku]) => [priceMap[sku] !== undefined ? priceMap[sku] : ""]);

  // Запись в колонку BG (59) — "Цена Озон по карте"
  const startRow = 2;
  const numRows = pricesToWrite.length;
  if (numRows > 0) {
    sheet.getRange(startRow, 59, numRows, 1).setValues(pricesToWrite);
  }

  Logger.log(`✅ Цена по карте записана в BG: ${pricesToWrite.filter(p => p[0] !== "").length} товаров`);
}
