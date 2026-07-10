// ============================================
// FERON API - Получение остатков по складам
// Заполняет колонки AI (35), AJ (36), AK (37)
// ============================================

/**
 * Обновить остатки по всем складам Feron
 *
 * Заполняет:
 * - AI (35): Ферон Самара
 * - AJ (36): Ферон Внуково
 * - AK (37): Ферон Новосибирск
 */
function updateFeronStocks() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет артикулов для обработки");
    return;
  }

  Logger.log("=== ОБНОВЛЕНИЕ ОСТАТКОВ FERON ===");

  // Читаем артикулы из колонки A (1)
  const articles = sheet.getRange(2, 1, lastRow - 1).getValues().flat();

  // Фильтруем валидные артикулы
  const validArticles = articles
    .map((art, index) => ({ article: String(art).trim(), index }))
    .filter(item => item.article && item.article !== "");

  if (validArticles.length === 0) {
    Logger.log("Нет валидных артикулов");
    return;
  }

  Logger.log(`Всего артикулов для запроса: ${validArticles.length}`);

  // Получаем остатки от Feron API
  const feronStocks = fetchFeronStocks(validArticles.map(item => item.article));

  if (!feronStocks) {
    Logger.log("❌ Не удалось получить остатки от Feron API");
    return;
  }

  // Подготавливаем массивы для записи
  const samaraStocks = articles.map(() => [""]);
  const vnukovoStocks = articles.map(() => [""]);
  const novosibirskStocks = articles.map(() => [""]);

  // Заполняем данные
  validArticles.forEach(item => {
    const stockData = feronStocks[item.article];
    if (stockData) {
      samaraStocks[item.index] = [stockData.samara || 0];
      vnukovoStocks[item.index] = [stockData.vnukovo || 0];
      novosibirskStocks[item.index] = [stockData.novosibirsk || 0];
    }
  });

  // Записываем в таблицу
  sheet.getRange(2, 35, samaraStocks.length, 1).setValues(samaraStocks);        // AI (35)
  sheet.getRange(2, 36, vnukovoStocks.length, 1).setValues(vnukovoStocks);     // AJ (36)
  sheet.getRange(2, 37, novosibirskStocks.length, 1).setValues(novosibirskStocks); // AK (37)

  // Статистика
  const samaraCount = samaraStocks.filter(v => v[0] && v[0] !== "").length;
  const vnukovoCount = vnukovoStocks.filter(v => v[0] && v[0] !== "").length;
  const novosibirskCount = novosibirskStocks.filter(v => v[0] && v[0] !== "").length;

  Logger.log(`✅ Завершено:`);
  Logger.log(`   Самара: ${samaraCount} товаров`);
  Logger.log(`   Внуково: ${vnukovoCount} товаров`);
  Logger.log(`   Новосибирск: ${novosibirskCount} товаров`);
}

/**
 * Получить остатки от Feron API
 *
 * @param {string[]} articles - Массив артикулов для фильтрации (или пустой массив для всех)
 * @returns {Object} Объект с артикулами и остатками по складам
 */
function fetchFeronStocks(articles) {
  // Если артикулов много, разбиваем на чанки
  const chunkSize = 1000;
  const chunks = [];

  if (!articles || articles.length === 0) {
    // Получаем все товары без фильтра
    chunks.push([]);
  } else if (articles.length > chunkSize) {
    // Разбиваем на части
    for (let i = 0; i < articles.length; i += chunkSize) {
      chunks.push(articles.slice(i, i + chunkSize));
    }
    Logger.log(`Разбито ${articles.length} артикулов на ${chunks.length} чанков`);
  } else {
    chunks.push(articles);
  }

  const stockMap = {};

  chunks.forEach((chunk, index) => {
    if (chunks.length > 1) {
      Logger.log(`Обработка чанка ${index + 1}/${chunks.length} (${chunk.length} артикулов)...`);
    }

    const chunkStocks = fetchFeronStocksChunk(chunk);

    if (chunkStocks) {
      Object.assign(stockMap, chunkStocks);
    }

    // Небольшая пауза между чанками
    if (index < chunks.length - 1) {
      Utilities.sleep(500);
    }
  });

  Logger.log(`✅ Всего получено данных от Feron: ${Object.keys(stockMap).length} товаров`);
  return stockMap;
}

/**
 * Получить остатки от Feron API для одного чанка
 *
 * @param {string[]} articles - Массив артикулов для фильтрации
 * @returns {Object} Объект с артикулами и остатками по складам
 */
