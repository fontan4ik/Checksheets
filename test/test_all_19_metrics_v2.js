/**
 * ТЕСТ ВСЕХ 19 МЕТРИК ДЛЯ ТОВАРА 22068-1 (ВЕРСИЯ 2)
 *
 * Исправлены API endpoints на основе рабочих .gs файлов
 */

const https = require('https');
const fs = require('fs');

// API KEYS
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
// 1. OZON PRODUCT INFO (A, B, C, D, E, U, V)
// ============================================
async function fetchOzonProductInfo() {
  console.log("\n=== 1. OZON PRODUCT INFO ===");

  // ИСПРАВЛЕНО: правильный endpoint для получения product_id
  const path = '/v3/product/info/list';
  const body = {
    filter: {
      offer_id: [ARTICLE],
      product_id: []
    },
    limit: 1
  };

  const headers = {
    'Client-Id': OZON_CLIENT_ID,
    'Api-Key': OZON_API_KEY
  };

  try {
    const result = await httpsPost('api-seller.ozon.ru', path, headers, body);
    console.log(`Status: ${result.status}`);

    if (result.data.result && result.data.result.items && result.data.result.items.length > 0) {
      const item = result.data.result.items[0];

      const resultData = {
        offer_id: item.offer_id,
        product_id: item.product_id,
        sku: item.sku || "",
        image: item.images?.[0] || "",
        name: item.name || ""
      };

      // Теперь получаем атрибуты (бренд, модель)
      const attrPath = '/v4/product/info/attributes';
      const attrBody = {
        filter: { offer_id: [ARTICLE] },
        limit: 1
      };

      const attrResult = await httpsPost('api-seller.ozon.ru', attrPath, headers, attrBody);

      if (attrResult.data.result && attrResult.data.result.length > 0) {
        const attrItem = attrResult.data.result[0];

        const extractAttribute = (item, attrId) => {
          const attr = item.attributes?.find(a => a.id === attrId);
          return attr?.values[0]?.value || "";
        };

        resultData.brand = extractAttribute(attrItem, 85);
        resultData.model = extractAttribute(attrItem, 9048);
      } else {
        resultData.brand = "";
        resultData.model = "";
      }

      console.log(`✅ Данные получены:`);
      console.log(`   offer_id (A): ${resultData.offer_id}`);
      console.log(`   product_id (U): ${resultData.product_id}`);
      console.log(`   sku (V): ${resultData.sku}`);
      console.log(`   brand (C): ${resultData.brand}`);
      console.log(`   model (B/D): ${resultData.model}`);

      return resultData;
    } else {
      console.log('❌ Товар не найден');
      return null;
    }
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
    return null;
  }
}

