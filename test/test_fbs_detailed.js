/**
 * ДЕТАЛЬНЫЙ ТЕСТ ФБС СКЛАДОВ - проверка формата ответа
 */

const https = require('https');

const WB_MARKETPLACE_TOKEN = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg1ODgzMjc3LCJpZCI6IjAxOWMyMzE3LWEyZTMtNzQ2NC1iZTY3LTY3ZDNlMGY4YWNlMSIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.XsB0AXxVxUo13JxstFFAtQXxUqE-MjtP02FnX08uyhh3MGUxfFdm5hgVvcHRFOR-aiv1CeDegedqNJ1k5u8wPw';

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
        resolve({ status: res.statusCode, rawData: data });
      });
    });
    req.on('error', reject);
    req.write(JSON.stringify(body));
    req.end();
  });
}

async function test() {
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ДЕТАЛЬНЫЙ ТЕСТ ФБС СКЛАДОВ - ПРОВЕРКА ФОРМАТА ОТВЕТА                 ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const headers = {
    'Authorization': WB_MARKETPLACE_TOKEN,
    'Content-Type': 'application/json'
  };

  const warehouseId = 1449484; // ФБС ФЕРОН МОСКВА
  const testSkus = ["22068-1", "23348-1", "25841-5"];

  console.log("\n=== ЗАПРОС ===");
  console.log(`POST https://marketplace-api.wildberries.ru/api/v3/stocks/${warehouseId}`);
  console.log(`Headers: ${JSON.stringify(headers, null, 2)}`);
  console.log(`Body: ${JSON.stringify({ skus: testSkus }, null, 2)}`);

  try {
    const result = await httpsPost(
      'marketplace-api.wildberries.ru',
      `/api/v3/stocks/${warehouseId}`,
      headers,
      { skus: testSkus }
    );

    console.log(`\n=== ОТВЕТ ===`);
    console.log(`Status: ${result.status}`);
    console.log(`\nRaw response (first 1000 chars):`);
    console.log(result.rawData.substring(0, 1000));

    // Пытаемся распарсить JSON
    try {
      const jsonData = JSON.parse(result.rawData);
      console.log(`\nParsed JSON structure:`);
      console.log(JSON.stringify(jsonData, null, 2));
    } catch (e) {
      console.log(`\n❌ Ошибка парсинга JSON: ${e.message}`);
    }

  } catch (e) {
    console.error(`\n❌ Ошибка: ${e.message}`);
  }
}

test();