function fetchFeronStocksChunk(articles) {
  const url = `${feronAPIUrl()}/v1/stocks/list`;

  const payload = {
    filter: articles || []
  };

  const options = {
    method: "post",
    headers: {
      "Content-Type": "application/json",
      "API-KEY": feronAPIKey()
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  try {
    // Диагностика: выводим URL и первые артикулы
    Logger.log(`URL запроса: ${url}`);
    if (articles && articles.length > 0) {
      Logger.log(`Примеры артикулов: ${articles.slice(0, 3).join(", ")}${articles.length > 3 ? "..." : ""}`);
    }
    Logger.log(`API-KEY (первые 10 символов): ${feronAPIKey().substring(0, 10)}...`);

    const response = retryFetch(url, options);

    // Проверка на null после retryFetch
    if (!response) {
      Logger.log(`❌ retryFetch вернул null - API не ответил`);
      return null;
    }

    const responseCode = response.getResponseCode();
    Logger.log(`Код ответа Feron API: ${responseCode}`);

    if (responseCode !== 200) {
      const responseText = response.getContentText();
      Logger.log(`❌ Ошибка Feron API (${responseCode}): ${responseText.substring(0, 500)}`);
      return null;
    }

    const responseText = response.getContentText();
    const data = JSON.parse(responseText);

    if (!Array.isArray(data)) {
      Logger.log(`❌ Неверный формат ответа Feron API`);
      return null;
    }

    // Создаём мапу: артикул -> { samara, vnukovo, novosibirsk }
    const stockMap = {};

    data.forEach(item => {
      const code = item.code;
      if (!code || !item.stocks) return;

      stockMap[code] = {
        samara: 0,
        vnukovo: 0,
        novosibirsk: 0
      };

      item.stocks.forEach(stock => {
        const warehouse = stock.warehouse;
        const quantity = stock.stock || 0;

        switch (warehouse) {
          case "samara":
            stockMap[code].samara = quantity;
            break;
          case "vnukovo":
            stockMap[code].vnukovo = quantity;
            break;
          case "novosibirsk":
            stockMap[code].novosibirsk = quantity;
            break;
        }
      });
    });

    return stockMap;

  } catch (e) {
    Logger.log(`❌ Ошибка при запросе к Feron API: ${e.message}`);
    return null;
  }
}

/**
 * Тестовая функция: проверить остатки конкретного артикула
 *
 * @param {string} article - Артикул для проверки
 */
function testFeronArticle(article) {
  Logger.log(`=== ПРОВЕРКА АРТИКУЛА ${article} ===`);

  const stocks = fetchFeronStocks([article]);

  if (!stocks || !stocks[article]) {
    Logger.log(`❌ Артикул ${article} не найден в Feron`);
    return;
  }

  const data = stocks[article];
  Logger.log(`Самара: ${data.samara}`);
  Logger.log(`Внуково: ${data.vnukovo}`);
  Logger.log(`Новосибирск: ${data.novosibirsk}`);
}

/**
 * Тестовая функция: проверить несколько артикулов
 */
function testFeronArticles() {
  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ТЕСТ FERON API                                                       ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");
  Logger.log(`Base URL: ${feronAPIUrl()}`);
  Logger.log(`API-KEY (первые 10 символов): ${feronAPIKey().substring(0, 10)}...`);
  Logger.log("");

  testFeronArticle("48546");
  testFeronArticle("38269");
}

/**
 * Диагностика: проверить подключение к Feron API без фильтра
 * Получает все товары с остатками
 */
function testFeronConnection() {
  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ТЕСТ ПОДКЛЮЧЕНИЯ FERON API (все товары)                            ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");
  Logger.log("");

  const stocks = fetchFeronStocks([]);

  if (!stocks) {
    Logger.log("❌ Не удалось подключиться к Feron API");
    Logger.log("");
    Logger.log("Возможные причины:");
    Logger.log("1. Неверный API-KEY");
    Logger.log("2. Неверный базовый URL");
    Logger.log("3. Сервер недоступен");
    return;
  }

  const count = Object.keys(stocks).length;
  Logger.log(`✅ Успешно! Получено товаров: ${count}`);
  Logger.log("");

  // Показать первые 3 товара
  const firstCodes = Object.keys(stocks).slice(0, 3);
  firstCodes.forEach(code => {
    const s = stocks[code];
    Logger.log(`Артикул ${code}: Москва=${s.samara || 0}, Внуково=${s.vnukovo || 0}, Новосибирск=${s.novosibirsk || 0}`);
  });
}
