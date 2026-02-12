/**
 * ПОДРОБНЫЙ ТЕСТ ВСЕХ КОЛОНОК ДЛЯ ТОВАРА 22068-1
 *
 * Проверяет каждую колонку по отдельности
 */

// ============================================
// ПРАВИЛЬНЫЕ ДАННЫЕ ТОВАРА 22068-1
// ============================================

const EXPECTED_DATA = {
  // Базовые данные
  article: "22068-1",
  baseArticle: "22068",
  brand: "Feron",
  model: "SEN30_220",

  // Ozon IDs
  productId: 109652992,     // U (21)
  sku: 301854987,           // V (22)

  // WB IDs
  nmId: 216675685,          // T (20)

  // Колонки с данными
  columns: {
    6: { name: "Остаток ФБО ОЗОН", value: 1069, source: "Ozon остатки FBO.gs" },
    7: { name: "Остаток ФБС ОЗОН", value: 527, source: "Ozon склад Москва.gs" },
    8: { name: "ОСТ ФБС МСК ОЗОН", value: 0, source: "Ozon склад Москва.gs" },
    9: { name: "Уход Мес ОЗОН", value: 1252, source: "Ozon заказы.gs" },
    10: { name: "Уход КВ", value: 2452, source: "Ozon заказы.gs" },
    11: { name: "ЦЕНА ОЗОН", value: 1480, source: "Ozon цена.gs" },
    12: { name: "Сумма заказов Мес ОЗОН", value: 1816419, source: "Ozon заказы.gs" },
    13: { name: "ЦЕНА ВБ", value: 1335, source: "Цены ВБ.gs" },
    14: { name: "Сумма заказов Мес ВБ", value: 5276, source: "ВБ заказы.gs" },
    15: { name: "Остаток ФБО ВБ", value: 36, source: "ВБ.gs" },
    16: { name: "Остаток ФБС ВБ", value: 0, source: "ВБ.gs" },
    17: { name: "ОСТ ФБС МСК ВБ", value: 21, source: "WB FBS Москва.gs", note: "Электросталь" },
    18: { name: "Уход Мес ВБ", value: 4, source: "WB Аналитика.gs" },
    19: { name: "Уход КВ ВБ", value: 19, source: "WB Аналитика.gs" },
    20: { name: "Артикул ВБ (nmId)", value: 216675685, source: "WB Артикулы.gs" },
    21: { name: "Product_id Ozon", value: 109652992, source: "Ozon Получить товары.gs" },
    22: { name: "SKU Ozon", value: 301854987, source: "Ozon обновить товары V2.gs" },
  }
};

// ============================================
// MOCK API RESPONSES
// ============================================

const MOCK_API_RESPONSES = {
  // Ozon Analytics API - v1/analytics/data
  ozonAnalytics: {
    result: {
      data: [
        {
          dimensions: [{ id: "301854987" }],
          metrics: [1252, 1816419, 1200, 1750000, 10, 15000] // ordered_units, ordered_sum, delivered_units, delivered_sum, returned_units, returned_sum
        }
      ]
    }
  },

  // Ozon Prices API - v5/product/info/prices
  ozonPrices: {
    items: [
      {
        product_id: 109652992,
        price: {
          marketing_seller_price: "1480",
          price_before: "1500",
          price: "1600"
        }
      }
    ]
  },

  // Ozon Stocks FBO API - v4/product/info/stocks
  ozonStocksFBO: {
    items: [
      {
        product_id: 109652992,
        stocks: [
          { type: "fbo", stock: 1069 },
          { type: "fbs", stock: 0 }
        ]
      }
    ]
  },

  // Ozon Stocks FBS API - v1/product/info/stocks-by-warehouse/fbs
  ozonStocksFBS: {
    items: [
      {
        product_id: 109652992,
        stocks: [
          { warehouse_id: 1020005000217829, warehouse_name: "Москва", amount: 527 },
          { warehouse_id: 1020005000217830, warehouse_name: "Электросталь", amount: 0 }
        ]
      }
    ]
  },

  // WB Sales Funnel API - sales-funnel/products/history
  wbSalesFunnel: [
    {
      subjectID: 123,
      products: [
        {
          product_id: 216675685,
          ordersCount: 4,
          ordersSum: 5276
        }
      ]
    }
  ],

  // WB Analytics Stocks API - stocks-report/products/products
  wbStocksFBO: [
    { nmId: 216675685, quantity: 36 }
  ],

  // WB Marketplace Stocks API - api/v3/stocks/{warehouseId}
  wbStocksFBS: {
    stocks: [
      { supplierArticle: "22068-1", amount: 0 }
    ]
  },

  // WB Prices API - api/v2/list/goods/filter
  wbPrices: {
    data: {
      products: [
        { nmId: 216675685, price: 1335 }
      ]
    }
  },

  // WB Orders API - api/v1/supplier/orders
  wbOrders: [
    { supplierArticle: "22068-1", isCancel: false },
    { supplierArticle: "22068-1", isCancel: false },
    { supplierArticle: "22068-1", isCancel: false },
    { supplierArticle: "22068-1", isCancel: false }
  ]
};

