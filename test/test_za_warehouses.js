/**
 * ТЕСТ СКЛАДОВ Z (26) И AA (27)
 * Проверяет фильтрацию по warehouseName для ФЕРОН МОСКВА и ВОЛЬТМИР
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
  console.log("║   ТЕСТ СКЛАДОВ Z (26) И AA (27)                                       ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const headers = { 'Authorization': `Bearer ${WB_TOKEN}` };

  // Фильтры
  const warehouseFilters = {
    Z:  {
      column: 26,
      name: "ФЕРОН МОСКВА",
      description: "Москва (Подольск 3)",
      filter: (name) => name.includes("Подольск 3")
    },
    AA: {
      column: 27,
      name: "ВОЛЬТМИР",
      description: "ул. Индустриальная,1Бк9, с.Преображенка",
      filter: (name) => name.includes("Индустриальная")
    }
  };

  console.log("\n=== ШАГ 1: Получение остатков ===");

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

    // Фильтруем для тестового артикула
    const articleStocks = allStocks.filter(s => s.supplierArticle === TEST_ARTICLE);
    console.log(`Записей для ${TEST_ARTICLE}: ${articleStocks.length}`);

    if (articleStocks.length === 0) {
      console.log(`❌ Артикул ${TEST_ARTICLE} не найден`);
      return;
    }

    console.log("\n=== ШАГ 2: Все склады для 22068-1 ===");

    articleStocks.forEach(stock => {
      console.log(`   [${stock.warehouseId}] ${stock.warehouseName}: ${stock.quantity} шт.`);
    });

    console.log("\n=== ШАГ 3: Применение фильтров ===");

    const results = {};

    // Инициализация
    Object.keys(warehouseFilters).forEach(key => {
      results[key] = 0;
    });

    // Применяем фильтры
    articleStocks.forEach(stock => {
      const whName = stock.warehouseName || "";
      const qty = stock.quantity || 0;

      Object.entries(warehouseFilters).forEach(([key, config]) => {
        if (config.filter(whName)) {
          results[key] += qty;
          console.log(`   ✓ "${whName}"`);
          console.log(`     Совпадает с ${config.name} (${config.column}): +${qty}`);
        }
      });
    });

    console.log("\n=== ШАГ 4: Результаты ===");

    Object.entries(warehouseFilters).forEach(([key, config]) => {
      const qty = results[key];
      console.log(`\n${config.column}: ${config.name}`);
      console.log(`   Фильтр: ${config.description}`);
      console.log(`   Quantity: ${qty}`);
      console.log(`   ${qty > 0 ? '✅' : '⚠️ '}  ${qty > 0 ? 'Есть остатки' : 'Нет остатков'}`);
    });

    console.log("\n=== ШАГ 5: Проверка других товаров ===");

    // Показать первые 5 других артикулов
    const uniqueArticles = [...new Set(allStocks.map(s => s.supplierArticle))].slice(0, 5);

    console.log(`\nПервые 5 артикулов:`);

    for (const article of uniqueArticles) {
      const stocks = allStocks.filter(s => s.supplierArticle === article);

      const zQty = stocks.reduce((sum, s) => {
        const name = s.warehouseName || "";
        return warehouseFilters.Z.filter(name) ? sum + s.quantity : sum;
      }, 0);

      const aaQty = stocks.reduce((sum, s) => {
        const name = s.warehouseName || "";
        return warehouseFilters.AA.filter(name) ? sum + s.quantity : sum;
      }, 0);

      console.log(`\n   ${article}:`);
      console.log(`      Z (26): ${zQty}`);
      console.log(`      AA (27): ${aaQty}`);
    }

    console.log("\n✅ Тест завершен");

  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }
}

test();
