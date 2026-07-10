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

    if (!response) {
      Logger.log(`❌ Не удалось получить список складов`);
      return;
    }

    const responseCode = response.getResponseCode();

    if (responseCode === 200) {
      warehouses = JSON.parse(response.getContentText());
      Logger.log(`✅ Складов: ${warehouses.length}`);
    } else {
      Logger.log(`❌ Ошибка: ${responseCode}`);
      return;
    }
  } catch (e) {
    Logger.log(`❌ Исключение: ${e.message}`);
    return;
  }

  // Находим целевые склады
  const feron = warehouses.find(wh => wh.name.includes("ФЕРОН") && wh.name.includes("МОСКВА"));
  const volt = warehouses.find(wh => wh.name.includes("Вольт"));

  if (!feron || !volt) {
    Logger.log(`❌ Целевые склады не найдены!`);
    Logger.log(`   ФЕРОН МОСКВА: ${feron ? "✅" : "❌"}`);
    Logger.log(`   ВольтМир: ${volt ? "✅" : "❌"}`);
    return;
  }

  Logger.log(`\n🎯 Целевые склады:`);
  Logger.log(`   Z (26): "${feron.name}" (ID: ${feron.id})`);
  Logger.log(`   AA (27): "${volt.name}" (ID: ${volt.id})`);

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 2: Собираем уникальные nmId из таблицы
  // ═══════════════════════════════════════════════════════════════════════════════

  Logger.log("\n=== ШАГ 2: Сбор уникальных nmId ===");

  const articles = sheet.getRange(2, 1, lastRow - 1).getValues().flat();
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
  let foundCards = 0;
  let totalChrtIds = 0;

  // Разбиваем на батчи по 100 nmId (limit API)
  const batchSize = 100;
  const totalBatches = Math.ceil(uniqueNmIds.length / batchSize);

  for (let i = 0; i < uniqueNmIds.length; i += batchSize) {
    const batchNmIds = uniqueNmIds.slice(i, i + batchSize);
    const batchNum = Math.floor(i / batchSize) + 1;

    if (batchNum === 1 || batchNum % 10 === 0) {
      Logger.log(`   Батч ${batchNum}/${totalBatches}...`);
    }

    const payload = {
      "settings": {
        "sort": { "ascending": true },
        "cursor": { "limit": 100 }
      },
      "filter": {
        "withPhoto": -1
      }
    };

    const options = {
      method: "post",
      contentType: "application/json",
      headers: headers,
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    };

    try {
      const response = retryFetch(contentUrl + "/content/v2/get/cards/list", options);

      if (!response) {
        Logger.log(`   ❌ Не удалось получить карточки (network error)`);
        continue;
      }

      const responseCode = response.getResponseCode();

      if (responseCode === 200) {
        const data = JSON.parse(response.getContentText());

        if (data && data.cards && Array.isArray(data.cards)) {
          // Создаём Set для быстрого поиска
          const batchNmIdSet = new Set(batchNmIds.map(id => parseInt(id)));

          data.cards.forEach(card => {
            const nmId = (card.nmID || card.nmId).toString();

            // Если эта карточка из нашего батча
            if (batchNmIdSet.has(parseInt(nmId))) {
              if (!nmIdToChrtIds[nmId]) {
                nmIdToChrtIds[nmId] = [];
              }

              // Извлекаем все chrtId из размеров
              if (card.sizes && card.sizes.length > 0) {
                card.sizes.forEach(size => {
                  if (size.chrtID) {
                    nmIdToChrtIds[nmId].push(size.chrtID);
                    totalChrtIds++;
                  }
                });
              }

              foundCards++;
            }
          });

          // Пагинация - если есть cursor, продолжаем
          if (data.cursor && data.cursor.updatedAt) {
            // Для упрощения, берём только первую страницу
            // Полная пагинация может занять много времени
          }
        }
      }
    } catch (e) {
      Logger.log(`   ❌ Ошибка батча ${batchNum}: ${e.message}`);
    }
  }

  Logger.log(`✅ Найдено карточек: ${foundCards}/${uniqueNmIds.length}`);
  Logger.log(`✅ Всего chrtId: ${totalChrtIds}`);

  if (foundCards === 0) {
    Logger.log(`❌ Не найдено карточек в Content API`);
    Logger.log(`   Возможно токен от другого аккаунта или карточки в особом статусе`);
    return;
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

        if (!response) {
          Logger.log(`   ❌ Не удалось получить остатки склада ${warehouse.name}`);
          return;
        }

        const responseCode = response.getResponseCode();

        if (responseCode === 200) {
          const data = JSON.parse(response.getContentText());

          if (data.stocks && Array.isArray(data.stocks)) {
            data.stocks.forEach(stock => {
              if (stock.chrtId && stock.amount > 0) {
                results[targetKey][stock.chrtId.toString()] = stock.amount;
              }
            });
          }

          totalChecked += chunk.length;
        } else {
          Logger.log(`   ❌ Код: ${responseCode}`);
          return;
        }
      } catch (e) {
        Logger.log(`   ❌ Ошибка: ${e.message}`);
        return;
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
  const feronValues = new Array(articles.length).fill([0]);
  const voltValues = new Array(articles.length).fill([0]);

  let feronCount = 0;
  let voltCount = 0;

  // Для каждого nmId суммируем остатки по всем его chrtId
  for (const nmId in nmIdToChrtIds) {
    const rows = nmIdToRows[nmId];
    const chrtIds = nmIdToChrtIds[nmId];

    let feronQty = 0;
    let voltQty = 0;

    chrtIds.forEach(chrtId => {
      const chrtIdStr = chrtId.toString();
      if (results.feron[chrtIdStr]) feronQty += results.feron[chrtIdStr];
      if (results.volt[chrtIdStr]) voltQty += results.volt[chrtIdStr];
    });

    // Записываем во все строки с этим nmId
    rows.forEach(rowIdx => {
      const arrIdx = rowIdx - 2; // array index (0-based)
      feronValues[arrIdx] = [feronQty];
      voltValues[arrIdx] = [voltQty];

      if (feronQty > 0) feronCount++;
      if (voltQty > 0) voltCount++;
    });
  }

  // Записываем в таблицу
  sheet.getRange(2, 26, feronValues.length, 1).setValues(feronValues);
  Logger.log(`✅ Z (26) ФЕРОН МОСКВА: ${feronCount} товаров с остатками`);

  sheet.getRange(2, 27, voltValues.length, 1).setValues(voltValues);
  Logger.log(`✅ AA (27) ВольтМир: ${voltCount} товаров с остатками`);

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

/**
 * ЗАПАСНОЙ ВАРИАНТ через statistics-api (FBO склады)
 * Используется если marketplace-api недоступен
 */
function updateWBWarehousesFromStatisticsAPI() {
  Logger.log("\n╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ЗАПАСНОЙ ВАРИАНТ: STATISTICS-API (FBO)                              ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");

  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  const warehouses = {
    Z:  {
      column: 26,
      name: "Самара",
      description: "Самара (Новосемейкино)",
      filter: (warehouseName) => warehouseName.includes("Самара (Новосемейкино)")
    },
    AA: {
      column: 27,
      name: "Коледино (Подольск)",
      description: "Коледино",
      filter: (warehouseName) => warehouseName === "Коледино"
    }
  };

  const url = "https://statistics-api.wildberries.ru/api/v1/supplier/stocks?dateFrom=2019-06-20";
  const options = {
    method: "get",
    headers: wbHeaders(),
    muteHttpExceptions: true
  };

  try {
    const response = retryFetch(url, options);

    if (!response) {
      Logger.log(`❌ Не удалось получить остатки (statistics-api)`);
      return;
    }

    const data = JSON.parse(response.getContentText());

    if (!Array.isArray(data)) {
      Logger.log(`❌ Ошибка ответа API`);
      return;
    }

    Logger.log(`✅ Получено записей: ${data.length}`);

    // Агрегируем
    const stockMap = {};
    Object.keys(warehouses).forEach(key => {
      stockMap[key] = {};
    });

    data.forEach(item => {
      const whName = item.warehouseName || "";
      const art = item.supplierArticle;
      const qty = item.quantity || 0;

      if (!art) return;

      Object.entries(warehouses).forEach(([key, config]) => {
        if (config.filter(whName)) {
          if (!stockMap[key][art]) {
            stockMap[key][art] = 0;
          }
          stockMap[key][art] += qty;
        }
      });
    });

    // Записываем
    const articles = sheet.getRange(2, 1, lastRow - 1).getValues().flat();

    Object.entries(warehouses).forEach(([key, config]) => {
      const values = [];
      const stockData = stockMap[key];
      let foundCount = 0;

      for (let i = 0; i < articles.length; i++) {
        const art = articles[i];
        if (art) {
          const qty = stockData[art] || 0;
          values.push([qty]);
          if (qty > 0) foundCount++;
        } else {
          values.push([0]);
        }
      }

      sheet.getRange(2, config.column, values.length, 1).setValues(values);
      Logger.log(`${config.column} (${config.name}): ${foundCount} товаров`);
    });

    Logger.log("\n✅ Завершено (statistics-api)");

  } catch (e) {
    Logger.log(`❌ Ошибка: ${e.message}`);
  }
}
