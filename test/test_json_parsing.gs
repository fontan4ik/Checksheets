/**
 * ТЕСТОВЫЕ ФУНКЦИИ ДЛЯ ПРОВЕРКИ ПАРСИНГА JSON
 *
 * Используют локальные JSON файлы для тестирования
 * без реальных API запросов
 */

/**
 * testParseOzonAttributes() - Тест парсинга v4/product/info/attributes
 */
function testParseOzonAttributes() {
  Logger.log("========================================");
  Logger.log("🧪 ТЕСТ ПАРСИНГА OZON ATTRIBUTES");
  Logger.log("========================================");

  // Загружаем JSON из файла
  const json = loadJSONFromFile("test/ozon_api_v4_attributes_response.json");
  const items = json.result;

  Logger.log(`\n📦 Получено товаров: ${items.length}`);

  items.forEach((item, index) => {
    Logger.log(`\n--- Товар ${index + 1} ---`);
    Logger.log(`offer_id: ${item.offer_id}`);
    Logger.log(`product_id: ${item.product_id}`);
    Logger.log(`sku: ${item.sku}`);

    // Тестируем extractBrand
    const brand = extractAttribute(item, 85);
    Logger.log(`Бренд (id=85): ${brand}`);

    // Тестируем extractModelAttribute
    const model = extractModelAttribute(item);
    Logger.log(`Модель (id=9048): ${model}`);

    // Проверка primary_image
    Logger.log(`Картинка: ${item.primary_image ? "Есть" : "Нет"}`);
  });

  Logger.log("\n========================================");
  Logger.log("✅ ТЕСТ ЗАВЕРШЁН");
  Logger.log("========================================");
}

/**
 * testParseOzonStocks() - Тест парсинга v4/product/info/stocks
 */
function testParseOzonStocks() {
  Logger.log("========================================");
  Logger.log("🧪 ТЕСТ ПАРСИНГА OZON STOCKS");
  Logger.log("========================================");

  const json = loadJSONFromFile("test/ozon_api_v4_stocks_response.json");
  const items = json.items;

  Logger.log(`\n📦 Получено товаров: ${items.length}`);

  items.forEach((item, index) => {
    Logger.log(`\n--- Товар ${index + 1} ---`);
    Logger.log(`product_id: ${item.product_id}`);

    // Парсим FBO остаток
    const fbo = item.stocks.find(s => s.type === "fbo");
    Logger.log(`FBO остаток: ${fbo ? fbo.present : 0}`);

    // Парсим FBS остаток
    const fbs = item.stocks.find(s => s.type === "fbs");
    Logger.log(`FBS остаток: ${fbs ? fbs.present : 0}`);

    // Парсим остаток по складу (например, Москва)
    const warehouse = item.stocks.find(s => s.warehouse_name === "Склад Москва");
    Logger.log(`Склад Москва: ${warehouse ? warehouse.present : 0}`);
  });

  Logger.log("\n========================================");
  Logger.log("✅ ТЕСТ ЗАВЕРШЁН");
  Logger.log("========================================");
}

/**
 * testParseOzonPrices() - Тест парсинга v5/product/info/prices
 */
function testParseOzonPrices() {
  Logger.log("========================================");
  Logger.log("🧪 ТЕСТ ПАРСИНГА OZON PRICES");
  Logger.log("========================================");

  const json = loadJSONFromFile("test/ozon_api_v5_prices_response.json");
  const items = json.items;

  Logger.log(`\n📦 Получено товаров: ${items.length}`);

  items.forEach((item, index) => {
    Logger.log(`\n--- Товар ${index + 1} ---`);
    Logger.log(`product_id: ${item.product_id}`);
    Logger.log(`ЦЕНА: ${item.price.price}`);
    Logger.log(`Старая цена: ${item.price.old_price || "Нет"}`);
    Logger.log(`Premium цена: ${item.price.premium_price || "Нет"}`);
  });

  Logger.log("\n========================================");
  Logger.log("✅ ТЕСТ ЗАВЕРШЁН");
  Logger.log("========================================");
}

/**
 * testParseWBStocks() - Тест парсинга WB stocks
 */
function testParseWBStocks() {
  Logger.log("========================================");
  Logger.log("🧪 ТЕСТ ПАРСИНГА WB STOCKS");
  Logger.log("========================================");

  const data = loadJSONFromFile("test/wb_api_stocks_response.json");

  Logger.log(`\n📦 Получено товаров: ${data.length}`);

  data.forEach((item, index) => {
    Logger.log(`\n--- Товар ${index + 1} ---`);
    Logger.log(`supplierArticle: ${item.supplierArticle}`);
    Logger.log(`quantity (остаток): ${item.quantity}`);
    Logger.log(`nmId: ${item.nmId}`);
    Logger.log(`barcode: ${item.barcode}`);
    Logger.log(`on site: ${item.is_on_site_stocks ? "Да" : "Нет"}`);
  });

  Logger.log("\n========================================");
  Logger.log("✅ ТЕСТ ЗАВЕРШЁН");
  Logger.log("========================================");
}

/**
 * testParseWBOrders() - Тест парсинга WB orders
 */
