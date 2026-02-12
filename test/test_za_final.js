/**
 * ФИНАЛЬНЫЙ ТЕСТ Z (26) и AA (27) - Самара и Коледино
 */

const https = require('https');

const WB_TOKEN = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg1ODgzMjc3LCJpZCI6IjAxOWMyMzE3LWEyZTMtNzQ2NC1iZTY3LTY3ZDNlMGY4YWNlMSIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.XsB0AXxVxUo13JxstFFAtQXxUqE-MjtP02FnX08uyhh3MGUxfFdm5hgVvcHRFOR-aiv1CeDegedqNJ1k5u8wPw';

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

async function test() {
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ФИНАЛЬНЫЙ ТЕСТ Z (26) и AA (27)                                      ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const headers = { 'Authorization': `Bearer ${WB_TOKEN}` };

  // Фильтры
  const warehouseFilters = {
    Z:  {
      column: 26,
      name: "Самара",
      description: "Самара (Новосемейкино)",
      filter: (name) => name.includes("Самара (Новосемейкино)")
    },
    AA: {
      column: 27,
      name: "Коледино (Подольск)",
      description: "Коледино",
      filter: (name) => name === "Коледино"
    }
  };

  console.log("\n=== ШАГ 1: Получение всех остатков ===");

  try {
    const result = await httpsGet(
      'statistics-api.wildberries.ru',
      '/api/v1/supplier/stocks?dateFrom=2019-06-20',
      headers
    );

    console.log(`Status: ${result.status}`);

    if (!Array.isArray(result.data)) {
      console.log("❌ Ответ не является массивом");
      return;
    }

    const allStocks = result.data;
    console.log(`Всего записей: ${allStocks.length}`);

    console.log("\n=== ШАГ 2: Анализ складов ===");

    // Агрегируем по складам
    const warehouseStats = {};

    allStocks.forEach(item => {
      const whName = item.warehouseName || "";
      const qty = item.quantity || 0;

      if (!warehouseStats[whName]) {
        warehouseStats[whName] = {
          articleCount: 0,
          totalQty: 0,
          articles: []
        };
      }

      const art = item.supplierArticle;
      if (art && qty > 0) {
        if (!warehouseStats[whName].articles.includes(art)) {
          warehouseStats[whName].articles.push(art);
          warehouseStats[whName].articleCount++;
        }
        warehouseStats[whName].totalQty += qty;
      }
    });

    console.log("\n=== ШАГ 3: Проверка складов ===");

    Object.entries(warehouseFilters).forEach(([key, config]) => {
      console.log(`\n${config.column}: ${config.name}`);
      console.log(`   Фильтр: ${config.description}`);

      const matchingWarehouses = Object.keys(warehouseStats).filter(whName =>
        config.filter(whName)
      );

      if (matchingWarehouses.length > 0) {
        console.log(`   ✅ Найдено складов: ${matchingWarehouses.length}`);
        matchingWarehouses.forEach(wh => {
          const stats = warehouseStats[wh];
          console.log(`      "${wh}"`);
          console.log(`      Товаров: ${stats.articleCount}`);
          console.log(`      Общий quantity: ${stats.totalQty}`);
        });
      } else {
        console.log(`   ❌ Складов не найдено`);
      }
    });

    console.log("\n=== ШАГ 4: Тестовый артикул 22068-1 ===");

    const articleStocks = allStocks.filter(s => s.supplierArticle === TEST_ARTICLE);
    console.log(`Записей для ${TEST_ARTICLE}: ${articleStocks.length}`);

    articleStocks.forEach(stock => {
      console.log(`   [${stock.warehouseId}] "${stock.warehouseName}": ${stock.quantity} шт.`);
    });

    console.log("\n=== ШАГ 5: Результаты для 22068-1 ===");

    const results = {};

    Object.entries(warehouseFilters).forEach(([key, config]) => {
      const matchingStocks = articleStocks.filter(s =>
        config.filter(s.warehouseName || "")
      );

      const totalQty = matchingStocks.reduce((sum, s) => sum + (s.quantity || 0), 0);

      results[key] = {
        warehouseName: matchingStocks.length > 0 ? matchingStocks[0].warehouseName : null,
        quantity: totalQty
      };

      console.log(`\n${config.column}: ${config.name}`);
      console.log(`   Quantity: ${totalQty}`);
      console.log(`   ${totalQty > 0 ? '✅' : '⚠️'}  ${totalQty > 0 ? 'Есть остатки' : 'Нет остатков'}`);
    });

    console.log("\n=== ШАГ 6: Проверка по ВСЕМ товарам ===");

    const stockMap = {};

    Object.keys(warehouseFilters).forEach(key => {
      stockMap[key] = {};
    });

    allStocks.forEach(item => {
      const whName = item.warehouseName || "";
      const art = item.supplierArticle;
      const qty = item.quantity || 0;

      if (!art) return;

      Object.entries(warehouseFilters).forEach(([key, config]) => {
        if (config.filter(whName)) {
          if (!stockMap[key][art]) {
            stockMap[key][art] = 0;
          }
          stockMap[key][art] += qty;
        }
      });
    });

    console.log("\nИтоговая статистика:");

    Object.entries(warehouseFilters).forEach(([key, config]) => {
      const articles = Object.keys(stockMap[key]);
      const totalQty = Object.values(stockMap[key]).reduce((a, b) => a + b, 0);

      console.log(`\n${config.column}: ${config.name}`);
      console.log(`   Товаров с остатками: ${articles.length}`);
      console.log(`   Общий quantity: ${totalQty}`);
    });

    // Показать ТОП-5 товаров по каждому складу
    console.log("\n=== ШАГ 7: ТОП-5 товаров ===");

    Object.entries(warehouseFilters).forEach(([key, config]) => {
      const articles = stockMap[key];

      const sorted = Object.entries(articles)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 5);

      console.log(`\n${config.column}: ${config.name}`);

      if (sorted.length === 0) {
        console.log(`   Нет товаров`);
      } else {
        sorted.forEach(([art, qty], i) => {
          console.log(`   ${i + 1}. ${art}: ${qty} шт.`);
        });
      }
    });

    console.log("\n✅ Тест завершен");

  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }
}

test();
