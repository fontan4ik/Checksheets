/**
 * ТЕСТ WB STOCKS ENDPOINTS
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

const headers = { 'Authorization': `Bearer ${WB_TOKEN}` };

console.log("╔════════════════════════════════════════════════════════════════════════╗");
console.log("║   ТЕСТ WB STOCKS ENDPOINTS                                          ║");
console.log("╚════════════════════════════════════════════════════════════════════════╝");

async function testAll() {
  // ============================================
  // 1. statistics-api v1
  // ============================================
  console.log("\n=== 1. statistics-api v1 ===");
  try {
    const result = await httpsGet('statistics-api.wildberries.ru', '/api/v1/supplier/stocks', headers);
    console.log(`Status: ${result.status}`);
    if (Array.isArray(result.data)) {
      console.log(`Is array: true, length: ${result.data.length}`);
      const found = result.data.find(s => s.supplierArticle === ARTICLE);
      if (found) {
        console.log(`✅ Found ${ARTICLE}:`, JSON.stringify(found));
      } else {
        console.log(`❌ NOT found ${ARTICLE}`);
        if (result.data.length > 0) {
          console.log(`First item:`, JSON.stringify(result.data[0]));
        }
      }
    }
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }

  // ============================================
  // 2. Analytics API v2
  // ============================================
  console.log("\n=== 2. Analytics API v2 ===");
  try {
    const body = {
      "skip": 0,
      "take": 1000,
      "orderBy": [
        {
          "field": "stocks",
          "sortOrder": "Desc"
        }
      ]
    };

    const result = await httpsPost('seller-analytics-api.wildberries.ru', '/api/v2/stocks-report/products/products', headers, body);
    console.log(`Status: ${result.status}`);

    if (result.data.data && Array.isArray(result.data.data)) {
      console.log(`Has data.data: true, length: ${result.data.data.length}`);
      const found = result.data.data.find(d => d.supplierArticle === ARTICLE);
      if (found) {
        console.log(`✅ Found ${ARTICLE}:`, JSON.stringify(found));
      } else {
        console.log(`❌ NOT found ${ARTICLE}`);
        if (result.data.data.length > 0) {
          console.log(`First item:`, JSON.stringify(result.data.data[0]));
        }
      }
    } else {
      console.log(`Keys:`, Object.keys(result.data));
      console.log(`Response:`, JSON.stringify(result.data).substring(0, 500));
    }
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }

  // ============================================
  // 3. content-api (card details)
  // ============================================
  console.log("\n=== 3. content-api (card details) ===");
  try {
    const body = {
      "settings": {
        "cursor": { "limit": 100 },
        "filter": { "withOrder": true, "text": ARTICLE }
      },
      "sort": { "supplySort": "ASC" }
    };

    const result = await httpsPost('content-api.wildberries.ru', '/api/v2/supplier/card/list', headers, body);
    console.log(`Status: ${result.status}`);

    if (result.data.cards && result.data.cards.length > 0) {
      const card = result.data.cards[0];
      console.log(`nmId: ${card.nmId}`);

      if (card.nmId) {
        // Попробуем получить детальную информацию по карточке
        console.log(`\n--- Попробуем получить детали по nmId=${card.nmId} ---`);
        const detailResult = await httpsGet('content-api.wildberries.ru', `/public/api/v1/info/card/${card.nmId}`, {});
        console.log(`Detail Status: ${detailResult.status}`);
        console.log(`Detail Keys:`, Object.keys(detailResult.data));

        if (detailResult.data.nomenclatures) {
          const nom = detailResult.data.nomenclatures[0];
          console.log(`\n✅ Nomenclature:`, JSON.stringify(nom, null, 2).substring(0, 500));
        }
      }
    }
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }
}

testAll();
