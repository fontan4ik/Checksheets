/**
 * ТЕСТ ДАННЫХ ДЛЯ ТОВАРА 024108(2)-1
 * Сравнение текущих и правильных значений
 */

console.log('=== ТЕСТ ТОВАРА 024108(2)-1 ===\n');

// Данные из таблицы
const tableData = {
  article: "024108(2)-1",
  F: 4,   // F (6): Остаток ФБО ОЗОН
  G: 189, // G (7): Остаток ФБС ОЗОН
  H: 0,   // H (8): ОСТ ФБС МСК ОЗОН
  I: 15,  // I (9): Уход Мес ОЗОН
  J: 84,  // J (10): Уход КВ
  K: 6258, // K (11): ЦЕНА ОЗОН ← НЕПРАВИЛЬНО! Должно быть 49026
  L: 3,   // L (12): Сумма заказов Мес ОЗОН
  M: 4540, // M (13): ЦЕНА ВБ
  N: 45400, // N (14): Сумма заказов Мес ВБ ← НЕПРАВИЛЬНО! Должно быть 108
  O: 10,  // O (15): Остаток ФБО ВБ
  P: 13,  // P (16): Остаток ФБС ВБ
  Q: 2044144882571, // Q (17): ОСТ ФБС МСК ВБ ← НЕПРАВИЛЬНО! Похоже на баркод. Должно быть 50
};

// Правильные данные
const correctData = {
  F: 4,
  G: 189,
  H: 0,
  I: 15,
  J: 84,
  K: 49026,  // ЦЕНА ОЗОН — нужно исправить
  L: 3,
  M: 4540,
  N: 108,    // Сумма заказов Мес ВБ — нужно исправить
  O: 10,
  P: 13,
  Q: 50,     // Остаток ФБС МСК ВБ — нужно исправить
};

console.log('=== СРАВНЕНИЕ ДАННЫХ ===\n');

const columns = {
  F: 'Остаток ФБО ОЗОН',
  G: 'Остаток ФБС ОЗОН',
  H: 'ОСТ ФБС МСК ОЗОН',
  I: 'Уход Мес ОЗОН',
  J: 'Уход КВ',
  K: 'ЦЕНА ОЗОН',
  L: 'Сумма заказов Мес ОЗОН',
  M: 'ЦЕНА ВБ',
  N: 'Сумма заказов Мес ВБ',
  O: 'Остаток ФБО ВБ',
  P: 'Остаток ФБС ВБ',
  Q: 'ОСТ ФБС МСК ВБ'
};

const issues = [];
const correct = [];

Object.keys(columns).forEach(col => {
  const current = tableData[col];
  const expected = correctData[col];
  const match = current === expected;

  console.log(`${col} (${columns[col]}):`);
  console.log(`  Текущее: ${current}`);
  console.log(`  Ожидается: ${expected}`);
  console.log(`  ${match ? '✅ ПРАВИЛЬНО' : '❌ НЕПРАВИЛЬНО'}`);
  console.log('');

  if (!match) {
    issues.push({ col, name: columns[col], current, expected });
  } else {
    correct.push(col);
  }
});

console.log('=== ИТОГ ===');
console.log(`Правильных полей: ${correct.length}`);
console.log(`Неправильных полей: ${issues.length}`);
console.log('');

if (issues.length > 0) {
  console.log('❌ ПРОБЛЕМНЫЕ ПОЛЯ:');
  issues.forEach(issue => {
    const diff = issue.expected - issue.current;
    console.log(`   ${issue.col} (${issue.name}):`);
    console.log(`     Текущее: ${issue.current}`);
    console.log(`     Ожидается: ${issue.expected}`);
    console.log(`     Разница: ${diff}`);
  });
  console.log('');

  // Анализ проблем
  console.log('=== АНАЛИЗ ПРОБЛЕМ ===');

  issues.forEach(issue => {
    if (issue.col === 'K') {
      console.log(`🔍 ЦЕНА ОЗОН (K):`);
      console.log(`   Текущее: ${issue.current} → Ожидается: ${issue.expected}`);
      console.log(`   Проблема: Используется price.price вместо price.marketing_seller_price`);
      console.log(`   Или: API возвращает другие поля для этого товара`);
    }

    if (issue.col === 'N') {
      console.log(`🔍 СУММА ЗАКАЗОВ МЕС ВБ (N):`);
      console.log(`   Текущее: ${issue.current} → Ожидается: ${issue.expected}`);
      console.log(`   Разница в ${issue.expected - issue.current} раз!`);
      console.log(`   Возможные причины:`);
      console.log(`   1. Используется старый API (orders) без фильтрации по периоду`);
      console.log(`   2. Артикул сопоставляется неправильно (024108(2)-1 vs 024108(2))`);
      console.log(`   3. Суммируются все заказы вместо последних 30 дней`);
    }

    if (issue.col === 'Q') {
      console.log(`🔍 ОСТ ФБС МСК ВБ (Q):`);
      console.log(`   Текущее: ${issue.current} (похоже на баркод!)`);
      console.log(`   Ожидается: ${issue.expected}`);
      console.log(`   Проблема: Записывается barcode вместо stock quantity`);
      console.log(`   Нужно проверить: WB FBS Москва.gs`);
    }
  });
}

console.log('');
console.log('=== РЕКОМЕНДАЦИИ ===');
console.log('1. Запустить diagnoseOzonPrice() для проверки полей цены');
console.log('2. Проверить WB API для артикула 024108(2)');
console.log('3. Убедиться что функции используют базовые артикулы (без суффиксов)');
console.log('4. Проверить что Q (17) записывает amount, а не barcode');
