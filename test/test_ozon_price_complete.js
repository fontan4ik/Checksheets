/**
 * ПОЛНЫЙ ТЕСТ ЦЕНЫ OZON
 * Все возможные сценарии ответа API
 */

console.log('=== ПОЛНЫЙ ТЕСТ ЦЕНЫ OZON ===\n');

// ============================================
// СЦЕНАРИИ ОТВЕТА API
// ============================================

const scenarios = [
  // Сценарий 1: 22068-1 - marketing_seller_price есть
  {
    name: "Сценарий 1: 22068-1",
    product_id: 109652992,
    api_response: {
      price: {
        price: "1516",                      // Цена с наценкой Ozon
        marketing_seller_price: "1480",     // ✅ Цена продавца (применяется)
        price_before: null,                 // Нет
        min_price: "1444"
      }
    },
    expected: 1480
  },

  // Сценарий 2: 024108(2)-1 - price_before есть, marketing_seller_price нет
  {
    name: "Сценарий 2: 024108(2)-1 (текущий товар)",
    product_id: 424697904,
    api_response: {
      price: {
        price: "6258",                      // Цена с наценкой (НЕПРАВИЛЬНАЯ)
        marketing_seller_price: null,       // Нет
        price_before: "49026",              // ✅ Базовая цена (применяется)
        old_price: "50000",
        min_price: "47000"
      }
    },
    expected: 49026
  },

  // Сценарий 3: Только price (все остальные поля отсутствуют)
  {
    name: "Сценарий 3: Только price",
    product_id: 123456,
    api_response: {
      price: {
        price: "5000",                      // ✅ Единственное доступное поле
        marketing_seller_price: null,
        price_before: null
      }
    },
    expected: 5000
  },

  // Сценарий 4: marketing_seller_price = 0 (использовать price_before)
  {
    name: "Сценарий 4: marketing_seller_price = 0",
    product_id: 789012,
    api_response: {
      price: {
        price: "3500",
        marketing_seller_price: "0",        // Есть, но равна 0
        price_before: "4000"                // ✅ Должна примениться
      }
    },
    expected: 4000
  },

  // Сценарий 5: marketing_seller_price = "" (пустая строка)
  {
    name: "Сценарий 5: marketing_seller_price = пустая строка",
    product_id: 345678,
    api_response: {
      price: {
        price: "2500",
        marketing_seller_price: "",         // Пустая строка
        price_before: "3000"                // ✅ Должна примениться
      }
    },
    expected: 3000
  },

  // Сценарий 6: Все поля числовые (не строки)
  {
    name: "Сценарий 6: Числовые поля",
    product_id: 456789,
    api_response: {
      price: {
        price: 2000,                        // Число, не строка
        marketing_seller_price: 1800,       // Число
        price_before: 1900
      }
    },
    expected: 1800
  },

  // Сценарий 7: min_price как fallback
  {
    name: "Сценарий 7: Использовать min_price",
    product_id: 567890,
    api_response: {
      price: {
        price: "1500",
        marketing_seller_price: null,
        price_before: null,
        min_price: "1200"                   // ✅ Минимальная цена
      }
    },
    expected: 1200  // Если min_price должен использоваться
  }
];

// ============================================
// ФУНКЦИЯ ВЫБОРА ЦЕНЫ (как в коде)
// ============================================

function selectPrice(item) {
  const p = item.price;
  // Текущая логика из Ozon цена.gs
  return p?.marketing_seller_price || p?.price_before || p?.price || "";
}

// ============================================
// АЛЬТЕРНАТИВНАЯ ФУНКЦИЯ (с min_price)
// ============================================

function selectPriceAlternative(item) {
  const p = item.price;
  // Альтернативная логика с min_price
  const price = p?.marketing_seller_price || p?.price_before || p?.price;

  // Если цена = 0, null, undefined, пустая строка, пробуем min_price
  if (!price || price === "0" || price === 0) {
    return p?.min_price || p?.price || "";
  }

  return price;
}

// ============================================
// ТЕСТИРОВАНИЕ
// ============================================

console.log('=== ТЕСТИРОВАНИЕ ТЕКУЩЕЙ ЛОГИКИ ===\n');

let currentPassed = 0;
let currentFailed = 0;

