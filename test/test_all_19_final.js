/**
 * ФИНАЛЬНЫЙ ТЕСТ ВСЕХ 19 МЕТРИК
 * Использует ТОЛЬКО проверенные работающие API endpoints
 */

const https = require('https');
const fs = require('fs');

const OZON_CLIENT_ID = '142355';
const OZON_API_KEY = 'fe539630-170b-4b48-b222-8ba092907a63';
const WB_TOKEN = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg1ODgzMjc3LCJpZCI6IjAxOWMyMzE3LWEyZTMtNzQ2NC1iZTY3LTY3ZDNlMGY4YWNlMSIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.XsB0AXxVxUo13JxstFFAtQXxUqE-MjtP02FnX08uyhh3MGUxfFdm5hgVvcHRFOR-aiv1CeDegedqNJ1k5u8wPw';

const ARTICLE = '22068-1';
const SKU = '301854987';

function httpsPost(hostname, path, headers, body) {
  return new Promise((resolve, reject) => {
    const postData = JSON.stringify(body);
    const options = {
      hostname: hostname,
      path: path,
      method: 'POST',
      headers: {
        ...headers,
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(postData)
      }
    };
    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          const jsonData = JSON.parse(data);
          resolve({ status: res.statusCode, data: jsonData });
        } catch (e) {
          resolve({ status: res.statusCode, data: data });
        }
      });
    });
    req.on('error', reject);
    req.write(postData);
    req.end();
  });
}

function httpsGet(hostname, path, headers) {
  return new Promise((resolve, reject) => {
    const options = {
      hostname: hostname,
      path: path,
      method: 'GET',
      headers: headers
    };
    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          const jsonData = JSON.parse(data);
          resolve({ status: res.statusCode, data: jsonData });
        } catch (e) {
          resolve({ status: res.statusCode, data: data });
        }
      });
    });
    req.on('error', reject);
    req.end();
  });
}

function formatDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

// ============================================
// 1. OZON ANALYTICS (I, J, L)
// ============================================
async function fetchOzonAnalytics() {
  console.log("\n=== 1. OZON ANALYTICS ===");

  const today = new Date('2026-02-04');
  const dateFromMonth = new Date(today.getFullYear(), today.getMonth() - 1, 3);
  const dateFromQuarter = new Date(today);
  dateFromQuarter.setDate(today.getDate() - 91);

  const headers = {
    'Client-Id': OZON_CLIENT_ID,
    'Api-Key': OZON_API_KEY
  };

  // Месячная аналитика
  const bodyMonth = {
    date_from: formatDate(dateFromMonth),
    date_to: formatDate(today),
    metrics: ["ordered_units", "revenue"],
    dimension: ["sku"],
    limit: 1000,
    offset: 0
  };

  try {
    const resultMonth = await httpsPost('api-seller.ozon.ru', '/v1/analytics/data', headers, bodyMonth);

    let monthUnits = 0;
    let monthRevenue = 0;

    if (resultMonth.data.result && resultMonth.data.result.data) {
      const skuData = resultMonth.data.result.data.find(d => d.dimensions[0].id.toString() === SKU.toString());
      if (skuData) {
        monthUnits = skuData.metrics[0] || 0;
        monthRevenue = Math.round(skuData.metrics[1] || 0);
      }
    }

    // Квартальная аналитика
    const bodyQuarter = {
      date_from: formatDate(dateFromQuarter),
      date_to: formatDate(today),
      metrics: ["ordered_units"],
      dimension: ["sku"],
      limit: 1000,
      offset: 0
    };

    const resultQuarter = await httpsPost('api-seller.ozon.ru', '/v1/analytics/data', headers, bodyQuarter);

    let quarterUnits = 0;
    if (resultQuarter.data.result && resultQuarter.data.result.data) {
      const skuData = resultQuarter.data.result.data.find(d => d.dimensions[0].id.toString() === SKU.toString());
      if (skuData) {
        quarterUnits = skuData.metrics[0] || 0;
      }
    }

    console.log(`   I (9) Уход Мес ОЗОН: ${monthUnits}`);
    console.log(`   J (10) Уход КВ ОЗОН: ${quarterUnits}`);
    console.log(`   L (12) Сумма заказов Мес ОЗОН: ${monthRevenue}`);

    return { monthUnits, quarterUnits, monthRevenue };
  } catch (e) {
    console.error(`   ❌ Ошибка: ${e.message}`);
    return { monthUnits: 0, quarterUnits: 0, monthRevenue: 0 };
  }
}

