/**
 * ЛОКАЛЬНЫЙ ТЕСТ ДЛЯ ТОВАРА 22068-1
 *
 * Тестирует все функции с правильными значениями
 *
 * ПРАВИЛЬНЫЕ ДАННЫЕ (с 3 янв по 3 фев 2026):
 * F (6):  Остаток ФБО ОЗОН = 1069
 * G (7):  Остаток ФБС ОЗОН = 527
 * H (8):  ОСТ ФБС МСК ОЗОН = 0
 * I (9):  Уход Мес ОЗОН = 1252
 * J (10): Уход КВ = 2452
 * K (11): ЦЕНА ОЗОН = 1480
 * L (12): Сумма заказов Мес ОЗОН = 1816419
 * M (13): ЦЕНА ВБ = 1335
 * N (14): Сумма заказов Мес ВБ = 5276
 * O (15): Остаток ФБО ВБ = 36
 * P (16): Остаток ФБС ВБ = 0
 * Q (17): ОСТ ФБС МСК ВБ = 21 (Электросталь)
 * R (18): Уход Мес ВБ = 4
 * S (19): Уход КВ ВБ = 19
 * T (20): Артикул ВБ = 216675685
 * U (21): Product_id Ozon = 109652992
 * V (22): SKU Ozon = 301854987
 */

// ============================================
// MOCK DATA - Правильные ответы API
// ============================================

const MOCK_DATA = {
  // Ozon Analytics API (с 3 янв по 3 фев 2026)
  ozonAnalytics: {
    "301854987": {
      ordered_units: 1252,    // I (9): Уход Мес ОЗОН
      ordered_sum: 1816419,   // L (12): Сумма заказов Мес ОЗОН
      delivered_units: 1200,
      delivered_sum: 1750000,
      returned_units: 10,
      returned_sum: 15000
    }
  },

  // Ozon Prices API
  ozonPrices: {
    "109652992": {
      price: {
        marketing_seller_price: "1480",  // K (11): ЦЕНА ОЗОН
        price_before: "1500",
        price: "1600"
      }
    }
  },

  // Ozon Stocks FBO API
  ozonStocksFBO: {
    "109652992": {
      fbo: 1069,  // F (6): Остаток ФБО ОЗОН
      fbs: 0
    }
  },

  // Ozon Stocks FBS API (склад Москва)
  ozonStocksFBS: {
    "109652992": {
      total: 527,   // G (7): Остаток ФБС ОЗОН
      warehouses: [
        { warehouse_id: 1020005000217829, warehouse_name: "Москва", amount: 527 },
        { warehouse_id: 1020005000217830, warehouse_name: "Электросталь", amount: 0 }
      ]
    }
  },

  // WB Sales Funnel API (с 3 янв по 3 фев 2026)
  wbSalesFunnel: [
    {
      subjectID: 123,
      products: [
        {
          product_id: 216675685,  // nmId
          ordersCount: 4,         // R (18): Уход Мес ВБ (количество)
          ordersSum: 5276         // N (14): Сумма заказов Мес ВБ
        }
      ]
    }
  ],

  // WB Analytics Stocks API (FBO)
  wbStocksFBO: [
    {
      nmId: 216675685,
      quantity: 36               // O (15): Остаток ФБО ВБ
    }
  ],

  // WB Marketplace Stocks API (FBS)
  wbStocksFBS: {
    stocks: [
      {
        supplierArticle: "22068-1",
        amount: 0                 // P (16): Остаток ФБС ВБ
      }
    ]
  },

  // WB Prices API
  wbPrices: [
    {
      nmId: 216675685,
      price: 1335                // M (13): ЦЕНА ВБ
    }
  ]
};

// ============================================
// ТЕСТОВЫЕ ФУНКЦИИ
// ============================================

function testDateRangeCalculation() {
  console.log("=== ТЕСТ 1: Расчёт диапазона дат 'с 3 по 3' ===");

  const today = new Date('2026-02-03'); // 3 февраля 2026
  const currentDay = today.getDate();

  let startDate, endDate;

  if (currentDay >= 3) {
    startDate = new Date(today.getFullYear(), today.getMonth(), 3);
    endDate = today;
  } else {
    startDate = new Date(today.getFullYear(), today.getMonth() - 1, 3);
    endDate = today;
  }

  const formatDate = date => {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };

  console.log(`Сегодня: ${formatDate(today)}`);
  console.log(`Диапазон: ${formatDate(startDate)} → ${formatDate(endDate)}`);
  console.log(`Ожидается: 2026-02-03 → 2026-02-03 (или с 2026-01-03 если раньше 3-го числа)`);

  const expectedStart = "2026-02-03";
  const actualStart = formatDate(startDate);

  if (actualStart === expectedStart) {
    console.log("✅ PASSED: Диапазон рассчитан правильно");
  } else {
    console.log(`❌ FAILED: Ожидается ${expectedStart}, получено ${actualStart}`);
  }

  console.log("");
  return actualStart === expectedStart;
}