// ============================================
// 2. OZON STOCKS (F, G, H) - ИСПРАВЛЕНО
// ============================================
async function fetchOzonStocks(sku) {
  console.log("\n=== 2. OZON STOCKS ===");

  // ИСПРАВЛЕНО: правильный endpoint для FBS stocks по SKU
  const path = '/v1/product/info/stocks-by-warehouse/fbs';
  const body = {
    sku: [parseInt(sku)],
    warehouse_type: "FBS"
  };

  const headers = {
    'Client-Id': OZON_CLIENT_ID,
    'Api-Key': OZON_API_KEY
  };

  try {
    const result = await httpsPost('api-seller.ozon.ru', path, headers, body);
    console.log(`Status (FBS): ${result.status}`);

    let fbsStock = 0;
    let moscowFbsStock = 0;

    if (result.data.result && result.data.result.rows) {
      result.data.result.rows.forEach(row => {
        const warehouseName = row.warehouse_name || "";
        const amount = row.amount || 0;

        if (warehouseName.includes('Москва') || warehouseName.includes('МСК') ||
            warehouseName.includes('Electro') || warehouseName.includes('Электросталь')) {
          moscowFbsStock += amount;
        } else {
          fbsStock += amount;
        }
      });
    }

    // Теперь получаем FBO stocks
    const fboPath = '/v4/product/info/stocks';
    const fboBody = {
      filter: {
        sku: [parseInt(sku)]
      },
      limit: 1000
    };

    const fboResult = await httpsPost('api-seller.ozon.ru', fboPath, headers, fboBody);
    console.log(`Status (FBO): ${fboResult.status}`);

    let fboStock = 0;

    if (fboResult.data.result && fboResult.data.result.rows) {
      fboResult.data.result.rows.forEach(row => {
        const warehouseName = row.warehouse_name || "";
        const amount = row.stocks?.[0]?.available || 0;

        // FBO склады
        if (warehouseName.includes('Розница') || warehouseName.includes('FBO') ||
            warehouseName.includes('Корпоративный') || warehouseName.includes('Экспресс')) {
          fboStock += amount;
        }
      });
    }

    console.log(`✅ Остатки получены:`);
    console.log(`   F (6) Остаток ФБО ОЗОН: ${fboStock} (ожидается 1069) ${fboStock === 1069 ? '✅' : '❌'}`);
    console.log(`   G (7) Остаток ФБС ОЗОН: ${fbsStock} (ожидается 527) ${fbsStock === 527 ? '✅' : '❌'}`);
    console.log(`   H (8) ОСТ ФБС МСК ОЗОН: ${moscowFbsStock} (ожидается 0) ${moscowFbsStock === 0 ? '✅' : '❌'}`);

    return { fboStock, fbsStock, moscowFbsStock };
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
    return { fboStock: 0, fbsStock: 0, moscowFbsStock: 0 };
  }
}

// ============================================
// 3. OZON ANALYTICS (I, J, L) - ИСПРАВЛЕНО
// ============================================
async function fetchOzonAnalytics(sku) {
  console.log("\n=== 3. OZON ANALYTICS ===");

  const today = new Date('2026-02-04');
  const dateFromMonth = new Date(today.getFullYear(), today.getMonth() - 1, 3); // 3 янв
  const dateFromQuarter = new Date(today);
  dateFromQuarter.setDate(today.getDate() - 91);

  const path = '/v1/analytics/data';

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
    const resultMonth = await httpsPost('api-seller.ozon.ru', path, headers, bodyMonth);
    console.log(`Status (месяц): ${resultMonth.status}`);

    let monthUnits = 0;
    let monthRevenue = 0;

    if (resultMonth.data.result && resultMonth.data.result.data) {
      const skuData = resultMonth.data.result.data.find(d => d.dimensions[0].id.toString() === sku.toString());
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

    const resultQuarter = await httpsPost('api-seller.ozon.ru', path, headers, bodyQuarter);
    console.log(`Status (квартал): ${resultQuarter.status}`);

    let quarterUnits = 0;
    if (resultQuarter.data.result && resultQuarter.data.result.data) {
      const skuData = resultQuarter.data.result.data.find(d => d.dimensions[0].id.toString() === sku.toString());
      if (skuData) {
        quarterUnits = skuData.metrics[0] || 0;
      }
    }

    console.log(`✅ Аналитика получена:`);
    console.log(`   I (9) Уход Мес ОЗОН: ${monthUnits} (ожидается 1252) ${monthUnits === 1252 ? '✅' : '❌'}`);
    console.log(`   J (10) Уход КВ ОЗОН: ${quarterUnits} (ожидается 2452) ${quarterUnits === 2452 ? '✅' : '❌'}`);
    console.log(`   L (12) Сумма заказов Мес ОЗОН: ${monthRevenue} (ожидается 1816419) ${monthRevenue === 1816419 ? '✅' : '❌'}`);

    return { monthUnits, quarterUnits, monthRevenue };
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
    return { monthUnits: 0, quarterUnits: 0, monthRevenue: 0 };
  }
}