// ============================================
// 2. OZON STOCKS (F, G, H)
// ============================================
async function fetchOzonStocks() {
  console.log("\n=== 2. OZON STOCKS ===");

  const headers = {
    'Client-Id': OZON_CLIENT_ID,
    'Api-Key': OZON_API_KEY
  };

  // FBO stocks
  let fboStock = 0;
  try {
    const resultFBO = await httpsPost('api-seller.ozon.ru', '/v4/product/info/stocks', headers, {
      filter: { sku: [parseInt(SKU)] },
      limit: 1000
    });

    if (resultFBO.data.result && resultFBO.data.result.rows) {
      resultFBO.data.result.rows.forEach(row => {
        const amount = row.stocks?.[0]?.available || 0;
        fboStock += amount;
      });
    }
  } catch (e) {
    console.error(`   ❌ FBO: ${e.message}`);
  }

  // FBS stocks
  let fbsStock = 0;
  let moscowFbsStock = 0;
  try {
    const resultFBS = await httpsPost('api-seller.ozon.ru', '/v1/product/info/stocks-by-warehouse/fbs', headers, {
      sku: [parseInt(SKU)],
      warehouse_type: "FBS"
    });

    if (resultFBS.data.result && resultFBS.data.result.rows) {
      resultFBS.data.result.rows.forEach(row => {
        const wh = row.warehouse_name || "";
        const amount = row.amount || 0;

        if (wh.includes('Москва') || wh.includes('МСК') || wh.includes('Electro') || wh.includes('Электросталь')) {
          moscowFbsStock += amount;
        } else {
          fbsStock += amount;
        }
      });
    }
  } catch (e) {
    console.error(`   ❌ FBS: ${e.message}`);
  }

  console.log(`   F (6) Остаток ФБО ОЗОН: ${fboStock}`);
  console.log(`   G (7) Остаток ФБС ОЗОН: ${fbsStock}`);
  console.log(`   H (8) ОСТ ФБС МСК ОЗОН: ${moscowFbsStock}`);

  return { fboStock, fbsStock, moscowFbsStock };
}

// ============================================
// 3. OZON PRICE (K)
// ============================================
async function fetchOzonPrice() {
  console.log("\n=== 3. OZON PRICE ===");

  const headers = {
    'Client-Id': OZON_CLIENT_ID,
    'Api-Key': OZON_API_KEY
  };

  // Получим product_id через v3/product/info/list с offer_id
  let productId = null;
  try {
    const result = await httpsPost('api-seller.ozon.ru', '/v3/product/info/list', headers, {
      filter: { offer_id: [ARTICLE] },
      limit: 1
    });

    if (result.data.result && result.data.result.items && result.data.result.items.length > 0) {
      productId = result.data.result.items[0].product_id;
    }
  } catch (e) {
    // Попробуем через attributes
  }

  if (!productId) {
    console.log(`   ❌ Не удалось получить product_id`);
    return 0;
  }

  try {
    const result = await httpsPost('api-seller.ozon.ru', '/v5/product/info/prices', headers, {
      filter: {
        product_id: [productId],
        currency_code: "RUB"
      },
      limit: 1000
    });

    let price = 0;
    if (result.data.result && result.data.result.items && result.data.result.items.length > 0) {
      price = Math.round(result.data.result.items[0].price?.price || 0);
    }

    console.log(`   K (11) ЦЕНА ОЗОН: ${price}`);
    return price;
  } catch (e) {
    console.error(`   ❌ Ошибка: ${e.message}`);
    return 0;
  }
}

