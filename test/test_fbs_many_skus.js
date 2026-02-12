/**
 * ТЕСТ ФБС С БОЛЬШИМ СПИСКОМ SKU
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
        try {
          const jsonData = JSON.parse(data);
          resolve({ status: res.statusCode, data: jsonData });
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
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ТЕСТ ФБС - БОЛЬШОЙ СПИСОК SKU                                        ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const headers = {
    'Authorization': WB_MARKETPLACE_TOKEN,
    'Content-Type': 'application/json'
  };

  const warehouseId = 1449484; // ФБС ФЕРОН МОСКВА

  // Пробуем много SKU
  const testSkus = [
    "22068-1", "22068-2", "22068-5",
    "23348-1", "23348-2", "23348-5",
    "25841-5",
    "39171-1", "32474-1", "41370-1"
  ];

  console.log(`\n=== ЗАПРОС К СКЛАДУ ${warehouseId} ===`);
  console.log(`SKU (${testSkus.length} шт.): ${testSkus.join(", ")}`);

  try {
    const result = await httpsPost(
      'marketplace-api.wildberries.ru',
      `/api/v3/stocks/${warehouseId}`,
      headers,
      { skus: testSkus }
    );

    console.log(`\nStatus: ${result.status}`);
    console.log(`\nОтвет:`);
    console.log(JSON.stringify(result.data, null, 2));

    if (result.data.stocks && Array.isArray(result.data.stocks)) {
      console.log(`\nЗаписей: ${result.data.stocks.length}`);

      if (result.data.stocks.length > 0) {
        console.log("\n✅ НАЙДЕНЫ ОСТАТКИ:");
        result.data.stocks.forEach(item => {
          console.log(`   ${item.sku}: ${item.amount} шт.`);
        });
      } else {
        console.log("\n❌ Пустой массив - нет остатков для этих SKU");
        console.log("\nВозможные причины:");
        console.log("1. Товаров нет на этом складе");
        console.log("2. Неверный формат SKU (нужен barcode?)");
        console.log("3. Склад не содержит эти товары");
      }
    }

  } catch (e) {
    console.error(`\n❌ Ошибка: ${e.message}`);
  }

  console.log("\n=== ПРОВЕРКА: Возможно нужен barcode? ===");

  // Пробуем с баркодами (если знаем)
  // Баркоды обычно имеют формат "0460..."
  const testBarcodes = [
    "4603730223348" // пример баркода
  ];

  console.log("\nЕсли нужны barcodes, нужно получить их из:");
  console.log("1. statistics-api /api/v1/supplier/stocks (там есть поле barcode)");
  console.log("2. marketplace-api /api/v2/list/goods/filter");

  console.log("\nПроверим statistics-api для получения баркодов...");

  const httpsGet = (hostname, path, headers) => {
    return new Promise((resolve, reject) => {
      const options = { hostname, path, method: 'GET', headers };
      const req = https.request(options, (res) => {
        let data = '';
        res.on('data', (chunk) => { data += chunk; });
        res.on('end', () => {
          try {
            resolve(JSON.parse(data));
          } catch (e) {
            resolve(data);
          }
        });
      });
      req.on('error', reject);
      req.end();
    });
  };

  const statsHeaders = { 'Authorization': `Bearer ${WB_MARKETPLACE_TOKEN}` };

  try {
    const stocks = await httpsGet(
      'statistics-api.wildberries.ru',
      '/api/v1/supplier/stocks?dateFrom=2019-06-20',
      statsHeaders
    );

    if (Array.isArray(stocks)) {
      // Ищем 22068-1
      const item = stocks.find(s => s.supplierArticle === "22068-1");

      if (item) {
        console.log("\n✅ Товар 22068-1 найден в statistics-api:");
        console.log(`   supplierArticle: ${item.supplierArticle}`);
        console.log(`   barcode: ${item.barcode}`);
        console.log(`   nmId: ${item.nmId}`);
        console.log(`   quantity: ${item.quantity}`);
        console.log("\nПопробуем использовать barcode в FBS API...");

        const barcodeResult = await httpsPost(
          'marketplace-api.wildberries.ru',
          `/api/v3/stocks/${warehouseId}`,
          headers,
          { skus: [item.barcode] }
        );

        console.log(`\nЗапрос с barcode "${item.barcode}":`);
        console.log(JSON.stringify(barcodeResult.data, null, 2));
      } else {
        console.log("\n❌ Товар 22068-1 не найден в statistics-api");
      }
    }

  } catch (e) {
    console.error(`\nОшибка: ${e.message}`);
  }
}
