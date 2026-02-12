/**
 * ОСТ ФБС МСК ОЗОН (H, 8) + Остаток ФБС ОЗОН (G, 7)
 *
 * ИСПРАВЛЕНО: Использует v4 API (ozonStocksApiURL) вместо сломанного v1 endpoint
 *
 * Логика:
 * - G (7): сумма ВСЕХ FBS складов (кроме конкретного склада Москва)
 * - H (8): остаток только на складе Москва (warehouse_id = ozonFBSWarehouseId)
 */
function getStocksByWarehouseFBS() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет данных для обработки");
    return;
  }

  // Читаем product_id из U (21) - v4 API работает с product_id
  const productIdsRaw = sheet.getRange(2, 21, lastRow - 1).getValues().flat();

  // Фильтруем валидные product_id
  const validProductIds = productIdsRaw
    .filter(id => id !== '' && id !== null && id !== undefined && id > 0);

  if (validProductIds.length === 0) {
    Logger.log("Нет product_id для запроса");
    return;
  }

  const targetWarehouseId = ozonFBSWarehouseId(); // 1020005000217829
  const batchSize = 1000;

  // Словари для остатков
  const warehouseStockMap = {};  // Для склада Москва (H, 8)
  const otherStockMap = {};      // Для всех остальных FBS складов (G, 7)

  let lastRequestTime = Date.now() - 1000 / RPS();

  Logger.log("=== ОБНОВЛЕНИЕ FBS ПО СКЛАДАМ (v4 API) ===");
  Logger.log("Целевой склад: " + targetWarehouseId);

  // Итерации по батчам product_id
  for (let i = 0; i < validProductIds.length; i += batchSize) {
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

    const batch = validProductIds.slice(i, i + batchSize);

    // Используем v4 API (работающий)
    const payload = {
      filter: {
        product_id: batch
      },
      limit: batch.length
    };

    const options = {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify(payload),
    };

    const response = retryFetch(ozonStocksApiURL(), options);

    if (!response) {
      Logger.log(`❌ Не удалось получить данные для батча ${i/batchSize + 1}`);
      continue;
    }

    const data = JSON.parse(response.getContentText());

    if (data.items && data.items.length > 0) {
      data.items.forEach(item => {
        const productId = item.product_id?.toString();

        if (!productId) return;

        // Фильтруем только FBS остатки
        const fbsStocks = (item.stocks || []).filter(s => s.type === 'fbs');

        fbsStocks.forEach(stock => {
          const whId = stock.warehouse_id;
          const present = stock.present || 0;

          if (!(productId in warehouseStockMap)) warehouseStockMap[productId] = 0;
          if (!(productId in otherStockMap)) otherStockMap[productId] = 0;

          if (whId === targetWarehouseId) {
            // Склад Москва - записываем в H (8)
            warehouseStockMap[productId] += present;
          } else {
            // Остальные FBS склады - суммируем в G (7)
            otherStockMap[productId] += present;
          }
        });
      });
    }

    if ((i / batchSize) % 5 === 0) {
      Logger.log(`Обработано батчей: ${Math.floor(i / batchSize) + 1}/${Math.ceil(validProductIds.length / batchSize)}`);
    }
  }

  // Подготовка массивов для записи (учитывая пустые строки)
  const stocksForWarehouse = productIdsRaw.map(pid =>
    pid && pid !== "" && pid > 0 ? [warehouseStockMap[pid.toString()] || 0] : [""]
  );
  const stocksOtherWarehouses = productIdsRaw.map(pid =>
    pid && pid !== "" && pid > 0 ? [otherStockMap[pid.toString()] || 0] : [""]
  );

  // Запись данных
  sheet.getRange(2, 7, stocksOtherWarehouses.length, 1).setValues(stocksOtherWarehouses); // G (7) - Остаток ФБС ОЗОН
  sheet.getRange(2, 8, stocksForWarehouse.length, 1).setValues(stocksForWarehouse);       // H (8) - ОСТ ФБС МСК ОЗОН

  const withWarehouseStock = Object.keys(warehouseStockMap).filter(k => warehouseStockMap[k] > 0).length;
  const withOtherStock = Object.keys(otherStockMap).filter(k => otherStockMap[k] > 0).length;

  Logger.log(`✅ G (7) Остаток ФБС ОЗОН: ${withOtherStock} товаров с остатками`);
  Logger.log(`✅ H (8) ОСТ ФБС МСК ОЗОН: ${withWarehouseStock} товаров с остатками`);
  Logger.log("✅ Завершено");
}
