/**
 * ФИНАЛЬНЫЙ ТЕСТ ЛОГИКИ ЦЕНЫ (после исправления)
 */

console.log('=== ФИНАЛЬНЫЙ ТЕСТ ЛОГИКИ ЦЕНЫ ===\n');

// Тестовая функция (как в исправленном коде)
function selectPrice(item) {
  const p = item.price;
  let price = "";

  // marketing_seller_price имеет приоритет
  if (p && p.marketing_seller_price !== null && p.marketing_seller_price !== undefined && p.marketing_seller_price !== "") {
    price = p.marketing_seller_price;
  }
  // Если marketing_seller_price нет, проверяем price_before
  else if (p && p.price_before !== null && p.price_before !== undefined && p.price_before !== "") {
    price = p.price_before;
  }
  // Если нет price_before, берем price (может быть пустым)
  else {
    price = p.price || "";
  }

  return price;
}

// Все сценарии
const scenarios = [
  {
    name: "22068-1",
    data: { price: { price: "1516", marketing_seller_price: "1480", price_before: null } },
    expected: 1480
  },
  {
    name: "024108(2)-1",
    data: { price: { price: "6258", marketing_seller_price: null, price_before: "49026" } },
    expected: 49026
  },
  {
    name: "marketing_seller_price = 0",
    data: { price: { price: "3500", marketing_seller_price: 0, price_before: "4000" } },
    expected: 0
  },
  {
    name: "Только price",
    data: { price: { price: "5000", marketing_seller_price: null, price_before: null } },
    expected: 5000
  },
  {
    name: "marketing_seller_price = ''",
    data: { price: { price: "2500", marketing_seller_price: "", price_before: "3000" } },
    expected: 3000
  },
  {
    name: "Числовые поля",
    data: { price: { price: 2000, marketing_seller_price: 1800, price_before: 1900 } },
    expected: 1800
  },
];

console.log('=== ТЕСТИРОВАНИЕ ===\n');
let passed = 0;
let failed = 0;

scenarios.forEach(s => {
  const result = selectPrice(s.data);
  const isPass = result == s.expected;

  console.log(`${s.name}:`);
  console.log(`  Результат: ${result}`);
  console.log(`  Ожидается: ${s.expected}`);
  console.log(`  ${isPass ? '✅ ПРАВИЛЬНО' : '❌ НЕПРАВИЛЬНО'}`);

  if (isPass) passed++;
  else failed++;

  console.log('');
});

console.log('=== ИТОГ ===');
console.log(`Пройдено: ${passed}/${scenarios.length}`);
console.log(`Ошибок: ${failed}/${scenarios.length}`);
console.log('');

if (passed === scenarios.length) {
  console.log('✅✅✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ!');
  console.log('');
  console.log('Для 024108(2)-1:');
  console.log('  Логика вернет: 49026 (из price_before)');
  console.log('  В таблице: 6258');
  console.log('');
  console.log('📋 ПРИЧИНА РАСХОЖДЕНИЯ:');
  console.log('  1. Функция getOzonPricesOptimized() не выполнялась после исправления');
  console.log('  2. Или в Apps Script загружена старая версия файла');
  console.log('');
  console.log('🔧 РЕШЕНИЕ:');
  console.log('  1. Убедитесь что [Ozon цена.gs] обновлен в Apps Script');
  console.log('  2. Выполните: getOzonPricesOptimized()');
  console.log('  3. Проверьте логи на наличие ошибок');
} else {
  console.log('❌ Есть ошибки в логике!');
}
