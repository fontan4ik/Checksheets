/**
 * ТЕСТ FBS СКЛАДОВ ПРОДАВЦА
 * Проверяет marketplace-api для получения остатков на FBS складах
 */

const https = require('https');

// Нужен API ключ для marketplace-api (не statistics-api!)
const WB_MARKETPLACE_TOKEN = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg1ODgzMjc3LCJpZCI6IjAxOWMyMzE3LWEyZTMtNzQ2NC1iZTY3LTY3ZDNlMGY4YWNlMSIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.XsB0AXxVxUo13JxstFFAtQXxUqE-MjtP02FnX08uyhh3MGUxfFdm5hgVvcHRFOR-aiv1CeDegedqNJ1k5u8wPw';

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
  console.log("║   ТЕСТ FBS СКЛАДОВ ПРОДАВЦА (marketplace-api)                         ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const headers = {
    'Authorization': WB_MARKETPLACE_TOKEN,
    'Content-Type': 'application/json'
  };

  // Целевые склады
  const targetWarehouses = {
    Z: { column: 26, name: "ФЕРОН МОСКВА", search: ["ФЕРОН", "МОСКВА"] },
    AA: { column: 27, name: "ВольтМир", search: ["ВольтМир", "ВОЛЬТМИР"] }
  };

  console.log("\n=== ШАГ 1: Получение списка FBS складов ===");

  try {
    const whResult = await httpsGet(
      'marketplace-api.wildberries.ru',
      '/api/v3/warehouses',
      headers
    );

    console.log(`Status: ${whResult.status}`);

    if (!Array.isArray(whResult.data)) {
      console.log(`❌ Ответ не является массивом`);
      console.log(`Ответ: ${JSON.stringify(whResult.data).substring(0, 500)}`);

      // Проверяем на ошибку авторизации
      if (whResult.status === 401 || whResult.status === 403) {
        console.log(`\n⚠️  Ошибка авторизации!`);
        console.log(`Вероятно используется токен от statistics-api`);
        console.log(`Для marketplace-api нужен другой токен!`);
      }
      return;
    }

    const warehouses = whResult.data;
    console.log(`✅ Получено складов: ${warehouses.length}`);

    console.log("\n=== ШАГ 2: Поиск целевых складов ===");

    const foundWarehouses = {};

    Object.entries(targetWarehouses).forEach(([key, config]) => {
      console.log(`\n${config.column}: ${config.name}`);
      console.log(`   Поиск: ${config.search.join(" + ")}`);

      const found = warehouses.find(wh => {
        const name = (wh.name || "").toUpperCase();
        return config.search.every(term => name.includes(term.toUpperCase()));
      });

      if (found) {
        foundWarehouses[key] = {
          id: found.id,
          name: found.name,
          officeId: found.officeId,
          isFbs: found.isFbs
        };
        console.log(`   ✅ Найден: ID=${found.id}, Name="${found.name}"`);
        if (found.officeId) console.log(`      officeId: ${found.officeId}`);
      } else {
        console.log(`   ❌ Не найден`);
      }
    });

    // Показываем все доступные склады
    console.log("\n=== ШАГ 3: Все доступные FBS склады ===");

    warehouses.forEach((wh, i) => {
      const fbsType = wh.isFbs ? 'FBS' : 'DD';
      console.log(`${(i + 1).toString().padStart(2)}. [${fbsType}] "${wh.name}" (ID: ${wh.id})`);
    });

    // Если нашли склады, проверяем остатки
    const foundCount = Object.keys(foundWarehouses).length;

    if (foundCount > 0) {
      console.log("\n=== ШАГ 4: Получение остатков ===");

      const testSkus = ["22068-1", "23348-1", "25841-5"];

      for (const [key, wh] of Object.entries(foundWarehouses)) {
        const config = targetWarehouses[key];

        console.log(`\n${config.column}: ${config.name} (ID: ${wh.id})`);

        try {
          const stockResult = await httpsPost(
            'marketplace-api.wildberries.ru',
            `/api/v3/stocks/${wh.id}`,
            headers,
            { skus: testSkus }
          );

          console.log(`   Status: ${stockResult.status}`);

          if (Array.isArray(stockResult.data)) {
            console.log(`   Получено записей: ${stockResult.data.length}`);

            stockResult.data.forEach(item => {
              console.log(`      ${item.sku}: ${item.amount} шт.`);
            });
          } else {
            console.log(`   ⚠️  Неверный формат ответа`);
          }

        } catch (e) {
          console.log(`   ❌ Ошибка: ${e.message}`);
        }
      }
    }

    console.log("\n=== ИТОГ ===");

    console.log(`\nНайдено складов: ${foundCount} из ${Object.keys(targetWarehouses).length}`);

    Object.entries(targetWarehouses).forEach(([key, config]) => {
      const found = foundWarehouses[key];
      console.log(`${config.column}: ${config.name} - ${found ? '✅' : '❌'} ${found ? `ID=${found.id}` : 'не найден'}`);
    });

    console.log("\n✅ Тест завершен");

  } catch (e) {
    console.error(`\n❌ Ошибка: ${e.message}`);
  }
}

test();
