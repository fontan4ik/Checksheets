/**
 * ПОЛУЧЕНИЕ РЕАЛЬНЫХ ДАННЫХ ЧЕРЕЗ API ДЛЯ ТОВАРА 22068-1
 *
 * Товар 22068-1:
 * - Product_id Ozon: 109652992
 * - SKU Ozon: 301854987
 * - nmId WB: 216675685
 */

const https = require('https');

// Ozon API ключи
const OZON_CLIENT_ID = '142355';
const OZON_API_KEY = 'fe539630-170b-4b48-b222-8ba092907a63';

// WB API токен
const WB_TOKEN = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg1ODgzMjc3LCJpZCI6IjAxOWMyMzE3LWEyZTMtNzQ2NC1iZTY3LTY3ZDNlMGY4YWNlMSIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.XsB0AXxVxUo13JxstFFAtQXxUqE-MjtP02FnX08uyhh3MGUxfFdm5hgVvcHRFOR-aiv1CeDegedqNJ1k5u8wPw';

// Данные товара
const PRODUCT_DATA = {
  productId: 109652992,
  sku: 301854987,
  nmId: 216675685,
  article: '22068-1'
};

// Функция для выполнения HTTPS POST запроса
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

      res.on('data', (chunk) => {
        data += chunk;
      });

      res.on('end', () => {
        try {
          const jsonData = JSON.parse(data);
          resolve({ status: res.statusCode, data: jsonData });
        } catch (e) {
          resolve({ status: res.statusCode, data: data });
        }
      });
    });

    req.on('error', (e) => {
      reject(e);
    });

    req.write(postData);
    req.end();
  });
}

// Функция для выполнения HTTPS GET запроса
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

      res.on('data', (chunk) => {
        data += chunk;
      });

      res.on('end', () => {
        try {
          const jsonData = JSON.parse(data);
          resolve({ status: res.statusCode, data: jsonData });
        } catch (e) {
          resolve({ status: res.statusCode, data: data });
        }
      });
    });

    req.on('error', (e) => {
      reject(e);
    });

    req.end();
  });
}

// ============================================
// API ЗАПРОСЫ
// ============================================

async function fetchOzonAnalytics() {
  console.log("\n=== 1. Ozon Analytics API ===");

  const today = new Date(); // 4 февраля 2026
  const dateFrom = new Date(today.getFullYear(), today.getMonth() - 1, 3); // 3 января 2026
  const dateTo = today;

  const formatDate = (d) => d.toISOString().slice(0, 10);

  const body = {
    date_from: formatDate(dateFrom),
    date_to: formatDate(dateTo),
    metrics: ["ordered_units", "ordered_sum", "delivered_units", "delivered_sum"],
    dimension: ["sku"],
    limit: 1000,
    offset: 0
  };

  const headers = {
    'Client-Id': OZON_CLIENT_ID,
    'Api-Key': OZON_API_KEY
  };

  try {
    const result = await httpsPost('api-seller.ozon.ru', '/v1/analytics/data', headers, body);
    console.log(`Status: ${result.status}`);

    // Сохраняем в файл
    const fs = require('fs');
    fs.writeFileSync('ozon_analytics_response.json', JSON.stringify(result.data, null, 2));
    console.log('✅ Сохранено: ozon_analytics_response.json');

    // Проверяем данные для SKU
    if (result.data.result && result.data.result.data) {
      const skuData = result.data.result.data.find(d => d.dimensions[0].id === String(PRODUCT_DATA.sku));
      if (skuData) {
        console.log(`\nДанные для SKU ${PRODUCT_DATA.sku}:`);
        console.log(`  ordered_units (Уход Мес ОЗОН): ${skuData.metrics[0]}`);
        console.log(`  ordered_sum (Сумма заказов Мес ОЗОН): ${skuData.metrics[1]}`);
      }
    }

    return result.data;
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
    return null;
  }
}

async function fetchOzonPrices() {
  console.log("\n=== 2. Ozon Prices API ===");

  const body = {
    filter: { product_id: [PRODUCT_DATA.productId] },
    limit: 1000
  };

  const headers = {
    'Client-Id': OZON_CLIENT_ID,
    'Api-Key': OZON_API_KEY
  };

  try {
    const result = await httpsPost('api-seller.ozon.ru', '/v5/product/info/prices', headers, body);
    console.log(`Status: ${result.status}`);

    const fs = require('fs');
    fs.writeFileSync('ozon_prices_response.json', JSON.stringify(result.data, null, 2));
    console.log('✅ Сохранено: ozon_prices_response.json');

    // Проверяем цену
    if (result.data.items && result.data.items.length > 0) {
      const product = result.data.items.find(i => i.product_id === PRODUCT_DATA.productId);
      if (product) {
        console.log(`\nЦена для product_id ${PRODUCT_DATA.productId}:`);
        console.log(`  marketing_seller_price: ${product.price.marketing_seller_price || 'N/A'}`);
        console.log(`  price_before: ${product.price.price_before || 'N/A'}`);
        console.log(`  price: ${product.price.price || 'N/A'}`);
      }
    }

    return result.data;
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
    return null;
  }
}

