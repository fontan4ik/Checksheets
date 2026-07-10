/**
 * ОСТ ФБС МСК ОЗОН (H, 8) + Остаток ФБС ОЗОН (G, 7)
 *
 * Использует v2 API stocks-by-warehouse/fbs, потому что v4 stocks не отдаёт warehouse_id.
 *
 * Логика:
 * - G (7): сумма ВСЕХ FBS складов (кроме конкретного склада Москва)
 * - H (8): остаток только на целевом складе (warehouse_id = ozonFBSWarehouseId)
 */
function getStocksByWarehouseFBS() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет данных для обработки");
    return;
  }

  // Читаем SKU из V (22) - v2 stocks-by-warehouse/fbs работает с sku.
  const skuRaw = sheet.getRange(2, 22, lastRow - 1).getValues().flat();

  // Фильтруем валидные SKU
  const validSkus = [...new Set(skuRaw
    .map(sku => sku?.toString().trim() || "")
    .filter(sku => sku !== "" && Number(sku) > 0))];

  if (validSkus.length === 0) {
    Logger.log("Нет SKU для запроса FBS по складам");
    return;
  }

  const targetWarehouseId = ozonFBSWarehouseId(); // 1020005000217829
  const batchSize = 100;
  const pageLimit = 1000;
  const customRps = 1;

  // Словари для остатков
  const warehouseStockMap = {};  // Для склада Москва (H, 8)
  const otherStockMap = {};      // Для всех остальных FBS складов (G, 7)

  let lastRequestTime = Date.now() - 1000 / customRps;

  Logger.log("=== ОБНОВЛЕНИЕ FBS ПО СКЛАДАМ (v2 API) ===");
  Logger.log("Целевой склад: " + targetWarehouseId);

  // Итерации по батчам SKU
  for (let i = 0; i < validSkus.length; i += batchSize) {
    lastRequestTime = rateLimitRPS(lastRequestTime, customRps);

    const batch = validSkus.slice(i, i + batchSize);
    let cursor = "";
    let hasNext = true;

    while (hasNext) {
      const payload = {
        sku: batch,
        limit: pageLimit
      };

      if (cursor) {
        payload.cursor = cursor;
      }

      const options = {
        method: "post",
        contentType: "application/json",
        headers: ozonHeaders(),
        payload: JSON.stringify(payload),
        muteHttpExceptions: true
      };

      const response = retryFetch(ozonFBSStocks(), options, 3);

      if (!response) {
        Logger.log(`❌ Не удалось получить данные FBS по складам для батча ${i / batchSize + 1}`);
        break;
      }

      const responseCode = response.getResponseCode();
      if (responseCode < 200 || responseCode >= 300) {
        Logger.log(`❌ FBS по складам вернул HTTP ${responseCode}: ${response.getContentText().substring(0, 500)}`);
        break;
      }

      const data = JSON.parse(response.getContentText());

      if (data.products && data.products.length > 0) {
        data.products.forEach(item => {
          const sku = item.sku?.toString();

          if (!sku) return;

          const whId = item.warehouse_id;
          const present = item.present || 0;

          if (!(sku in warehouseStockMap)) warehouseStockMap[sku] = 0;
          if (!(sku in otherStockMap)) otherStockMap[sku] = 0;

          if (whId === targetWarehouseId) {
            warehouseStockMap[sku] += present;
          } else {
            otherStockMap[sku] += present;
          }
        });
      }

      hasNext = data.has_next === true && data.cursor;
      cursor = data.cursor || "";

      if (hasNext) {
        Utilities.sleep(500);
      }
    }

    if ((i / batchSize) % 10 === 0) {
      Logger.log(`Обработано батчей: ${Math.floor(i / batchSize) + 1}/${Math.ceil(validSkus.length / batchSize)}`);
    }
  }

  // Подготовка массивов для записи (учитывая пустые строки)
  const stocksForWarehouse = skuRaw.map(sku =>
    sku && sku !== "" && Number(sku) > 0 ? [warehouseStockMap[sku.toString().trim()] || 0] : [""]
  );
  const stocksOtherWarehouses = skuRaw.map(sku =>
    sku && sku !== "" && Number(sku) > 0 ? [otherStockMap[sku.toString().trim()] || 0] : [""]
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
