function main(){
  // O (15) обновляется отдельным шагом WbMain через Statistics API.
  // Не перезаписываем его старым запросом Marketplace API с payload {skus}.

  // P (16): Остаток ФБС ВБ — Marketplace API по chrtId.
  updateWBStocksFBSByChrtId(798761, 16);

  // Q (17): ОСТ ФБС МСК ВБ - склад Москва
  updateWBFBSMoscow();             // Остатки FBS на складе Москва
}

// -- MAIN functions

/** Обновляет Q по chrtId со склада WB 1449484 (Москва). */
function updateWBFBSMoscow() {
  updateWBStocksFBSByChrtId(1449484, 17);
}

/**
 * Обновление остатков ФБС ВБ по chrtId из колонки AZ (52)
 *
 * Обновляет колонку targetColumn (по умолчанию P, 16): Остаток ФБС ВБ
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
function updateWBStocksFBSByChrtId(warehouseId = 798761, targetColumn = 16) {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет данных для обновления.");
    return;
  }

  Logger.log(`=== ОБНОВЛЕНИЕ ОСТАТКОВ ФБС ВБ (${targetColumn}) ПО CHRTID ===`);
  Logger.log(`Warehouse ID: ${warehouseId}`);

  // Читаем chrtId из колонки AZ (52)
  const chrtIds = sheet.getRange(2, 52, lastRow - 1).getValues().flat(); // AZ (52): chrtId
  const currentStocks = sheet.getRange(2, targetColumn, lastRow - 1).getValues().flat();
  const newStocks = Array.from({ length: lastRow - 1 }, () => [0]);

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
            newStocks[rowIndex][0] = amount;
          }
        }
      });
    } catch (e) {
      Logger.log(`❌ Ошибка при обработке чанка ${chunkIndex + 1}: ${e.message}`);
      continue;
    }
  }

  for (let i = 0; i < newStocks.length; i++) {
    if (Number(currentStocks[i] || 0) !== Number(newStocks[i][0] || 0)) {
      updatedCount++;
    }
  }
  sheet.getRange(2, targetColumn, newStocks.length, 1).setValues(newStocks);

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

/** Совместимое имя ручного запуска: тот же расчёт P из AZ. */
function updateWBStocksFBSDirectFromChrtIdColumn() {
  // Используем стандартный warehouseId для FBS
  updateWBStocksFBSByChrtId(798761, 16);
}

