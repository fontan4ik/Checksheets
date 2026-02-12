// ТЕСТ ДЛЯ 48724-1
// Симуляция получения остатков по конкретному артикулу

console.log("╔════════════════════════════════════════════════════════════════════════╗");
console.log("║   ТЕСТ АРТИКУЛА 48724-1                                               ║");
console.log("╚════════════════════════════════════════════════════════════════════════╝");

// Ожидаемые результаты от пользователя
const expectedResults = {
  "ФЕРОН МОСКВА": 20,
  "ВольтМир": 5
};

console.log("\n=== ОЖИДАЕМЫЕ РЕЗУЛЬТАТЫ ===");
console.log(`Артикул: 48724-1`);
console.log(`ФЕРОН МОСКВА (Z): ${expectedResults["ФЕРОН МОСКВА"]} шт.`);
console.log(`ВольтМир (AA): ${expectedResults["ВольтМир"]} шт.`);

// ==================== ШАГ 1: Проверка запроса ====================
console.log("\n=== ШАГ 1: Анализ запроса API ===");

const testSku = "48724-1";
const warehouseZ = { id: 1449484, name: "ФБС ФЕРОН МОСКВА" };
const warehouseAA = { id: 798761, name: "ВольтМир" };

console.log("\nЗапрос для ФЕРОН МОСКВА:");
console.log(`  URL: https://suppliers-api.wildberries.ru/api/v3/stocks/${warehouseZ.id}`);
console.log(`  Method: POST`);
console.log(`  Headers: Authorization: Bearer <token>`);
console.log(`  Body: ${JSON.stringify({ skus: [testSku] }, null, 2)}`);

console.log("\nОжидаемый ответ:");
const expectedResponseZ = {
  "stocks": [
    { "sku": "48724-1", "amount": 20 }
  ]
};
console.log(`  ${JSON.stringify(expectedResponseZ, null, 2).split('\n').map(l => '  ' + l).join('\n')}`);

console.log("\nЗапрос для ВольтМир:");
console.log(`  URL: https://suppliers-api.wildberries.ru/api/v3/stocks/${warehouseAA.id}`);
console.log(`  Method: POST`);
console.log(`  Body: ${JSON.stringify({ skus: [testSku] }, null, 2)}`);

console.log("\nОжидаемый ответ:");
const expectedResponseAA = {
  "stocks": [
    { "sku": "48724-1", "amount": 5 }
  ]
};
console.log(`  ${JSON.stringify(expectedResponseAA, null, 2).split('\n').map(l => '  ' + l).join('\n')}`);

// ==================== ШАГ 2: Проверка обработки ответа ====================
console.log("\n=== ШАГ 2: Логика обработки ответа ===");

function processStockResponse(response, warehouseName) {
  console.log(`\nОбработка ответа для "${warehouseName}":`);
  console.log(`  Входящие данные: ${JSON.stringify(response)}`);

  const stockMap = {};
  if (response.stocks && Array.isArray(response.stocks)) {
    response.stocks.forEach(stock => {
      if (stock.sku) {
        stockMap[stock.sku] = stock.amount || 0;
        console.log(`    ${stock.sku} → ${stock.amount} шт.`);
      }
    });
  }

  const qty = stockMap[testSku] || 0;
  console.log(`  Результат для ${testSku}: ${qty} шт.`);
  return qty;
}

const qtyZ = processStockResponse(expectedResponseZ, "ФЕРОН МОСКВА");
const qtyAA = processStockResponse(expectedResponseAA, "ВольтМир");

// ==================== ШАГ 3: Проверка записи в таблицу ====================
console.log("\n=== ШАГ 3: Запись в Google Sheets ===");
console.log("\nДанные для записи в таблицу:");
console.log("┌───────────┬──────────────┬──────────────┐");
console.log("│ Артикул   │ Z (26) ФЕРОН │ AA (27) ВМ   │");
console.log("├───────────┼──────────────┼──────────────┤");
console.log(`│ ${testSku.padEnd(9)} │ ${qtyZ.toString().padEnd(12)} │ ${qtyAA.toString().padEnd(12)} │`);
console.log("└───────────┴──────────────┴──────────────┘");

// ==================== ДИАГНОСТИКА ====================
console.log("\n=== ДИАГНОСТИКА ВОЗМОЖНЫХ ПРОБЛЕМ ===");

console.log("\n1. Проверьте, что API возвращает данные:");
console.log("   - Выполните testSuppliersAPI() в Apps Script");
console.log("   - Проверьте логи на наличие складов 1449484 и 798761");

console.log("\n2. Проверьте формат SKU:");
console.log("   - supplierArticle: 48724-1");
console.log("   - barcode: (может быть другой)");
console.log("   - nmId: (числовой ID WB)");

console.log("\n3. Возможные причины пустых данных:");
console.log("   ❌ Артикул не найден в системе WB");
console.log("   ❌ Неверный формат SKU (нужен barcode, а не supplierArticle)");
console.log("   ❌ Нет остатков на этих складах");
console.log("   ❌ API token не имеет доступа к этим складам");

// ==================== ТЕСТ РАЗНЫХ ФОРМАТОВ SKU ====================
console.log("\n=== ТЕСТ РАЗНЫХ ФОРМАТОВ SKU ===");
console.log("\nВозможно, API требует другой формат SKU:");
console.log("  1. supplierArticle: \"48724-1\"");
console.log("  2. barcode: (число со штрих-кода)");
console.log("  3. nmId: (числовой ID, например: 12345678)");

console.log("\nТекущий код использует supplierArticle из колонки A.");
console.log("Если API требует другой формат, нужно будет добавить преобразование.");

// ==================== РЕКОМЕНДАЦИИ ====================
console.log("\n" + "═".repeat(76));
console.log("РЕКОМЕНДАЦИИ:");
console.log("\n1. Выполните в Apps Script:");
console.log("   testSuppliersAPI()");
console.log("\n2. Проверьте логи - найдены ли склады?");
console.log("\n3. Если склады найдены, но остатки пустые:");
console.log("   - Возможно API требует barcode вместо supplierArticle");
console.log("   - Нужно проверить API документацию для поля 'sku'");
console.log("\n4. Запустите с отладкой:");
console.log("   В WB Склады.gs добавьте логирование ответа API:");
console.log("   Logger.log('Response: ' + responseText);");