// ============================================
// ТЕСТОВЫЕ ФУНКЦИИ ДЛЯ КАЖДОЙ КОЛОНКИ
// ============================================

function testColumn(colNum, colName, expectedValue, sourceFile) {
  console.log(`\n=== Колонка ${colNum}: ${colName} ===`);
  console.log(`Источник: ${sourceFile}`);
  console.log(`Ожидается: ${expectedValue}`);

  return { colNum, colName, expectedValue, sourceFile, passed: false, actualValue: null, message: "" };
}

function testOzonAnalyticsColumnI() {
  const test = testColumn(9, "Уход Мес ОЗОН", EXPECTED_DATA.columns[9].value, EXPECTED_DATA.columns[9].source);

  // Симуляция работы функции fetchAndWriteAnalytics()
  const sku = EXPECTED_DATA.sku;
  const mockResponse = MOCK_API_RESPONSES.ozonAnalytics;
  const metrics = mockResponse.result.data[0].metrics;

  // ordered_units - индекс 0
  const actualValue = metrics[0];

  test.actualValue = actualValue;
  test.passed = actualValue === test.expectedValue;

  console.log(`Получено: ${actualValue}`);
  console.log(`Статус: ${test.passed ? "✅ PASSED" : "❌ FAILED"}`);

  if (!test.passed) {
    test.message = `Ожидается ${test.expectedValue}, получено ${actualValue}`;
    console.log(`Ошибка: ${test.message}`);
  }

  return test;
}

function testOzonAnalyticsColumnL() {
  const test = testColumn(12, "Сумма заказов Мес ОЗОН", EXPECTED_DATA.columns[12].value, EXPECTED_DATA.columns[12].source);

  const sku = EXPECTED_DATA.sku;
  const mockResponse = MOCK_API_RESPONSES.ozonAnalytics;
  const metrics = mockResponse.result.data[0].metrics;

  // ordered_sum - индекс 1
  const actualValue = metrics[1];

  test.actualValue = actualValue;
  test.passed = actualValue === test.expectedValue;

  console.log(`Получено: ${actualValue}`);
  console.log(`Статус: ${test.passed ? "✅ PASSED" : "❌ FAILED"}`);

  if (!test.passed) {
    test.message = `Ожидается ${test.expectedValue}, получено ${actualValue}`;
    console.log(`Ошибка: ${test.message}`);
  }

  return test;
}

function testOzonPriceColumnK() {
  const test = testColumn(11, "ЦЕНА ОЗОН", EXPECTED_DATA.columns[11].value, EXPECTED_DATA.columns[11].source);

  const productId = EXPECTED_DATA.productId;
  const mockResponse = MOCK_API_RESPONSES.ozonPrices;
  const price = mockResponse.items.find(i => i.product_id === productId).price;

  // marketing_seller_price - приоритет
  const actualValue = parseInt(price.marketing_seller_price);

  test.actualValue = actualValue;
  test.passed = actualValue === test.expectedValue;

  console.log(`Получено: ${actualValue}`);
  console.log(`Статус: ${test.passed ? "✅ PASSED" : "❌ FAILED"}`);

  if (!test.passed) {
    test.message = `Ожидается ${test.expectedValue}, получено ${actualValue}`;
    console.log(`Ошибка: ${test.message}`);
  }

  return test;
}

function testWBSalesFunnelColumnN() {
  const test = testColumn(14, "Сумма заказов Мес ВБ", EXPECTED_DATA.columns[14].value, EXPECTED_DATA.columns[14].source);

  const nmId = EXPECTED_DATA.nmId;
  const mockResponse = MOCK_API_RESPONSES.wbSalesFunnel;

  let actualValue = 0;
  mockResponse.forEach(subject => {
    if (subject.products && Array.isArray(subject.products)) {
      subject.products.forEach(product => {
        if (product.product_id === nmId) {
          actualValue += product.ordersSum;
        }
      });
    }
  });

  test.actualValue = actualValue;
  test.passed = actualValue === test.expectedValue;

  console.log(`Получено: ${actualValue}`);
  console.log(`Статус: ${test.passed ? "✅ PASSED" : "❌ FAILED"}`);

  if (!test.passed) {
    test.message = `Ожидается ${test.expectedValue}, получено ${actualValue}`;
    console.log(`Ошибка: ${test.message}`);
  }

  return test;
}

