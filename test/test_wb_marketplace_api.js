/**
 * ТЕСТ WB MARKETPLACE API
 */

const https = require('https');

const WB_TOKEN = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg1ODgzMjc3LCJpZCI6IjAxOWMyMzE3LWEyZTMtNzQ2NC1iZTY3LTY3ZDNlMGY4YWNlMSIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.XsB0AXxVxUo13JxstFFAtQXxUqE-MjtP02FnX08uyhh3MGUxfFdm5hgVvcHRFOR-aiv1CeDegedqNJ1k5u8wPw';

const ARTICLE = '22068-1';

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
  console.log("║   ТЕСТ WB MARKETPLACE API (warehouse_id)                             ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const headers = { 'Authorization': `Bearer ${WB_TOKEN}` };

  // Тестируем разные warehouse_id
  const warehouseIds = [
    { id: 1449484, name: 'ФБО (O, 15)' },
    { id: 798761, name: 'ФБС (P, 16)' }
  ];

  for (const wh of warehouseIds) {
    console.log(`\n=== Warehouse ${wh.id} (${wh.name}) ===`);

    try {
      const result = await httpsGet('marketplace-api.wildberries.ru', `/api/v3/stocks/${wh.id}`, headers);
      console.log(`Status: ${result.status}`);

      if (Array.isArray(result.data)) {
        console.log(`Is array: true, length: ${result.data.length}`);

        const found = result.data.find(s => s.supplierArticle === ARTICLE);
        if (found) {
          console.log(`✅ Found ${ARTICLE}:`, JSON.stringify(found));
        } else {
          console.log(`❌ NOT found ${ARTICLE}`);
          if (result.data.length > 0) {
            console.log(`First 3 items:`, result.data.slice(0, 3).map(s => ({
              article: s.supplierArticle,
              qty: s.quantity
            })));
          }
        }
      } else {
        console.log(`Keys:`, Object.keys(result.data));
        console.log(`Response:`, JSON.stringify(result.data).substring(0, 300));
      }
    } catch (e) {
      console.error(`❌ Ошибка: ${e.message}`);
    }
  }
}

test();
