/**
 * WB ОСТАТКИ FBS ПО CHRTID - УЛУЧШЕННАЯ ВЕРСИЯ
 *
 * Заполняет колонку O (15): Остаток ФБС ВБ
 * Сопоставляет по chrtId из колонки AZ (52)
 *
 * ИСПОЛЬЗУЕТ:
 * GET https://marketplace-api.wildberries.ru/api/v3/warehouses - получение списка складов
 * POST https://marketplace-api.wildberries.ru/api/v3/stocks/{warehouseId} - получение остатков
 *
 * НОВОЕ: Выгружает остатки со ВСЕХ складов FBS и суммирует их
 */

/**
 * Получает список всех складов WB
 * @returns {Array} Массив объектов складов с полями: id, name, officeId
 */
function getWBWarehouses() {
  const url = "https://marketplace-api.wildberries.ru/api/v3/warehouses";

  const options = {
    method: "get",
    contentType: "application/json",
    headers: wbHeaders(),
    muteHttpExceptions: true
  };

  try {
    const response = retryFetch(url, options);

    if (!response) {
      Logger.log("❌ Не удалось получить список складов");
      return [];
    }

    const responseText = response.getContentText();
    let data;

    try {
      data = JSON.parse(responseText);
    } catch (e) {
      Logger.log(`❌ Ошибка парсинга JSON списка складов: ${e.message}`);
      if (responseText.trim().startsWith('<')) {
        Logger.log(`⚠️ API вернул HTML вместо JSON. Проверьте токен WB.`);
      }
      return [];
    }

    if (!data || !Array.isArray(data)) {
      Logger.log(`❌ Неверная структура ответа API складов: ${JSON.stringify(data).substring(0, 200)}`);
      return [];
    }

    Logger.log(`✅ Получено складов: ${data.length}`);
    data.forEach(wh => {
      Logger.log(`  - ${wh.name} (id: ${wh.id}, officeId: ${wh.officeId})`);
    });
    return data;

  } catch (e) {
    Logger.log(`❌ Ошибка при получении списка складов: ${e.message}`);
    return [];
  }
}

/**
 * ОСНОВНАЯ ФУНКЦИЯ: Обновляет остатки FBS со ВСЕХ складов WB
 * Суммирует остатки для одинаковых chrtId с разных складов
 */
