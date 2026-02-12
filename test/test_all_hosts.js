const https = require('https');

const WB_TOKEN = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg1ODgzMjc3LCJpZCI6IjAxOWMyMzE3LWEyZTMtNzQ2NC1iZTY3LTY3ZDNlMGY4YWNlMSIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.XsB0AXxVxUo13JxstFFAtQXxUqE-MjtP02FnX08uyhh3MGUxfFdm5hgVvcHRFOR-aiv1CeDegedqNJ1k5u8wPw';

function httpsGet(hostname, path, headers) {
  return new Promise((resolve, reject) => {
    const options = { hostname, path, method: 'GET', headers };
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
    req.end();
  });
}

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
  console.log("TEST ALL WB HOSTS");

  const headers = { 'Authorization': WB_TOKEN };
  const warehouseId = 1449484;
  const testSkus = ["22068-1", "23348-1", "25841-5"];

  const hosts = [
    'marketplace-api.wildberries.ru',
    'suppliers-api.wildberries.ru',
    'statistics-api.wildberries.ru'
  ];

  for (const host of hosts) {
    console.log(`\n=== HOST: ${host} ===`);

    // TEST 1: /api/v3/warehouses
    console.log("TEST 1: GET /api/v3/warehouses");
    try {
      const result = await httpsGet(host, '/api/v3/warehouses', headers);
      console.log(`Status: ${result.status}`);
      if (Array.isArray(result.data)) {
        console.log(`✅ Складов: ${result.data.length}`);
      } else {
        console.log(`Response:`, JSON.stringify(result.data).substring(0, 200));
      }
    } catch (e) {
      console.log(`❌ Error: ${e.message}`);
    }

    // TEST 2: POST /api/v3/stocks/{warehouseId}
    console.log(`\nTEST 2: POST /api/v3/stocks/${warehouseId}`);
    try {
      const result = await httpsPost(host, `/api/v3/stocks/${warehouseId}`, {
        ...headers,
        'Content-Type': 'application/json'
      }, { skus: testSkus });
      console.log(`Status: ${result.status}`);
      console.log(`Response:`, JSON.stringify(result.data));
    } catch (e) {
      console.log(`❌ Error: ${e.message}`);
    }
  }
}

test().catch(e => console.error("Error:", e));
