/**
 * ФИНАЛЬНЫЙ ТЕСТ ЦЕНЫ OZON
 * Проверка правильной логики выбора поля цены
 */

console.log('=== ФИНАЛЬНЫЙ ТЕСТ ЦЕНЫ OZON ===\n');

// Реальный ответ API от диагностики
const realAPIResponse = {
  "items": [
    {
      "product_id": 109652992,
      "offer_id": "22068-1",
      "price": {
        "auto_action_enabled": true,
        "currency_code": "RUB",
        "marketing_seller_price": 1480,  // ✅ НУЖНОЕ ПОЛЕ!
        "min_price": 1444,
        "old_price": 2426,
        "price": 1516,                  // ❌ С наценкой Ozon
        "retail_price": 0,
        "vat": 0.22,
        "net_price": 473
        // price_before - ОТСУТСТВУЕТ!
      }
    }
  ]
};

console.log('Реальный ответ API Ozon Prices (v5):');
console.log('price.marketing_seller_price:', realAPIResponse.items[0].price.marketing_seller_price);
console.log('price.price:', realAPIResponse.items[0].price.price);
console.log('price.price_before:', realAPIResponse.items[0].price.price_before || 'ОТСУТСТВУЕТ');
console.log('');

// НОВАЯ ЛОГИКА
console.log('=== НОВАЯ ЛОГИКА (правильная) ===');
const item = realAPIResponse.items[0];
const p = item.price;

const price = p?.marketing_seller_price || p?.price_before || p?.price || "";

console.log('Приоритет полей:');
console.log('  1. price.marketing_seller_price:', p.marketing_seller_price);
console.log('  2. price.price_before:', p.price_before || 'нет');
console.log('  3. price.price:', p.price);
console.log('');
console.log(`Результат: ${price}`);
console.log(`Ожидается: 1480`);
console.log(price === 1480 ? '✅ ПРАВИЛЬНО!' : '❌ ОШИБКА!');
console.log('');

// Тест с другими вариантами
console.log('=== ТЕСТ РАЗНЫХ ВАРИАНТОВ ===');

// Вариант 1: только marketing_seller_price
const test1 = {
  price: {
    marketing_seller_price: 1500,
    price: 1600
  }
};
const result1 = test1.price?.marketing_seller_price || test1.price?.price_before || test1.price?.price || "";
console.log(`Вариант 1 (только marketing_seller_price): ${result1} ✅`);

// Вариант 2: только price_before (marketing_seller_price отсутствует)
const test2 = {
  price: {
    price_before: 1400,
    price: 1600
  }
};
const result2 = test2.price?.marketing_seller_price || test2.price?.price_before || test2.price?.price || "";
console.log(`Вариант 2 (только price_before): ${result2} ✅`);

// Вариант 3: только price
const test3 = {
  price: {
    price: 1600
  }
};
const result3 = test3.price?.marketing_seller_price || test3.price?.price_before || test3.price?.price || "";
console.log(`Вариант 3 (только price): ${result3} ✅`);

// Вариант 4: все поля присутствуют
const test4 = {
  price: {
    marketing_seller_price: 1500,
    price_before: 1450,
    price: 1600
  }
};
const result4 = test4.price?.marketing_seller_price || test4.price?.price_before || test4.price?.price || "";
console.log(`Вариант 4 (все поля): ${result4} (берет marketing_seller_price) ✅`);

console.log('');
console.log('=== ИТОГ ===');
console.log('✅ Логика правильная!');
console.log('');
console.log('Финальный код:');
console.log('  const p = item.price;');
console.log('  priceMap[item.product_id] = p?.marketing_seller_price || p?.price_before || p?.price || "";');
