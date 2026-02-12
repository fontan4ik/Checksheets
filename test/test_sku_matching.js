/**
 * ЛОКАЛЬНЫЙ ТЕСТ: Проверка логики сопоставления SKU
 * Симуляция процесса обработки данных из API
 */

console.log('=== ТЕСТ СОПОСТАВЛЕНИЯ SKU ===\n');

// Симуляция данных из таблицы (колонка S)
const tableData = [
  { article: "22068-1", sku: "301854987" },
  { article: "22068-2", sku: "301854997" },
  { article: "22068-3", sku: "" },  // пустой
  { article: "22068-4", sku: "12345" },
  { article: "22068-5", sku: "67890" }
];

console.log('1. ДАННЫЕ ИЗ ТАБЛИЦЫ (S - SKU):');
tableData.forEach(d => {
  console.log(`   ${d.article}: SKU="${d.sku}"`);
});
console.log('');

// Шаг 1: Создаем skuIndexPairs
const skuIndexPairs = tableData.map((d, index) => ({
  sku: d.sku?.toString().trim() || "",
  rowIndex: index
}));

console.log('2. SKU INDEX PAIRS:');
skuIndexPairs.forEach((p, i) => {
  console.log(`   [${i}] sku="${p.sku}", rowIndex=${p.rowIndex}`);
});
console.log('');

// Шаг 2: Создаем validSkus (уникальные непустые)
const validSkus = [...new Set(skuIndexPairs.filter(x => x.sku !== "").map(x => x.sku))];

console.log('3. VALID SKU (для запроса к API):');
console.log(`   Всего: ${validSkus.length}`);
console.log(`   ${validSkus.join(', ')}`);
console.log('');

// Шаг 3: Симуляция ответа API
// API возвращает данные, но SKU могут быть в ДРУГОМ формате!
const apiResponse = {
  result: {
    data: [
      {
        dimensions: [{ id: "301854987", name: "301854987" }],
        metrics: [15, 527600]  // [ordered_units, revenue]
      },
      {
        dimensions: [{ id: 301854997, name: "301854997" }],  // ← ЧИСЛО, не строка!
        metrics: [5, 150000]
      },
      {
        dimensions: [{ id: "12345", name: "12345" }],
        metrics: [10, 50000]
      }
    ]
  }
};

console.log('4. API ОТВЕТ:');
apiResponse.result.data.forEach(entry => {
  const sku = entry.dimensions[0].id;
  const metrics = entry.metrics;
  console.log(`   SKU=${sku} (type: ${typeof sku}), ordered_units=${metrics[0]}, revenue=${metrics[1]}`);
});
console.log('');

// Шаг 4: Создаем resultMap
const resultMap = {};
apiResponse.result.data.forEach(entry => {
  const skuObj = entry.dimensions[0];
  const sku = skuObj?.id?.toString();  // ← Преобразуем в строку
  if (sku) {
    resultMap[sku] = entry.metrics;
  }
});

console.log('5. RESULT MAP (после парсинга API):');
Object.entries(resultMap).forEach(([sku, metrics]) => {
  console.log(`   "${sku}" → [${metrics.join(', ')}]`);
});
console.log('');

// Шаг 6: Проверка сопоставления
console.log('6. СОПОСТАВЛЕНИЕ ДАННЫХ:');

const orderedUnitsMonthList = [];
const revenueMonthList = [];

skuIndexPairs.forEach(({ sku }) => {
  if (!sku) {
    orderedUnitsMonthList.push([""]);
    revenueMonthList.push([""]);
  } else {
    const monthMetrics = resultMap[sku] || [0, 0];
    orderedUnitsMonthList.push([monthMetrics[0] || 0]);
    revenueMonthList.push([monthMetrics[1] || 0]);

    const status = monthMetrics[0] > 0 ? "✅" : "❌";
    console.log(`   SKU "${sku}" → ordered_units=${monthMetrics[0]}, revenue=${monthMetrics[1]} ${status}`);
  }
});
console.log('');

// Шаг 7: Итог
console.log('7. РЕЗУЛЬТАТ ДЛЯ ЗАПИСИ В ТАБЛИЦУ:');
tableData.forEach((d, i) => {
  const units = orderedUnitsMonthList[i][0];
  const revenue = revenueMonthList[i][0];
  console.log(`   ${d.article}: I=${units}, L=${revenue}`);
});
console.log('');

// Анализ проблемы
console.log('=== АНАЛИЗ ПРОБЛЕМЫ ===');

// Проверяем каждый SKU из validSkus
let foundCount = 0;
let missingCount = 0;

console.log('Проверка SKU из validSkus:');
validSkus.forEach(sku => {
  if (resultMap[sku]) {
    foundCount++;
    console.log(`   "${sku}" → ✅ НАЙДЕН`);
  } else {
    missingCount++;
    console.log(`   "${sku}" → ❌ НЕ НАЙДЕН`);
  }
});

console.log('');
console.log(`Статистика:`);
console.log(`  validSkus.length = ${validSkus.length}`);
console.log(`  Object.keys(resultMap).length = ${Object.keys(resultMap).length}`);
console.log(`  Найдено: ${foundCount}`);
console.log(`  Не найдено: ${missingCount}`);
console.log('');

// Проблема: если API возвращает SKU как число
console.log('=== ВОЗМОЖНАЯ ПРОБЛЕМА: ТИПЫ ДАННЫХ ===');
console.log('Если API возвращает:');
console.log('  Таблица: "301854987" (строка)');
console.log('  API: 301854987 (число)');
console.log('После toString(): "301854987" = "301854987" ✅');
console.log('');
console.log('НО если API возвращает:');
console.log('  Таблица: "301854987"');
console.log('  API: "301854987" (но с пробелом: " 301854987")');
console.log('После toString(): "301854987" ≠ " 301854987" ❌');
console.log('');

// Проверка на совпадение типов
console.log('=== ПРОВЕРКА СОВПАДЕНИЯ ТИПОВ ===');
const tableSku = "301854987";
const apiSku1 = "301854987";
const apiSku2 = 301854987;
const apiSku3 = " 301854987";

console.log(`Таблица: "${tableSku}" (type: ${typeof tableSku})`);
console.log(`API 1: "${apiSku1}" (type: ${typeof apiSku1}) → ${tableSku === apiSku1 ? "✅" : "❌"}`);
console.log(`API 2: ${apiSku2} (type: ${typeof apiSku2}) → ${tableSku === String(apiSku2) ? "✅" : "❌"}`);
console.log(`API 3: "${apiSku3}" (type: ${typeof apiSku3}) → ${tableSku === apiSku3 ? "✅" : "❌"}`);
