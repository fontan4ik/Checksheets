/**
 * ОТЛАДКА L (12) - Сумма заказов Мес ОЗОН
 */

const https = require('https');

const OZON_CLIENT_ID = '273849';
const OZON_API_KEY = '4475806e-5701-4f70-9368-69962efae726';

function httpsPost(hostname, path, headers, body) {
  return new Promise((resolve, reject) => {
    const options = {
      hostname: hostname,
      path: path,
      method: 'POST',
      headers: headers
    };

    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          const jsonData = JSON.parse(data);
          resolve({ status: res.statusCode, data: jsonData, raw: data });
        } catch (e) {
          resolve({ status: res.statusCode, data: data, raw: data });
        }
      });
    });

    req.on('error', reject);
    req.write(JSON.stringify(body));
    req.end();
  });
}

function formatDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

async function test() {
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ОТЛАДКА L (12) - Сумма заказов Мес ОЗОН                                ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const headers = {
    'Client-Id': OZON_CLIENT_ID,
    'Api-Key': OZON_API_KEY,
    'Content-Type': 'application/json'
  };

  const today = new Date();
  const startDate30 = new Date(today);
  startDate30.setDate(today.getDate() - 30);

  const startDate90 = new Date(today);
  startDate90.setDate(today.getDate() - 90);

  console.log("\n=== ТЕСТ 1: Без фильтра по SKU (последние 30 дней) ===");
  const body1 = {
    date_from: formatDate(startDate30),
    date_to: formatDate(today),
    dimension: ["sku"],
    metrics: ["ordered_units", "revenue"],
    limit: 10,
    offset: 0
  };

  const result1 = await httpsPost('api-seller.ozon.ru', '/v1/analytics/data', headers, body1);
  console.log(`Status: ${result1.status}`);
  const data1 = result1.data?.result?.data || [];
  console.log(`Записей: ${data1.length}`);

  if (data1.length > 0) {
    console.log("\nПервые 3 записи:");
    data1.slice(0, 3).forEach((entry, i) => {
      console.log(`  [${i+1}] SKU: ${entry.dimensions[0]?.id}, ordered_units: ${entry.metrics[0]}, revenue: ${entry.metrics[1]}`);
    });
  }

  console.log("\n=== ТЕСТ 2: С фильтром по SKU 301854987 (30 дней) ===");
  const body2 = {
    date_from: formatDate(startDate30),
    date_to: formatDate(today),
    dimension: ["sku"],
    metrics: ["ordered_units", "revenue"],
    filters: [
      {
        key: "sku",
        op: "EQ",
        value: "301854987"
      }
    ],
    limit: 1,
    offset: 0
  };

  const result2 = await httpsPost('api-seller.ozon.ru', '/v1/analytics/data', headers, body2);
  console.log(`Status: ${result2.status}`);
  const data2 = result2.data?.result?.data || [];
  console.log(`Записей: ${data2.length}`);

  if (data2.length > 0) {
    console.log("\nДанные для SKU 301854987:");
    console.log(`  ordered_units: ${data2[0].metrics[0]}`);
    console.log(`  revenue: ${data2[0].metrics[1]}`);
  } else {
    console.log("❌ Нет данных для SKU 301854987 за последние 30 дней");
  }

  console.log("\n=== ТЕСТ 3: SKU 301854987 (90 дней) ===");
  const body3 = {
    date_from: formatDate(startDate90),
    date_to: formatDate(today),
    dimension: ["sku"],
    metrics: ["ordered_units", "revenue"],
    filters: [
      {
        key: "sku",
        op: "EQ",
        value: "301854987"
      }
    ],
    limit: 1,
    offset: 0
  };

  const result3 = await httpsPost('api-seller.ozon.ru', '/v1/analytics/data', headers, body3);
  console.log(`Status: ${result3.status}`);
  const data3 = result3.data?.result?.data || [];
  console.log(`Записей: ${data3.length}`);

  if (data3.length > 0) {
    console.log("\n✅ Данные за 90 дней:");
    console.log(`  ordered_units: ${data3[0].metrics[0]}`);
    console.log(`  revenue: ${data3[0].metrics[1]}`);
  } else {
    console.log("❌ Нет данных для SKU 301854987 за последние 90 дней");
    console.log("\nВозможно SKU неверный или товара не существует");
  }

  console.log("\n=== ТЕСТ 4: Проверка валидности API ключа ===");
  const body4 = {
    date_from: "2025-01-01",
    date_to: formatDate(today),
    dimension: ["sku"],
    metrics: ["ordered_units"],
    limit: 1,
    offset: 0
  };

  const result4 = await httpsPost('api-seller.ozon.ru', '/v1/analytics/data', headers, body4);
  console.log(`Status: ${result4.status}`);
  if (result4.data.error) {
    console.log("❌ Ошибка API:");
    console.log(JSON.stringify(result4.data.error, null, 2));
  } else {
    console.log("✅ API ключ валиден");
  }
}

test();
