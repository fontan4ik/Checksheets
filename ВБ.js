function importStocksWithImages() {
  const url = "https://statistics-api.wildberries.ru/api/v1/supplier/stocks?dateFrom=2019-06-20";
  const sheet = mainSheet();

  const options = {
    method: "GET",
    headers: wbHeaders(),
  };

  const response = retryFetch(url, options);

  if (!response) {
    Logger.log(`❌ Не удалось получить остатки WB (importStocksWithImages)`);
    return;
  }

  const data = JSON.parse(response.getContentText());

  const totals = {};
  const nmIds = {};
  const barcodes = {};

  data.forEach(item => {
    const article = item.supplierArticle;
    const quantity = item.quantity;
    const nmId = item.nmId;
    const barcode = item.barcode

    if (totals[article]) {
      totals[article] += quantity;
    } else {
      totals[article] = quantity;
      nmIds[article] = nmId;
      barcodes[article] = barcode
    }
  });

  // Заголовки — если пусто
  if (sheet.getLastRow() === 0) {
    sheet.getRange(1, 1).setValue("Артикул");
    sheet.getRange(1, 2).setValue("Фото");
    sheet.getRange(1, 12).setValue("Сумма остатков");
  }

  // Чтение всех артикулов из колонки A
  const lastRow = sheet.getLastRow();
  const articleRange = sheet.getRange(2, 1, lastRow - 1, 18).getValues(); // get 18 columns to include old barcode & nmId
  const articleMap = {}; // { article: rowNumber }

  for (let i = 0; i < articleRange.length; i++) {
    const val = articleRange[i][0];
    if (val) articleMap[val] = i + 2; // +2 т.к. строки начинаются с 2
  }

  for (let i = 0; i < articleRange.length; i++) {
    const rowData = articleRange[i];
    const article = rowData[0];
    if (!article) continue;

    articleMap[article] = {
      row: i + 2,
      oldQuantity: rowData[11], // column L
      oldBarcode: rowData[16]   // column Q
    };
  }

  for (let article in totals) {
    const quantity = totals[article];

    if (articleMap[article]) {
      const rowInfo = articleMap[article];

      // Обновляем если значения изменились
      if (rowInfo.oldQuantity !== quantity) {
        sheet.getRange(rowInfo.row, 12).setValue(quantity); // column L
      }
      // УБРАНО: запись barcode в колонку Q (17) - это "ОСТ ФБС МСК ВБ"
    } else {
      // Добавляем новую строку
      const newRow = addAndFormatRow(sheet, 1, article);
      sheet.getRange(newRow, 12).setValue(quantity);
    }
  }
};

function main(){
  // ИСПРАВЛЕНО: колонки 15 (O), 16 (P), 17 (Q) для остатков WB
  // ПРОВЕРЬТЕ: какой warehouse_id соответствует FBO/FBS/Москва

  // O (15): Остаток ФБО ВБ
  updateStockFromWB(1449484, 15);  // warehouse_id для ФБО

  // P (16): Остаток ФБС ВБ
  updateStockFromWB(798761, 16);   // warehouse_id для ФБS

  // Q (17): ОСТ ФБС МСК ВБ - склад Москва
  updateWBFBSMoscow();             // Остатки FBS на складе Москва
}

// -- MAIN functions

