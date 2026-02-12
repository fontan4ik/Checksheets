/**
 * ДИАГНОСТИКА ПРОБЛЕМНЫХ API
 */

const https = require('https');
const fs = require('fs');

const OZON_CLIENT_ID = '142355';
const OZON_API_KEY = 'fe539630-170b-4b48-b222-8ba092907a63';
const WB_TOKEN = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg1ODgzMjc3LCJpZCI6IjAxOWMyMzE3LWEyZTMtNzQ2NC1iZTY3LTY3ZDNlMGY4YWNlMSIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.XsB0AXxVxUo13JxstFFAtQXxUqE-MjtP02FnX08uyhh3MGUxfFdm5hgVvcHRFOR-aiv1CeDegedqNJ1k5u8wPw';

const ARTICLE = '22068-1';
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

async function main() {
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ДИАГНОСТИКА ПРОБЛЕМНЫХ API                                          ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const ozonHeaders = {
    'Client-Id': OZON_CLIENT_ID,
    'Api-Key': OZON_API_KEY
  };

  // ============================================
  // 1. OZON STOCKS FBO
  // ============================================
  console.log("\n=== 1. OZON STOCKS FBO ===");
  try {
    const result = await httpsPost('api-seller.ozon.ru', '/v4/product/info/stocks', ozonHeaders, {
      filter: { sku: [parseInt(SKU)] },
      limit: 1000
    });

    console.log(`Status: ${result.status}`);
    fs.writeFileSync('diag_ozon_stocks_fbo.json', JSON.stringify(result.data, null, 2));

    if (result.data.result) {
      console.log(`Has result: ${!!result.data.result}`);
      console.log(`Has rows: ${!!result.data.result.rows}`);
      if (result.data.result.rows) {
        console.log(`Rows count: ${result.data.result.rows.length}`);
        if (result.data.result.rows.length > 0) {
          console.log(`First row:`, JSON.stringify(result.data.result.rows[0]).substring(0, 200));
        }
      }
    }
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }

  // ============================================
  // 2. OZON STOCKS FBS
  // ============================================
  console.log("\n=== 2. OZON STOCKS FBS ===");
  try {
    const result = await httpsPost('api-seller.ozon.ru', '/v1/product/info/stocks-by-warehouse/fbs', ozonHeaders, {
      sku: [parseInt(SKU)],
      warehouse_type: "FBS"
    });

    console.log(`Status: ${result.status}`);
    fs.writeFileSync('diag_ozon_stocks_fbs.json', JSON.stringify(result.data, null, 2));

    if (result.data.result) {
      console.log(`Has result: ${!!result.data.result}`);
      console.log(`Has rows: ${!!result.data.result.rows}`);
      if (result.data.result.rows) {
        console.log(`Rows count: ${result.data.result.rows.length}`);
        if (result.data.result.rows.length > 0) {
          console.log(`First row:`, JSON.stringify(result.data.result.rows[0]).substring(0, 200));
        }
      }
    }
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }

  // ============================================
  // 3. WB ANALYTICS
  // ============================================
  console.log("\n=== 3. WB ANALYTICS ===");

  const today = new Date('2026-02-04');
  const dateFromMonth = new Date(today.getFullYear(), today.getMonth() - 1, 3);

  const formatDateISO = (d) => {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}T00:00:00.000Z`;
  };

  const pathMonth = `/api/v2/supplier/analytics?dateFrom=${formatDateISO(dateFromMonth)}&dateTo=${formatDateISO(today)}&key=supplierArticle&limit=1000&offset=0`;
  console.log(`URL: ${pathMonth}`);

  try {
    const result = await httpsGet('statistics-api.wildberries.ru', pathMonth, {
      'Authorization': `Bearer ${WB_TOKEN}`
    });

    console.log(`Status: ${result.status}`);
    fs.writeFileSync('diag_wb_analytics.json', JSON.stringify(result.data, null, 2));

    if (result.data.result) {
      console.log(`Has result: ${!!result.data.result}`);
      console.log(`Is array: ${Array.isArray(result.data.result)}`);
      console.log(`Result length: ${result.data.result.length || 0}`);

      if (Array.isArray(result.data.result)) {
        const found = result.data.result.find(r => r.supplierArticle === ARTICLE);
        if (found) {
          console.log(`✅ Found ${ARTICLE}:`, JSON.stringify(found));
        } else {
          console.log(`❌ NOT found ${ARTICLE}`);
          console.log(`First 3 items:`, result.data.result.slice(0, 3).map(r => ({ article: r.supplierArticle, orders: r.ordersCount })));
        }
      }
    }
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }

  // ============================================
  // 4. WB STOCKS
  // ============================================
  console.log("\n=== 4. WB STOCKS ===");
  try {
    const result = await httpsGet('statistics-api.wildberries.ru', '/api/v2/supplier/stocks', {
      'Authorization': `Bearer ${WB_TOKEN}`
    });

    console.log(`Status: ${result.status}`);
    fs.writeFileSync('diag_wb_stocks.json', JSON.stringify(result.data, null, 2));

    if (Array.isArray(result.data)) {
      console.log(`Is array: true`);
      console.log(`Data length: ${result.data.length}`);

      const found = result.data.find(s => s.supplierArticle === ARTICLE);
      if (found) {
        console.log(`✅ Found ${ARTICLE}:`, JSON.stringify(found));
      } else {
        console.log(`❌ NOT found ${ARTICLE}`);
        console.log(`First 3 items:`, result.data.slice(0, 3).map(s => ({ article: s.supplierArticle, qty: s.quantity })));
      }
    }
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }

  // ============================================
  // 5. WB PRICE
  // ============================================
  console.log("\n=== 5. WB PRICE (content-api) ===");
  try {
    const body = {
      numpyKey: "catalog",
      settings: {
        cursor: { limit: 100 },
        filter: { withOrder: true, text: ARTICLE }
      },
      sort: { supplySort: "ASC" }
    };

    const result = await httpsPost('content-api.wildberries.ru', '/api/v2/supplier/card/list', {
      'Authorization': `Bearer ${WB_TOKEN}`
    }, body);

    console.log(`Status: ${result.status}`);
    fs.writeFileSync('diag_wb_price.json', JSON.stringify(result.data, null, 2));

    if (result.data.cards) {
      console.log(`Has cards: ${!!result.data.cards}`);
      console.log(`Cards length: ${result.data.cards.length}`);

      if (result.data.cards.length > 0) {
        const card = result.data.cards[0];
        console.log(`First card nmId: ${card.nmId}`);
        console.log(`First card has sizes: ${!!card.sizes}`);
        if (card.sizes) {
          console.log(`Sizes count: ${card.sizes.length}`);
          if (card.sizes.length > 0) {
            console.log(`First size:`, JSON.stringify(card.sizes[0]));
          }
        }
      }
    }
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }

  console.log("\n✅ Все диагностические данные сохранены в файлы diag_*.json");
}

main();