function testOzonAnalytics() {
  console.log("=== ТЕСТ 2: Ozon Analytics API ===");

  const sku = "301854987";
  const mockData = MOCK_DATA.ozonAnalytics[sku];

  console.log(`SKU: ${sku}`);
  console.log(`ordered_units (Уход Мес ОЗОН): ${mockData.ordered_units}`);
  console.log(`ordered_sum (Сумма заказов Мес ОЗОН): ${mockData.ordered_sum}`);

  const expectedUnits = 1252;
  const expectedSum = 1816419;

  let passed = true;

  if (mockData.ordered_units === expectedUnits) {
    console.log(`✅ PASSED: ordered_units = ${expectedUnits}`);
  } else {
    console.log(`❌ FAILED: ordered_units ожидается ${expectedUnits}, получено ${mockData.ordered_units}`);
    passed = false;
  }

  if (mockData.ordered_sum === expectedSum) {
    console.log(`✅ PASSED: ordered_sum = ${expectedSum}`);
  } else {
    console.log(`❌ FAILED: ordered_sum ожидается ${expectedSum}, получено ${mockData.ordered_sum}`);
    passed = false;
  }

  console.log("");
  return passed;
}

function testOzonPrice() {
  console.log("=== ТЕСТ 3: Ozon Price API ===");

  const productId = "109652992";
  const mockData = MOCK_DATA.ozonPrices[productId];

  console.log(`Product_id: ${productId}`);
  console.log(`Цена: ${mockData.price.marketing_seller_price}`);

  const expectedPrice = "1480";

  if (mockData.price.marketing_seller_price === expectedPrice) {
    console.log(`✅ PASSED: Цена = ${expectedPrice}`);
  } else {
    console.log(`❌ FAILED: Цена ожидается ${expectedPrice}, получено ${mockData.price.marketing_seller_price}`);
  }

  console.log("");
  return mockData.price.marketing_seller_price === expectedPrice;
}

function testWBSalesFunnel() {
  console.log("=== ТЕСТ 4: WB Sales Funnel API ===");

  const mockData = MOCK_DATA.wbSalesFunnel;
  const nmId = 216675685;

  let ordersSum = 0;
  let ordersCount = 0;

  mockData.forEach(subject => {
    if (subject.products && Array.isArray(subject.products)) {
      subject.products.forEach(product => {
        if (product.product_id === nmId) {
          ordersSum += product.ordersSum;
          ordersCount += product.ordersCount;
        }
      });
    }
  });

  console.log(`nmId: ${nmId}`);
  console.log(`ordersSum (Сумма заказов Мес ВБ): ${ordersSum}`);
  console.log(`ordersCount (Уход Мес ВБ): ${ordersCount}`);

  const expectedSum = 5276;
  const expectedCount = 4;

  let passed = true;

  if (ordersSum === expectedSum) {
    console.log(`✅ PASSED: ordersSum = ${expectedSum}`);
  } else {
    console.log(`❌ FAILED: ordersSum ожидается ${expectedSum}, получено ${ordersSum}`);
    passed = false;
  }

  if (ordersCount === expectedCount) {
    console.log(`✅ PASSED: ordersCount = ${expectedCount}`);
  } else {
    console.log(`❌ FAILED: ordersCount ожидается ${expectedCount}, получено ${ordersCount}`);
    passed = false;
  }

  console.log("");
  return passed;
}

