/**
 * ПРОВЕРКА API OZON АНАЛИТИКА
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

    console.log("Request URL: https://" + hostname + path);
    console.log("Headers:", JSON.stringify(headers, null, 2));

    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        console.log(`Response Status: ${res.statusCode}`);
        console.log(`Response Headers:`, res.headers);

        try {
          const jsonData = JSON.parse(data);
          resolve({ status: res.statusCode, data: jsonData, raw: data });
        } catch (e) {
          resolve({ status: res.statusCode, data: data, raw: data });
        }
      });
    });

    req.on('error', (err) => {
      console.error("Request Error:", err.message);
      reject(err);
    });

    req.write(JSON.stringify(body));
    req.end();
  });
}

async function test() {
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ПРОВЕРКА API OZON АНАЛИТИКА                                          ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const headers = {
    'Client-Id': OZON_CLIENT_ID,
    'Api-Key': OZON_API_KEY,
    'Content-Type': 'application/json'
  };

  const today = new Date();
  const startDate = new Date(today);
  startDate.setDate(today.getDate() - 30);

  // Простейший запрос
  const body = {
    date_from: "2025-01-01",
    date_to: "2025-02-04",
    dimension: ["sku"],
    metrics: ["ordered_units"],
    limit: 1,
    offset: 0
  };

  console.log("\nRequest Body:");
  console.log(JSON.stringify(body, null, 2));

  try {
    const result = await httpsPost(
      'api-seller.ozon.ru',
      '/v1/analytics/data',
      headers,
      body
    );

    console.log("\n=== РЕЗУЛЬТАТ ===");

    if (result.data.error) {
      console.log("❌ ОШИБКА API:");
      console.log(JSON.stringify(result.data.error, null, 2));

      if (result.data.error.code === 'invalid_client') {
        console.log("\n⚠️  Неверный Client-Id или Api-Key");
      } else if (result.data.error.code === 'forbidden') {
        console.log("\n⚠️  Нет доступа к аналитике");
      }
    } else {
      console.log("✅ ЗАПРОС УСПЕШЕН");
      const data = result.data?.result?.data || [];
      console.log(`Записей: ${data.length}`);
    }

  } catch (e) {
    console.error(`\n❌ Ошибка: ${e.message}`);
  }
}

test();
