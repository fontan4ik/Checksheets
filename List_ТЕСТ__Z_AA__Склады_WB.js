/**
 * СКЛАДЫ WB FBS (обновлённая версия с chrtId)
 *
 * Заполняет колонки:
 * - Z (26): ФЕРОН МОСКВА
 * - AA (27): ВольтМир
 *
 * Алгоритм:
 * 1. Читает nmId из колонки T
 * 2. Content API - получает chrtId по nmId
 * 3. Marketplace API - получает остатки по chrtId
 *
 * ВАЖНО: marketplace-api использует chrtId, НЕ nmId!
 */

function updateWBWarehousesByName() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет артикулов.");
    return;
  }

  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ОБНОВЛЕНИЕ СКЛАДОВ WB FBS (Z, AA) через chrtId                       ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");

  const headers = wbHeaders();
  const marketplaceUrl = "https://marketplace-api.wildberries.ru";
  const contentUrl = "https://content-api.wildberries.ru";

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 1: Получаем список складов
  // ═══════════════════════════════════════════════════════════════════════════════

  Logger.log("\n=== ШАГ 1: Список складов ===");

  const warehousesUrl = `${marketplaceUrl}/api/v3/warehouses`;
  const warehouseOptions = {
    method: "get",
    headers: headers,
    muteHttpExceptions: true
  };

  let warehouses = [];
  try {
    const response = retryFetch(warehousesUrl, warehouseOptions);

    if (!response) throw new Error("WB API не вернул список складов; таблица не обновлена");

    const responseCode = response.getResponseCode();

    if (responseCode === 200) {
      warehouses = JSON.parse(response.getContentText());
      if (!Array.isArray(warehouses)) throw new Error("WB API вернул некорректный список складов");
      Logger.log(`✅ Складов: ${warehouses.length}`);
    } else {
      throw new Error(`WB API список складов HTTP ${responseCode}; таблица не обновлена`);
    }
  } catch (e) {
    Logger.log(`❌ Исключение: ${e.message}`);
    throw e;
  }

  // Находим целевые склады
  const feronMatches = warehouses.filter(wh => String(wh?.name || "").includes("ФЕРОН") && String(wh?.name || "").includes("МОСКВА"));
  const voltMatches = warehouses.filter(wh => String(wh?.name || "").includes("Вольт"));
  const feron = feronMatches.length === 1 ? feronMatches[0] : null;
  const volt = voltMatches.length === 1 ? voltMatches[0] : null;

  if (!feron || !volt) {
    Logger.log(`❌ Целевые склады не найдены!`);
    Logger.log(`   ФЕРОН МОСКВА: ${feron ? "✅" : "❌"}`);
    Logger.log(`   ВольтМир: ${volt ? "✅" : "❌"}`);
    throw new Error("WB целевые склады не найдены однозначно; таблица не обновлена");
  }

  Logger.log(`\n🎯 Целевые склады:`);
  Logger.log(`   Z (26): "${feron.name}" (ID: ${feron.id})`);
  Logger.log(`   AA (27): "${volt.name}" (ID: ${volt.id})`);

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 2: Собираем уникальные nmId из таблицы
  // ═══════════════════════════════════════════════════════════════════════════════

  Logger.log("\n=== ШАГ 2: Сбор уникальных nmId ===");

  const articles = sheet.getRange(2, 1, lastRow - 1).getValues().flat();
  const feronStockColumn = columnByHeader_(sheet, "ФЕРОН МОСКВА");
  const voltStockColumn = columnByHeader_(sheet, "ВОЛЬТМИР");
  const nmIds = sheet.getRange(2, 20, lastRow - 1).getValues().flat();

  const nmIdToRows = {}; // nmId -> [row indices]
  const uniqueNmIds = [];

  articles.forEach((art, i) => {
    const nmId = nmIds[i];
    if (nmId && nmId !== "" && !isNaN(nmId) && Number(nmId) > 0) {
      const nmIdStr = nmId.toString();
      if (!nmIdToRows[nmIdStr]) {
        nmIdToRows[nmIdStr] = [];
        uniqueNmIds.push(nmIdStr);
      }
      nmIdToRows[nmIdStr].push(i + 2); // row number
    }
  });

  Logger.log(`✅ Уникальных nmId: ${uniqueNmIds.length}`);
  Logger.log(`   Всего строк с nmId: ${Object.values(nmIdToRows).reduce((sum, rows) => sum + rows.length, 0)}`);

  if (uniqueNmIds.length === 0) {
    Logger.log(`❌ Нет nmId для обновления`);
    return;
  }

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 3: Content API - получаем chrtId по nmId
  // ═══════════════════════════════════════════════════════════════════════════════

  Logger.log("\n=== ШАГ 3: Content API - получение chrtId ===");
  Logger.log(`Загружаем карточки для ${uniqueNmIds.length} nmId...`);

  const nmIdToChrtIds = {}; // nmId -> [chrtId]
  const requestedNmIdSet = new Set(uniqueNmIds.map(String));
  const seenCatalogNmIds = new Set();
  let foundCards = 0;
  let totalChrtIds = 0;
  let cursor = null;
  let pageCount = 0;
  const pageSize = 100;

  while (true) {
    const cursorPayload = { limit: pageSize };
    if (cursor) {
      cursorPayload.updatedAt = cursor.updatedAt;
      cursorPayload.nmID = cursor.nmID;
    }
    const payload = {
      settings: {
        sort: { ascending: true },
        cursor: cursorPayload,
        filter: { withPhoto: -1 },
      },
    };
    const options = {
      method: "post",
      contentType: "application/json",
      headers: headers,
      payload: JSON.stringify(payload),
      muteHttpExceptions: true,
    };

    const response = retryFetch(contentUrl + "/content/v2/get/cards/list", options);
    if (!response) throw new Error("WB Content API не вернул страницу карточек; таблица не обновлена");
    const responseCode = response.getResponseCode();
    if (responseCode < 200 || responseCode >= 300) {
      throw new Error(`WB Content API HTTP ${responseCode}: ${response.getContentText().substring(0, 300)}`);
    }
    const data = JSON.parse(response.getContentText());
    const responseTotal = Number(data?.cursor?.total);
    if (!data || !Array.isArray(data.cards) || !data.cursor ||
        data.cursor.total === null || data.cursor.total === undefined || data.cursor.total === "" ||
        !Number.isSafeInteger(responseTotal) || responseTotal < 0) {
      throw new Error("WB Content API вернул неполную структуру пагинации; таблица не обновлена");
    }

    data.cards.forEach(card => {
      const nmId = Number(card?.nmID ?? card?.nmId);
      if (!Number.isSafeInteger(nmId) || nmId <= 0) {
        throw new Error("WB Content API вернул карточку без корректного nmID");
      }
      const key = String(nmId);
      if (!requestedNmIdSet.has(key)) return;
      if (seenCatalogNmIds.has(key)) {
        throw new Error(`WB Content API вернул повторную карточку nmID ${key}`);
      }
      seenCatalogNmIds.add(key);

      if (!Array.isArray(card.sizes) || card.sizes.length === 0) return;
      const chrtIds = card.sizes.map(size => Number(size?.chrtID));
      if (chrtIds.some(id => !Number.isSafeInteger(id) || id <= 0) || new Set(chrtIds).size !== chrtIds.length) {
        throw new Error(`WB Content API вернул неполные размеры карточки nmID ${key}`);
      }
      nmIdToChrtIds[key] = chrtIds;
      foundCards++;
      totalChrtIds += chrtIds.length;
    });

    pageCount++;
    if (pageCount > 500) throw new Error("WB Content API pagination exceeded 500 pages");
    const total = responseTotal;
    if (total < pageSize) break;

    const nextCursor = {
      updatedAt: String(data.cursor.updatedAt ?? "").trim(),
      nmID: Number(data.cursor.nmID),
    };
    if (!nextCursor.updatedAt || !Number.isSafeInteger(nextCursor.nmID) || nextCursor.nmID <= 0 ||
        (cursor && nextCursor.updatedAt === cursor.updatedAt && nextCursor.nmID === cursor.nmID)) {
      throw new Error("WB Content API cursor did not advance; таблица не обновлена");
    }
    cursor = nextCursor;
    Utilities.sleep(650);
  }

  Logger.log(`✅ Найдено карточек: ${foundCards}/${uniqueNmIds.length}`);
  Logger.log(`✅ Всего chrtId: ${totalChrtIds}`);

  if (foundCards === 0) {
    throw new Error("WB Content API не вернул карточки с размерами; таблица не обновлена");
  }

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 4: Собираем все уникальные chrtId
  // ═══════════════════════════════════════════════════════════════════════════════

  Logger.log("\n=== ШАГ 4: Сбор уникальных chrtId ===");

  const chrtIdToNmIds = {}; // chrtId -> [nmId]
  const uniqueChrtIds = [];

  for (const nmId in nmIdToChrtIds) {
    const chrtIds = nmIdToChrtIds[nmId];
    chrtIds.forEach(chrtId => {
      const chrtIdStr = chrtId.toString();
      if (!chrtIdToNmIds[chrtIdStr]) {
        chrtIdToNmIds[chrtIdStr] = [];
        uniqueChrtIds.push(chrtIdStr);
      }
      chrtIdToNmIds[chrtIdStr].push(nmId);
    });
  }

  Logger.log(`✅ Уникальных chrtId: ${uniqueChrtIds.length}`);

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 5: Marketplace API - остатки по складам
  // ═══════════════════════════════════════════════════════════════════════════════

  Logger.log("\n=== ШАГ 5: Marketplace API - остатки ===");

  const results = {
    feron: {}, // chrtId -> amount
    volt: {}   // chrtId -> amount
  };

  // Функция для проверки одного склада
  const checkWarehouse = (warehouse, targetKey, columnName) => {
    Logger.log(`\n[${columnName}] (ID: ${warehouse.id})`);

    const chunkSize = 999;
    let totalChecked = 0;

    for (let i = 0; i < uniqueChrtIds.length; i += chunkSize) {
      const chunk = uniqueChrtIds.slice(i, i + chunkSize);

      const url = `${marketplaceUrl}/api/v3/stocks/${warehouse.id}`;
      const payload = {
        chrtIds: chunk.map(id => parseInt(id))
      };

      const options = {
        method: "post",
        contentType: "application/json",
        headers: headers,
        payload: JSON.stringify(payload),
        muteHttpExceptions: true
      };

      try {
        const response = retryFetch(url, options);
        if (!response) throw new Error(`WB не вернул остатки склада ${warehouse.name}`);

        const responseCode = response.getResponseCode();
        if (responseCode !== 200) throw new Error(`WB HTTP ${responseCode} для склада ${warehouse.name}`);
        const data = JSON.parse(response.getContentText());
        if (!data || !Array.isArray(data.stocks)) {
          throw new Error(`WB вернул неполную структуру остатков склада ${warehouse.name}`);
        }

        const requested = new Set(chunk.map(String));
        const seen = new Set();
        data.stocks.forEach(stock => {
          const chrtId = Number(stock?.chrtId);
          const amountRaw = stock?.amount;
          const amount = Number(amountRaw);
          const key = String(chrtId);
          if (!Number.isSafeInteger(chrtId) || chrtId <= 0 || !requested.has(key) ||
              seen.has(key) || amountRaw === null || amountRaw === undefined || amountRaw === "" ||
              !Number.isSafeInteger(amount) || amount < 0) {
            throw new Error(`WB вернул неполный или неожиданный chrtId/остаток: ${JSON.stringify(stock).substring(0, 200)}`);
          }
          seen.add(key);
          results[targetKey][key] = amount;
        });

        totalChecked += chunk.length;
      } catch (e) {
        Logger.log(`   ❌ Ошибка: ${e.message}`);
        throw e;
      }
    }

    const withStock = Object.keys(results[targetKey]).length;
    Logger.log(`   ✅ Проверено chrtId: ${totalChecked}`);
    Logger.log(`   ✅ С остатками: ${withStock}`);
  };

  checkWarehouse(feron, 'feron', 'Z (26): ФЕРОН МОСКВА');
  checkWarehouse(volt, 'volt', 'AA (27): ВольтМир');

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 6: Запись результатов в таблицу
  // ═══════════════════════════════════════════════════════════════════════════════

  Logger.log("\n=== ШАГ 6: Запись в таблицу ===");

  // Подготавливаем массивы значений
  const feronValues = new Array(articles.length).fill(null).map(() => [""]);
  const voltValues = new Array(articles.length).fill(null).map(() => [""]);
  const feronWriteMask = new Array(articles.length).fill(false);
  const voltWriteMask = new Array(articles.length).fill(false);

  let feronCount = 0;
  let voltCount = 0;

  // Для каждого nmId суммируем остатки по всем его chrtId
  for (const nmId in nmIdToChrtIds) {
    const rows = nmIdToRows[nmId];
    const chrtIds = nmIdToChrtIds[nmId];

    const chrtIdKeys = chrtIds.map(String);
    const feronComplete = chrtIdKeys.every(key => Object.prototype.hasOwnProperty.call(results.feron, key));
    const voltComplete = chrtIdKeys.every(key => Object.prototype.hasOwnProperty.call(results.volt, key));
    const feronQty = feronComplete ? chrtIdKeys.reduce((sum, key) => sum + results.feron[key], 0) : null;
    const voltQty = voltComplete ? chrtIdKeys.reduce((sum, key) => sum + results.volt[key], 0) : null;

    // Записываем во все строки с этим nmId
    rows.forEach(rowIdx => {
      const arrIdx = rowIdx - 2; // array index (0-based)
      if (feronComplete) {
        feronValues[arrIdx] = [feronQty];
        feronWriteMask[arrIdx] = true;
      }
      if (voltComplete) {
        voltValues[arrIdx] = [voltQty];
        voltWriteMask[arrIdx] = true;
      }

      if (feronComplete && feronQty > 0) feronCount++;
      if (voltComplete && voltQty > 0) voltCount++;
    });
  }

  const feronWritten = writeMaskedColumnValues_(sheet, feronStockColumn, feronValues, feronWriteMask);
  Logger.log(`✅ Z (26) ФЕРОН МОСКВА: ${feronCount} товаров с остатками; записано полных строк ${feronWritten}`);

  const voltWritten = writeMaskedColumnValues_(sheet, voltStockColumn, voltValues, voltWriteMask);
  Logger.log(`✅ AA (27) ВольтМир: ${voltCount} товаров с остатками; записано полных строк ${voltWritten}`);

  // ═══════════════════════════════════════════════════════════════════════════════
  // ИТОГИ
  // ═══════════════════════════════════════════════════════════════════════════════

  Logger.log("\n=== ИТОГИ ===");

  const totalFeron = Object.values(results.feron).reduce((sum, qty) => sum + qty, 0);
  const totalVolt = Object.values(results.volt).reduce((sum, qty) => sum + qty, 0);

  Logger.log(`📊 Статистика:`);
  Logger.log(`   Всего nmId в таблице: ${uniqueNmIds.length}`);
  Logger.log(`   Найдено карточек: ${foundCards}`);
  Logger.log(`   Уникальных chrtId: ${uniqueChrtIds.length}`);
  Logger.log(`   `);
  Logger.log(`   Z (26) ФЕРОН МОСКВА: ${feronCount} товаров с остатками, всего ${totalFeron} шт`);
  Logger.log(`   AA (27) ВольтМир: ${voltCount} товаров с остатками, всего ${totalVolt} шт`);

  if (feronCount > 0 || voltCount > 0) {
    Logger.log(`\n✅ УСПЕХ! Данные по FBS складам обновлены!`);
  } else {
    Logger.log(`\n⚠️  Нет остатков на FBS складах`);
    Logger.log(`   Возможно товары только на FBO складах WB`);
  }

  Logger.log("\n════════════════════════════════════════════════════════════════════════\n");
}
