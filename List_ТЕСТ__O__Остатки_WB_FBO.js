/**
 * WB STOCKS - ИСПРАВЛЕННАЯ ВЕРСИЯ
 *
 * Заполняет колонку O (15): Остаток ФБО ВБ
 * Использует Seller Analytics API для остатков по складам WB.
 */

function updateWBStocksFromStatisticsAPI() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет артикулов.");
    return;
  }

  Logger.log("=== ОБНОВЛЕНИЕ ОСТАТКОВ ФБО ВБ (O, 15) ===");

  const articles = sheet.getRange(2, 1, lastRow - 1).getValues().flat(); // A (1): Артикул
  const stockColumn = columnByHeader_(sheet, "Остаток ФБО ВБ");
  const nmIdValues = sheet.getRange(2, 20, lastRow - 1).getValues().flat(); // T (20): Артикул WB
  const pageSize = 1000;

  const normalizeNmId = value => {
    if (value === null || value === undefined) {
      return null;
    }

    const valueType = typeof value;
    if (valueType !== "number" && valueType !== "string") {
      return null;
    }

    const valueText = String(value).trim();
    if (!valueText) {
      return null;
    }

    const numericValue = Number(valueText);
    if (!Number.isFinite(numericValue) || numericValue <= 0) {
      return null;
    }

    return numericValue;
  };

  const nmIds = [];
  const requestedNmIds = {};
  nmIdValues.forEach(value => {
    const nmId = normalizeNmId(value);
    if (nmId === null || requestedNmIds[nmId]) {
      return;
    }

    requestedNmIds[nmId] = true;
    nmIds.push(nmId);
  });

  if (nmIds.length === 0) {
    Logger.log("Нет валидных nmId.");
    return;
  }

  const url = `${WB_ANALYTICS_BASE_URL()}/api/analytics/v1/stocks-report/wb-warehouses`;
  const stockMap = {};
  const seenNmIds = new Set();
  const filterBatchSize = 1000;
  let requestCount = 0;
  let totalRecords = 0;

  try {
    for (let filterStart = 0; filterStart < nmIds.length; filterStart += filterBatchSize) {
      const nmIdBatch = nmIds.slice(filterStart, filterStart + filterBatchSize);
      let offset = 0;

      while (true) {
        if (requestCount > 0) {
          Utilities.sleep(12000);
        }
        requestCount++;

        const payload = {
          nmIds: nmIdBatch,
          limit: pageSize,
          offset: offset
        };
        const options = {
          method: "post",
          headers: wbAnalyticsHeaders(),
          contentType: "application/json",
          payload: JSON.stringify(payload),
          muteHttpExceptions: true
        };
        const response = retryFetch(url, options);

        if (!response) {
          throw new Error("Не удалось получить остатки ФБО ВБ");
        }

        const responseCode = response.getResponseCode();
        if (responseCode < 200 || responseCode >= 300) {
          throw new Error(`WB FBO HTTP ${responseCode}: ${response.getContentText().substring(0, 300)}`);
        }
        const data = JSON.parse(response.getContentText());
        const items = data && data.data && Array.isArray(data.data.items) ? data.data.items : null;
        if (items === null) {
          throw new Error(`WB FBO вернул неполный ответ: ${JSON.stringify(data).substring(0, 200)}`);
        }

        const requested = new Set(nmIdBatch.map(String));
        totalRecords += items.length;
        items.forEach(item => {
          const rawNmId = item.nmId !== undefined && item.nmId !== null ? item.nmId : item.nmID;
          const nmId = normalizeNmId(rawNmId);
          const quantity = Number(item.quantity);
          if (nmId === null || !requested.has(String(nmId)) || !Number.isFinite(quantity) || quantity < 0) {
            throw new Error("WB FBO вернул неполную или неожиданную запись товара");
          }

          const key = String(nmId);
          stockMap[key] = (stockMap[key] || 0) + quantity;
          seenNmIds.add(key);
        });

        Logger.log(`✅ Получено записей: ${items.length} (offset: ${offset})`);

        if (items.length < pageSize) {
          break;
        }

        offset += pageSize;
        if (offset / pageSize > 100) throw new Error("WB FBO pagination exceeded 100 pages");
      }
    }

    // Записываем только товары, для которых WB вернул валидную запись.
    const writeMask = articles.map((article, index) => {
      const nmId = normalizeNmId(nmIdValues[index]);
      return Boolean(String(article ?? "").trim() && nmId !== null && seenNmIds.has(String(nmId)));
    });
    const updatedStocks = articles.map((article, index) => {
      const nmId = normalizeNmId(nmIdValues[index]);
      return [writeMask[index] ? stockMap[String(nmId)] : ""];
    });
    let foundCount = 0;

    for (let i = 0; i < articles.length; i++) {
      if (!writeMask[i]) continue;
      if (updatedStocks[i][0] > 0) {
        foundCount++;
      }
    }

    const written = writeMaskedColumnValues_(sheet, stockColumn, updatedStocks, writeMask);

    Logger.log(`Найдено товаров с остатками: ${foundCount}`);
    Logger.log(`Полных строк записано: ${written}; получено товаров с остатками: ${foundCount}`);
    Logger.log(`Всего записей API: ${totalRecords}`);
    Logger.log(`✅ Завершено`);

  } catch (e) {
    Logger.log(`❌ Ошибка: ${e.message}`);
    throw e;
  }
}