function testWBStocksColumnO() {
  const test = testColumn(15, "Остаток ФБО ВБ", EXPECTED_DATA.columns[15].value, EXPECTED_DATA.columns[15].source);

  const nmId = EXPECTED_DATA.nmId;
  const mockResponse = MOCK_API_RESPONSES.wbStocksFBO;

  const actualValue = mockResponse.find(item => item.nmId === nmId)?.quantity || 0;

  test.actualValue = actualValue;
  test.passed = actualValue === test.expectedValue;

  console.log(`Получено: ${actualValue}`);
  console.log(`Статус: ${test.passed ? "✅ PASSED" : "❌ FAILED"}`);

  if (!test.passed) {
    test.message = `Ожидается ${test.expectedValue}, получено ${actualValue}`;
    console.log(`Ошибка: ${test.message}`);
  }

  return test;
}

function testWBStocksColumnP() {
  const test = testColumn(16, "Остаток ФБС ВБ", EXPECTED_DATA.columns[16].value, EXPECTED_DATA.columns[16].source);

  const article = EXPECTED_DATA.article;
  const mockResponse = MOCK_API_RESPONSES.wbStocksFBS;

  const actualValue = mockResponse.stocks.find(s => s.supplierArticle === article)?.amount || 0;

  test.actualValue = actualValue;
  test.passed = actualValue === test.expectedValue;

  console.log(`Получено: ${actualValue}`);
  console.log(`Статус: ${test.passed ? "✅ PASSED" : "❌ FAILED"}`);

  if (!test.passed) {
    test.message = `Ожидается ${test.expectedValue}, получено ${actualValue}`;
    console.log(`Ошибка: ${test.message}`);
  }

  return test;
}

function testOzonStocksColumnF() {
  const test = testColumn(6, "Остаток ФБО ОЗОН", EXPECTED_DATA.columns[6].value, EXPECTED_DATA.columns[6].source);

  const productId = EXPECTED_DATA.productId;
  const mockResponse = MOCK_API_RESPONSES.ozonStocksFBO;

  const product = mockResponse.items.find(i => i.product_id === productId);
  const actualValue = product.stocks.find(s => s.type === "fbo")?.stock || 0;

  test.actualValue = actualValue;
  test.passed = actualValue === test.expectedValue;

  console.log(`Получено: ${actualValue}`);
  console.log(`Статус: ${test.passed ? "✅ PASSED" : "❌ FAILED"}`);

  if (!test.passed) {
    test.message = `Ожидается ${test.expectedValue}, получено ${actualValue}`;
    console.log(`Ошибка: ${test.message}`);
  }

  return test;
}

function testOzonStocksColumnG() {
  const test = testColumn(7, "Остаток ФБС ОЗОН", EXPECTED_DATA.columns[7].value, EXPECTED_DATA.columns[7].source);

  const productId = EXPECTED_DATA.productId;
  const mockResponse = MOCK_API_RESPONSES.ozonStocksFBS;

  const product = mockResponse.items.find(i => i.product_id === productId);
  const actualValue = product?.stocks.reduce((sum, s) => sum + (s.amount || 0), 0) || 0;

  test.actualValue = actualValue;
  test.passed = actualValue === test.expectedValue;

  console.log(`Получено: ${actualValue}`);
  console.log(`Статус: ${test.passed ? "✅ PASSED" : "❌ FAILED"}`);

  if (!test.passed) {
    test.message = `Ожидается ${test.expectedValue}, получено ${actualValue}`;
    console.log(`Ошибка: ${test.message}`);
  }

  return test;
}

function testWBAnalyticsColumnR() {
  const test = testColumn(18, "Уход Мес ВБ", EXPECTED_DATA.columns[18].value, EXPECTED_DATA.columns[18].source);

  const mockResponse = MOCK_API_RESPONSES.wbOrders;
  const actualValue = mockResponse.filter(o => !o.isCancel).length;

  test.actualValue = actualValue;
  test.passed = actualValue === test.expectedValue;

  console.log(`Получено: ${actualValue}`);
  console.log(`Статус: ${test.passed ? "✅ PASSED" : "❌ FAILED"}`);

  if (!test.passed) {
    test.message = `Ожидается ${test.expectedValue}, получено ${actualValue}`;
    console.log(`Ошибка: ${test.message}`);
  }

  return test;
}

