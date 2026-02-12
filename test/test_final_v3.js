/**
 * ФИНАЛЬНЫЙ ТЕСТ - используем проверенные методы из рабочих .gs файлов
 */

const https = require('https');
const fs = require('fs');

const OZON_CLIENT_ID = '142355';
const OZON_API_KEY = 'fe539630-170b-4b48-b222-8ba092907a63';
const WB_TOKEN = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg1ODgzMjc3LCJpZCI6IjAxOWMyMzE3LWEyZTMtNzQ2NC1iZTY3LTY3ZDNlMGY4YWNlMSIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.XsB0AXxVxUo13JxstFFAtQXxUqE-MjtP02FnX08uyhh3MGUxfFdm5hgVvcHRFOR-aiv1CeDegedqNJ1k5u8wPw';

const SKU = '301854987'; // Известный SKU

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
// 1. ANALYTICS (I, J, L) - работает по SKU
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
    console.log(`Status (месяц): ${resultMonth.status}`);

    let monthUnits = 0;
    let monthRevenue = 0;

    if (resultMonth.data.result && resultMonth.data.result.data) {
      const skuData = resultMonth.data.result.data.find(d => d.dimensions[0].id.toString() === SKU.toString());
      if (skuData) {
        monthUnits = skuData.metrics[0] || 0;
        monthRevenue = Math.round(skuData.metrics[1] || 0);
        console.log(`✅ Данные найдены для SKU ${SKU}`);
        console.log(`   ordered_units: ${monthUnits} (ожидается 1252) ${monthUnits === 1252 ? '✅' : '❌'}`);
        console.log(`   revenue: ${monthRevenue} (ожидается 1816419) ${monthRevenue === 1816419 ? '✅' : '❌'}`);
      } else {
        console.log(`❌ SKU ${SKU} не найден`);
        console.log(`   Всего записей: ${resultMonth.data.result.data.length}`);
        // Покажем первые 3 SKU для диагностики
        resultMonth.data.result.data.slice(0, 3).forEach(d => {
          console.log(`   - SKU: ${d.dimensions[0].id}`);
        });
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
    console.log(`Status (квартал): ${resultQuarter.status}`);

    let quarterUnits = 0;
    if (resultQuarter.data.result && resultQuarter.data.result.data) {
      const skuData = resultQuarter.data.result.data.find(d => d.dimensions[0].id.toString() === SKU.toString());
      if (skuData) {
        quarterUnits = skuData.metrics[0] || 0;
        console.log(`   ordered_units (квартал): ${quarterUnits} (ожидается 2452) ${quarterUnits === 2452 ? '✅' : '❌'}`);
      }
    }

    return { monthUnits, quarterUnits, monthRevenue };
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
    return { monthUnits: 0, quarterUnits: 0, monthRevenue: 0 };
  }
}

// ============================================
// 2. WB ORDERS (N) - работает
// ============================================
async function fetchWBOrders() {
  console.log("\n=== 2. WB ORDERS ===");

  const today = new Date('2026-02-04');
  const dateFrom = new Date(today.getFullYear(), today.getMonth() - 1, 3);

  const path = `/api/v1/supplier/orders?dateFrom=${formatDate(dateFrom)}`;
  const headers = { 'Authorization': `Bearer ${WB_TOKEN}` };

  try {
    const result = await httpsGet('statistics-api.wildberries.ru', path, headers);
    console.log(`Status: ${result.status}`);

    let totalSum = 0;
    let ordersCount = 0;

    if (Array.isArray(result.data)) {
      result.data.forEach(order => {
        if (order.supplierArticle === '22068-1' && !order.isCancel) {
          totalSum += order.priceWithDisc;
          ordersCount++;
        }
      });
    }

    console.log(`✅ Заказов для 22068-1: ${ordersCount} (ожидается 4)`);
    console.log(`   Сумма: ${totalSum} (ожидается 5276) ${totalSum === 5276 ? '✅' : '❌'}`);

    return { totalSum, ordersCount };
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
    return { totalSum: 0, ordersCount: 0 };
  }
}

// ============================================
// ГЛАВНАЯ ФУНКЦИЯ
// ============================================
async function main() {
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ФИНАЛЬНЫЙ ТЕСТ ДЛЯ SKU 301854987 (22068-1)                         ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  // 1. Ozon Analytics
  const analytics = await fetchOzonAnalytics();

  // 2. WB Orders
  const wbOrders = await fetchWBOrders();

  // Итоговая сводка
  console.log("\n╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ИТОГОВАЯ СВОДКА                                                      ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const results = [
    { col: 'I (9)', name: 'Уход Мес ОЗОН', value: analytics.monthUnits, expected: 1252 },
    { col: 'J (10)', name: 'Уход КВ ОЗОН', value: analytics.quarterUnits, expected: 2452 },
    { col: 'L (12)', name: 'Сумма заказов Мес ОЗОН', value: analytics.monthRevenue, expected: 1816419 },
    { col: 'N (14)', name: 'Сумма заказов Мес ВБ', value: wbOrders.totalSum, expected: 5276 },
  ];

  let passed = 0;
  results.forEach(r => {
    const status = r.value === r.expected ? '✅' : '❌';
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
  fs.writeFileSync('test_results_final.json', JSON.stringify(results, null, 2));
}

main();