function testParseWBOrders() {
  Logger.log("========================================");
  Logger.log("🧪 ТЕСТ ПАРСИНГА WB ORDERS");
  Logger.log("========================================");

  const data = loadJSONFromFile("test/wb_api_orders_response.json");

  // Фильтруем отменённые
  const validOrders = data.filter(o => !o.isCancel);

  Logger.log(`\n📦 Всех заказов: ${data.length}`);
  Logger.log(`📦 Валидных заказов (не отменены): ${validOrders.length}`);

  // Агрегируем по артикулам
  const stats = {};
  validOrders.forEach(order => {
    const art = order.supplierArticle;
    if (!stats[art]) {
      stats[art] = { count: 0, sum: 0 };
    }
    stats[art].count++;
    stats[art].sum += order.priceWithDisc;
  });

  Logger.log("\n📊 Статистика по артикулам:");
  Object.entries(stats).forEach(([art, stat]) => {
    Logger.log(`  ${art}:`);
    Logger.log(`    Заказов: ${stat.count}`);
    Logger.log(`    Сумма: ${stat.sum}`);
  });

  Logger.log("\n========================================");
  Logger.log("✅ ТЕСТ ЗАВЕРШЁН");
  Logger.log("========================================");
}

/**
 * loadJSONFromFile() - Загружает JSON из файла
 *
 * ВАЖНО: В Apps Script это нужно адаптировать!
 * Либо загружать из Drive, либо встраивать JSON в код.
 */
function loadJSONFromFile(filePath) {
  // В реальном Apps Script нужно использовать DriveApp
  // Для тестирования можно встроить JSON напрямую

  if (filePath === "test/ozon_api_v4_attributes_response.json") {
    return OZON_ATTRIBUTES_MOCK;
  } else if (filePath === "test/ozon_api_v4_stocks_response.json") {
    return OZON_STOCKS_MOCK;
  } else if (filePath === "test/ozon_api_v5_prices_response.json") {
    return OZON_PRICES_MOCK;
  } else if (filePath === "test/wb_api_stocks_response.json") {
    return WB_STOCKS_MOCK;
  } else if (filePath === "test/wb_api_orders_response.json") {
    return WB_ORDERS_MOCK;
  }

  return {};
}

// ============================================
// MOCK ДАННЫЕ (встроенные в код для тестирования)
// ============================================

const OZON_ATTRIBUTES_MOCK = {
  "result": [
    {
      "offer_id": "52065-1",
      "product_id": 123456789,
      "sku": 12345,
      "name": "Пресс гидравлический ручной КВТ ПГР-70",
      "primary_image": "https://cdn-image.ozon.ru/...",
      "description_category_id": 17035473,
      "attributes": [
        {
          "id": 85,
          "values": [{"value": "КВТ"}]
        },
        {
          "id": 9048,
          "values": [{"value": "52065"}]
        }
      ]
    },
    {
      "offer_id": "TR089-1",
      "product_id": 987654321,
      "sku": 54321,
      "name": "Светильник трековый Gauss",
      "primary_image": "https://cdn-image.ozon.ru/...",
      "description_category_id": 17035473,
      "attributes": [
        {
          "id": 85,
          "values": [{"value": "Gauss"}]
        },
        {
          "id": 9048,
          "values": [{"value": "019ab5dc91b07999b68acf91328614ab"}]
        }
      ]
    }
  ]
};

const OZON_STOCKS_MOCK = {
  "items": [
    {
      "product_id": 123456789,
      "stocks": [
        {"type": "fbo", "present": 15, "reserved": 2},
        {"type": "fbs", "present": 8, "reserved": 1},
        {"type": "fbs", "present": 5, "warehouse_name": "Склад Москва"}
      ]
    },
    {
      "product_id": 987654321,
      "stocks": [
        {"type": "fbo", "present": 0, "reserved": 0},
        {"type": "fbs", "present": 25, "reserved": 3}
      ]
    }
  ]
};

const OZON_PRICES_MOCK = {
  "items": [
    {
      "product_id": 123456789,
      "price": {"price": "159900", "old_price": "199900"}
    },
    {
      "product_id": 987654321,
      "price": {"price": "89000", "old_price": ""}
    }
  ]
};

const WB_STOCKS_MOCK = [
  {
    "supplierArticle": "52065-1",
    "quantity": 25,
    "nmId": 12345678,
    "barcode": "4601234567890"
  },
  {
    "supplierArticle": "TR089-1",
    "quantity": 12,
    "nmId": 87654321,
    "barcode": "4600987654321"
  }
];

const WB_ORDERS_MOCK = [
  {
    "supplierArticle": "52065-1",
    "finishedPrice": 15990,
    "priceWithDisc": 13990,
    "isCancel": false
  },
  {
    "supplierArticle": "TR089-1",
    "finishedPrice": 8900,
    "priceWithDisc": 7500,
    "isCancel": false
  },
  {
    "supplierArticle": "52065-1",
    "finishedPrice": 15990,
    "priceWithDisc": 15990,
    "isCancel": true
  }
];

/**
 * extractAttribute() - Копия функции из Ozon обновить товары V2.gs
 */
function extractAttribute(item, attributeId) {
  if (!item.attributes || !Array.isArray(item.attributes)) {
    return "";
  }

  const attr = item.attributes.find(a => a.id === attributeId);

  if (!attr || !attr.values || attr.values.length === 0) {
    return "";
  }

  const value = attr.values[0];
  return typeof value === "string" ? value : (value.value || "");
}

/**
 * extractModelAttribute() - Копия функции из Ozon обновить товары V2.gs
 */
function extractModelAttribute(item) {
  const modelIds = [9048, 22390];

  for (const id of modelIds) {
    const value = extractAttribute(item, id);
    if (value) {
      return value;
    }
  }

  return "";
}
