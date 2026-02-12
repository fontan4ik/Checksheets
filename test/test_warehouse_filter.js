/**
 * ТЕСТ ФИЛЬТРАЦИИ СКЛАДОВ WB
 * Проверяет логику фильтрации по warehouseName и агрегации quantity
 */

const https = require('https');

const WB_TOKEN = process.env.WB_TOKEN || 'your_token_here';
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

function testWarehouseFiltering() {
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ТЕСТ ФИЛЬТРАЦИИ СКЛАДОВ WB                                             ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const headers = { 'Authorization': `Bearer ${WB_TOKEN}` };

  // Определение фильтров для складов
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
    },
    AI: {
      column: 35,
      name: "Ферон Самара",
      description: "Самарская область, г.Самара",
      filter: (name) => name.includes("г.Самара")
    },
    AJ: {
      column: 36,
      name: "Ферон Внуково",
      description: "г. Москва, Внуково",
      filter: (name) => name.includes("Внуково")
    }
  };

  console.log("\n=== ШАГ 1: Получение всех остатков ===");

  httpsGet('statistics-api.wildberries.ru', '/api/v1/supplier/stocks?dateFrom=2019-06-20', headers)
    .then(result => {
      console.log(`Status: ${result.status}`);
      const stocks = result.data;

      if (!Array.isArray(stocks)) {
        console.log("❌ Ответ не является массивом");
        return;
      }

      console.log(`Получено записей: ${stocks.length}`);

      // Фильтруем для тестового артикула
      const articleStocks = stocks.filter(s => s.supplierArticle === TEST_ARTICLE);
      console.log(`\nЗаписей для ${TEST_ARTICLE}: ${articleStocks.length}`);

      if (articleStocks.length === 0) {
        console.log(`❌ Артикул ${TEST_ARTICLE} не найден`);
        return;
      }

      console.log("\n=== ШАГ 2: Агрегация по складам ===");

      const results = {};

      // Инициализация результатов
      Object.keys(warehouseFilters).forEach(key => {
        results[key] = 0;
      });

      // Сумма всех FBO (колонка O)
      let totalFBO = 0;

      articleStocks.forEach(stock => {
        const whName = stock.warehouseName || "";
        const qty = stock.quantity || 0;
        const whId = stock.warehouseId;

        console.log(`\n   Warehouse ${whId} (${whName}):`);
        console.log(`      quantity: ${qty}`);

        // Добавляем к общей сумме FBO
        totalFBO += qty;

        // Проверяем фильтры
        Object.entries(warehouseFilters).forEach(([key, config]) => {
          if (config.filter(whName)) {
            console.log(`      ✓ Совпадает с ${config.name} (колонка ${config.column})`);
            results[key] += qty;
          }
        });
      });

      console.log("\n=== ШАГ 3: Результаты ===");

      console.log(`\nO (15): Остаток ФБО ВБ (все склады): ${totalFBO}`);

      Object.entries(warehouseFilters).forEach(([key, config]) => {
        console.log(`\n${config.column}: ${config.name}`);
        console.log(`   Фильтр: ${config.description}`);
        console.log(`   Quantity: ${results[key]}`);
      });

      console.log("\n=== ШАГ 4: Проверка ===");

      // Проверяем что сумма совпадает
      const warehouseSum = Object.values(results).reduce((a, b) => a + b, 0);
      console.log(`\nСумма по складам: ${warehouseSum}`);
      console.log(`Общая сумма FBO: ${totalFBO}`);

      if (warehouseSum <= totalFBO) {
        console.log("✅ Сумма корректна (может быть меньше, есть склады без фильтра)");
      } else {
        console.log("❌ Ошибка: сумма по складам больше общей суммы!");
      }

      // Показываем какие склады не попали в фильтры
      console.log("\n=== ШАГ 5: Склады без фильтра ===");

      articleStocks.forEach(stock => {
        const whName = stock.warehouseName || "";
        const qty = stock.quantity || 0;

        const hasFilter = Object.values(warehouseFilters).some(config => config.filter(whName));

        if (!hasFilter) {
          console.log(`   "${whName}": ${qty} (нет фильтра)`);
        }
      });

    })
    .catch(e => {
      console.error(`❌ Ошибка: ${e.message}`);
    });
}

// Запуск теста
testWarehouseFiltering();