async function fetchOzonStocks() {
  console.log("\n=== 3. Ozon Stocks API (FBO/FBS) ===");

  const body = {
    filter: { product_id: [PRODUCT_DATA.productId] },
    limit: 1000
  };

  const headers = {
    'Client-Id': OZON_CLIENT_ID,
    'Api-Key': OZON_API_KEY
  };

  try {
    const result = await httpsPost('api-seller.ozon.ru', '/v4/product/info/stocks', headers, body);
    console.log(`Status: ${result.status}`);

    const fs = require('fs');
    fs.writeFileSync('ozon_stocks_response.json', JSON.stringify(result.data, null, 2));
    console.log('✅ Сохранено: ozon_stocks_response.json');

    // Проверяем остатки
    if (result.data.items && result.data.items.length > 0) {
      const product = result.data.items.find(i => i.product_id === PRODUCT_DATA.productId);
      if (product && product.stocks) {
        const fbo = product.stocks.find(s => s.type === 'fbo');
        const fbs = product.stocks.find(s => s.type === 'fbs');
        console.log(`\nОстатки для product_id ${PRODUCT_DATA.productId}:`);
        console.log(`  FBO: ${fbo ? fbo.stock : 0}`);
        console.log(`  FBS: ${fbs ? fbs.stock : 0}`);
      }
    }

    return result.data;
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
    return null;
  }
}

async function fetchWBSalesFunnel() {
  console.log("\n=== 4. WB Sales Funnel API ===");

  const today = new Date(); // 4 февраля 2026
  const dateFrom = new Date(today.getFullYear(), today.getMonth() - 1, 3); // 3 января 2026
  const dateTo = today;

  const formatDate = (d) => d.toISOString().slice(0, 10);

  const path = `/api/analytics/v3/sales-funnel/products/history`;

  const headers = {
    'Authorization': `Bearer ${WB_TOKEN}`
  };

  // ИСПРАВЛЕНО: WB API требует POST вместо GET, aggregationLevel как строка
  const body = {
    period: {
      from: formatDate(dateFrom),
      to: formatDate(dateTo)
    },
    orderBy: [
      {
        field: "ordersSum",
        order: "DESC"
      }
    ],
    limit: 100000
  };

  try {
    const result = await httpsPost('seller-analytics-api.wildberries.ru', path, headers, body);
    console.log(`Status: ${result.status}`);

    const fs = require('fs');
    fs.writeFileSync('wb_sales_funnel_response.json', JSON.stringify(result.data, null, 2));
    console.log('✅ Сохранено: wb_sales_funnel_response.json');

    // Проверяем данные для nmId
    if (Array.isArray(result.data)) {
      for (const subject of result.data) {
        if (subject.products) {
          const product = subject.products.find(p => p.product_id === PRODUCT_DATA.nmId);
          if (product) {
            console.log(`\nДанные для nmId ${PRODUCT_DATA.nmId}:`);
            console.log(`  ordersCount (Уход Мес ВБ): ${product.ordersCount}`);
            console.log(`  ordersSum (Сумма заказов Мес ВБ): ${product.ordersSum}`);
            break;
          }
        }
      }
    }

    return result.data;
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
    return null;
  }
}

async function fetchWBStocks() {
  console.log("\n=== 5. WB Stocks API (FBO) ===");

  const today = new Date(); // 4 февраля 2026
  const dateFrom = new Date(today.getFullYear(), today.getMonth() - 1, 3); // 3 января 2026
  const dateTo = today;

  const formatDateISO = (d) => {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}T00:00:00.000Z`;
  };

  const path = `/api/v2/stocks-report/products/products`;

  const headers = {
    'Authorization': `Bearer ${WB_TOKEN}`
  };

  // ИСПРАВЛЕНО: WB API требует POST вместо GET
  const body = {
    dateFrom: formatDateISO(dateFrom),
    dateTo: formatDateISO(dateTo),
    skip: 0,
    take: 100000
  };

  try {
    const result = await httpsPost('seller-analytics-api.wildberries.ru', path, headers, body);
    console.log(`Status: ${result.status}`);

    const fs = require('fs');
    fs.writeFileSync('wb_stocks_response.json', JSON.stringify(result.data, null, 2));
    console.log('✅ Сохранено: wb_stocks_response.json');

    // Проверяем остатки для nmId
    if (Array.isArray(result.data)) {
      const product = result.data.find(p => p.nmId === PRODUCT_DATA.nmId);
      if (product) {
        console.log(`\nОстаток FBO для nmId ${PRODUCT_DATA.nmId}:`);
        console.log(`  quantity: ${product.quantity}`);
      }
    }

    return result.data;
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
    return null;
  }
}

// ============================================
// ГЛАВНАЯ ФУНКЦИЯ
// ============================================

async function main() {
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ПОЛУЧЕНИЕ РЕАЛЬНЫХ ДАННЫХ ЧЕРЕЗ API ДЛЯ ТОВАРА 22068-1               ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");
  console.log("\nТовар:");
  console.log(`  Артикул: ${PRODUCT_DATA.article}`);
  console.log(`  Product_id Ozon: ${PRODUCT_DATA.productId}`);
  console.log(`  SKU Ozon: ${PRODUCT_DATA.sku}`);
  console.log(`  nmId WB: ${PRODUCT_DATA.nmId}`);

  console.log("\nПериод: с 3 по 3 число текущего месяца");

  // Выполняем все запросы
  await fetchOzonAnalytics();
  await fetchOzonPrices();
  await fetchOzonStocks();
  await fetchWBSalesFunnel();
  await fetchWBStocks();

  console.log("\n╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ГОТОВО! Проверьте JSON файлы в текущей директории                       ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");
}

main();
