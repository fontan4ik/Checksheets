/**
 * ТЕСТ ПОЛЕЙ ЦЕНЫ OZON API v5
 * Проверка различных полей цены
 */

console.log('=== ТЕСТ ПОЛЕЙ ЦЕНЫ OZON ===\n');

// Симуляция ответа от Ozon Prices API v5
const ozonPriceResponse = {
  "items": [
    {
      "product_id": 109652992,
      "price": {
        "price": "1516",              // Текущая цена (что мы используем)
        "price_before": "1480",       // Базовая цена (возможно нужно брать эту!)
        "price_before_first": "1480", // Первоначальная цена
        "premium_price": "1550",      // Премиум цена
        "currency_code": "RUB"
      }
    }
  ]
};

console.log('API Ответ Ozon Prices (v5):');
console.log(JSON.stringify(ozonPriceResponse, null, 2));
console.log('');

const item = ozonPriceResponse.items[0];

console.log('=== АНАЛИЗ ПОЛЕЙ ЦЕНЫ ===');
console.log('Текущее поле (price.price):');
console.log(`  Значение: "${item.price.price}"`);
console.log(`  Тип: ${typeof item.price.price}`);
console.log(`  Число: ${Number(item.price.price)}`);
console.log('');

console.log('Альтернативные поля:');
console.log(`  price.price_before: "${item.price.price_before}" → ${Number(item.price.price_before)}`);
console.log(`  price.price_before_first: "${item.price.price_before_first}" → ${Number(item.price.price_before_first)}`);
console.log(`  price.premium_price: "${item.price.premium_price}" → ${Number(item.price.premium_price)}`);
console.log('');

console.log('=== ПРОВЕРКА ЛОГИКИ ===');

// СТАРАЯ ЛОГИКА
const oldPrice = item.price.price;
console.log('СТАРАЯ ЛОГИКА (price.price):');
console.log(`  Цена: ${oldPrice}`);
console.log(`  Ожидается: 1480`);
console.log(`  ${oldPrice === "1480" ? '✅ ПРАВИЛЬНО' : '❌ НЕПРАВИЛЬНО (разница: ' + (Number(oldPrice) - 1480) + ')'}`);
console.log('');

// НОВАЯ ЛОГИКА (вариант 1)
const newPrice1 = item.price.price_before || item.price.price;
console.log('НОВАЯ ЛОГИКА ВАРИАНТ 1 (price_before, если есть, иначе price):');
console.log(`  Цена: ${newPrice1}`);
console.log(`  ${newPrice1 === "1480" ? '✅ ПРАВИЛЬНО' : '❌'}`);
console.log('');

// НОВАЯ ЛОГИКА (вариант 2)
const newPrice2 = item.price.price_before_first || item.price.price_before || item.price.price;
console.log('НОВАЯ ЛОГИКА ВАРИАНТ 2 (price_before_first -> price_before -> price):');
console.log(`  Цена: ${newPrice2}`);
console.log(`  ${newPrice2 === "1480" ? '✅ ПРАВИЛЬНО' : '❌'}`);
console.log('');

// НОВАЯ ЛОГИКА (вариант 3 - минимальная цена)
const prices = [
  Number(item.price.price) || 0,
  Number(item.price.price_before) || 0,
  Number(item.price.price_before_first) || 0
].filter(p => p > 0);
const minPrice = Math.min(...prices);
console.log('НОВАЯ ЛОГИКА ВАРИАНТ 3 (минимальная цена):');
console.log(`  Цена: ${minPrice}`);
console.log(`  ${minPrice === 1480 ? '✅ ПРАВИЛЬНО' : '❌'}`);
console.log('');

console.log('=== РЕКОМЕНДАЦИЯ ===');

if (item.price.price_before && Number(item.price.price_before) === 1480) {
  console.log('✅ Используйте price.price_before вместо price.price');
  console.log('');
  console.log('Код:');
  console.log('  // СТАРАЯ:');
  console.log('  priceMap[item.product_id] = item.price?.price || "";');
  console.log('');
  console.log('  // НОВАЯ:');
  console.log('  priceMap[item.product_id] = item.price?.price_before || item.price?.price || "";');
} else if (item.price.price_before_first && Number(item.price.price_before_first) === 1480) {
  console.log('✅ Используйте price.price_before_first вместо price.price');
} else {
  console.log('⚠️  Не удалось определить правильное поле');
  console.log('   Запустите diagnoseOzonPrice() в Apps Script');
}
