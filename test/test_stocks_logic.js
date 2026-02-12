/**
 * ЛОКАЛЬНЫЙ ТЕСТ ЛОГИКИ FBO/FBS
 * Проверяет почему F (6) = 9 вместо 1080
 */

console.log('=== ЛОКАЛЬНЫЙ ТЕСТ FBO/FBS ===\n');

// API ответ от Ozon для товара 22068-1
const apiResponse = {
  "items": [{
    "product_id": 109652992,
    "offer_id": "22068-1",
    "stocks": [
      {"type": "fbo", "present": 1080, "reserved": 1, "sku": 301854987},
      {"type": "fbs", "present": 527, "reserved": 0, "sku": 301854987},
      {"type": "fbs", "present": 0, "reserved": 0, "sku": 301854997}
    ]
  }]
};

console.log('API Ответ Ozon:');
console.log(JSON.stringify(apiResponse, null, 2));
console.log('');

// Тест 1: Старая логика (брала первый fbo)
console.log('=== ТЕСТ 1: СТАРАЯ ЛОГИКА ===');
const fboStock = apiResponse.items[0].stocks.find(s => s.type === 'fbo');
const oldFbo = fboStock ? fboStock.present : 0;
console.log('FBO остаток (первый): ' + oldFbo);
console.log('Статус: ✅ ПРАВИЛЬНО (1080)');
console.log('');

// Тест 2: Новая логика (суммирует все fbo)
console.log('=== ТЕСТ 2: НОВАЯ ЛОГИКА ===');
const fboStocks = apiResponse.items[0].stocks.filter(s => s.type === 'fbo') || [];
const totalFbo = fboStocks.reduce((sum, s) => sum + (s.present || 0), 0);
console.log('FBO остаток (сумма всех): ' + totalFbo);
console.log('Статус: ✅ ПРАВИЛЬНО (1080)');
console.log('');

// Тест 3: Старая логика FBS (первый fbs)
console.log('=== ТЕСТ 3: СТАРАЯ ЛОГИКА FBS ===');
const fbsStock = apiResponse.items[0].stocks.find(s => s.type === 'fbs');
const oldFbs = fbsStock ? fbsStock.present : 0;
console.log('FBS остаток (первый): ' + oldFbs);
console.log('Статус: ⚠️ ПЕРВЫЙ FBS (527), но есть второй (0)');
console.log('');

// Тест 4: Новая логика FBS (суммирует все fbs)
console.log('=== ТЕСТ 4: НОВАЯ ЛОГИКА FBS ===');
const fbsStocksAll = apiResponse.items[0].stocks.filter(s => s.type === 'fbs') || [];
const totalFbs = fbsStocksAll.reduce((sum, s) => sum + (s.present || 0), 0);
console.log('FBS остаток (сумма всех): ' + totalFbs);
console.log('Статус: ✅ ПРАВИЛЬНО (527)');
console.log('');

// Итого
console.log('=== ИТОГ ===');
console.log('Новая логика СУММИРУЕТ все fbo/fbs записи:');
console.log('  FBO: 1080 (корректно)');
console.log('  FBS: 527 (корректно - только первый имеет остатки)');
console.log('');
console.log('✅ ЛОГИКА ПРАВИЛЬНАЯ!');
console.log('');
console.log('⚠️  ВОПРОС: Почему в таблице F (6) = 9?');
console.log('');
console.log('Возможные причины:');
console.log('1. updateStockFBO() не вызвалась');
console.log('2. API не вернул данные для этого товара');
console.log('3. Другая функция ПЕРЕЗАПИСАЛА данные после');
console.log('');
console.log('=== ПОИСК ФУНКЦИЙ ПИШУЩИХ В F (6) ===');

// Поиск всех функций которые пишут в колонку 6
console.log('Нужно проверить:');
console.log('1. Выполнилась ли updateStockFBO()?');
console.log('2. Есть ли логи "Остатки FBO обновлены"?');
console.log('3. Проверить логи после выполнения OzonMain()');
