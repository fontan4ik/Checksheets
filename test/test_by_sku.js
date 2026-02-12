/**
 * ТЕСТ через SKU вместо offer_id
 * Используем известный SKU: 301854987
 */

const https = require('https');

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

function formatDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

async function main() {
  console.log("=== ТЕСТ ЧЕРЕЗ SKU ===");
  console.log(`SKU: ${SKU}`);

  const headers = {
    'Client-Id': OZON_CLIENT_ID,
    'Api-Key': OZON_API_KEY
  };

  // 1. Попробуем получить product info через SKU
  console.log("\n=== 1. PRODUCT INFO (через filter SKU) ===");
  try {
    const body = {
      filter: { sku: SKU }
    };
    console.log(`Request body: ${JSON.stringify(body)}`);
    const result = await httpsPost('api-seller.ozon.ru', '/v3/product/info/list', headers, body);
    console.log(`Status: ${result.status}`);
    console.log(JSON.stringify(result.data, null, 2).substring(0, 500));

    if (result.data.result && result.data.result.items && result.data.result.items.length > 0) {
      const item = result.data.result.items[0];
      console.log(`✅ НАЙДЕНО:`);
      console.log(`   offer_id: ${item.offer_id}`);
      console.log(`   product_id: ${item.product_id}`);
      console.log(`   sku: ${item.sku}`);

      // Сохраняем для следующих запросов
      var productId = item.product_id;
      var offerId = item.offer_id;
    } else {
      console.log(`❌ Не найдено`);
      return;
    }
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
    return;
  }

  // 2. Analytics
  console.log("\n=== 2. ANALYTICS (по SKU) ===");
  const today = new Date('2026-02-04');
  const dateFromMonth = new Date(today.getFullYear(), today.getMonth() - 1, 3);

  try {
    const result = await httpsPost('api-seller.ozon.ru', '/v1/analytics/data', headers, {
      date_from: formatDate(dateFromMonth),
      date_to: formatDate(today),
      metrics: ["ordered_units", "revenue"],
      dimension: ["sku"],
      limit: 1000,
      offset: 0
    });
    console.log(`Status: ${result.status}`);

    if (result.data.result && result.data.result.data) {
      const skuData = result.data.result.data.find(d => d.dimensions[0].id.toString() === SKU.toString());
      if (skuData) {
        console.log(`✅ ДАННЫЕ:`);
        console.log(`   ordered_units: ${skuData.metrics[0]} (ожидается 1252)`);
        console.log(`   revenue: ${Math.round(skuData.metrics[1])} (ожидается 1816419)`);
      } else {
        console.log(`❌ SKU ${SKU} не найден в analytics`);
        console.log(`   Всего записей: ${result.data.result.data.length}`);
      }
    }
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }

  // 3. Stocks (FBO)
  console.log("\n=== 3. STOCKS FBO ===");
  try {
    const result = await httpsPost('api-seller.ozon.ru', '/v4/product/info/stocks', headers, {
      filter: { sku: [parseInt(SKU)] },
      limit: 1000
    });
    console.log(`Status: ${result.status}`);

    if (result.data.result && result.data.result.rows) {
      let fboStock = 0;
      result.data.result.rows.forEach(row => {
        const amount = row.stocks?.[0]?.available || 0;
        fboStock += amount;
      });
      console.log(`✅ FBO Stock: ${fboStock} (ожидается 1069)`);
    }
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }

  // 4. Stocks (FBS)
  console.log("\n=== 4. STOCKS FBS ===");
  try {
    const result = await httpsPost('api-seller.ozon.ru', '/v1/product/info/stocks-by-warehouse/fbs', headers, {
      sku: [parseInt(SKU)],
      warehouse_type: "FBS"
    });
    console.log(`Status: ${result.status}`);

    if (result.data.result && result.data.result.rows) {
      let fbsStock = 0;
      let moscowStock = 0;

      result.data.result.rows.forEach(row => {
        const wh = row.warehouse_name || "";
        const amount = row.amount || 0;

        if (wh.includes('Москва') || wh.includes('МСК') || wh.includes('Electro')) {
          moscowStock += amount;
        } else {
          fbsStock += amount;
        }
      });

      console.log(`✅ FBS Stock: ${fbsStock} (ожидается 527)`);
      console.log(`✅ Moscow FBS: ${moscowStock} (ожидается 0)`);
    }
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }

  // 5. Price
  console.log("\n=== 5. PRICE ===");
  try {
    const result = await httpsPost('api-seller.ozon.ru', '/v5/product/info/prices', headers, {
      filter: {
        product_id: [productId],
        currency_code: "RUB"
      },
      limit: 1000
    });
    console.log(`Status: ${result.status}`);

    if (result.data.result && result.data.result.items && result.data.result.items.length > 0) {
      const item = result.data.result.items[0];
      const price = Math.round(item.price?.price || 0);
      console.log(`✅ Price: ${price} (ожидается 1480)`);
    }
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }

  // 6. Attributes (brand, model, image)
  console.log("\n=== 6. ATTRIBUTES ===");
  try {
    const result = await httpsPost('api-seller.ozon.ru', '/v4/product/info/attributes', headers, {
      filter: { offer_id: [offerId] },
      limit: 1
    });
    console.log(`Status: ${result.status}`);

    if (result.data.result && result.data.result.length > 0) {
      const item = result.data.result[0];

      const extractAttribute = (item, attrId) => {
        const attr = item.attributes?.find(a => a.id === attrId);
        return attr?.values[0]?.value || "";
      };

      const brand = extractAttribute(item, 85);
      const model = extractAttribute(item, 9048);
      const image = item.images?.[0] || "";

      console.log(`✅ Brand: ${brand} (ожидается Feron)`);
      console.log(`✅ Model: ${model} (ожидается SEN30_220 или 22068)`);
      console.log(`✅ Image: ${image ? 'Есть' : 'Нет'}`);
    }
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }
}

main();