// ============================================
// 4. OZON PRICE (K) - ИСПРАВЛЕНО
// ============================================
async function fetchOzonPrice(productId) {
  console.log("\n=== 4. OZON PRICE ===");

  // ИСПРАВЛЕНО: правильный endpoint
  const path = '/v5/product/info/prices';
  const body = {
    filter: {
      product_id: [parseInt(productId)],
      currency_code: "RUB"
    },
    limit: 1000
  };

  const headers = {
    'Client-Id': OZON_CLIENT_ID,
    'Api-Key': OZON_API_KEY
  };

  try {
    const result = await httpsPost('api-seller.ozon.ru', path, headers, body);
    console.log(`Status: ${result.status}`);

    let price = 0;
    if (result.data.result && result.data.result.items && result.data.result.items.length > 0) {
      const item = result.data.result.items[0];
      price = Math.round(item.price?.price || 0);
    }

    console.log(`✅ Цена получена:`);
    console.log(`   K (11) ЦЕНА ОЗОН: ${price} (ожидается 1480) ${price === 1480 ? '✅' : '❌'}`);

    return price;
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
    return 0;
  }
}

// ============================================
// 5. WB PRICE (M) и nmId (T) - ИСПРАВЛЕНО
// ============================================
async function fetchWBPrice() {
  console.log("\n=== 5. WB PRICE ===");

  // ИСПРАВЛЕНО: правильный endpoint для поиска товаров
  const path = '/api/v2/supplier/card/list';

  const headers = {
    'Authorization': `Bearer ${WB_TOKEN}`
  };

  const body = {
    numpyKey: "catalog",
    settings: {
      cursor: { limit: 100 },
      filter: { withOrder: true, text: ARTICLE }
    },
    sort: { supplySort: "ASC" }
  };

  try {
    const result = await httpsPost('content-api.wildberries.ru', path, headers, body);
    console.log(`Status: ${result.status}`);

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

    console.log(`✅ Цена WB получена:`);
    console.log(`   M (13) ЦЕНА ВБ: ${price} (ожидается 1335) ${price === 1335 ? '✅' : '❌'}`);
    console.log(`   T (20) Артикул ВБ (nmId): ${nmId} ${nmId > 0 ? '✅' : '❌'}`);

    return { price, nmId };
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
    return { price: 0, nmId: 0 };
  }
}

// ============================================
// 6. WB ORDERS (N) - РАБОТАЕТ
// ============================================
async function fetchWBOrders() {
  console.log("\n=== 6. WB ORDERS ===");

  const today = new Date('2026-02-04');
  const dateFrom = new Date(today.getFullYear(), today.getMonth() - 1, 3); // 3 янв

  const path = `/api/v1/supplier/orders?dateFrom=${formatDate(dateFrom)}`;

  const headers = {
    'Authorization': `Bearer ${WB_TOKEN}`
  };

  try {
    const result = await httpsGet('statistics-api.wildberries.ru', path, headers);
    console.log(`Status: ${result.status}`);

    let totalSum = 0;

    if (Array.isArray(result.data)) {
      result.data.forEach(order => {
        if (order.supplierArticle === ARTICLE && !order.isCancel) {
          totalSum += order.priceWithDisc;
        }
      });
    }

    console.log(`✅ Сумма заказов WB получена:`);
    console.log(`   N (14) Сумма заказов Мес ВБ: ${totalSum} (ожидается 5276) ${totalSum === 5276 ? '✅' : '❌'}`);

    return totalSum;
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
    return 0;
  }
}

// ============================================
// 7. WB STOCKS (O, P) - ИСПРАВЛЕНО
// ============================================
async function fetchWBStocks() {
  console.log("\n=== 7. WB STOCKS ===");

  // ИСПРАВЛЕНО: правильный endpoint для остатков
  const path = '/api/v2/supplier/stocks';

  const headers = {
    'Authorization': `Bearer ${WB_TOKEN}`
  };

  try {
    const result = await httpsGet('statistics-api.wildberries.ru', path, headers);
    console.log(`Status: ${result.status}`);

    let fboStock = 0;
    let fbsStock = 0;

    if (Array.isArray(result.data)) {
      const stockData = result.data.find(s => s.supplierArticle === ARTICLE);
      if (stockData) {
        fboStock = stockData.quantity || 0;
      }
    }

    console.log(`✅ Остатки WB получены:`);
    console.log(`   O (15) Остаток ФБО ВБ: ${fboStock} (ожидается 36) ${fboStock === 36 ? '✅' : '❌'}`);
    console.log(`   P (16) Остаток ФБС ВБ: ${fbsStock} (ожидается 0) ${fbsStock === 0 ? '✅' : '❌'}`);

    return { fboStock, fbsStock };
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
    return { fboStock: 0, fbsStock: 0 };
  }
}