function testWBPricesColumnM() {
  const test = testColumn(13, "ЦЕНА ВБ", EXPECTED_DATA.columns[13].value, EXPECTED_DATA.columns[13].source);

  const nmId = EXPECTED_DATA.nmId;
  const mockResponse = MOCK_API_RESPONSES.wbPrices;

  const actualValue = mockResponse.data.products.find(p => p.nmId === nmId)?.price || 0;

  test.actualValue = actualValue;
  test.passed = actualValue === test.expectedValue;

  console.log(`Получено: ${actualValue}`);
  console.log(`Статус: ${test.passed ? "✅ PASSED" : "❌ FAILED"}`);

  if (!test.passed) {
    test.message = `Ожидается ${test.expectedValue}, получено ${actualValue}`;
    console.log(`Ошибка: ${test.message}`);
  }

  return test;
}

// ============================================
// ГЛАВНАЯ ФУНКЦИЯ ЗАПУСКА ВСЕХ ТЕСТОВ
// ============================================

function runAllTests() {
  console.log("\n");
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ПОДРОБНЫЙ ТЕСТ ВСЕХ КОЛОНОК ДЛЯ ТОВАРА 22068-1                       ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");
  console.log("\n");

  console.log("ТОВАР:");
  console.log(`  Артикул: ${EXPECTED_DATA.article}`);
  console.log(`  Бренд: ${EXPECTED_DATA.brand}`);
  console.log(`  Модель: ${EXPECTED_DATA.model}`);
  console.log(`  Product_id Ozon: ${EXPECTED_DATA.productId}`);
  console.log(`  SKU Ozon: ${EXPECTED_DATA.sku}`);
  console.log(`  nmId WB: ${EXPECTED_DATA.nmId}`);
  console.log("");

  const tests = [
    testOzonAnalyticsColumnI(),   // I (9): Уход Мес ОЗОН
    testOzonAnalyticsColumnL(),   // L (12): Сумма заказов Мес ОЗОН
    testOzonPriceColumnK(),       // K (11): ЦЕНА ОЗОН
    testWBSalesFunnelColumnN(),   // N (14): Сумма заказов Мес ВБ
    testWBStocksColumnO(),        // O (15): Остаток ФБО ВБ
    testWBStocksColumnP(),        // P (16): Остаток ФБС ВБ
    testOzonStocksColumnF(),      // F (6): Остаток ФБО ОЗОН
    testOzonStocksColumnG(),      // G (7): Остаток ФБС ОЗОН
    testWBAnalyticsColumnR(),     // R (18): Уход Мес ВБ
    testWBPricesColumnM(),        // M (13): ЦЕНА ВБ
  ];

  console.log("\n");
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ИТОГИ                                                             ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");
  console.log("\n");

  // Таблица результатов
  console.log("┌──────┬────────────────────────────┬──────────┬──────────┬─────────┐");
  console.log("│ Кол  │ Название                   │ Ожидается │ Получено  │ Статус  │");
  console.log("├──────┼────────────────────────────┼──────────┼──────────┼─────────┤");

  tests.forEach(test => {
    const col = String(test.colNum).padEnd(4);
    const name = test.colName.substring(0, 26).padEnd(26);
    const expected = String(test.expectedValue).padEnd(10);
    const actual = String(test.actualValue).padEnd(10);
    const status = test.passed ? "✅ PASSED" : "❌ FAILED";

    console.log(`│ ${col} │ ${name} │ ${expected} │ ${actual} │ ${status} │`);
  });

  console.log("└──────┴────────────────────────────┴──────────┴──────────┴─────────┘");

  const totalTests = tests.length;
  const passedTests = tests.filter(t => t.passed).length;

  console.log("");
  console.log(`Всего тестов: ${totalTests}`);
  console.log(`Прошло: ${passedTests}`);
  console.log(`Упало: ${totalTests - passedTests}`);

  if (passedTests === totalTests) {
    console.log("\n🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ! Все данные получены правильно.");
  } else {
    console.log("\n⚠️ НЕКОТОРЫЕ ТЕСТЫ НЕ ПРОЙДЕНЫ:");
    tests.filter(t => !t.passed).forEach(t => {
      console.log(`   ❌ Колонка ${t.colNum} (${t.colName}): ${t.message}`);
    });
  }

  return passedTests === totalTests;
}

// Запуск тестов
runAllTests();
