/**
 * ТЕСТ СУММЫ ЗАКАЗОВ WB ДЛЯ 024108(2)-1
 * Проверка почему 45400 вместо 108
 */

console.log('=== ТЕСТ СУММЫ ЗАКАЗОВ WB ДЛЯ 024108(2)-1 ===\n');

// Текущее значение в таблице: 45400
// Ожидается: 108
// Разница: 45292

console.log('Анализ проблемы:');
console.log('  Текущее значение: 45400');
console.log('  Ожидается: 108');
console.log('  Разница: 45292');
console.log('  Отношение: 45400 / 108 = ' + (45400 / 108).toFixed(2));
console.log('');

console.log('=== ВОЗМОЖНЫЕ ПРИЧИНЫ ===\n');

// Причина 1: Умножение на 100 (копейки вместо рублей)
console.log('1. Проверка: копейки вместо рублей');
const kop = 45400 / 100;
console.log(`   45400 копеек = ${kop} рублей`);
console.log(`   ${kop === 108 ? '✅ ПОХОЖЕ!' : '❌ Не совпадает'}`);
console.log('');

// Причина 2: Суммируются ВСЕ заказы (весь период) вместо 30 дней
console.log('2. Проверка: все заказы вместо последних 30 дней');
const totalOrders = 45400;
const monthOrders = 108;
const ratio = totalOrders / monthOrders;
console.log(`   Если ${totalOrders} — это все заказы`);
console.log(`   А ${monthOrders} — за 30 дней`);
console.log(`   То период = ${ratio.toFixed(1)} месяцев (${ratio / 30} дней)`);
console.log('');

// Причина 3: Ошибка в артикуле (сопоставление не работает)
console.log('3. Проверка: ошибка сопоставления артикула');
console.log('   Артикул в таблице: 024108(2)-1');
console.log('   Артикул в API: 024108(2) или 024108');
console.log('   Базовый артикул: 024108(2)');
console.log('   Если не убирается суффикс - сопоставление не сработает');
console.log('');

// Причина 4: Wrong field in API response
console.log('4. Проверка: неправильное поле в API');
console.log('   API может возвращать:');
console.log('   - priceWithDisc: цена со скидкой (в копейках?)');
console.log('   - totalPrice: полная стоимость заказа');
console.log('   - finishedPrice: финальная цена');
console.log('');

// Симуляция различных вариантов API
console.log('=== СИМУЛЯЦИЯ API ОТВЕТА ===\n');

const apiVariants = [
  {
    name: 'Вариант А: правильные данные',
    article: '024108(2)',
    orders: [
      { quantity: 1, priceWithDisc: 36 },
      { quantity: 1, priceWithDisc: 36 },
      { quantity: 3, priceWithDisc: 36 }  // Итого: 108
    ],
    sum: 108
  },
  {
    name: 'Вариант Б: данные в копейках',
    article: '024108(2)',
    orders: [
      { quantity: 1, priceWithDisc: 3600 },  // 36.00 рублей в копейках
      { quantity: 1, priceWithDisc: 3600 },
      { quantity: 3, priceWithDisc: 3600 }
    ],
    sum: 18000
  },
  {
    name: 'Вариант В: много заказов',
    article: '024108(2)',
    orders: Array.from({length: 1261}, (_, i) => ({
      quantity: 1,
      priceWithDisc: 36
    })),
    sum: 45396  // Близко к 45400!
  }
];

apiVariants.forEach(variant => {
  console.log(`${variant.name}:`);
  console.log(`  Заказов: ${variant.orders.length}`);
  console.log(`  Сумма: ${variant.sum}`);
  if (variant.sum === 45400 || variant.sum === 45396) {
    console.log(`  ✅ ПОХОЖЕ НА ПРИЧИНУ! Суммируется ${variant.orders.length} заказов`);
  }
  console.log('');
});

console.log('=== РЕКОМЕНДАЦИЯ ===');
console.log('');
console.log('Для 024108(2)-1:');
console.log('1. Проверить период выборки (dateFrom)');
console.log('2. Убедиться что используется базовый артикул (без суффикса -1)');
console.log('3. Проверить что priceWithDisc в рублях, а не в копейках');
console.log('4. Проверить фильтр по isCancel (отмененные заказы)');
console.log('');
console.log('Если 45400 — это сумма 1261 заказа по 36 руб:');
console.log('  → Возможно берется ВЕСЬ период вместо 30 дней');
console.log('  → Или не фильтруются отмененные заказы');