// ============================================
// 8. WB ANALYTICS (R, S) - ИСПРАВЛЕНО
// ============================================
async function fetchWBAnalytics() {
  console.log("\n=== 8. WB ANALYTICS ===");

  const today = new Date('2026-02-04');
  const dateFromMonth = new Date(today.getFullYear(), today.getMonth() - 1, 3); // 3 янв
  const dateFromQuarter = new Date(2025, 10, 3); // 3 ноя 2025

  const formatDateISO = (d) => {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}T00:00:00.000Z`;
  };

  // ИСПРАВЛЕНО: правильный endpoint для аналитики
  const pathMonth = `/api/v2/supplier/analytics?dateFrom=${formatDateISO(dateFromMonth)}&dateTo=${formatDateISO(today)}&key=supplierArticle&limit=1000&offset=0`;

  const headers = {
    'Authorization': `Bearer ${WB_TOKEN}`
  };

  try {
    const resultMonth = await httpsGet('statistics-api.wildberries.ru', pathMonth, headers);
    console.log(`Status (месяц): ${resultMonth.status}`);

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
    console.log(`Status (квартал): ${resultQuarter.status}`);

    let quarterOrders = 0;
    if (resultQuarter.data && resultQuarter.data.result && Array.isArray(resultQuarter.data.result)) {
      const quarterData = resultQuarter.data.result.find(r => r.supplierArticle === ARTICLE);
      if (quarterData) {
        quarterOrders = quarterData.ordersCount || 0;
      }
    }

    console.log(`✅ Аналитика WB получена:`);
    console.log(`   R (18) Уход Мес ВБ: ${monthOrders} (ожидается 4) ${monthOrders === 4 ? '✅' : '❌'}`);
    console.log(`   S (19) Уход КВ ВБ: ${quarterOrders} (ожидается 19) ${quarterOrders === 19 ? '✅' : '❌'}`);

    return { monthOrders, quarterOrders };
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
    return { monthOrders: 0, quarterOrders: 0 };
  }
}

// ============================================
// ГЛАВНАЯ ФУНКЦИЯ
// ============================================
async function main() {
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ТЕСТ ВСЕХ 19 МЕТРИК ДЛЯ ТОВАРА 22068-1 (V2)                        ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  // 1. Product Info
  const productInfo = await fetchOzonProductInfo();
  if (!productInfo) {
    console.log("\n❌ Не удалось получить информацию о товаре");
    return;
  }

  // 2. Stocks
  const stocks = await fetchOzonStocks(productInfo.sku);

  // 3. Analytics
  const analytics = await fetchOzonAnalytics(productInfo.sku);

  // 4. Ozon Price
  const ozonPrice = await fetchOzonPrice(productInfo.product_id);

  // 5. WB Price
  const wbPriceData = await fetchWBPrice();

  // 6. WB Orders
  const wbOrders = await fetchWBOrders();

  // 7. WB Stocks
  const wbStocks = await fetchWBStocks();

  // 8. WB Analytics
  const wbAnalytics = await fetchWBAnalytics();

  // Итоговая сводка
  console.log("\n╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ИТОГОВАЯ СВОДКА                                                      ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const results = [
    { col: 'A (1)', name: 'Артикул', value: ARTICLE, expected: ARTICLE, status: '✅' },
    { col: 'B (2)', name: 'Модель', value: productInfo.model, expected: '22068', status: productInfo.model === '22068' ? '✅' : '❌' },
    { col: 'C (3)', name: 'Бренд', value: productInfo.brand, expected: 'Feron', status: productInfo.brand === 'Feron' ? '✅' : '❌' },
    { col: 'D (4)', name: 'Артикул производителя', value: productInfo.model, expected: 'SEN30_220', status: productInfo.model === 'SEN30_220' ? '✅' : '❌' },
    { col: 'E (5)', name: 'Картинка', value: productInfo.image ? 'Да' : 'Нет', expected: 'Да', status: productInfo.image ? '✅' : '❌' },
    { col: 'F (6)', name: 'Остаток ФБО ОЗОН', value: stocks.fboStock, expected: 1069, status: stocks.fboStock === 1069 ? '✅' : '❌' },
    { col: 'G (7)', name: 'Остаток ФБС ОЗОН', value: stocks.fbsStock, expected: 527, status: stocks.fbsStock === 527 ? '✅' : '❌' },
    { col: 'H (8)', name: 'ОСТ ФБС МСК ОЗОН', value: stocks.moscowFbsStock, expected: 0, status: stocks.moscowFbsStock === 0 ? '✅' : '❌' },
    { col: 'I (9)', name: 'Уход Мес ОЗОН', value: analytics.monthUnits, expected: 1252, status: analytics.monthUnits === 1252 ? '✅' : '❌' },
    { col: 'J (10)', name: 'Уход КВ ОЗОН', value: analytics.quarterUnits, expected: 2452, status: analytics.quarterUnits === 2452 ? '✅' : '❌' },
    { col: 'K (11)', name: 'ЦЕНА ОЗОН', value: ozonPrice, expected: 1480, status: ozonPrice === 1480 ? '✅' : '❌' },
    { col: 'L (12)', name: 'Сумма заказов Мес ОЗОН', value: analytics.monthRevenue, expected: 1816419, status: analytics.monthRevenue === 1816419 ? '✅' : '❌' },
    { col: 'M (13)', name: 'ЦЕНА ВБ', value: wbPriceData.price, expected: 1335, status: wbPriceData.price === 1335 ? '✅' : '❌' },
    { col: 'N (14)', name: 'Сумма заказов Мес ВБ', value: wbOrders, expected: 5276, status: wbOrders === 5276 ? '✅' : '❌' },
    { col: 'O (15)', name: 'Остаток ФБО ВБ', value: wbStocks.fboStock, expected: 36, status: wbStocks.fboStock === 36 ? '✅' : '❌' },
    { col: 'P (16)', name: 'Остаток ФБС ВБ', value: wbStocks.fbsStock, expected: 0, status: wbStocks.fbsStock === 0 ? '✅' : '❌' },
    { col: 'R (18)', name: 'Уход Мес ВБ', value: wbAnalytics.monthOrders, expected: 4, status: wbAnalytics.monthOrders === 4 ? '✅' : '❌' },
    { col: 'S (19)', name: 'Уход КВ ВБ', value: wbAnalytics.quarterOrders, expected: 19, status: wbAnalytics.quarterOrders === 19 ? '✅' : '❌' },
    { col: 'T (20)', name: 'Артикул ВБ (nmId)', value: wbPriceData.nmId, expected: '>0', status: wbPriceData.nmId > 0 ? '✅' : '❌' },
    { col: 'U (21)', name: 'Product_id Ozon', value: productInfo.product_id, expected: '>0', status: productInfo.product_id > 0 ? '✅' : '❌' },
    { col: 'V (22)', name: 'SKU Ozon', value: productInfo.sku, expected: SKU, status: productInfo.sku === SKU ? '✅' : '❌' },
  ];

  results.forEach(r => {
    console.log(`${r.status} ${r.col.padEnd(6)} ${r.name.padEnd(30)} ${String(r.value).padStart(10)} (ожид. ${r.expected})`);
  });

  const passed = results.filter(r => r.status === '✅').length;
  const total = results.length;

  console.log(`\n${passed}/${total} метрик совпадают`);

  if (passed === total) {
    console.log("\n🎉 ВСЕ МЕТРИКИ СОВПАДАЮТ!");
  } else {
    console.log("\n⚠️ Есть расхождения. Продолжаем доработку...");
  }

  // Сохраняем результаты
  fs.writeFileSync('test_results_v2.json', JSON.stringify(results, null, 2));
}

main();
