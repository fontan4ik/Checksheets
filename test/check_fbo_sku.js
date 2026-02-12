/**
 * Проверка FBO SKU в ответе
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

async function main() {
  console.log("=== ПРОВЕРКА FBO SKU ===");

  const result = await httpsPost('api-seller.ozon.ru', '/v4/product/info/stocks', {
    'Client-Id': OZON_CLIENT_ID,
    'Api-Key': OZON_API_KEY
  }, {
    filter: { sku: [parseInt(SKU)] },
    limit: 1000
  });

  console.log(`Status: ${result.status}`);
  console.log(`Has result: ${!!result.data.result}`);
  console.log(`Has items: ${!!result.data.result?.items}`);

  if (result.data.result?.items) {
    console.log(`Items count: ${result.data.result.items.length}`);

    if (result.data.result.items.length === 0) {
      console.log(`❌ ПУСТО! SKU ${SKU} не найден в FBO stocks!`);
      console.log(`   Возможно товар продаётся только на FBS.`);
    } else {
      let fboTotal = 0;
      result.data.result.items.forEach(item => {
        console.log(`\nItem: ${item.offer_id}`);
        if (item.stocks) {
          item.stocks.forEach(stock => {
            console.log(`  Type: ${stock.type}, Present: ${stock.present}`);
            if (stock.type === 'fbo') {
              fboTotal += stock.present;
            }
          });
        }
      });
      console.log(`\n✅ FBO Total: ${fboTotal}`);
    }
  }
}

main();
