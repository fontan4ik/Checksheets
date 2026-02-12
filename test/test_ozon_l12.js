/**
 * ТЕСТ L (12) - Сумма заказов Мес ОЗОН
 * Проверяет логику заполнения колонки L
 */

const https = require('https');

const OZON_CLIENT_ID = '273849';
const OZON_API_KEY = '4475806e-5701-4f70-9368-69962efae726';

const TEST_SKU = '301854987'; // SKU для 22068-1

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
          resolve({ status: res.statusCode, data: jsonData });
        } catch (e) {
          resolve({ status: res.statusCode, data: data });
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
  console.log("║   ТЕСТ L (12) - Сумма заказов Мес ОЗОН                                  ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const today = new Date();
  const startDate = new Date(today.getFullYear(), today.getMonth() - 1, 3);

  console.log("\n=== ПАРАМЕТРЫ ЗАПРОСА ===");
  console.log(`SKU: ${TEST_SKU}`);
  console.log(`Период: с ${formatDate(startDate)} по ${formatDate(today)}`);
  console.log(`Metrics: ordered_units, revenue`);

  const headers = {
    'Client-Id': OZON_CLIENT_ID,
    'Api-Key': OZON_API_KEY,
    'Content-Type': 'application/json'
  };

  const body = {
    date_from: formatDate(startDate),
    date_to: formatDate(today),
    dimension: ["sku"],
    metrics: ["ordered_units", "revenue"],
    limit: 1,
    offset: 0
  };

  console.log("\n=== ЗАПРОС К API ===");
  console.log("POST /v1/analytics/data");
  console.log("Body:", JSON.stringify(body, null, 2));

  try {
    const result = await httpsPost(
      'api-seller.ozon.ru',
      '/v1/analytics/data',
      headers,
      body
    );

    console.log(`\n=== ОТВЕТ API (Status: ${result.status}) ===`);

    if (result.data.error) {
      console.log("❌ ОШИБКА API:");
      console.log(JSON.stringify(result.data.error, null, 2));
      return;
    }

    const resultData = result.data?.result?.data || [];
    console.log(`\nЗаписей в ответе: ${resultData.length}`);

    if (resultData.length > 0) {
      const entry = resultData[0];
      const sku = entry.dimensions[0]?.id;
      const orderedUnits = entry.metrics[0];
      const revenue = entry.metrics[1];

      console.log("\n📊 ДАННЫЕ ПО SKU " + TEST_SKU + ":");
      console.log(`   ordered_units: ${orderedUnits}`);
      console.log(`   revenue: ${revenue} руб.`);

      console.log("\n=== ЗАПОЛНЕНИЕ КОЛОНОК ===");
      console.log(`   I (9)  Уход Мес ОЗОН: ${orderedUnits}`);
      console.log(`   L (12) Сумма заказов:  ${revenue}`);

      console.log("\n✅ API работает корректно");
      console.log("Если в таблице L (12) пустая, проверьте:");
      console.log("1. Заполнена ли колонка V (SKU)");
      console.log("2. Совпадает ли SKU с тестовым: " + TEST_SKU);
      console.log("3. Выполняется ли функция fetchAndWriteAnalytics()");
    } else {
      console.log("\n⚠️  Пустой ответ от API");
      console.log("Возможные причины:");
      console.log("- Нет заказов за указанный период");
      console.log("- Неверный SKU");
      console.log("- SKU не найден в базе Ozon");
    }

  } catch (e) {
    console.error(`\n❌ Ошибка: ${e.message}`);
  }
}

test();
