/**
 * ТЕСТ СПИСКА ВСЕХ СКЛАДОВ WB
 */

const https = require('https');

const WB_TOKEN = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg1ODgzMjc3LCJpZCI6IjAxOWMyMzE3LWEyZTMtNzQ2NC1iZTY3LTY3ZDNlMGY4YWNlMSIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.XsB0AXxVxUo13JxstFFAtQXxUqE-MjtP02FnX08uyhh3MGUxfFdm5hgVvcHRFOR-aiv1CeDegedqNJ1k5u8wPw';

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

async function test() {
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   СПИСОК ВСЕХ СКЛАДОВ WB                                             ║");
  console.log("╚════════════════════╨═══════════════════════════════════════════════════════╝");

  const headers = { 'Authorization': `Bearer ${WB_TOKEN}` };

  // API для получения списка складов
  console.log("\n=== GET WAREHOUSES ===");

  try {
    const result = await httpsGet('marketplace-api.wildberries.ru', '/api/v3/warehouses', headers);
    console.log(`Status: ${result.status}`);

    console.log(`Keys:`, Object.keys(result.data));

    const jsonStr = JSON.stringify(result.data, null, 2);
    console.log(`\nResponse:\n${jsonStr.substring(0, 2000)}`);

    // Если это массив, покажем первый элемент
    if (Array.isArray(result.data)) {
      console.log(`\n=== ПЕРВЫЙ СКЛАД ===`);
      console.log(JSON.stringify(result.data[0], null, 2));
    }
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }

  // Попробую другой endpoint
  console.log("\n=== GET SUPPLIER WAREHOUSES ===");

  try {
    const result = await httpsGet('supervisor-api.wildberries.ru', '/api/v1/warehouses', headers);
    console.log(`Status: ${result.status}`);

    console.log(`Keys:`, Object.keys(result.data));

    const jsonStr = JSON.stringify(result.data, null, 2);
    console.log(`\nResponse:\n${jsonStr.substring(0, 2000)}`);
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }
}

test();
