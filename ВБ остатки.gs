/**
 * WB STOCKS - ИСПРАВЛЕННАЯ ВЕРСИЯ
 *
 * Заполняет колонку O (15): Остаток ФБО ВБ
 *
 * ИСПРАВЛЕНО: Использует правильный API:
 * GET https://statistics-api.wildberries.ru/api/v1/supplier/stocks?dateFrom=2019-06-20
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
  const currentStocks = sheet.getRange(2, 15, lastRow - 1).getValues().flat(); // O (15): Остаток ФБО ВБ

  // ИСПРАВЛЕНО: используем старый API statistics-api
  const url = "https://statistics-api.wildberries.ru/api/v1/supplier/stocks?dateFrom=2019-06-20";

  const options = {
    method: "get",
    headers: wbHeaders(),
    muteHttpExceptions: true
  };

  try {
    const response = retryFetch(url, options);

    if (!response) {
      Logger.log(`❌ Не удалось получить остатки ФБО ВБ`);
      return;
    }

    const data = JSON.parse(response.getContentText());

    if (!Array.isArray(data)) {
      Logger.log(`❌ Ошибка ответа API: ${JSON.stringify(data).substring(0, 200)}`);
      return;
    }

    Logger.log(`✅ Получено записей: ${data.length}`);

    // ИСПРАВЛЕНО: суммируем quantity по supplierArticle
    const stockMap = {};

    data.forEach(item => {
      const supplierArticle = item.supplierArticle;
      const quantity = item.quantity || 0;

      if (supplierArticle) {
        if (!stockMap[supplierArticle]) {
          stockMap[supplierArticle] = 0;
        }
        stockMap[supplierArticle] += quantity;
      }
    });

    // Обновляем таблицу
    let updatedStockRows = 0;
    let foundCount = 0;

    for (let i = 0; i < articles.length; i++) {
      const art = articles[i];

      if (!art) {
        continue;
      }

      const artStr = String(art).trim();
      const quantity = stockMap[artStr] || 0;

      if (quantity > 0) {
        foundCount++;
      }

      const oldValue = currentStocks[i];

      // ИСПРАВЛЕНО: обновляем если значения не совпадают (включая случай undefined/пусто)
      if (oldValue != quantity) {
        sheet.getRange(i + 2, 15).setValue(quantity); // O (15)
        updatedStockRows++;
      }
    }

    // ДИАГНОСТИКА для 22068-1
    const testArticle = "22068-1";
    const testQuantity = stockMap[testArticle] || 0;
    Logger.log(``);
    Logger.log(`=== ДИАГНОСТИКА ${testArticle} ===`);
    Logger.log(`   Остаток ФБО ВБ: ${testQuantity} (ожидается 36)`);
    Logger.log(`${testQuantity === 36 ? '✅' : '❌'} Проверка данных`);

    Logger.log(`Найдено товаров с остатками: ${foundCount}`);
    Logger.log(`Обновлено строк: ${updatedStockRows}`);
    Logger.log(`✅ Завершено`);

  } catch (e) {
    Logger.log(`❌ Ошибка: ${e.message}`);
  }
}

/**
 * СТАРАЯ ВЕРСИЯ через marketplace-api (не работает для всех товаров)
 * Оставлена для совместимости
 */
function updateStockFromWB(stock_id, column) {
  const url = `https://marketplace-api.wildberries.ru/api/v3/stocks/${stock_id}`;

  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет артикулов.");
    return;
  }

  const articles = sheet.getRange(2, 1, lastRow - 1).getValues().flat();
  const currentStocks = sheet.getRange(2, column, lastRow - 1).getValues().flat();

  Logger.log(`=== ОБНОВЛЕНИЕ СКЛАДА ${stock_id} (колонка ${column}) ===`);

  const articleIndexMap = new Map();
  const baseArticleIndexMap = new Map();

  articles.forEach((art, i) => {
    if (art) {
      const artStr = String(art).trim();
      articleIndexMap.set(artStr, i);

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
      Logger.log(`❌ Не удалось получить данные склада ${stock_id}`);
      continue;
    }

    var data = JSON.parse(response.getContentText());
    data = data['stocks'];
    if (data && Array.isArray(data)) {
      data.forEach(stock => {
        const supplierArticle = stock.supplierArticle ? String(stock.supplierArticle).trim() : null;
        const quantity = stock.amount || 0;

        if (!supplierArticle) return;

        foundCount++;

        let matchIndex = articleIndexMap.get(supplierArticle);

        if (matchIndex === undefined) {
          matchIndex = baseArticleIndexMap.get(supplierArticle);
        }

        if (matchIndex !== undefined) {
          const row = matchIndex + 2;
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
