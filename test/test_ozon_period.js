/**
 * Проверка Ozon Analytics за разные периоды
 */

const https = require('https');

const OZON_CLIENT_ID = '142355';
const OZON_API_KEY = 'fe539630-170b-4b48-b222-8ba092907a63';
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

async function testPeriod(dateFrom, dateTo) {
  console.log(`\n=== Период: ${dateFrom} → ${dateTo} ===`);

  const body = {
    date_from: dateFrom,
    date_to: dateTo,
    metrics: ["ordered_units", "ordered_sum", "delivered_units", "delivered_sum", "returned_units", "returned_sum"],
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

    if (result.data.result && result.data.result.data) {
      const skuData = result.data.result.data.find(d => d.dimensions[0].id === SKU);
      if (skuData) {
        console.log(`SKU: ${SKU}`);
        console.log(`  ordered_units (индекс 0): ${skuData.metrics[0]}`);
        console.log(`  ordered_sum (индекс 1): ${skuData.metrics[1]}`);
        console.log(`  delivered_units (индекс 2): ${skuData.metrics[2] || 'N/A'}`);
        console.log(`  delivered_sum (индекс 3): ${skuData.metrics[3] || 'N/A'}`);
        console.log(`  returned_units (индекс 4): ${skuData.metrics[4] || 'N/A'}`);
        console.log(`  returned_sum (индекс 5): ${skuData.metrics[5] || 'N/A'}`);
      } else {
        console.log(`SKU ${SKU} не найден`);
      }
    }

    return result.data;
  } catch (e) {
    console.error(`Ошибка: ${e.message}`);
    return null;
  }
}

async function main() {
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ПРОВЕРКА OZON ANALYTICS ЗА РАЗНЫЕ ПЕРИОДЫ                          ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  // Текущий период (с 3 января по сегодня)
  await testPeriod('2026-01-03', '2026-02-04');

  // Весь прошлый месяц (январь)
  await testPeriod('2026-01-01', '2026-01-31');

  // С 3 декабря по 3 января
  await testPeriod('2025-12-03', '2026-01-03');
}

main();