function updateWBStocksFBSAllWarehouses() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет данных для обновления.");
    return;
  }

  Logger.log(`=== ОБНОВЛЕНИЕ ОСТАТКОВ ФБС ВБ СО ВСЕХ СКЛАДОВ (O, 15) ПО CHRTID ===`);

  // Получаем список всех складов
  const warehouses = getWBWarehouses();

  if (warehouses.length === 0) {
    Logger.log("❌ Не удалось получить список складов. Используем склад по умолчанию.");
    updateWBStocksFBSByChrtId(798761);
    return;
  }

  Logger.log(`Будет обработано складов: ${warehouses.length}`);
  warehouses.forEach(wh => {
    Logger.log(`  - ${wh.name} (ID: ${wh.id})`);
  });

  // Читаем chrtId из колонки AZ (52)
  const chrtIds = sheet.getRange(2, 52, lastRow - 1).getValues().flat(); // AZ (52): chrtId

  // Подготовим мап для быстрого поиска индекса по chrtId
  const chrtIdIndexMap = new Map();
  chrtIds.forEach((chrtId, i) => {
    if (chrtId && chrtId > 0) {
      const chrtIdNum = parseInt(chrtId);
      if (!isNaN(chrtIdNum)) {
        chrtIdIndexMap.set(chrtIdNum, i);
      }
    }
  });

  // Получим уникальные chrtId для запроса
  const uniqueChrtIds = [...new Set([...chrtIdIndexMap.keys()].filter(id => id > 0))];

  if (uniqueChrtIds.length === 0) {
    Logger.log("Нет действительных chrtId для запроса.");
    return;
  }

  Logger.log(`Найдено уникальных chrtId в таблице: ${uniqueChrtIds.length}`);

  // Map для накопления остатков: chrtId -> totalAmount
  const stocksAccumulator = new Map();

  // Разобьем на чанки по 1000 (ограничение API)
  const chunkSize = 1000;
  const chunks = [];
  for (let i = 0; i < uniqueChrtIds.length; i += chunkSize) {
    chunks.push(uniqueChrtIds.slice(i, i + chunkSize));
  }

  Logger.log(`Чанков для обработки: ${chunks.length}`);
  Logger.log(``);

  let totalFoundCount = 0;
  let lastRequestTime = Date.now() - 1000 / WB_RPS();

  // Проходим по каждому складу
  for (let whIndex = 0; whIndex < warehouses.length; whIndex++) {
    const warehouse = warehouses[whIndex];
    const warehouseId = warehouse.id;
    const warehouseName = warehouse.name;

    Logger.log(`--- СКЛАД ${whIndex + 1}/${warehouses.length}: ${warehouseName} (ID: ${warehouseId}) ---`);

    const url = `https://marketplace-api.wildberries.ru/api/v3/stocks/${warehouseId}`;
    let warehouseFoundCount = 0;

    // Обработка чанков для текущего склада
    for (let chunkIndex = 0; chunkIndex < chunks.length; chunkIndex++) {
      const chunk = chunks[chunkIndex];

      // Ограничиваем частоту запросов
      lastRequestTime = rateLimitRPS(lastRequestTime, WB_RPS());

      const options = {
        method: "post",
        contentType: "application/json",
        headers: wbHeaders(),
        payload: JSON.stringify({
          chrtIds: chunk
        }),
        muteHttpExceptions: true
      };

      try {
        const response = retryFetch(url, options);

        if (!response) {
          Logger.log(`  ❌ Не удалось получить данные для чанка ${chunkIndex + 1}/${chunks.length}`);
          continue;
        }

        const responseText = response.getContentText();
        let data;

        try {
          data = JSON.parse(responseText);
        } catch (e) {
          Logger.log(`  ❌ Ошибка парсинга JSON для чанка ${chunkIndex + 1}: ${e.message}`);
          if (responseText.trim().startsWith('<')) {
            Logger.log(`  ⚠️ API вернул HTML вместо JSON. Проверьте токен WB.`);
          }
          continue;
        }

        // Проверяем структуру ответа
        if (!data || !Array.isArray(data.stocks)) {
          Logger.log(`  ❌ Неверная структура ответа API для чанка ${chunkIndex + 1}`);
          continue;
        }

        // Обрабатываем ответ - накапливаем остатки
        const stocks = data.stocks;

        stocks.forEach(stock => {
          const chrtId = stock.chrtId;
          const amount = stock.amount || 0;

          if (chrtId && amount > 0) {
            warehouseFoundCount++;

            // Суммируем остатки для одинаковых chrtId
            const currentAmount = stocksAccumulator.get(chrtId) || 0;
            stocksAccumulator.set(chrtId, currentAmount + amount);
          }
        });

        if (chunks.length > 1) {
          Logger.log(`  Чанк ${chunkIndex + 1}/${chunks.length}: найдено ${stocks.length} позиций`);
        }

      } catch (e) {
        Logger.log(`  ❌ Ошибка при обработке чанка ${chunkIndex + 1}: ${e.message}`);
        continue;
      }
    }

    Logger.log(`  Найдено остатков на складе: ${warehouseFoundCount}`);
    totalFoundCount += warehouseFoundCount;
    Logger.log(``);
  }

  // Записываем накопленные остатки в таблицу
  Logger.log(`--- ЗАПИСЬ РЕЗУЛЬТАТОВ В ТАБЛИЦУ ---`);
  Logger.log(`Всего найдено остатков (с учетом всех складов): ${totalFoundCount}`);
  Logger.log(`Уникальных товаров с остатками: ${stocksAccumulator.size}`);

  let updatedCount = 0;
  const currentStocks = sheet.getRange(2, 15, lastRow - 1).getValues().flat(); // O (15): Остаток ФБС ВБ

  stocksAccumulator.forEach((totalAmount, chrtId) => {
    const rowIndex = chrtIdIndexMap.get(chrtId);

    if (rowIndex !== undefined) {
      const row = rowIndex + 2; // +2 т.к. первая строка — заголовок
      const oldValue = currentStocks[rowIndex];

      if (oldValue !== totalAmount) {
        sheet.getRange(row, 15).setValue(totalAmount); // O (15): Остаток ФБС ВБ
        updatedCount++;
      }
    }
  });

  // Обнуляем товары, которых нет в остатках
  for (let i = 0; i < chrtIds.length; i++) {
    const chrtId = parseInt(chrtIds[i]);
    if (chrtId > 0 && !stocksAccumulator.has(chrtId)) {
      const oldValue = currentStocks[i];
      if (oldValue !== 0 && oldValue !== "" && oldValue !== null) {
        sheet.getRange(i + 2, 15).setValue(0); // O (15): Остаток ФБС ВБ
        updatedCount++;
      }
    }
  }

  Logger.log(`Обновлено строк: ${updatedCount}`);
  Logger.log(`✅ ЗАВЕРШЕНО`);
}

/**
 * ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: Обновляет остатки FBS для конкретного склада
 * @param {number} warehouseId - ID склада WB
 */