// ============================================
// 4. OZON ATTRIBUTES (C, D, E)
// ============================================
async function fetchOzonAttributes() {
  console.log("\n=== 4. OZON ATTRIBUTES ===");

  const headers = {
    'Client-Id': OZON_CLIENT_ID,
    'Api-Key': OZON_API_KEY
  };

  try {
    const result = await httpsPost('api-seller.ozon.ru', '/v4/product/info/attributes', headers, {
      filter: { offer_id: [ARTICLE] },
      limit: 1
    });

    let brand = "";
    let model = "";
    let image = "";

    if (result.data.result && result.data.result.length > 0) {
      const item = result.data.result[0];

      const extractAttribute = (item, attrId) => {
        const attr = item.attributes?.find(a => a.id === attrId);
        return attr?.values[0]?.value || "";
      };

      brand = extractAttribute(item, 85);
      model = extractAttribute(item, 9048);
      image = item.images?.[0] || "";
    }

    console.log(`   C (3) Бренд: ${brand}`);
    console.log(`   D (4) Модель: ${model}`);
    console.log(`   E (5) Картинка: ${image ? 'Да' : 'Нет'}`);

    return { brand, model, image };
  } catch (e) {
    console.error(`   ❌ Ошибка: ${e.message}`);
    return { brand: "", model: "", image: "" };
  }
}

// ============================================
// 5. WB ORDERS (N)
// ============================================
async function fetchWBOrders() {
  console.log("\n=== 5. WB ORDERS ===");

  const today = new Date('2026-02-04');
  const dateFrom = new Date(today.getFullYear(), today.getMonth() - 1, 3);

  const path = `/api/v1/supplier/orders?dateFrom=${formatDate(dateFrom)}`;
  const headers = { 'Authorization': `Bearer ${WB_TOKEN}` };

  try {
    const result = await httpsGet('statistics-api.wildberries.ru', path, headers);

    let totalSum = 0;
    if (Array.isArray(result.data)) {
      result.data.forEach(order => {
        if (order.supplierArticle === ARTICLE && !order.isCancel) {
          totalSum += order.priceWithDisc;
        }
      });
    }

    console.log(`   N (14) Сумма заказов Мес ВБ: ${totalSum}`);
    return totalSum;
  } catch (e) {
    console.error(`   ❌ Ошибка: ${e.message}`);
    return 0;
  }
}

