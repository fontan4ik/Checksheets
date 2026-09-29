/**
 * ОСТ ФБС МСК ОЗОН (H, 8)
 *
 * Использует v2 API stocks-by-warehouse/fbs, потому что v4 stocks не отдаёт warehouse_id.
 *
 * Логика:
 * - H (8): остаток только на целевом складе (warehouse_id = ozonFBSWarehouseId)
 * G (7) заполняет updateAllFBSStocks() суммой всех FBS складов.
 */
function getStocksByWarehouseFBS() {
  return runWithTelegramAlertGAS_('getStocksByWarehouseFBS', getStocksByWarehouseFBS_);
}

function getStocksByWarehouseFBS_() {
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
    .filter(sku => sku !== "" && Number.isSafeInteger(Number(sku)) && Number(sku) > 0))];

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
  const seenSkus = new Set();

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
        throw new Error(`Не удалось получить данные FBS по складам для батча ${i / batchSize + 1}`);
      }

      const responseCode = response.getResponseCode();
      if (responseCode < 200 || responseCode >= 300) {
        throw new Error(`FBS по складам вернул HTTP ${responseCode}: ${response.getContentText().substring(0, 500)}`);
      }

      const data = JSON.parse(response.getContentText());
      if (!data || !Array.isArray(data.products) || typeof data.has_next !== "boolean") {
        throw new Error(`Ozon FBS вернул неполную структуру ответа для батча ${i / batchSize + 1}`);
      }
      const requested = new Set(batch.map(String));

      data.products.forEach(item => {
        const sku = String(item?.sku ?? "").trim();
        const presentRaw = item?.present;
        const present = Number(presentRaw);
        if (!sku || !requested.has(sku) || presentRaw === null || presentRaw === undefined || presentRaw === "" ||
            !Number.isSafeInteger(present) || present < 0 ||
            item?.warehouse_id === undefined || item?.warehouse_id === null) {
          throw new Error(`Ozon FBS вернул неполную или неожиданную складскую запись: ${JSON.stringify(item).substring(0, 200)}`);
        }
        seenSkus.add(sku);
        if (!Object.prototype.hasOwnProperty.call(warehouseStockMap, sku)) warehouseStockMap[sku] = 0;
        if (String(item.warehouse_id) === String(targetWarehouseId)) {
          warehouseStockMap[sku] += present;
        }
      });

      if (data.has_next) {
        const nextCursor = String(data.cursor ?? "").trim();
        if (!nextCursor || nextCursor === cursor || data.products.length === 0) {
          throw new Error(`Ozon FBS pagination did not advance for batch ${i / batchSize + 1}`);
        }
        hasNext = true;
        cursor = nextCursor;
      } else {
        hasNext = false;
      }

      if (hasNext) {
        Utilities.sleep(500);
      }
    }

    if ((i / batchSize) % 10 === 0) {
      Logger.log(`Обработано батчей: ${Math.floor(i / batchSize) + 1}/${Math.ceil(validSkus.length / batchSize)}`);
    }
  }

  // Подготовка массивов для записи (учитывая пустые строки)
  const writeMask = skuRaw.map(sku => seenSkus.has(String(sku ?? "").trim()));
  const stocksForWarehouse = skuRaw.map((sku, index) => [
    writeMask[index] ? warehouseStockMap[String(sku).trim()] : ""
  ]);
  const written = writeMaskedColumnValues_(
    sheet,
    columnByHeader_(sheet, 'ОСТ ФБС МСК ОЗОН'),
    stocksForWarehouse,
    writeMask,
  );

  const withWarehouseStock = Object.keys(warehouseStockMap).filter(k => warehouseStockMap[k] > 0).length;

  Logger.log(`✅ H (8) ОСТ ФБС МСК ОЗОН: ${withWarehouseStock} товаров с остатками; записано ${written} полных строк`);
  Logger.log("✅ Завершено");
}
