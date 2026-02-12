/**
 * ТЕСТ ИСПРАВЛЕНИЯ: Проверка правильности маппинга данных
 * Проблема: valuesToWrite.length != fullProductIds.length
 * Результат: данные пишутся не в те строки
 */

console.log('=== ТЕСТ ИСПРАВЛЕНИЯ МАССИВА ===\n');

// Симуляция данных из таблицы
const fullProductIds = [
  109652992,  // position 0 → row 2  (22068-1)
  0,          // position 1 → row 3  (невалидный)
  '',         // position 2 → row 4  (пустой)
  null,       // position 3 → row 5  (null)
  123456789,  // position 4 → row 6  (другой товар)
  987654321,  // position 5 → row 7  (еще один)
  0,          // position 6 → row 8  (невалидный)
  111111111   // position 7 → row 9  (последний валидный)
];

console.log('fullProductIds (все строки из таблицы):');
console.log(fullProductIds);
console.log('Всего строк: ' + fullProductIds.length);
console.log('');

// Отфильтрованные (старый логик)
const fullProductIdsFull = fullProductIds
  .filter(id => id !== '' && id !== null && id !== undefined && id > 0);

console.log('fullProductIdsFull (отфильтрованные):');
console.log(fullProductIdsFull);
console.log('Всего валидных: ' + fullProductIdsFull.length);
console.log('');

// API данные
const stockMap = {
  '109652992': 1080,  // 22068-1
  '123456789': 500,
  '987654321': 200,
  '111111111': 150
};

console.log('stockMap (данные из API):');
console.log(JSON.stringify(stockMap, null, 2));
console.log('');

// СТАРАЯ ЛОГИКА (НЕПРАВИЛЬНАЯ)
console.log('=== СТАРАЯ ЛОГИКА (ОШИБКА) ===');
const oldValuesToWrite = fullProductIdsFull.map(pid => {
  const key = pid?.toString();
  return [key && key !== "" ? stockMap[key] ?? '' : ''];
});

console.log('valuesToWrite (длина: ' + oldValuesToWrite.length + '):');
console.log(JSON.stringify(oldValuesToWrite));
console.log('');

console.log('ЗАПИСЬ в таблицу (столбец F, строки 2-' + (1 + oldValuesToWrite.length) + '):');
oldValuesToWrite.forEach((val, i) => {
  const rowNum = i + 2;
  const originalPid = fullProductIds[i];
  const expectedPid = fullProductIdsFull[i];
  console.log(`  F${rowNum}: ${val[0]} ← для product_id=${expectedPid} (оригинал позиция ${i}: ${originalPid})`);
});
console.log('');

console.log('❌ ПРОБЛЕМА:');
console.log('   - Пишем только ' + oldValuesToWrite.length + ' значений');
console.log('   - А всего строк ' + fullProductIds.length);
console.log('   - Последние ' + (fullProductIds.length - oldValuesToWrite.length) + ' строк НЕ ОБНОВЛЯЮТСЯ!');
console.log('');

// Если 111111111 находится после позиции 4 (длина отфильтрованного)
console.log('ПРИМЕР: product_id=111111111 на позиции 7:');
console.log('   → В fullProductIdsFull: position 5 (после фильтрации)');
console.log('   → Но valuesToWrite имеет длину ' + oldValuesToWrite.length);
console.log('   → Значение 150 запишется в строку ' + (2 + 5) + ', а не в строку 9!');
console.log('   → Фактически, строка 9 НЕ ОБНОВИТСЯ (останется старое значение 9)');
console.log('');

// НОВАЯ ЛОГИКА (ПРАВИЛЬНАЯ)
console.log('=== НОВАЯ ЛОГИКА (ИСПРАВЛЕНО) ===');
const newValuesToWrite = fullProductIds.map(pid => {
  const key = pid?.toString();
  if (key && key !== "" && pid !== '' && pid !== null && pid !== undefined && pid > 0) {
    return [stockMap[key] ?? ''];
  }
  return [''];
});

console.log('valuesToWrite (длина: ' + newValuesToWrite.length + '):');
console.log(JSON.stringify(newValuesToWrite));
console.log('');

console.log('ЗАПИСЬ в таблицу (столбец F, строки 2-' + (1 + newValuesToWrite.length) + '):');
newValuesToWrite.forEach((val, i) => {
  const rowNum = i + 2;
  const pid = fullProductIds[i];
  console.log(`  F${rowNum}: ${val[0]} ← для product_id=${pid}`);
});
console.log('');

console.log('✅ ПРАВИЛЬНО:');
console.log('   - Пишем ' + newValuesToWrite.length + ' значений (равно количеству строк)');
console.log('   - Все строки обновляются корректно');
console.log('   - product_id=111111111 → значение 150 попадет в F9');
console.log('');

// Итоговая проверка
console.log('=== ПРОВЕРКА КОРРЕКТНОСТИ ===');

let errors = [];

newValuesToWrite.forEach((val, i) => {
  const pid = fullProductIds[i];
  const rowNum = i + 2;

  // Проверяем соответствие
  if (pid && pid !== '' && pid !== null && pid !== undefined && pid > 0) {
    const expected = stockMap[pid.toString()] ?? '';
    const actual = val[0];

    if (actual !== expected) {
      errors.push(`Строка ${rowNum} (product_id=${pid}): ожидается ${expected}, получено ${actual}`);
    } else {
      console.log(`✅ Строка ${rowNum} (product_id=${pid}): ${actual} - ПРАВИЛЬНО`);
    }
  } else {
    if (val[0] !== '') {
      errors.push(`Строка ${rowNum} (невалидный product_id): ожидается '', получено ${val[0]}`);
    } else {
      console.log(`✅ Строка ${rowNum} (невалидный product_id): '' - ПРАВИЛЬНО`);
    }
  }
});

console.log('');
if (errors.length === 0) {
  console.log('✅✅✅ ВСЁ ПРАВИЛЬНО! НОВАЯ ЛОГИКА РАБОТАЕТ КОРРЕКТНО!');
} else {
  console.log('❌❌❌ ОШИБКИ:');
  errors.forEach(e => console.log('   ' + e));
}