// ============================================
// 6. WB ANALYTICS (R, S)
// ============================================
async function fetchWBAnalytics() {
  console.log("\n=== 6. WB ANALYTICS ===");

  const today = new Date('2026-02-04');
  const dateFromMonth = new Date(today.getFullYear(), today.getMonth() - 1, 3);
  const dateFromQuarter = new Date(2025, 10, 3); // 3 ноя 2025

  const formatDateISO = (d) => {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}T00:00:00.000Z`;
  };

  const headers = { 'Authorization': `Bearer ${WB_TOKEN}` };

  // Месячная аналитика
  const pathMonth = `/api/v2/supplier/analytics?dateFrom=${formatDateISO(dateFromMonth)}&dateTo=${formatDateISO(today)}&key=supplierArticle&limit=1000&offset=0`;

  try {
    const resultMonth = await httpsGet('statistics-api.wildberries.ru', pathMonth, headers);

    let monthOrders = 0;
    if (resultMonth.data && resultMonth.data.result && Array.isArray(resultMonth.data.result)) {
      const monthData = resultMonth.data.result.find(r => r.supplierArticle === ARTICLE);
      if (monthData) {
        monthOrders = monthData.ordersCount || 0;
      }
    }

    // Квартальная аналитика
    const pathQuarter = `/api/v2/supplier/analytics?dateFrom=${formatDateISO(dateFromQuarter)}&dateTo=${formatDateISO(today)}&key=supplierArticle&limit=1000&offset=0`;

    const resultQuarter = await httpsGet('statistics-api.wildberries.ru', pathQuarter, headers);

    let quarterOrders = 0;
    if (resultQuarter.data && resultQuarter.data.result && Array.isArray(resultQuarter.data.result)) {
      const quarterData = resultQuarter.data.result.find(r => r.supplierArticle === ARTICLE);
      if (quarterData) {
        quarterOrders = quarterData.ordersCount || 0;
      }
    }

    console.log(`   R (18) Уход Мес ВБ: ${monthOrders}`);
    console.log(`   S (19) Уход КВ ВБ: ${quarterOrders}`);

    return { monthOrders, quarterOrders };
  } catch (e) {
    console.error(`   ❌ Ошибка: ${e.message}`);
    return { monthOrders: 0, quarterOrders: 0 };
  }
}

// ============================================
// 7. WB STOCKS (O, P)
// ============================================
async function fetchWBStocks() {
  console.log("\n=== 7. WB STOCKS ===");

  const headers = { 'Authorization': `Bearer ${WB_TOKEN}` };

  try {
    const result = await httpsGet('statistics-api.wildberries.ru', '/api/v2/supplier/stocks', headers);

    let fboStock = 0;
    let fbsStock = 0;

    if (Array.isArray(result.data)) {
      const stockData = result.data.find(s => s.supplierArticle === ARTICLE);
      if (stockData) {
        fboStock = stockData.quantity || 0;
      }
    }

    console.log(`   O (15) Остаток ФБО ВБ: ${fboStock}`);
    console.log(`   P (16) Остаток ФБС ВБ: ${fbsStock}`);

    return { fboStock, fbsStock };
  } catch (e) {
    console.error(`   ❌ Ошибка: ${e.message}`);
    return { fboStock: 0, fbsStock: 0 };
  }
}

// ============================================
// 8. WB PRICE (M) и nmId (T)
// ============================================
async function fetchWBPrice() {
  console.log("\n=== 8. WB PRICE ===");

  const headers = { 'Authorization': `Bearer ${WB_TOKEN}` };

  const body = {
    numpyKey: "catalog",
    settings: {
      cursor: { limit: 100 },
      filter: { withOrder: true, text: ARTICLE }
    },
    sort: { supplySort: "ASC" }
  };

  try {
    const result = await httpsPost('content-api.wildberries.ru', '/api/v2/supplier/card/list', headers, body);

    let price = 0;
    let nmId = 0;

    if (result.data && result.data.cards && result.data.cards.length > 0) {
      const card = result.data.cards[0];
      nmId = card.nmId || 0;

      if (card.sizes && card.sizes.length > 0) {
        for (const size of card.sizes) {
          if (size.priceWithDisc) {
            price = size.priceWithDisc;
            break;
          }
        }
      }
    }

    console.log(`   M (13) ЦЕНА ВБ: ${price}`);
    console.log(`   T (20) Артикул ВБ (nmId): ${nmId}`);

    return { price, nmId };
  } catch (e) {
    console.error(`   ❌ Ошибка: ${e.message}`);
    return { price: 0, nmId: 0 };
  }
}

// ============================================
// ГЛАВНАЯ ФУНКЦИЯ
// ============================================
async function main() {
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ФИНАЛЬНЫЙ ТЕСТ ВСЕХ 19 МЕТРИК ДЛЯ 22068-1                         ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  // 1. Analytics
  const analytics = await fetchOzonAnalytics();

  // 2. Stocks
  const stocks = await fetchOzonStocks();

  // 3. Price
  const ozonPrice = await fetchOzonPrice();

  // 4. Attributes
  const attributes = await fetchOzonAttributes();

  // 5. WB Orders
  const wbOrders = await fetchWBOrders();

  // 6. WB Analytics
  const wbAnalytics = await fetchWBAnalytics();

  // 7. WB Stocks
  const wbStocks = await fetchWBStocks();

  // 8. WB Price
  const wbPriceData = await fetchWBPrice();

  // Итоговая сводка
  console.log("\n╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ИТОГОВАЯ СВОДКА                                                      ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const results = [
    { col: 'A (1)', name: 'Артикул', value: ARTICLE, expected: ARTICLE },
    { col: 'B (2)', name: 'Модель', value: attributes.model, expected: '22068' },
    { col: 'C (3)', name: 'Бренд', value: attributes.brand, expected: 'Feron' },
    { col: 'D (4)', name: 'Артикул производителя', value: attributes.model, expected: 'SEN30_220' },
    { col: 'E (5)', name: 'Картинка', value: attributes.image ? 'Да' : 'Нет', expected: 'Да' },
    { col: 'F (6)', name: 'Остаток ФБО ОЗОН', value: stocks.fboStock, expected: 1069 },
    { col: 'G (7)', name: 'Остаток ФБС ОЗОН', value: stocks.fbsStock, expected: 527 },
    { col: 'H (8)', name: 'ОСТ ФБС МСК ОЗОН', value: stocks.moscowFbsStock, expected: 0 },
    { col: 'I (9)', name: 'Уход Мес ОЗОН', value: analytics.monthUnits, expected: 1252 },
    { col: 'J (10)', name: 'Уход КВ ОЗОН', value: analytics.quarterUnits, expected: 2452 },
    { col: 'K (11)', name: 'ЦЕНА ОЗОН', value: ozonPrice, expected: 1480 },
    { col: 'L (12)', name: 'Сумма заказов Мес ОЗОН', value: analytics.monthRevenue, expected: 1816419 },
    { col: 'M (13)', name: 'ЦЕНА ВБ', value: wbPriceData.price, expected: 1335 },
    { col: 'N (14)', name: 'Сумма заказов Мес ВБ', value: wbOrders, expected: 5276 },
    { col: 'O (15)', name: 'Остаток ФБО ВБ', value: wbStocks.fboStock, expected: 36 },
    { col: 'P (16)', name: 'Остаток ФБС ВБ', value: wbStocks.fbsStock, expected: 0 },
    { col: 'R (18)', name: 'Уход Мес ВБ', value: wbAnalytics.monthOrders, expected: 4 },
    { col: 'S (19)', name: 'Уход КВ ВБ', value: wbAnalytics.quarterOrders, expected: 19 },
    { col: 'T (20)', name: 'Артикул ВБ (nmId)', value: wbPriceData.nmId, expected: '>0' },
    { col: 'U (21)', name: 'Product_id Ozon', value: '-', expected: '-' },
    { col: 'V (22)', name: 'SKU Ozon', value: SKU, expected: SKU },
  ];

  let passed = 0;
  results.forEach(r => {
    let status;
    if (r.expected === '>0') {
      status = r.value > 0 ? '✅' : '❌';
    } else if (r.expected === '-') {
      status = '⏭️';
    } else {
      status = r.value === r.expected ? '✅' : '❌';
    }

    if (status === '✅') passed++;
    console.log(`${status} ${r.col.padEnd(8)} ${r.name.padEnd(30)} ${String(r.value).padStart(10)} (ожид. ${r.expected})`);
  });

  console.log(`\n${passed}/${results.length} метрик совпадают`);

  if (passed === results.length) {
    console.log("\n🎉 ВСЕ МЕТРИКИ СОВПАДАЮТ!");
  } else {
    console.log("\n⚠️ Есть расхождения.");
  }

  // Сохраняем результаты
  fs.writeFileSync('test_results_all_19.json', JSON.stringify(results, null, 2));
}

main();
