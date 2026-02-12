/**
 * ТЕСТ: Проверка marketplace-api с большим количеством SKU
 */

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
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ТЕСТ MARKETPLACE-API - БОЛЬШОЙ ЗАПРОС                                 ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const warehouseId = 1449484; // ФБС ФЕРОН МОСКВА

  console.log(`\n=== ШАГ 1: Получение списка СКЛАДОВ ===`);

  const headers1 = { 'Authorization': WB_TOKEN };

  try {
    const whResult = await httpsGet(
      'marketplace-api.wildberries.ru',
      '/api/v3/warehouses',
      headers1
    );

    console.log(`Status: ${whResult.status}`);

    if (Array.isArray(whResult.data)) {
      console.log(`✅ Складов получено: ${whResult.data.length}`);

      // Находим нужный склад
      const targetWh = whResult.data.find(wh => wh.id === warehouseId);

      if (targetWh) {
        console.log(`\n=== ШАГ 2: Склад "${targetWh.name}" (ID: ${warehouseId}) ===`);

        // Генерируем много SKU для теста
        const testSkus = [];
        for (let i = 1; i <= 500; i++) {
          testSkus.push(`${i}`);
        }
        testSkus.push("22068-1", "23348-1", "25841-5", "39171-1");

        console.log(`Отправляем SKU: ${testSkus.length} шт.`);
        console.log(`Примеры: ${testSkus.slice(0, 10).join(", ")} ...`);

        const headers2 = {
          'Authorization': WB_TOKEN,
          'Content-Type': 'application/json'
        };

        const stockResult = await httpsPost(
          'marketplace-api.wildberries.ru',
          `/api/v3/stocks/${warehouseId}`,
          headers2,
          { skus: testSkus }
        );

        console.log(`\nStatus: ${stockResult.status}`);
        console.log(`\nОтвет:`);
        console.log(JSON.stringify(stockResult.data, null, 2));

        if (stockResult.data.stocks && Array.isArray(stockResult.data.stocks)) {
          const stocks = stockResult.data.stocks;
          console.log(`\nЗаписей в stocks: ${stocks.length}`);

          if (stocks.length > 0) {
            console.log(`\n✅ ЕСТЬ ДАННЫЕ!`);
            console.log(`\nПервые 10 записей:`);
            stocks.slice(0, 10).forEach((item, i) => {
              console.log(`   ${i + 1}. sku: ${item.sku}, amount: ${item.amount}`);
            });
          } else {
            console.log(`\n⚠️  Пустой массив - товаров нет на складе`);
          }
        }

      } else {
        console.log(`❌ Склад ${warehouseId} не найден`);
      }

    } else {
      console.log(`❌ Неверный формат ответа складов`);
    }

  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }
}

test();