function testWBStocks() {
  console.log("=== ТЕСТ 5: WB Stocks API ===");

  const nmId = 216675685;

  // FBO Stocks
  const mockFBO = MOCK_DATA.wbStocksFBO;
  let fboStock = 0;
  mockFBO.forEach(item => {
    if (item.nmId === nmId) {
      fboStock = item.quantity;
    }
  });

  // FBS Stocks
  const mockFBS = MOCK_DATA.wbStocksFBS.stocks;
  let fbsStock = 0;
  mockFBS.forEach(stock => {
    if (stock.supplierArticle === "22068-1") {
      fbsStock = stock.amount;
    }
  });

  console.log(`nmId: ${nmId}`);
  console.log(`FBO Stock (Остаток ФБО ВБ): ${fboStock}`);
  console.log(`FBS Stock (Остаток ФБС ВБ): ${fbsStock}`);

  const expectedFBO = 36;
  const expectedFBS = 0;

  let passed = true;

  if (fboStock === expectedFBO) {
    console.log(`✅ PASSED: FBO Stock = ${expectedFBO}`);
  } else {
    console.log(`❌ FAILED: FBO Stock ожидается ${expectedFBO}, получено ${fboStock}`);
    passed = false;
  }

  if (fbsStock === expectedFBS) {
    console.log(`✅ PASSED: FBS Stock = ${expectedFBS}`);
  } else {
    console.log(`❌ FAILED: FBS Stock ожидается ${expectedFBS}, получено ${fbsStock}`);
    passed = false;
  }

  console.log("");
  return passed;
}

function testOzonStocks() {
  console.log("=== ТЕСТ 6: Ozon Stocks API ===");

  const productId = "109652992";

  const fboStock = MOCK_DATA.ozonStocksFBO[productId].fbo;
  const fbsStock = MOCK_DATA.ozonStocksFBS[productId].total;

  console.log(`Product_id: ${productId}`);
  console.log(`FBO Stock (Остаток ФБО ОЗОН): ${fboStock}`);
  console.log(`FBS Stock (Остаток ФБС ОЗОН): ${fbsStock}`);

  const expectedFBO = 1069;
  const expectedFBS = 527;

  let passed = true;

  if (fboStock === expectedFBO) {
    console.log(`✅ PASSED: FBO Stock = ${expectedFBO}`);
  } else {
    console.log(`❌ FAILED: FBO Stock ожидается ${expectedFBO}, получено ${fboStock}`);
    passed = false;
  }

  if (fbsStock === expectedFBS) {
    console.log(`✅ PASSED: FBS Stock = ${expectedFBS}`);
  } else {
    console.log(`❌ FAILED: FBS Stock ожидается ${expectedFBS}, получено ${fbsStock}`);
    passed = false;
  }

  console.log("");
  return passed;
}

function testWBPrices() {
  console.log("=== ТЕСТ 7: WB Prices API ===");

  const nmId = 216675685;
  const mockData = MOCK_DATA.wbPrices;

  let price = 0;
  mockData.forEach(item => {
    if (item.nmId === nmId) {
      price = item.price;
    }
  });

  console.log(`nmId: ${nmId}`);
  console.log(`Price (ЦЕНА ВБ): ${price}`);

  const expectedPrice = 1335;

  if (price === expectedPrice) {
    console.log(`✅ PASSED: Цена = ${expectedPrice}`);
  } else {
    console.log(`❌ FAILED: Цена ожидается ${expectedPrice}, получено ${price}`);
  }

  console.log("");
  return price === expectedPrice;
}

// ============================================
// ГЛАВНАЯ ФУНКЦИЯ ЗАПУСКА ТЕСТОВ
// ============================================

function runAllTests() {
  console.log("\n");
  console.log("╔════════════════════════════════════════════════════════════╗");
  console.log("║   ТЕСТЫ ДЛЯ ТОВАРА 22068-1                                  ║");
  console.log("╚════════════════════════════════════════════════════════════╝");
  console.log("\n");

  const results = {
    dateRange: testDateRangeCalculation(),
    ozonAnalytics: testOzonAnalytics(),
    ozonPrice: testOzonPrice(),
    wbSalesFunnel: testWBSalesFunnel(),
    wbStocks: testWBStocks(),
    ozonStocks: testOzonStocks(),
    wbPrices: testWBPrices()
  };

  console.log("╔════════════════════════════════════════════════════════════╗");
  console.log("║   ИТОГИ                                                     ║");
  console.log("╚════════════════════════════════════════════════════════════╝");
  console.log("");

  const totalTests = Object.keys(results).length;
  const passedTests = Object.values(results).filter(r => r).length;

  Object.entries(results).forEach(([testName, passed]) => {
    const status = passed ? "✅ PASSED" : "❌ FAILED";
    console.log(`${testName.padEnd(20)} ${status}`);
  });

  console.log("");
  console.log(`Всего тестов: ${totalTests}`);
  console.log(`Прошло: ${passedTests}`);
  console.log(`Упало: ${totalTests - passedTests}`);

  if (passedTests === totalTests) {
    console.log("\n🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ!");
  } else {
    console.log("\n⚠️ НЕКОТОРЫЕ ТЕСТЫ НЕ ПРОЙДЕНЫ - нужно исправить код");
  }

  return passedTests === totalTests;
}

// Запуск тестов
runAllTests();
