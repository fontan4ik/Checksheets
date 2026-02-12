/**
 * ТЕСТ: Проверка остатков по складам Z (26) и AA (27)
 * Анализирует ВСЕ товары из API, не только 22068-1
 */

const https = require('https');

const WB_TOKEN = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg1ODgzMjc3LCJpZCI6IjAxOWMyMzE3LWEyZTMtNzQ2NC1iZTY3LTY3ZDNlMGY4YWNlMSIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.XsB0AXxVxUo13JxstFFAtQXxUqE-MjtP02FnX08uyhh3MGUxfFdm5hgVvcHRFOR-aiv1CeDegedqNJ1k5u8wPw';

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
  console.log("║   ПРОВЕРКА ОСТАТКОВ Z (26) И AA (27) - ВСЕ ТОВАРЫ                      ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const headers = { 'Authorization': `Bearer ${WB_TOKEN}` };

  // Фильтры
  const warehouseFilters = {
    Z:  {
      column: 26,
      name: "ФЕРОН МОСКВА",
      filter: (name) => name.includes("Подольск 3")
    },
    AA: {
      column: 27,
      name: "ВОЛЬТМИР",
      filter: (name) => name.includes("Индустриальная")
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

    console.log("\n=== ШАГ 2: Анализ warehouseName ===");

    // Собираем все уникальные warehouseName
    const uniqueWarehouses = {};
    allStocks.forEach(item => {
      const whName = item.warehouseName || "НЕ УКАЗАНО";
      if (!uniqueWarehouses[whName]) {
        uniqueWarehouses[whName] = {
          warehouseId: item.warehouseId,
          count: 0,
          totalQty: 0
        };
      }
      uniqueWarehouses[whName].count++;
      uniqueWarehouses[whName].totalQty += (item.quantity || 0);
    });

    console.log(`Уникальных складов: ${Object.keys(uniqueWarehouses).length}`);

    // Сортируем по количеству записей
    const sortedWarehouses = Object.entries(uniqueWarehouses)
      .sort((a, b) => b[1].count - a[1].count);

    console.log("\nТОП-20 складов по количеству записей:");
    console.log("─────────────────────────────────────────────────────────────────────────");

    sortedWarehouses.slice(0, 20).forEach(([name, data], i) => {
      console.log(`${(i + 1).toString().padStart(2)}. "${name}"`);
      console.log(`    ID: ${data.warehouseId}`);
      console.log(`    Записей: ${data.count}`);
      console.log(`    Общий quantity: ${data.totalQty}`);
    });

    console.log("\n=== ШАГ 3: Проверка фильтров ===");

    // Проверяем фильтры
    console.log("\nФильтр Z (26): " + JSON.stringify(warehouseFilters.Z.filter));
    console.log("Фильтр AA (27): " + JSON.stringify(warehouseFilters.AA.filter));

    console.log("\n=== ШАГ 4: Поиск совпадений ===");

    const results = {};

    Object.keys(warehouseFilters).forEach(key => {
      const config = warehouseFilters[key];

      // Находим warehouseName, которые совпадают с фильтром
      const matchingWarehouses = Object.keys(uniqueWarehouses).filter(whName =>
        config.filter(whName)
      );

      console.log(`\n${config.column}: ${config.name}`);
      console.log(`   Фильтр: ${config.description}`);
      console.log(`   Найти склады: name.includes("${config.filter.toString().match(/\(\"(.+)\"\)/)[1]}")`);

      if (matchingWarehouses.length > 0) {
        console.log(`   ✅ Найдено складов: ${matchingWarehouses.length}`);
        matchingWarehouses.forEach(wh => {
          const data = uniqueWarehouses[wh];
          console.log(`      ✓ "${wh}" (${data.count} записей, total qty: ${data.totalQty})`);
        });
      } else {
        console.log(`   ❌ Складов не найдено!`);
        console.log(`   ⚠️  Возможно название warehouseName не совпадает`);
      }

      // Считаем сколько товаров на этих складах
      const stockMap = {};
      let totalArticles = 0;
      let totalQty = 0;

      allStocks.forEach(item => {
        const whName = item.warehouseName || "";
        if (config.filter(whName)) {
          const art = item.supplierArticle;
          const qty = item.quantity || 0;

          if (!stockMap[art]) {
            stockMap[art] = 0;
            totalArticles++;
          }
          stockMap[art] += qty;
          totalQty += qty;
        }
      });

      results[key] = {
        warehouses: matchingWarehouses,
        articleCount: totalArticles,
        totalQuantity: totalQty,
        stocks: stockMap
      };

      console.log(`   Товаров на складе: ${totalArticles}`);
      console.log(`   Общий quantity: ${totalQty}`);
    });

    console.log("\n=== ШАГ 5: Проверка других возможных названий ===");

    // Ищем склады с похожими названиями
    console.log("\nПоиск 'Подольск':");
    const podolskMatches = Object.keys(uniqueWarehouses).filter(name =>
      name.toLowerCase().includes("подольск") ||
      name.toLowerCase().includes("podolsk")
    );
    podolskMatches.forEach(name => {
      const data = uniqueWarehouses[name];
      console.log(`   "${name}" (${data.count} записей)`);
    });

    console.log("\nПоиск 'Индустриальная':");
    const industriaMatches = Object.keys(uniqueWarehouses).filter(name =>
      name.toLowerCase().includes("индустриальная") ||
      name.toLowerCase().includes("индустриальная") ||
      name.toLowerCase().includes("индустриал")
    );
    industriaMatches.forEach(name => {
      const data = uniqueWarehouses[name];
      console.log(`   "${name}" (${data.count} записей)`);
    });

    console.log("\n=== ШАГ 6: ИТОГ ===");

    Object.entries(warehouseFilters).forEach(([key, config]) => {
      const result = results[key];
      console.log(`\n${config.column}: ${config.name}`);
      console.log(`   Складов найдено: ${result.warehouses.length}`);
      console.log(`   Товаров: ${result.articleCount}`);
      console.log(`   Остатков: ${result.totalQuantity}`);

      if (result.articleCount === 0) {
        console.log(`   ⚠️  Нет товаров! Нужно изменить фильтр.`);
      } else {
        console.log(`   ✅ Есть товары!`);
      }
    });

    console.log("\n✅ Тест завершен");

  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }
}

test();
