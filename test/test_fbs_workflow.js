// ТЕСТ ПОЛНОГО РАБОЧЕГО ПРОЦЕССА FBS
// Симулирует весь процесс получения данных по складам

const mockWarehouses = {
  warehouses: [
    { id: 1449484, name: "ФБС ФЕРОН МОСКВА", officeId: 10110, isFbs: true, isDbs: false },
    { id: 798761, name: "ВольтМир", officeId: 128, isFbs: true, isDbs: false },
    { id: 123456, name: "Коледино", officeId: 999, isFbs: false, isDbs: true }
  ]
};

const mockStocks1449484 = {
  stocks: [
    { sku: "22068-1", amount: 10 },
    { sku: "23348-1", amount: 25 },
    { sku: "25841-5", amount: 15 }
  ]
};

const mockStocks798761 = {
  stocks: [
    { sku: "22068-1", amount: 5 },
    { sku: "23348-1", amount: 12 },
    { sku: "39171-1", amount: 30 }
  ]
};

// Тестовые артикулы (как в таблице)
const testArticles = [
  "22068-1",
  "23348-1",
  "25841-5",
  "39171-1",
  "99999-1"  // nonexistent
];

console.log("╔════════════════════════════════════════════════════════════════════════╗");
console.log("║   ТЕСТ FBS РАБОЧЕГО ПРОЦЕССА                                          ║");
console.log("╚════════════════════════════════════════════════════════════════════════╝");

// ==================== ШАГ 1: Получение списка складов ====================
console.log("\n=== ШАГ 1: GET /api/v3/warehouses ===");
console.log(`Получено складов: ${mockWarehouses.warehouses.length}`);

console.log("\nСписок всех складов:");
mockWarehouses.warehouses.forEach((wh, i) => {
  const type = wh.isFbs ? 'FBS' : (wh.isDbs ? 'DBS' : '?');
  console.log(`   ${(i + 1)}. [${type}] "${wh.name}" (ID: ${wh.id})`);
});

// ==================== ШАГ 2: Поиск целевых складов ====================
console.log("\n=== ШАГ 2: Поиск целевых складов ===");

const targetSearch = {
  Z: { column: 26, name: "ФЕРОН МОСКВА", search: ["ФЕРОН", "МОСКВА"] },
  AA: { column: 27, name: "ВольтМир", search: ["ВольтМир", "ВОЛЬТМИР"] }
};

const foundWarehouses = {};

Object.entries(targetSearch).forEach(([key, config]) => {
  const found = mockWarehouses.warehouses.find(wh => {
    const name = (wh.name || "").toUpperCase();
    return config.search.every(term => name.includes(term.toUpperCase()));
  });

  if (found) {
    foundWarehouses[key] = { id: found.id, name: found.name };
    console.log(`${config.column} (${config.name}): ✅ "${found.name}" (ID: ${found.id})`);
  } else {
    console.log(`${config.column} (${config.name}): ❌ Не найден`);
  }
});

const foundCount = Object.keys(foundWarehouses).length;
console.log(`\nНайдено складов: ${foundCount} из 2`);

if (foundCount < 2) {
  console.log("❌ Недостаточно складов найдено!");
  process.exit(1);
}

// ==================== ШАГ 3: Получение остатков по складам ====================
console.log("\n=== ШАГ 3: GET /api/v3/stocks/{warehouseId} ===");

const results = {};
const stockResponses = {
  1449484: mockStocks1449484,
  798761: mockStocks798761
};

Object.entries(foundWarehouses).forEach(([key, wh]) => {
  const config = targetSearch[key];
  console.log(`\n${config.column}: ${config.name} (ID: ${wh.id})`);

  // Симуляция POST запроса
  const stockData = stockResponses[wh.id];
  console.log(`   Ответ API: ${JSON.stringify(stockData)}`);

  // Создаём map для быстрого поиска
  const stockMap = {};
  if (stockData.stocks && Array.isArray(stockData.stocks)) {
    stockData.stocks.forEach(stock => {
      if (stock.sku) {
        stockMap[stock.sku] = stock.amount || 0;
      }
    });
  }

  results[key] = stockMap;
  console.log(`   Загружено артикулов: ${Object.keys(stockMap).length}`);
});

// ==================== ШАГ 4: Запись в таблицу ====================
console.log("\n=== ШАГ 4: Формирование данных для таблицы ===");

Object.entries(targetSearch).forEach(([key, config]) => {
  const stockMap = results[key];

  console.log(`\nКолонка ${config.column} (${config.name}):`);

  const values = [];
  let foundCount = 0;

  testArticles.forEach(art => {
    const qty = stockMap[art] || 0;
    values.push(qty);
    if (qty > 0) foundCount++;
    console.log(`   ${art}: ${qty}`);
  });

  console.log(`   Товаров с остатками: ${foundCount} из ${testArticles.length}`);
});

// ==================== ДИАГНОСТИКА 22068-1 ====================
console.log("\n=== ДИАГНОСТИКА ДЛЯ 22068-1 ===");

Object.entries(targetSearch).forEach(([key, config]) => {
  const stockMap = results[key];
  const qty = stockMap["22068-1"] || 0;
  console.log(`${config.column} (${config.name}): ${qty} шт.`);
});

// ==================== ИТОГОВАЯ ПРОВЕРКА ====================
console.log("\n=== ПРОВЕРКА РЕЗУЛЬТАТОВ ===");

const expectedResults = {
  "22068-1": { Z: 10, AA: 5 },
  "23348-1": { Z: 25, AA: 12 },
  "25841-5": { Z: 15, AA: 0 },
  "39171-1": { Z: 0, AA: 30 }
};

let allPassed = true;

Object.entries(expectedResults).forEach(([sku, expected]) => {
  const zActual = results["Z"][sku] || 0;
  const aaActual = results["AA"][sku] || 0;

  const zPass = zActual === expected.Z;
  const aaPass = aaActual === expected.AA;

  if (!zPass || !aaPass) {
    allPassed = false;
    console.log(`❌ ${sku}: Z=${zActual} (ожидалось ${expected.Z}), AA=${aaActual} (ожидалось ${expected.AA})`);
  } else {
    console.log(`✅ ${sku}: Z=${zActual}, AA=${aaActual}`);
  }
});

console.log("\n" + "═".repeat(76));
if (allPassed) {
  console.log("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ!");
  console.log("\nЛогика корректна. Можно загружать WB Склады.gs в Apps Script.");
} else {
  console.log("❌ ТЕСТЫ НЕ ПРОЙДЕНЫ!");
  process.exit(1);
}
