/**
 * WB ОСТАТКИ FBS ПО CHRTID - НОВАЯ ВЕРСИЯ
 *
 * Заполняет колонку O (15): Остаток ФБС ВБ
 * Сопоставляет по chrtId из колонки AZ (52)
 *
 * ИСПОЛЬЗУЕТ:
 * POST https://marketplace-api.wildberries.ru/api/v3/stocks/{warehouseId}
 *
 * Payload:
 * {
 *   "chrtIds": [12345678, ...]
 * }
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
 * Обертка для обновления остатков FBS по chrtId с использованием стандартного warehouseId
 */
function updateWBStocksFBSDirect() {
  // Используем стандартный warehouseId для FBS
  updateWBStocksFBSByChrtId(798761);
}