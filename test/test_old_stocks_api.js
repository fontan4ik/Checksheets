/**
 * ТЕСТ СТАРОГО WB STOCKS API
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
  console.log("║   ТЕСТ СТАРОГО WB STOCKS API                                         ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const headers = { 'Authorization': `Bearer ${WB_TOKEN}` };

  // Старый API как в importStocksWithImages()
  console.log("\n=== statistics-api v1 ===");

  try {
    const result = await httpsGet('statistics-api.wildberries.ru', '/api/v1/supplier/stocks?dateFrom=2019-06-20', headers);
    console.log(`Status: ${result.status}`);

    if (Array.isArray(result.data)) {
      console.log(`Is array: true, length: ${result.data.length}`);

      const found = result.data.find(s => s.supplierArticle === ARTICLE);
      if (found) {
        console.log(`\n✅ Found ${ARTICLE}:`, JSON.stringify(found));
        console.log(`\n   Quantity: ${found.quantity}`);
      } else {
        console.log(`\n❌ NOT found ${ARTICLE}`);
        console.log(`\nFirst 5 items:`, result.data.slice(0, 5).map(s => ({
          article: s.supplierArticle,
          qty: s.quantity,
          nmId: s.nmId
        })));
      }
    } else {
      console.log(`Keys:`, Object.keys(result.data));
      const jsonStr = JSON.stringify(result.data, null, 2);
      console.log(`\nResponse:\n${jsonStr.substring(0, 500)}`);
    }
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }
}

test();
