// Тестовый файл для локального тестирования Feron API.gs
// Эмуляция среды Google Apps Script

// Эмуляция объектов Google Apps Script
const Logger = {
  log: console.log
};

const Utilities = {
  sleep: (milliseconds) => {
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, milliseconds);
  }
};

// Глобальные функции, которые должны быть определены
function feronAPIUrl() {
  // Здесь должен быть ваш URL API Feron
  return process.env.FERON_API_URL || 'https://clientapi.shop.feron.ru';
}

function feronAPIKey() {
  // Здесь должен быть ваш API ключ Feron
  return process.env.FERON_API_KEY || 'your_api_key_here';
}

// Эмуляция HTTP-запросов
function retryFetch(url, options) {
  // Имитация работы retryFetch
  return fetch(url, options);
}

// Эмуляция Google Sheets
function mainSheet() {
  // Создаем mock объект для листа
  return new MockSheet();
}

class MockSheet {
  constructor() {
    // Тестовые данные - артикулы в колонке A
    this.data = [
      ['', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', ''],
      ['48546', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', ''], // строка 2
      ['38269', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', ''], // строка 3
      ['12345', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '']  // строка 4
    ];
  }

  getLastRow() {
    return this.data.length;
  }

  getRange(startRow, startCol, numRows, numCols = 1) {
    return new MockRange(this, startRow, startCol, numRows, numCols);
  }
}

class MockRange {
  constructor(sheet, startRow, startCol, numRows, numCols) {
    this.sheet = sheet;
    this.startRow = startRow - 1; // преобразование к 0-индексации
    this.startCol = startCol - 1; // преобразование к 0-индексации
    this.numRows = numRows;
    this.numCols = numCols;
  }

  getValues() {
    const values = [];
    for (let i = 0; i < this.numRows; i++) {
      const row = [];
      for (let j = 0; j < this.numCols; j++) {
        row.push(this.sheet.data[this.startRow + i][this.startCol + j]);
      }
      values.push(row);
    }
    return values;
  }

  setValues(values) {
    for (let i = 0; i < this.numRows; i++) {
      for (let j = 0; j < this.numCols; j++) {
        if (i < values.length && j < values[i].length) {
          this.sheet.data[this.startRow + i][this.startCol + j] = values[i][j];
        }
      }
    }
  }
}

// Теперь импортируем основные функции из Feron API.gs
// Так как мы работаем с локальным файлом, будем копировать код

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
    body: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  try {
    // Вместо реального запроса используем mock-ответ
    const response = mockFeronStocksResponse(articles);

    // Проверка на null после retryFetch
    if (!response) {
      Logger.log(`❌ retryFetch вернул null - API не ответил`);
      return null;
    }

    const responseCode = response.status;

    if (responseCode !== 200) {
      const responseText = response.text;
      Logger.log(`❌ Ошибка Feron API (${responseCode}): ${responseText.substring(0, 500)}`);
      return null;
    }

    const data = response.json;

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
    body: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  try {
    // Вместо реального запроса используем mock-ответ
    const response = mockFeronPricesResponse(articles);

    if (!response) {
      Logger.log(`❌ retryFetch вернул null`);
      return null;
    }

    const responseCode = response.status;

    if (responseCode !== 200) {
      const responseText = response.text;
      Logger.log(`❌ Ошибка Feron API (${responseCode}): ${responseText.substring(0, 500)}`);
      return null;
    }

    const responseText = response.text;
    const data = response.json;

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
    body: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  try {
    // Вместо реального запроса используем mock-ответ
    const response = mockFeronProductsResponse(articles);

    if (!response) {
      Logger.log(`❌ retryFetch вернул null`);
      return null;
    }

    const responseCode = response.status;

    if (responseCode !== 200) {
      const responseText = response.text;
      Logger.log(`❌ Ошибка Feron API (${responseCode}): ${responseText.substring(0, 500)}`);
      return null;
    }

    const responseText = response.text;
    const data = response.json;

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
    // Вместо реального запроса используем mock-ответ
    const response = mockFeronSingleProductResponse(code);

    if (!response) {
      return null;
    }

    const responseCode = response.status;

    if (responseCode !== 200) {
      Logger.log(`❌ Товар ${code} не найден (${responseCode})`);
      return null;
    }

    const responseText = response.text;
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

// Mock-функции для эмуляции API-ответов
function mockFeronStocksResponse(articles) {
  // Возвращаем mock-ответ с данными остатков
  const response = [];

  if (articles.length === 0) {
    // Если нет фильтра, возвращаем тестовые данные для нескольких артикулов
    response.push(
      {
        code: "48546",
        stocks: [
          { warehouse: "samara", stock: 10 },
          { warehouse: "vnukovo", stock: 5 },
          { warehouse: "novosibirsk", stock: 8 }
        ]
      },
      {
        code: "38269",
        stocks: [
          { warehouse: "samara", stock: 0 },
          { warehouse: "vnukovo", stock: 15 },
          { warehouse: "novosibirsk", stock: 3 }
        ]
      },
      {
        code: "12345",
        stocks: [
          { warehouse: "samara", stock: 20 },
          { warehouse: "vnukovo", stock: 7 },
          { warehouse: "novosibirsk", stock: 12 }
        ]
      }
    );
  } else {
    // Если есть фильтр, возвращаем только запрошенные артикулы
    articles.forEach(article => {
      if (article === "48546") {
        response.push({
          code: "48546",
          stocks: [
            { warehouse: "samara", stock: 10 },
            { warehouse: "vnukovo", stock: 5 },
            { warehouse: "novosibirsk", stock: 8 }
          ]
        });
      } else if (article === "38269") {
        response.push({
          code: "38269",
          stocks: [
            { warehouse: "samara", stock: 0 },
            { warehouse: "vnukovo", stock: 15 },
            { warehouse: "novosibirsk", stock: 3 }
          ]
        });
      } else {
        response.push({
          code: article,
          stocks: [
            { warehouse: "samara", stock: 1 },
            { warehouse: "vnukovo", stock: 2 },
            { warehouse: "novosibirsk", stock: 3 }
          ]
        });
      }
    });
  }

  return {
    status: 200,
    json: response,
    text: JSON.stringify(response)
  };
}

function mockFeronPricesResponse(articles) {
  // Возвращаем mock-ответ с данными цен
  const response = [];

  articles.forEach(article => {
    response.push({
      code: article,
      prices: [
        { type: "rrc", price: Math.floor(Math.random() * 1000) + 500 },
        { type: "mic", price: Math.floor(Math.random() * 800) + 400 }
      ]
    });
  });

  return {
    status: 200,
    json: response,
    text: JSON.stringify(response)
  };
}

function mockFeronProductsResponse(articles) {
  // Возвращаем mock-ответ с данными товаров
  const response = [];

  articles.forEach(article => {
    response.push({
      code: article,
      brand: "Test Brand",
      model: "Test Model",
      name: `Product ${article}`,
      images: [`https://example.com/image${article}.jpg`]
    });
  });

  return {
    status: 200,
    json: response,
    text: JSON.stringify(response)
  };
}

function mockFeronSingleProductResponse(code) {
  // Возвращаем mock-ответ с данными одного товара
  const response = {
    code: code,
    brand: "Test Brand",
    model: "Test Model",
    name: `Product ${code}`,
    images: [`https://example.com/image${code}.jpg`]
  };

  return {
    status: 200,
    json: response,
    text: JSON.stringify(response)
  };
}

// Функция для запуска тестов
function runTests() {
  console.log("Запуск тестов Feron API...\n");

  console.log("1. Тест подключения к Feron API:");
  testFeronConnection();

  console.log("\n2. Тест остатков для конкретных артикулов:");
  testFeronArticles();

  console.log("\n3. Тест цен:");
  testFeronPrices();

  console.log("\n4. Тест получения данных товаров:");
  testFeronProducts();

  console.log("\n5. Тест обновления остатков:");
  updateFeronStocks();

  console.log("\nТесты завершены!");
}

// Запуск тестов если файл выполняется напрямую
if (require.main === module) {
  runTests();
}

module.exports = {
  updateFeronStocks,
  fetchFeronStocks,
  fetchFeronPrices,
  fetchFeronProducts,
  fetchFeronProduct,
  testFeronArticle,
  testFeronArticles,
  testFeronConnection,
  testFeronPrices,
  testFeronProducts,
  runTests
};