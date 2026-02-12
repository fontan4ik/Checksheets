/**
 * ЛОКАЛЬНЫЙ ТЕСТ: WB Склады через chrtId
 *
 * Проверяет правильную логику на всех артикулах из таблицы
 * НЕ записывает в таблицу, только тестирует API
 */

function testWBWarehousesByChrtId() {
  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ЛОКАЛЬНЫЙ ТЕСТ: FBS склады через chrtId                                 ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");

  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("❌ Нет данных");
    return;
  }

  // Читаем данные
  const articles = sheet.getRange(2, 1, lastRow - 1).getValues().flat();
  const nmIds = sheet.getRange(2, 20, lastRow - 1).getValues().flat();

  Logger.log(`\n📦 Всего строк: ${articles.length}`);
  Logger.log(`Столбцы: A (Артикул) и T (nmId)`);

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 1: Получаем список складов
  // ═══════════════════════════════════════════════════════════════════════════════

  Logger.log("\n=== ШАГ 1: Список складов ===");

  const headers = wbHeaders();
  const marketplaceUrl = "https://marketplace-api.wildberries.ru";

  const warehousesUrl = `${marketplaceUrl}/api/v3/warehouses`;
  const warehouseOptions = {
    method: "get",
    headers: headers,
    muteHttpExceptions: true
  };

  let warehouses = [];
  try {
    const response = retryFetch(warehousesUrl, warehouseOptions);
    const responseCode = response.getResponseCode();

    if (responseCode === 200) {
      warehouses = JSON.parse(response.getContentText());
      Logger.log(`✅ Складов: ${warehouses.length}`);

      warehouses.forEach((wh, i) => {
        const type = wh.isFbs ? 'FBS' : (wh.isDbs ? 'DBS' : '?');
        Logger.log(`   ${i + 1}. [${type}] "${wh.name}" (ID: ${wh.id})`);
      });
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
  Logger.log(`   ФЕРОН МОСКВА: "${feron.name}" (ID: ${feron.id})`);
  Logger.log(`   ВольтМир: "${volt.name}" (ID: ${volt.id})`);

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 2: Собираем уникальные nmId
  // ═══════════════════════════════════════════════════════════════════════════════

  Logger.log("\n=== ШАГ 2: Сбор уникальных nmId ===");

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
    Logger.log(`❌ Нет nmId для теста`);
    return;
  }

  // Берём первые 100 nmId для теста
  const testNmIds = uniqueNmIds.slice(0, 100);
  Logger.log(`\n🧪 Тестируем на первых ${testNmIds.length} nmId`);

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 3: Content API - получаем chrtId по nmId
  // ═══════════════════════════════════════════════════════════════════════════════

  Logger.log("\n=== ШАГ 3: Content API - получение chrtId ===");

  const contentUrl = "https://content-api.wildberries.ru";
  const nmIdToChrtIds = {}; // nmId -> [chrtId]
  let foundCards = 0;

  // Разбиваем на батчи по 100 nmId
  const batchSize = 100;
  for (let i = 0; i < testNmIds.length; i += batchSize) {
    const batchNmIds = testNmIds.slice(i, i + batchSize);
    const batchNum = Math.floor(i / batchSize) + 1;
    const totalBatches = Math.ceil(testNmIds.length / batchSize);

    Logger.log(`\n[Батч ${batchNum}/${totalBatches}] nmId: ${batchNmIds.length}`);

    const payload = {
      "settings": {
        "sort": { "ascending": true },
        "cursor": { "limit": 1000 }
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
      const responseCode = response.getResponseCode();

      if (responseCode === 200) {
        const data = JSON.parse(response.getContentText());

        if (data && data.cards && Array.isArray(data.cards)) {
          Logger.log(`   ✅ Получено карточек: ${data.cards.length}`);

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
                  }
                });
              }

              foundCards++;
            }
          });
        } else {
          Logger.log(`   ⚠️  Неверный формат ответа`);
        }
      } else {
        Logger.log(`   ❌ Ошибка: ${responseCode}`);
        Logger.log(`   Response: ${response.getContentText().substring(0, 300)}`);
      }
    } catch (e) {
      Logger.log(`   ❌ Исключение: ${e.message}`);
    }
  }

  Logger.log(`\n📊 Результаты Content API:`);
  Logger.log(`   Найдено карточек: ${foundCards} из ${testNmIds.length}`);
  Logger.log(`   nmId с chrtId: ${Object.keys(nmIdToChrtIds).length}`);

  // Показываем примеры
  let examplesCount = 0;
  for (const nmId in nmIdToChrtIds) {
    if (examplesCount < 3) {
      const chrtIds = nmIdToChrtIds[nmId];
      const rows = nmIdToRows[nmId];
      Logger.log(`   Пример ${examplesCount + 1}: nmId=${nmId}, chrtId=[${chrtIds.slice(0, 2).join(", ")}${chrtIds.length > 2 ? "..." : ""}], строк=${rows.slice(0, 3).join(", ")}${rows.length > 3 ? "..." : ""}`);
      examplesCount++;
    }
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

  if (uniqueChrtIds.length === 0) {
    Logger.log(`❌ Нет chrtId для проверки складов`);
    return;
  }

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 5: Marketplace API - остатки по складам
  // ═══════════════════════════════════════════════════════════════════════════════

  Logger.log("\n=== ШАГ 5: Marketplace API - остатки ===");

  const results = {
    feron: {}, // chrtId -> amount
    volt: {}   // chrtId -> amount
  };

  // Функция для проверки одного склада
  const checkWarehouse = (warehouse, targetKey) => {
    Logger.log(`\n[${warehouse.name}]`);

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

  checkWarehouse(feron, 'feron');
  checkWarehouse(volt, 'volt');

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 6: Примеры результатов
  // ═══════════════════════════════════════════════════════════════════════════════

  Logger.log("\n=== ШАГ 6: Примеры с остатками ===");

  let count = 0;
  for (const nmId in nmIdToChrtIds) {
    if (count >= 5) break;

    const chrtIds = nmIdToChrtIds[nmId];
    const rows = nmIdToRows[nmId];

    let feronQty = 0;
    let voltQty = 0;

    chrtIds.forEach(chrtId => {
      const chrtIdStr = chrtId.toString();
      if (results.feron[chrtIdStr]) feronQty += results.feron[chrtIdStr];
      if (results.volt[chrtIdStr]) voltQty += results.volt[chrtIdStr];
    });

    if (feronQty > 0 || voltQty > 0) {
      Logger.log(`\n${count + 1}. nmId: ${nmId}, строк(и): ${rows.join(", ")}`);
      Logger.log(`   ФЕРОН МОСКВА: ${feronQty} шт`);
      Logger.log(`   ВольтМир: ${voltQty} шт`);
      count++;
    }
  }

  if (count === 0) {
    Logger.log(`\n⚠️  Нет товаров с остатками на первых ${testNmIds.length} nmId`);
  }

  // ═══════════════════════════════════════════════════════════════════════════════
  // ИТОГИ
  // ═══════════════════════════════════════════════════════════════════════════════

  Logger.log("\n=== ИТОГИ ===");

  const totalFeron = Object.values(results.feron).reduce((sum, qty) => sum + qty, 0);
  const totalVolt = Object.values(results.volt).reduce((sum, qty) => sum + qty, 0);

  Logger.log(`📊 Статистика (первые ${testNmIds.length} nmId):`);
  Logger.log(`   Content API: найдено карточек ${foundCards}/${testNmIds.length}`);
  Logger.log(`   Уникальных chrtId: ${uniqueChrtIds.length}`);
  Logger.log(`   ФЕРОН МОСКВА: ${Object.keys(results.feron).length} товаров с остатками, всего ${totalFeron} шт`);
  Logger.log(`   ВольтМир: ${Object.keys(results.volt).length} товаров с остатками, всего ${totalVolt} шт`);

  if (Object.keys(results.feron).length > 0 || Object.keys(results.volt).length > 0) {
    Logger.log(`\n✅ УСПЕХ! Логика работает, есть остатки!`);
    Logger.log(`\n💡 Можно обновлять WB Склады.gs`);
  } else {
    Logger.log(`\n⚠️  Нет остатков на тестовой выборке`);
    Logger.log(`\nРекомендации:`);
    Logger.log(`   1. Проверьте что токен от правильного аккаунта`);
    Logger.log(`   2. Проверьте что есть FBS склады с остатками`);
    Logger.log(`   3. Попробуйте увеличить тестовую выборку`);
  }

  Logger.log("════════════════════════════════════════════════════════════════════════");
}
