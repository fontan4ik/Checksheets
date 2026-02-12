/**
 * ТЕСТ WB MARKETPLACE API (с skus)
 */

const https = require('https');

const WB_TOKEN = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg1ODgzMjc3LCJpZCI6IjAxOWMyMzE3LWEyZTMtNzQ2NC1iZTY3LTY3ZDNlMGY4YWNlMSIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.XsB0AXxVxUo13JxstFFAtQXxUqE-MjtP02FnX08uyhh3MGUxfFdm5hgVvcHRFOR-aiv1CeDegedqNJ1k5u8wPw';

const ARTICLE = '22068-1';

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

async function test() {
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ТЕСТ WB MARKETPLACE API (skus)                                  ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const headers = { 'Authorization': `Bearer ${WB_TOKEN}` };

  // Тестируем warehouse 1449484 (ФБО)
  console.log(`\n=== Warehouse 1449484 (ФБО O, 15) ===`);

  try {
    const result = await httpsPost('marketplace-api.wildberries.ru', '/api/v3/stocks/1449484', headers, {
      skus: [ARTICLE]
    });

    console.log(`Status: ${result.status}`);

    if (result.data.stocks && Array.isArray(result.data.stocks)) {
      console.log(`Has stocks array: true, length: ${result.data.stocks.length}`);

      const found = result.data.stocks.find(s => s.supplierArticle === ARTICLE);
      if (found) {
        console.log(`✅ Found ${ARTICLE}:`, JSON.stringify(found));
        console.log(`   Quantity: ${found.amount || found.quantity}`);
      } else {
        console.log(`❌ NOT found ${ARTICLE}`);
        if (result.data.stocks.length > 0) {
          console.log(`First 3 items:`, result.data.stocks.slice(0, 3).map(s => ({
            article: s.supplierArticle,
            amount: s.amount || s.quantity
          })));
        }
      }
    } else {
      console.log(`Keys:`, Object.keys(result.data));
      const jsonStr = JSON.stringify(result.data, null, 2);
      console.log(`Response:\n${jsonStr.substring(0, 800)}`);
    }
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }

  // Тестируем warehouse 798761 (ФБС)
  console.log(`\n=== Warehouse 798761 (ФБС P, 16) ===`);

  try {
    const result = await httpsPost('marketplace-api.wildberries.ru', '/api/v3/stocks/798761', headers, {
      skus: [ARTICLE]
    });

    console.log(`Status: ${result.status}`);

    if (result.data.stocks && Array.isArray(result.data.stocks)) {
      console.log(`Has stocks array: true, length: ${result.data.stocks.length}`);

      const found = result.data.stocks.find(s => s.supplierArticle === ARTICLE);
      if (found) {
        console.log(`✅ Found ${ARTICLE}:`, JSON.stringify(found));
        console.log(`   Quantity: ${found.amount || found.quantity}`);
      } else {
        console.log(`❌ NOT found ${ARTICLE}`);
      }
    } else {
      console.log(`Keys:`, Object.keys(result.data));
      const jsonStr = JSON.stringify(result.data, null, 2);
      console.log(`Response:\n${jsonStr.substring(0, 800)}`);
    }
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }
}

test();
