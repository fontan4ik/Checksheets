// ============================================
// FERON API - Полная интеграция с API Feron
// ============================================
//
// БАЗОВЫЙ URL: https://clientapi.shop.feron.ru
// АУТЕНТИФИКАЦИЯ: API-KEY в заголовке
//
// ДОСТУПНЫЕ ENDPOINTS:
// 1. POST /v1/products/list - Список товаров (с фильтром по артикулам)
// 2. GET /v1/products/{code} - Данные конкретного товара
// 3. POST /v1/stocks/list - Остатки по складам
// 4. GET /v1/stocks/{code} - Остатки конкретного товара
// 5. POST /v1/prices/list - Цены товаров (только получение данных)
// 6. GET /v1/prices/{code} - Цены конкретного товара
// 7. POST /v1/reports/sellout - Отчёты о продажах
//
// ЗАПОЛНЯЕМЫЕ КОЛОНКИ:
// - AI (35): Ферон Самара
// - AJ (36): Ферон Внуково
// - AK (37): Ферон Новосибирск
//
// СКЛАДЫ FERON:
// - samara - Самара
// - vnukovo - Внуково (Москва)
// - novosibirsk - Новосибирск
//
// ============================================

// ============================================
// ОСТАТКИ (STOCKS)
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
    const response = retryFetch(url, options);

    // Проверка на null после retryFetch
    if (!response) {
      Logger.log(`❌ retryFetch вернул null - API не ответил`);
      return null;
    }

    const responseCode = response.getResponseCode();

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
 * Получить цены от Feron API
 *
 * @param {string[]} articles - Массив артикулов для фильтрации
 * @returns {Object} Объект с артикулами и ценами
 */
function fetchFeronPrices(articles) {
  const url = `${feronAPIUrl()}/v1/prices/list`;

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
    const response = retryFetch(url, options);

    if (!response) {
      Logger.log(`❌ retryFetch вернул null`);
      return null;
    }

    const responseCode = response.getResponseCode();

    if (responseCode !== 200) {
      const responseText = response.getContentText();
      Logger.log(`❌ Ошибка Feron API (${responseCode}): ${responseText.substring(0, 500)}`);
      return null;
    }

    const responseText = response.getContentText();
    const data = JSON.parse(responseText);

    if (!Array.isArray(data)) {
      Logger.log(`❌ Неверный формат ответа`);
      return null;
    }

    // Создаём мапу: артикул -> { rrc, mic }
    const priceMap = {};

    data.forEach(item => {
      const code = item.code;
      if (!code || !item.prices) return;

      priceMap[code] = {
        rrc: null,
        mic: null
      };

      item.prices.forEach(price => {
        const type = price.type;
        const value = price.price || 0;

        switch (type) {
          case "rrc":
            priceMap[code].rrc = value;
            break;
          case "mic":
            priceMap[code].mic = value;
            break;
        }
      });
    });

    Logger.log(`✅ Получено цен: ${Object.keys(priceMap).length} товаров`);
    return priceMap;

  } catch (e) {
    Logger.log(`❌ Ошибка при запросе цен: ${e.message}`);
    return null;
  }
}

// ============================================
// ТОВАРЫ (PRODUCTS)
// ============================================

/**
 * Получить данные товаров от Feron API
 *
 * @param {string[]} articles - Массив артикулов для фильтрации (или null для всех)
 * @returns {Array} Массив объектов товаров
 */
function fetchFeronProducts(articles) {
  const url = `${feronAPIUrl()}/v1/products/list`;

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
    const response = retryFetch(url, options);

    if (!response) {
      Logger.log(`❌ retryFetch вернул null`);
      return null;
    }

    const responseCode = response.getResponseCode();

    if (responseCode !== 200) {
      const responseText = response.getContentText();
      Logger.log(`❌ Ошибка Feron API (${responseCode}): ${responseText.substring(0, 500)}`);
      return null;
    }

    const responseText = response.getContentText();
    const data = JSON.parse(responseText);

    if (!Array.isArray(data)) {
      Logger.log(`❌ Неверный формат ответа`);
      return null;
    }

    Logger.log(`✅ Получено товаров: ${data.length}`);
    return data;

  } catch (e) {
    Logger.log(`❌ Ошибка при запросе товаров: ${e.message}`);
    return null;
  }
}

/**
 * Получить данные одного товара по артикулу
 *
 * @param {string} code - Артикул товара
 * @returns {Object|null} Объект товара или null
 */
function fetchFeronProduct(code) {
  const url = `${feronAPIUrl()}/v1/products/${encodeURIComponent(code)}`;

  const options = {
    method: "get",
    headers: {
      "API-KEY": feronAPIKey()
    },
    muteHttpExceptions: true
  };

  try {
    const response = retryFetch(url, options);

    if (!response) {
      return null;
    }

    const responseCode = response.getResponseCode();

    if (responseCode !== 200) {
      Logger.log(`❌ Товар ${code} не найден (${responseCode})`);
      return null;
    }

    const responseText = response.getContentText();
    return JSON.parse(responseText);

  } catch (e) {
    Logger.log(`❌ Ошибка при запросе товара ${code}: ${e.message}`);
    return null;
  }
}

// ============================================
// ТЕСТОВЫЕ ФУНКЦИИ
// ============================================

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
    Logger.log(`Артикул ${code}: Самара=${s.samara || 0}, Внуково=${s.vnukovo || 0}, Новосибирск=${s.novosibirsk || 0}`);
  });
}

/**
 * Тест цен: проверить цены для артикулов
 */
function testFeronPrices() {
  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ТЕСТ ЦЕН FERON API                                                   ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");
  Logger.log("");

  const prices = fetchFeronPrices(["48546", "38269"]);

  if (!prices) {
    Logger.log("❌ Не удалось получить цены");
    return;
  }

  Object.keys(prices).forEach(code => {
    const p = prices[code];
    Logger.log(`Артикул ${code}:`);
    Logger.log(`  RRC: ${p.rrc || "нет"}`);
    Logger.log(`  MIC: ${p.mic || "нет"}`);
  });
}

/**
 * Тест товаров: получить данные товаров
 */
function testFeronProducts() {
  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ТЕСТ ТОВАРОВ FERON API                                               ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");
  Logger.log("");

  const products = fetchFeronProducts(["48546", "38269"]);

  if (!products) {
    Logger.log("❌ Не удалось получить товары");
    return;
  }

  products.forEach(p => {
    Logger.log(`Артикул: ${p.code}`);
    Logger.log(`  Бренд: ${p.brand}`);
    Logger.log(`  Модель: ${p.model}`);
    Logger.log(`  Название: ${p.name}`);
    if (p.images && p.images.length > 0) {
      Logger.log(`  Изображений: ${p.images.length}`);
      Logger.log(`  Первое изображение: ${p.images[0]}`);
    }
    Logger.log("");
  });
}