function updateWBStocksFBSByChrtId(warehouseId = 798761) {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет данных для обновления.");
    return;
  }

  Logger.log(`=== ОБНОВЛЕНИЕ ОСТАТКОВ ФБС ВБ (O, 15) ПО CHRTID ===`);
  Logger.log(`Warehouse ID: ${warehouseId}`);

  // Читаем chrtId из колонки AZ (52)
  const chrtIds = sheet.getRange(2, 52, lastRow - 1).getValues().flat(); // AZ (52): chrtId
  const currentStocks = sheet.getRange(2, 15, lastRow - 1).getValues().flat(); // O (15): Остаток ФБС ВБ

  // Подготовим мап для быстрого поиска индекса по chrtId
  const chrtIdIndexMap = new Map();
  chrtIds.forEach((chrtId, i) => {
    if (chrtId && chrtId > 0) {
      const chrtIdNum = parseInt(chrtId);
      if (!isNaN(chrtIdNum)) {
        chrtIdIndexMap.set(chrtIdNum, i);
      }
    }
  });

  // Получим уникальные chrtId для запроса
  const uniqueChrtIds = [...new Set([...chrtIdIndexMap.keys()].filter(id => id > 0))];

  if (uniqueChrtIds.length === 0) {
    Logger.log("Нет действительных chrtId для запроса.");
    return;
  }

  Logger.log(`Найдено уникальных chrtId: ${uniqueChrtIds.length}`);

  // Разобьем на чанки по 1000 (ограничение API)
  const chunkSize = 1000;
  const chunks = [];
  for (let i = 0; i < uniqueChrtIds.length; i += chunkSize) {
    chunks.push(uniqueChrtIds.slice(i, i + chunkSize));
  }

  // URL для API запроса
  const url = `https://marketplace-api.wildberries.ru/api/v3/stocks/${warehouseId}`;

  let updatedCount = 0;
  let foundCount = 0;

  // Обработка чанков
  for (let chunkIndex = 0; chunkIndex < chunks.length; chunkIndex++) {
    const chunk = chunks[chunkIndex];

    Logger.log(`Обработка чанка ${chunkIndex + 1}/${chunks.length}: ${chunk.length} chrtId`);

    // Ограничиваем частоту запросов
    const lastRequestTime = rateLimitRPS(Date.now() - 1000 / WB_RPS(), WB_RPS());

    const options = {
      method: "post",
      contentType: "application/json",
      headers: wbHeaders(),
      payload: JSON.stringify({
        chrtIds: chunk
      }),
      muteHttpExceptions: true
    };

    try {
      const response = retryFetch(url, options);

      if (!response) {
        Logger.log(`❌ Не удалось получить данные для чанка ${chunkIndex + 1}`);
        continue;
      }

      const responseText = response.getContentText();
      let data;

      try {
        data = JSON.parse(responseText);
      } catch (e) {
        Logger.log(`❌ Ошибка парсинга JSON для чанка ${chunkIndex + 1}: ${e.message}`);

        // Проверяем если это HTML (ошибка авторизации и т.д.)
        if (responseText.trim().startsWith('<')) {
          Logger.log(`⚠️ API вернул HTML вместо JSON. Проверьте токен WB.`);
          Logger.log(`Первые 200 символов: ${responseText.substring(0, 200)}`);
          continue;
        }

        Logger.log(`Ответ: ${responseText.substring(0, 500)}`);
        continue;
      }

      // Проверяем структуру ответа
      if (!data || !Array.isArray(data.stocks)) {
        Logger.log(`❌ Неверная структура ответа API для чанка ${chunkIndex + 1}: ${JSON.stringify(data).substring(0, 200)}`);
        continue;
      }

      // Обрабатываем ответ
      const stocks = data.stocks;

      stocks.forEach(stock => {
        const chrtId = stock.chrtId;
        const amount = stock.amount || 0;

        if (chrtId) {
          foundCount++;

          // Находим соответствующий индекс в таблице
          const rowIndex = chrtIdIndexMap.get(chrtId);

          if (rowIndex !== undefined) {
            const row = rowIndex + 2; // +2 т.к. первая строка — заголовок
            const oldValue = currentStocks[rowIndex];

            if (oldValue !== amount) {
              sheet.getRange(row, 15).setValue(amount); // O (15): Остаток ФБС ВБ
              updatedCount++;
            }
          }
        }
      });
    } catch (e) {
      Logger.log(`❌ Ошибка при обработке чанка ${chunkIndex + 1}: ${e.message}`);
      continue;
    }
  }

  Logger.log(``);
  Logger.log(`Найдено остатков в API: ${foundCount}`);
  Logger.log(`Обновлено строк: ${updatedCount}`);
  Logger.log(`✅ Завершено`);
}

/**
 * ТОЧКА ВХОДА: Обновление остатков FBS со всех складов (рекомендуется)
 */
function updateWBStocksFBSDirect() {
  updateWBStocksFBSAllWarehouses();
}
