const https = require('https');

const WB_MARKETPLACE_TOKEN = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg1ODgzMjc3LCJpZCI6IjAxOWMyMzE3LWEyZTMtNzQ2NC1iZTY3LTY3ZDNlMGY4YWNlMSIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.XsB0AXxVxUo13JxstFFAtQXxUqE-MjtP02FnX08uyhh3MGUxfFdm5hgVvcHRFOR-aiv1CeDegedqNJ1k5u8wPw';

function httpsPost(hostname, path, headers, body) {
  return new Promise((resolve, reject) => {
    const options = { hostname, path, method: 'POST', headers };
    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          resolve({ status: res.statusCode, data: JSON.parse(data) });
        } catch (e) {
          resolve({ status: res.statusCode, data: data });
        }
      });
    });
    req.on('error', reject);
    req.write(JSON.stringify(body));
    req.end();
  });
}

async function test() {
  console.log("TEST FBS WAREHOUSE");

  const headers = {
    'Authorization': WB_MARKETPLACE_TOKEN,
    'Content-Type': 'application/json'
  };

  // 1. Проверка с barcode
  console.log("\n=== TEST 1: With barcode ===");

  const result1 = await httpsPost(
    'marketplace-api.wildberries.ru',
    '/api/v3/stocks/1449484',
    headers,
    { skus: ["4603730223348"] }
  );

  console.log("Status:", result1.status);
  console.log("Response:", JSON.stringify(result1.data, null, 2));

  // 2. Проверка с nmId
  console.log("\n=== TEST 2: With nmId ===");

  const result2 = await httpsPost(
    'marketplace-api.wildberries.ru',
    '/api/v3/stocks/1449484',
    headers,
    { skus: ["216675685"] }
  );

  console.log("Status:", result2.status);
  console.log("Response:", JSON.stringify(result2.data, null, 2));

  // 3. Проверка с supplierArticle
  console.log("\n=== TEST 3: With supplierArticle ===");

  const result3 = await httpsPost(
    'marketplace-api.wildberries.ru',
    '/api/v3/stocks/1449484',
    headers,
    { skus: ["22068-1"] }
  );

  console.log("Status:", result3.status);
  console.log("Response:", JSON.stringify(result3.data, null, 2));
}

test().catch(e => console.error("Error:", e));