function updateStockFromWB(stock_id, column) {
  const url = `https://marketplace-api.wildberries.ru/api/v3/stocks/${stock_id}`;

  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет артикулов.");
    return;
  }

  const articles = sheet.getRange(2, 1, lastRow - 1).getValues().flat(); // A (1): Артикул
  const currentStocks = sheet.getRange(2, column, lastRow - 1).getValues().flat();

  Logger.log(`=== ОБНОВЛЕНИЕ СКЛАДА ${stock_id} (колонка ${column}) ===`);

  // ИСПРАВЛЕНО: создаем мап для базовых артикулов (без суффиксов -1, -2)
  // Пример: "23348-1" -> "23348"
  const articleIndexMap = new Map();
  const baseArticleIndexMap = new Map();

  articles.forEach((art, i) => {
    if (art) {
      const artStr = String(art).trim();
      articleIndexMap.set(artStr, i);

      // Убираем суффикс после дефиса
      const baseArt = artStr.split('-')[0];
      if (baseArt !== artStr) {
        baseArticleIndexMap.set(baseArt, i);
      }
    }
  });

  const chunkSize = 999;
  let updatedStockRows = 0;
  let foundCount = 0;

  let lastRequestTime = Date.now() - 1000 / WB_RPS();

  // Итерации
  for (let i = 0; i < articles.length; i += chunkSize) {
    lastRequestTime = rateLimitRPS(lastRequestTime, WB_RPS());

    const chunk = articles.slice(i, i + chunkSize);
    const options = {
      method: "post",
      contentType: "application/json",
      headers: wbHeaders(),
      payload: JSON.stringify({ skus: chunk }),
    };
    const response = retryFetch(url, options);

    if (!response) {
      Logger.log(`❌ Не удалось получить данные склада (пустой ответ)`);
      continue;
    }

    const responseText = response.getContentText();

    // Безопасный парсинг JSON с диагностикой
    let data;
    try {
      data = JSON.parse(responseText);
    } catch (e) {
      Logger.log(`❌ Ошибка парсинга JSON: ${e.message}`);

      // Проверяем если это HTML (ошибка авторизации и т.д.)
      if (responseText.trim().startsWith('<')) {
        Logger.log(`⚠️ API вернул HTML вместо JSON. Проверьте токен WB.`);
        Logger.log(`Первые 200 символов: ${responseText.substring(0, 200)}`);
        continue;
      }

      // Логируем фрагмент вокруг ошибки
      const errorMatch = e.message.match(/position (\d+)/);
      if (errorMatch) {
        const errorPos = parseInt(errorMatch[1]);
        const start = Math.max(0, errorPos - 300);
        const end = Math.min(responseText.length, errorPos + 300);
        Logger.log(`Фрагмент вокруг позиции ${errorPos}:`);
        Logger.log(responseText.substring(start, end));
      } else {
        Logger.log(`Первые 500 символов ответа: ${responseText.substring(0, 500)}`);
      }

      continue;
    }
    data = data['stocks'];
    if (data && Array.isArray(data)) {
      data.forEach(stock => {
        // ИСПРАВЛЕНО: используем supplierArticle вместо sku
        const supplierArticle = stock.supplierArticle ? String(stock.supplierArticle).trim() : null;
        const quantity = stock.amount || 0;

        if (!supplierArticle) return;

        foundCount++;

        // Сначала пробуем найти по полному артикулу
        let matchIndex = articleIndexMap.get(supplierArticle);

        // Если не нашли, пробуем по базовому артикулу (без суффикса)
        if (matchIndex === undefined) {
          matchIndex = baseArticleIndexMap.get(supplierArticle);
        }

        if (matchIndex !== undefined) {
          const row = matchIndex + 2; // +2 т.к. первая строка — заголовок
          const oldValue = currentStocks[matchIndex];

          if (oldValue !== quantity) {
            sheet.getRange(row, column).setValue(quantity);
            updatedStockRows++;
          }
        }
      });
    } else {
      Logger.log("Ошибка ответа: " + response.getContentText());
    };
  };

  Logger.log(`Найдено записей в API: ${foundCount}`);
  Logger.log(`Обновлено строк: ${updatedStockRows}`);
  Logger.log(`✅ Завершено`);
}

