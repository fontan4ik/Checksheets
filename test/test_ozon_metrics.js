/**
 * Пробуем разные metrics для Ozon Analytics
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

async function testMetrics(metrics, description) {
  console.log(`\n=== ${description} ===`);

  const body = {
    date_from: '2026-01-03',
    date_to: '2026-02-04',
    metrics: metrics,
    dimension: ['sku'],
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
        console.log(`  Metrics (${metrics.length}):`, skuData.metrics);
      } else {
        console.log(`SKU ${SKU} не найден`);
      }
      console.log(`  Всего записей: ${result.data.result.data.length}`);
    }

    return result.data;
  } catch (e) {
    console.error(`Ошибка: ${e.message}`);
    return null;
  }
}

async function main() {
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ПРОБА РАЗНЫХ METRICS ДЛЯ OZON ANALYTICS                             ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  // Пробуем разные combinations
  await testMetrics(['ordered_units', 'revenue'], 'ordered_units + revenue');
  await testMetrics(['ordered_units', 'ordered_revenue'], 'ordered_units + ordered_revenue');
  await testMetrics(['ordered_units', 'sales_sum'], 'ordered_units + sales_sum');
  await testMetrics(['delivered_units', 'delivered_sum'], 'delivered_units + delivered_sum');
  await testMetrics(['ordered_units'], 'только ordered_units');
}

main();
