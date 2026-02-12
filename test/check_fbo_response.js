/**
 * Проверка полной структуры ответа FBO
 */

const https = require('https');
const fs = require('fs');

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
  console.log("=== ПРОВЕРКА СТРУКТУРЫ FBO ===");

  const result = await httpsPost('api-seller.ozon.ru', '/v4/product/info/stocks', {
    'Client-Id': OZON_CLIENT_ID,
    'Api-Key': OZON_API_KEY
  }, {
    filter: { sku: [parseInt(SKU)] },
    limit: 1000
  });

  console.log(`Status: ${result.status}`);
  console.log(`Keys:`, Object.keys(result.data));

  // Сохраняем полный ответ
  fs.writeFileSync('fbo_response_full.json', JSON.stringify(result.data, null, 2));
  console.log(`\nСохранено: fbo_response_full.json`);

  // Показываем начало ответа
  const jsonStr = JSON.stringify(result.data, null, 2);
  console.log(`\nПервые 1000 символов:\n${jsonStr.substring(0, 1000)}`);
}

main();