function updateWBFBSMoscow() {
  const warehouseId = 1449484; // Коледино (Подмосковье) - ПРОВЕРИТЬ!
  const column = 17; // Q (17): ОСТ ФБС МСК ВБ

  const url = `https://marketplace-api.wildberries.ru/api/v3/stocks/${warehouseId}`;
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет артикулов.");
    return;
  }

  const articles = sheet.getRange(2, 1, lastRow - 1).getValues().flat();

  Logger.log(`=== ОБНОВЛЕНИЕ FBS МОСКВА (склад ${warehouseId}, колонка Q) ===`);

  // ИСПРАВЛЕНО: создаем мап для базовых артикулов
  const baseArticleIndexMap = new Map();
  articles.forEach((art, i) => {
    if (art) {
      const baseArt = String(art).trim().split('-')[0];
      baseArticleIndexMap.set(baseArt, i);
    }
  });

  const chunkSize = 999;
  let updatedCount = 0;

  let lastRequestTime = Date.now() - 1000 / WB_RPS();

  for (let i = 0; i < articles.length; i += chunkSize) {
    lastRequestTime = rateLimitRPS(lastRequestTime, WB_RPS());

    const chunk = articles.slice(i, i + chunkSize);
    const options = {
      method: "post",
      contentType: "application/json",
      headers: wbHeaders(),
      payload: JSON.stringify({ skus: chunk }),
    };
    const response = retryFetch(url, options);

    if (!response) {
      Logger.log(`❌ Не удалось получить данные склада (пустой ответ)`);
      continue;
    }

    const responseText = response.getContentText();

    // Безопасный парсинг JSON с диагностикой
    let data;
    try {
      data = JSON.parse(responseText);
    } catch (e) {
      Logger.log(`❌ Ошибка парсинга JSON: ${e.message}`);

      // Проверяем если это HTML (ошибка авторизации и т.д.)
      if (responseText.trim().startsWith('<')) {
        Logger.log(`⚠️ API вернул HTML вместо JSON. Проверьте токен WB.`);
        Logger.log(`Первые 200 символов: ${responseText.substring(0, 200)}`);
        continue;
      }

      // Логируем фрагмент вокруг ошибки
      const errorMatch = e.message.match(/position (\d+)/);
      if (errorMatch) {
        const errorPos = parseInt(errorMatch[1]);
        const start = Math.max(0, errorPos - 300);
        const end = Math.min(responseText.length, errorPos + 300);
        Logger.log(`Фрагмент вокруг позиции ${errorPos}:`);
        Logger.log(responseText.substring(start, end));
      } else {
        Logger.log(`Первые 500 символов ответа: ${responseText.substring(0, 500)}`);
      }

      continue;
    }
    data = data['stocks'];

    if (data && Array.isArray(data)) {
      data.forEach(stock => {
        const supplierArticle = stock.supplierArticle ? String(stock.supplierArticle).trim() : null;
        const quantity = stock.amount || 0;

        if (!supplierArticle) return;

        // Ищем по базовому артикулу (без суффикса)
        const matchIndex = baseArticleIndexMap.get(supplierArticle);

        if (matchIndex !== undefined) {
          const row = matchIndex + 2;
          sheet.getRange(row, column).setValue(quantity);
          updatedCount++;
        }
      });
    }
  };

  Logger.log(`Обновлено строк: ${updatedCount}`);
  Logger.log(`✅ Завершено`);
}

/**
 * ИСПРАВЛЕНО: FBO остатки через Analytics API (правильный метод)
 *
 * Заполняет колонку O (15): Остаток ФБО ВБ
 *
 * Использует правильный API endpoint:
 * GET https://seller-analytics-api.wildberries.ru/api/v2/stocks-report/products/products
 *
 * Параметры:
 * @param {string} dateFrom - Начальная дата в формате ISO (YYYY-MM-DDTHH:mm:ss.SSSZ)
 * @param {string} dateTo - Конечная дата в формате ISO
 */
