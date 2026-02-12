/**
 * ТЕСТ ЛОГИКИ С ?? (nullish coalescing)
 */

console.log('=== ТЕСТ ЛОГИКИ С ?? ===\n');

// Тест значений
const testValues = [
  { name: 'marketing_seller_price = 1480', ms: 1480, pb: null, p: 1516, expected: 1480 },
  { name: 'marketing_seller_price = null, price_before = 49026', ms: null, pb: 49026, p: 6258, expected: 49026 },
  { name: 'marketing_seller_price = 0, price_before = 4000', ms: 0, pb: 4000, p: 3500, expected: 0 },
  { name: 'marketing_seller_price = "", price_before = 3000', ms: "", pb: 3000, p: 2500, expected: 3000 },
  { name: 'Все поля null', ms: null, pb: null, p: null, expected: "" },
  { name: 'Только price', ms: null, pb: null, p: 5000, expected: 5000 },
];

console.log('=== ОПЕРАТОР || (старый) ===\n');
let oldPassed = 0;
testValues.forEach(t => {
  const result = t.ms || t.pb || t.p || "";
  const passed = result == t.expected;
  console.log(`${t.name}:`);
  console.log(`  Результат: ${result}, Ожидается: ${t.expected} - ${passed ? '✅' : '❌'}`);
  if (passed) oldPassed++;
});

console.log(`\nПройдено: ${oldPassed}/${testValues.length}\n`);

console.log('=== ОПЕРАТОР ?? (новый) ===\n');
let newPassed = 0;
testValues.forEach(t => {
  const result = t.ms ?? t.pb ?? t.p ?? "";
  const passed = result == t.expected;
  console.log(`${t.name}:`);
  console.log(`  Результат: ${result}, Ожидается: ${t.expected} - ${passed ? '✅' : '❌'}`);
  if (passed) newPassed++;
});

console.log(`\nПройдено: ${newPassed}/${testValues.length}\n`);

if (newPassed > oldPassed) {
  console.log('✅ Оператор ?? ЛУЧШЕ!');
} else if (newPassed === oldPassed) {
  console.log('⚠️  Результат одинаковый, но ?? безопаснее для 0');
} else {
  console.log('❌ Что-то не так...');
}

// Проверка конкретных товаров
console.log('\n=== ПРОВЕРКА КОНКРЕТНЫХ ТОВАРОВ ===\n');

console.log('22068-1:');
const p1 = { marketing_seller_price: 1480, price_before: null, price: 1516 };
const r1_old = p1.marketing_seller_price || p1.price_before || p1.price || "";
const r1_new = p1.marketing_seller_price ?? p1.price_before ?? p1.price ?? "";
console.log(`  Старый (||): ${r1_old} - ${r1_old == 1480 ? '✅' : '❌'}`);
console.log(`  Новый (??): ${r1_new} - ${r1_new == 1480 ? '✅' : '❌'}`);

console.log('\n024108(2)-1:');
const p2 = { marketing_seller_price: null, price_before: 49026, price: 6258 };
const r2_old = p2.marketing_seller_price || p2.price_before || p2.price || "";
const r2_new = p2.marketing_seller_price ?? p2.price_before ?? p2.price ?? "";
console.log(`  Старый (||): ${r2_old} - ${r2_old == 49026 ? '✅' : '❌'}`);
console.log(`  Новый (??): ${r2_new} - ${r2_new == 49026 ? '✅' : '❌'}`);

console.log('\nТовар с marketing_seller_price = 0:');
const p3 = { marketing_seller_price: 0, price_before: 4000, price: 3500 };
const r3_old = p3.marketing_seller_price || p3.price_before || p3.price || "";
const r3_new = p3.marketing_seller_price ?? p3.price_before ?? p3.price ?? "";
console.log(`  Старый (||): ${r3_old} - ${r3_old == 0 ? '✅' : '❌ (берет 4000 вместо 0)'}`);
console.log(`  Новый (??): ${r3_new} - ${r3_new == 0 ? '✅' : '❌'}`);

console.log('\n=== ВЫВОД ===');
console.log('Для товаров 22068-1 и 024108(2)-1 БЕЗ РАЗНИЦЫ (оба оператора работают).');
console.log('Но ?? лучше для случая marketing_seller_price = 0.');
console.log('');
console.log('ПРОБЛЕМА: В таблице 6258 вместо 49026 для 024108(2)-1');
console.log('ПРИЧИНА: Не выполнена функция getOzonPricesOptimized() после исправления!');
