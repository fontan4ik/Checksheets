/**
 * ТЕСТ ЦЕНЫ OZON ДЛЯ 024108(2)-1
 * Проверка почему 6258 вместо 49026
 */

console.log('=== ТЕСТ ЦЕНЫ OZON ДЛЯ 024108(2)-1 ===\n');

// Симуляция возможных ответов API для разных товаров
const testCases = [
  {
    name: "22068-1 (ранний пример)",
    productId: 109652992,
    response: {
      price: {
        marketing_seller_price: 1480,
        price: 1516,
        price_before: null
      }
    },
    expected: 1480
  },
  {
    name: "024108(2)-1 (текущий пример)",
    productId: 424697904,
    response: {
      price: {
        marketing_seller_price: null,  // Может отсутствовать!
        price: 6258,                   // Текущее значение
        price_before: 49026,           // Возможно именно здесь правильная цена!
        old_price: 50000
      }
    },
    expected: 49026
  },
  {
    name: "Вариант 3: минимальная цена",
    productId: 123456,
    response: {
      price: {
        marketing_seller_price: null,
        price: 7000,
        price_before: null,
        min_price: 5000  // Может нужно брать min_price?
      }
    },
    expected: 5000
  }
];

console.log('=== ПРОВЕРКА ЛОГИКИ ВЫБОРА ЦЕНЫ ===\n');

testCases.forEach(test => {
  console.log(`Товар: ${test.name}`);
  console.log(`product_id: ${test.productId}`);
  console.log('');

  const p = test.response.price;

  console.log('Поля цены:');
  console.log(`  marketing_seller_price: ${p.marketing_seller_price || 'нет'}`);
  console.log(`  price_before: ${p.price_before || 'нет'}`);
  console.log(`  price: ${p.price}`);
  console.log(`  old_price: ${p.old_price || 'нет'}`);
  console.log(`  min_price: ${p.min_price || 'нет'}`);
  console.log('');

  // Текущая логика
  const currentPrice = p.marketing_seller_price || p.price_before || p.price || "";
  console.log(`Результат (текущая логика): ${currentPrice}`);
  console.log(`Ожидается: ${test.expected}`);
  console.log(currentPrice === test.expected ? '✅ ПРАВИЛЬНО' : `❌ НЕПРАВИЛЬНО (разница: ${test.expected - currentPrice})`);
  console.log('');

  if (currentPrice !== test.expected) {
    console.log(`⚠️  Нужно использовать другое поле!`);
    console.log(`   Попробовать: ${p.price_before ? 'price_before' : p.min_price ? 'min_price' : 'другое поле'}`);
  }
  console.log('---');
});

console.log('');
console.log('=== АНАЛИЗ ПРОБЛЕМЫ ДЛЯ 024108(2)-1 ===');
console.log('');

const problemCase = testCases[1];
const p = problemCase.response.price;

console.log('Текущий приоритет полей:');
console.log('  1. marketing_seller_price');
console.log('  2. price_before');
console.log('  3. price');
console.log('');

console.log('Для 024108(2)-1:');
console.log(`  marketing_seller_price = ${p.marketing_seller_price} (нет)`);
console.log(`  price_before = ${p.price_before} ✅`);
console.log(`  price = ${p.price}`);
console.log('');

const result = p.marketing_seller_price || p.price_before || p.price;
console.log(`Результат: ${result}`);
console.log(`Ожидается: ${problemCase.expected}`);
console.log('');

if (result === problemCase.expected) {
  console.log('✅ Логика правильная! Цена должна быть 49026');
  console.log('');
  console.log('Возможная причина неправильного значения в таблице:');
  console.log('  - Старая версия функции (до исправления) использовала только price.price');
  console.log('  - Нужно перезапустить getOzonPricesOptimized()');
} else {
  console.log('❌ Нужно изменить логику выбора цены!');
}
