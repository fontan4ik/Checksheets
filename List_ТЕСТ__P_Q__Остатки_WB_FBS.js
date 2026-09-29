function main(){
  // O (15) обновляется отдельным шагом WbMain через Statistics API.
  // Не перезаписываем его старым запросом Marketplace API с payload {skus}.

  // P (16): Остаток ФБС ВБ — Marketplace API по chrtId.
  updateWBStocksFBSByChrtId(798761, "Остаток ФБС ВБ");

  // Q (17): ОСТ ФБС МСК ВБ - склад Москва
  updateWBFBSMoscow();             // Остатки FBS на складе Москва
}

// -- MAIN functions

/** Обновляет Q по chrtId со склада WB 1449484 (Москва). */
function updateWBFBSMoscow() {
  updateWBStocksFBSByChrtId(1449484, "ОСТ ФБС МСК ВБ");
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
function updateWBStocksFBSByChrtId(warehouseId = 798761, targetHeader = "Остаток ФБС ВБ") {
  const sheet = mainSheet();
  const targetColumn = columnByHeader_(sheet, targetHeader);
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
  const newStocks = Array.from({ length: lastRow - 1 }, () => [""]);
  const writeMask = Array.from({ length: lastRow - 1 }, () => false);

  // Подготовим мап для быстрого поиска индекса по chrtId
  const chrtIdIndexMap = new Map();
  chrtIds.forEach((chrtId, i) => {
    const chrtIdNum = Number(chrtId);
    if (!Number.isSafeInteger(chrtIdNum) || chrtIdNum <= 0) return;
    if (!chrtIdIndexMap.has(chrtIdNum)) chrtIdIndexMap.set(chrtIdNum, []);
    chrtIdIndexMap.get(chrtIdNum).push(i);
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
        throw new Error(`Не удалось получить данные для чанка ${chunkIndex + 1}`);
      }
      const responseCode = response.getResponseCode();
      if (responseCode < 200 || responseCode >= 300) {
        throw new Error(`WB FBS HTTP ${responseCode}: ${response.getContentText().substring(0, 300)}`);
      }

      const responseText = response.getContentText();
      const data = JSON.parse(responseText);

      // Проверяем структуру ответа
      if (!data || !Array.isArray(data.stocks)) {
        Logger.log(`❌ Неверная структура ответа API для чанка ${chunkIndex + 1}: ${JSON.stringify(data).substring(0, 200)}`);
        continue;
      }

      // Обрабатываем ответ
      const stocks = data.stocks;
      const requested = new Set(chunk.map(String));
      const seen = new Set();

      stocks.forEach(stock => {
        const chrtId = Number(stock?.chrtId);
        const amountRaw = stock?.amount;
        const amount = Number(amountRaw);
        const key = String(chrtId);
        if (!Number.isSafeInteger(chrtId) || chrtId <= 0 || !requested.has(key) ||
            seen.has(key) || amountRaw === null || amountRaw === undefined || amountRaw === "" ||
            !Number.isSafeInteger(amount) || amount < 0) {
          throw new Error(`WB FBS вернул неполную или неожиданную запись: ${JSON.stringify(stock).substring(0, 200)}`);
        }
        seen.add(key);
        foundCount++;

        // Пишем только chrtId, которые WB явно вернул в полном ответе.
        const rowIndexes = chrtIdIndexMap.get(chrtId) || [];
        rowIndexes.forEach(rowIndex => {
          newStocks[rowIndex][0] = amount;
          writeMask[rowIndex] = true;
        });
      });
    } catch (e) {
      Logger.log(`❌ Ошибка при обработке чанка ${chunkIndex + 1}: ${e.message}; таблица не обновлена`);
      throw e;
    }
  }

  for (let i = 0; i < newStocks.length; i++) {
    if (writeMask[i] && Number(currentStocks[i] || 0) !== Number(newStocks[i][0] || 0)) {
      updatedCount++;
    }
  }
  const written = writeMaskedColumnValues_(sheet, targetColumn, newStocks, writeMask);

  Logger.log(``);
  Logger.log(`Найдено остатков в API: ${foundCount}`);
  Logger.log(`Обновлено значений: ${updatedCount}; записано полных строк: ${written}`);
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
  updateWBStocksFBSByChrtId(798761, "Остаток ФБС ВБ");
}
