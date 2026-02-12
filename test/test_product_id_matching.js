/**
 * ТЕСТ: Почему product_id не найден
 */

console.log('=== ТЕСТ СОПОСТАВЛЕНИЯ PRODUCT_ID ===\n');

// Данные из диагностики
const tableProductId = 424697904;  // Из таблицы
const searchProductId = 424697904;  // Что ищет функция

console.log('1. Проблема с типами данных:');
console.log('   В таблице: ' + tableProductId);
console.log('   Тип: ' + typeof tableProductId);
console.log('');

// Считывание из таблицы
console.log('2. Что возвращает getValues():');
const mockValues = [[424697904], [null], [12345], ['']];
console.log('   RAW: ' + JSON.stringify(mockValues));
console.log('');

// Логика фильтрации из функции
console.log('3. Логика фильтрации из getOzonPricesOptimized():');
console.log('   Код:');
console.log('   const productIds = productIdRange.map(r => r[0])');
console.log('       .filter(id => id !== \'\' && id !== null && id !== undefined && id > 0 && !isNaN(id));');
console.log('');

const filtered = mockValues.map(r => r[0]).filter(id => id !== '' && id !== null && id !== undefined && id > 0 && !isNaN(id));

console.log('   Результат фильтрации:');
console.log('   ' + JSON.stringify(filtered));
console.log('');

// Проверка: найден ли 424697904
const found = filtered.includes(424697904);
console.log('   Включен ли 424697904: ' + found);
console.log('');

if (!found) {
  console.log('   ❌ ПРОБЛЕМА НАЙДЕНА!');
  console.log('   Функция НЕ НАЙДЕТ product_id = 424697904');
} else {
  console.log('   ✅ 424697904 найден в массиве');
}

console.log('');
console.log('=== ПРОВЕРКА PAYLOAD ===');
console.log('Payload отправляется:');
console.log('  {');
console.log('    filter: { product_id: [424697904] },');
console.log('    limit: 1');
console.log('  }');
console.log('');
console.log('⚠️  ВОПРОС: API Ozon ожидает product_id как ЧИСЛО или СТРОКА?');
console.log('');
console.log('Посмотрим документацию API:');
console.log('  v5/product/info/prices:');
console.log('  filter: { product_id: [123, 456] } — числа');
console.log('');

console.log('=== РЕШЕНИЕ ===');
console.log('В коде используется chunk.map(Number):');
console.log('  const payload = JSON.stringify({');
console.log('    filter: { product_id: chunk.map(Number) },  // ← Преобразует в числа');
console.log('    limit: chunk.length');
console.log('  });');
console.log('');
console.log('Это правильно! API Ozon ожидает ЧИСЛА.');
console.log('');
console.log('Но可能 проблема в том, что в таблице product_id хранится как СТРОКА!');