function updateFBOStocksFromAnalytics(dateFrom, dateTo) {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет артикулов.");
    return;
  }

  Logger.log(`=== ОБНОВЛЕНИЕ FBO ОСТАТКОВ (Analytics API) ===`);
  Logger.log(`Период: с ${dateFrom} по ${dateTo}`);

  // Формируем URL для stocks report API
  const url = `${wbAnalyticsStocksURL()}?dateFrom=${encodeURIComponent(dateFrom)}&dateTo=${encodeURIComponent(dateTo)}&limit=100000`;

  Logger.log(`API Endpoint: ${url}`);

  const options = {
    method: "get",
    headers: wbHeaders(),
    muteHttpExceptions: true
  };

  try {
    const response = retryFetch(url, options);

    if (!response) {
      Logger.log(`❌ Не удалось получить FBO остатки (Analytics API)`);
      return;
    }

    const responseText = response.getContentText();

    // Безопасный парсинг JSON с диагностикой
    let data;
    try {
      data = JSON.parse(responseText);
    } catch (e) {
      Logger.log(`❌ Ошибка парсинга JSON: ${e.message}`);

      // Проверяем если это HTML (ошибка авторизации и т.д.)
      if (responseText.trim().startsWith('<')) {
        Logger.log(`⚠️ API вернул HTML вместо JSON. Проверьте токен WB.`);
        Logger.log(`Первые 200 символов: ${responseText.substring(0, 200)}`);
        return;
      }

      // Логируем фрагмент вокруг ошибки
      const errorMatch = e.message.match(/position (\d+)/);
      if (errorMatch) {
        const errorPos = parseInt(errorMatch[1]);
        const start = Math.max(0, errorPos - 300);
        const end = Math.min(responseText.length, errorPos + 300);
        Logger.log(`Фрагмент вокруг позиции ${errorPos}:`);
        Logger.log(responseText.substring(start, end));
      } else {
        Logger.log(`Первые 500 символов ответа: ${responseText.substring(0, 500)}`);
      }

      return;
    }

    // Проверка структуры ответа
    if (!data || !Array.isArray(data)) {
      Logger.log(`❌ Ошибка ответа API: ${JSON.stringify(data).substring(0, 200)}`);
      return;
    }

    Logger.log(`✅ Получено товаров: ${data.length}`);

    // Агрегируем данные по nmId
    const stockMap = {};

    data.forEach(item => {
      const nmId = item.nmId;
      const quantity = item.quantity || 0;

      if (nmId) {
        if (!stockMap[nmId]) {
          stockMap[nmId] = 0;
        }
        stockMap[nmId] += quantity;
      }
    });

    // Читаем nmId из колонки T (20)
    const nmIds = sheet.getRange(2, 20, lastRow - 1).getValues().flat();
    const currentStocks = sheet.getRange(2, 15, lastRow - 1).getValues().flat(); // O (15)

    let updatedCount = 0;

    // Обновляем остатки
    const newStocks = [];
    for (let i = 0; i < nmIds.length; i++) {
      const nmId = nmIds[i];
      const newStock = nmId ? (stockMap[nmId] || 0) : "";

      if (newStock !== "" && newStock !== currentStocks[i]) {
        updatedCount++;
      }

      newStocks.push([newStock]);
    }

    // Записываем в O (15): Остаток ФБО ВБ
    sheet.getRange(2, 15, newStocks.length, 1).setValues(newStocks);

    Logger.log(`Обновлено строк: ${updatedCount}`);
    Logger.log(`✅ Завершено`);

  } catch (e) {
    Logger.log(`❌ Ошибка: ${e.message}`);
    Logger.log(e.stack);
  }
}

/**
 * Новая главная функция для обновления всех остатков WB
 * Использует правильные API endpoints
 */
function mainV2() {
  const today = new Date();

  // Форматируем даты для WB Analytics API (ISO format)
  const formatDateISO = date => {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}T00:00:00.000Z`;
  };

  // Диапазон: сегодняшний день месяц назад по сегодня
  const dateFrom = new Date(today.getFullYear(), today.getMonth() - 1, today.getDate());
  const dateTo = today;

  const dateFromISO = formatDateISO(dateFrom);
  const dateToISO = formatDateISO(dateTo);

  // O (15): Остаток ФБО ВБ - через Analytics API
  updateFBOStocksFromAnalytics(dateFromISO, dateToISO);

  // P (16), Q (17): FBS остатки - оставляем старый метод через warehouse API
  updateStockFromWB(1449484, 16); // P: Остаток ФБС ВБ
  updateWBFBSMoscow();            // Q: ОСТ ФБС МСК ВБ
}

/**
 * Обновление остатков ФБС ВБ по chrtId из колонки AZ (52)
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

/**
 * Обновление остатков ФБС ВБ по chrtId из колонки AZ (52)
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
function updateWBStocksFBSByChrtIdFromChrtIdColumn(warehouseId = 798761) {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет данных для обновления.");
    return;
  }

  Logger.log(`=== ОБНОВЛЕНИЕ ОСТАТКОВ ФБС ВБ (O, 15) ПО CHRTID ИЗ КОЛОНКИ AZ (52) ===`);
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
 * Обертка для обновления остатков FBS по chrtId из колонки AZ (52)
 */
function updateWBStocksFBSDirectFromChrtIdColumn() {
  // Используем стандартный warehouseId для FBS
  updateWBStocksFBSByChrtIdFromChrtIdColumn(798761);
}