scenarios.forEach(scenario => {
  const result = selectPrice(scenario.api_response);
  const passed = result == scenario.expected; // Используем == для сравнения числа и строки

  console.log(`${scenario.name}:`);
  console.log(`  product_id: ${scenario.product_id}`);
  console.log(`  price.price: ${scenario.api_response.price.price}`);
  console.log(`  price.marketing_seller_price: ${scenario.api_response.price.marketing_seller_price || 'нет'}`);
  console.log(`  price.price_before: ${scenario.api_response.price.price_before || 'нет'}`);
  console.log(`  price.min_price: ${scenario.api_response.price.min_price || 'нет'}`);
  console.log(`  Результат: ${result}`);
  console.log(`  Ожидается: ${scenario.expected}`);
  console.log(`  ${passed ? '✅ ПРАВИЛЬНО' : '❌ НЕПРАВИЛЬНО'}`);

  if (passed) {
    currentPassed++;
  } else {
    currentFailed++;
    console.log(`  ⚠️  Разница: ${scenario.expected - result}`);
  }
  console.log('');
});

console.log(`=== ИТОГ ТЕКУЩЕЙ ЛОГИКИ ===`);
console.log(`Пройдено: ${currentPassed}/${scenarios.length}`);
console.log(`Ошибок: ${currentFailed}/${scenarios.length}`);
console.log('');

// ============================================
// ТЕСТИРОВАНИЕ АЛЬТЕРНАТИВНОЙ ЛОГИКИ
// ============================================

console.log('=== ТЕСТИРОВАНИЕ АЛЬТЕРНАТИВНОЙ ЛОГИКИ (с min_price) ===\n');

let altPassed = 0;
let altFailed = 0;

scenarios.forEach(scenario => {
  const result = selectPriceAlternative(scenario.api_response);
  const passed = result == scenario.expected;

  console.log(`${scenario.name}:`);
  console.log(`  Результат: ${result}`);
  console.log(`  Ожидается: ${scenario.expected}`);
  console.log(`  ${passed ? '✅ ПРАВИЛЬНО' : '❌ НЕПРАВИЛЬНО'}`);

  if (passed) {
    altPassed++;
  } else {
    altFailed++;
  }
  console.log('');
});

console.log(`=== ИТОГ АЛЬТЕРНАТИВНОЙ ЛОГИКИ ===`);
console.log(`Пройдено: ${altPassed}/${scenarios.length}`);
console.log(`Ошибок: ${altFailed}/${scenarios.length}`);
console.log('');

// ============================================
// СРАВНЕНИЕ
// ============================================

console.log('=== СРАВНЕНИЕ ЛОГИК ===');
console.log(`Текущая логика: ${currentPassed}/${scenarios.length} пройдено`);
console.log(`Альтернативная логика: ${altPassed}/${scenarios.length} пройдено`);
console.log('');

if (altPassed > currentPassed) {
  console.log('✅ РЕКОМЕНДАЦИЯ: Использовать альтернативную логику с min_price');
} else if (currentPassed === scenarios.length) {
  console.log('✅ Текущая логика ПРАВИЛЬНАЯ!');
} else {
  console.log('⚠️  Обе логики имеют ошибки. Нужно дополнительное исследование.');
}

// ============================================
// ДИАГНОСТИКА ДЛЯ КОНКРЕТНЫХ ТОВАРОВ
// ============================================

console.log('');
console.log('=== ДИАГНОСТИКА КОНКРЕТНЫХ ТОВАРОВ ===');
console.log('');

// Для 22068-1
const s1 = scenarios[0];
console.log(`22068-1 (product_id: ${s1.product_id}):`);
const r1 = selectPrice(s1.api_response);
console.log(`  Текущая цена: ${r1}`);
console.log(`  Ожидается: ${s1.expected}`);
console.log(`  ${r1 == s1.expected ? '✅' : '❌'}`);
console.log('');

// Для 024108(2)-1
const s2 = scenarios[1];
console.log(`024108(2)-1 (product_id: ${s2.product_id}):`);
const r2 = selectPrice(s2.api_response);
console.log(`  Текущая цена в таблице: 6258`);
console.log(`  Цена из API (price): ${s2.api_response.price.price}`);
console.log(`  Цена из API (price_before): ${s2.api_response.price.price_before}`);
console.log(`  Результат функции: ${r2}`);
console.log(`  Ожидается: ${s2.expected}`);
console.log(`  ${r2 == s2.expected ? '✅' : '❌'}`);
if (r2 == s2.expected) {
  console.log('');
  console.log(`  📋 РЕКОМЕНДАЦИЯ:`);
  console.log(`  - Логика функции ПРАВИЛЬНАЯ`);
  console.log(`  - Значение 6258 в таблице = СТАРАЯ версия до исправления`);
  console.log(`  - Нужно перезапустить getOzonPricesOptimized()`);
}
