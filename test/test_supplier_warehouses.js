/**
 * ТЕСТ SUPPLIER API - Склады продавца и остатки
 * Проверяет получение списка складов и остатков по ним
 */

const https = require('https');

const WB_SUPPLIERS_TOKEN = process.env.WB_SUPPLIERS_TOKEN || 'your_token_here';
const TEST_ARTICLE = '22068-1';

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

async function testSupplierWarehouses() {
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ТЕСТ SUPPLIER API - Склады продавца и остатки                         ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const headers = { 'Authorization': WB_SUPPLIERS_TOKEN };

  // Целевые склады
  const targetWarehouses = {
    AB: { column: 28, name: "ФЕРОН ФБС", search: ["ФЕРОН", "ФБС"] },
    AC: { column: 29, name: "ЭТМ САМАРА", search: ["ЭТМ", "САМАРА"] }
  };

  console.log("\n=== ШАГ 1: Получение списка складов ===");

  try {
    const whResult = await httpsGet(
      'suppliers-api.wildberries.ru',
      '/api/v3/warehouses',
      headers
    );

    console.log(`Status: ${whResult.status}`);

    if (!Array.isArray(whResult.data)) {
      console.log("❌ Ответ не является массивом");
      return;
    }

    console.log(`Получено складов: ${whResult.data.length}`);

    console.log("\n=== ШАГ 2: Поиск целевых складов ===");

    const foundWarehouses = {};

    Object.entries(targetWarehouses).forEach(([key, config]) => {
      console.log(`\n${config.column}: ${config.name}`);
      console.log(`   Поиск: ${config.search.join(" + ")}`);

      const found = whResult.data.find(wh => {
        const name = (wh.name || "").toUpperCase();
        return config.search.every(term => name.includes(term.toUpperCase()));
      });

      if (found) {
        foundWarehouses[key] = {
          id: found.id,
          name: found.name,
          type: found.type,
          address: found.address
        };
        console.log(`   ✅ Найден: ID=${found.id}, Name="${found.name}"`);
      } else {
        console.log(`   ❌ Не найден`);
      }
    });

    console.log("\n=== ШАГ 3: Получение остатков по складам ===");

    for (const [key, config] of Object.entries(targetWarehouses)) {
      const wh = foundWarehouses[key];

      if (!wh) {
        console.log(`\n${config.column}: ${config.name}`);
        console.log(`   Пропуск (склад не найден)`);
        continue;
      }

      console.log(`\n${config.column}: ${config.name} (ID: ${wh.id})`);

      try {
        const stocksResult = await httpsPost(
          'suppliers-api.wildberries.ru',
          `/api/v3/stocks/${wh.id}`,
          {
            ...headers,
            'Content-Type': 'application/json'
          },
          { skus: [TEST_ARTICLE] }
        );

        console.log(`   Status: ${stocksResult.status}`);

        if (stocksResult.data.stocks && Array.isArray(stocksResult.data.stocks)) {
          const stocks = stocksResult.data.stocks;

          // Ищем наш артикул
          const articleStock = stocks.find(s => s.supplierArticle === TEST_ARTICLE);

          if (articleStock) {
            console.log(`   ✅ quantity: ${articleStock.amount}`);
          } else {
            console.log(`   ⚠️  Артикул ${TEST_ARTICLE} не найден на складе`);
          }

        } else {
          console.log(`   ❌ Неверный формат ответа`);
          console.log(`   ${JSON.stringify(stocksResult.data).substring(0, 200)}`);
        }

      } catch (e) {
        console.log(`   ❌ Ошибка запроса: ${e.message}`);
      }
    }

    console.log("\n=== ИТОГ ===");

    const foundCount = Object.keys(foundWarehouses).length;
    console.log(`\nНайдено складов: ${foundCount} из ${Object.keys(targetWarehouses).length}`);

    console.log("\nСопоставление с таблицей:");
    console.log(`AB (28): ${foundWarehouses.AB ? '✅ ' + foundWarehouses.AB.name : '❌ Не найден'}`);
    console.log(`AC (29): ${foundWarehouses.AC ? '✅ ' + foundWarehouses.AC.name : '❌ Не найден'}`);

  } catch (e) {
    console.error(`\n❌ Ошибка: ${e.message}`);
  }
}

// Запуск теста
testSupplierWarehouses();
