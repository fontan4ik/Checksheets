/**
 * ТЕСТ: Проверка правильного product_id
 */

console.log('=== ТЕСТ PRODUCT_ID ===\n');

// Данные из диагностики
const tableData = {
  article: "024108(2)-1",
  U_product_id: 608930963,  // Это Product_id Ozon!
  T_article_wb: 424697904,  // Это nmId (Артикул ВБ)
  current_price: 6258
};

console.log('Данные из таблицы:');
console.log('  Артикул: ' + tableData.article);
console.log('  U (21): Product_id Ozon = ' + tableData.U_product_id);
console.log('  T (20): Артикул ВБ (nmId) = ' + tableData.T_article_wb);
console.log('  K (11): Текущая цена = ' + tableData.current_price);
console.log('');

console.log('❌ ОШИБКА В ДИАГНОСТИКЕ:');
console.log('   Искали product_id = ' + tableData.T_article_wb);
console.log('   Но это nmId из колонки T!');
console.log('   Правильный product_id в колонке U = ' + tableData.U_product_id);
console.log('');

console.log('=== ПРОВЕРКА API ===');

// Симуляция API ответа для product_id = 608930963
const apiResponse = {
  items: [
    {
      product_id: 608930963,
      offer_id: "024108(2)-1",
      price: {
        price: "6258",
        marketing_seller_price: null,
        price_before: "49026",  // ✅ Вот она!
        min_price: "47000"
      }
    }
  ]
};

const item = apiResponse.items[0];
const p = item.price;

console.log('API ответ для product_id = ' + tableData.U_product_id + ':');
console.log('  price.price: ' + p.price);
console.log('  price.marketing_seller_price: ' + (p.marketing_seller_price || 'нет'));
console.log('  price.price_before: ' + p.price_before);
console.log('');

// Логика выбора
let selectedPrice = "";
if (p && p.marketing_seller_price !== null && p.marketing_seller_price !== undefined && p.marketing_seller_price !== "") {
  selectedPrice = p.marketing_seller_price;
} else if (p && p.price_before !== null && p.price_before !== undefined && p.price_before !== "") {
  selectedPrice = p.price_before;
} else {
  selectedPrice = p.price || "";
}

console.log('Результат логики:');
console.log('  Выбранная цена: ' + selectedPrice);
console.log('  Ожидается: 49026');
console.log('');

if (selectedPrice == 49026) {
  console.log('✅✅✅ ПРАВИЛЬНО!');
  console.log('');
  console.log('📋 РЕШЕНИЕ:');
  console.log('   Нужно запросить цену для product_id = ' + tableData.U_product_id);
  console.log('   А НЕ для ' + tableData.T_article_wb + ' (это nmId!)');
  console.log('');
  console.log('   Функция getOzonPricesOptimized() уже использует U (21),');
  console.log('   значит она должна вернуть 49026.');
  console.log('');
  console.log('   Возможно нужно:');
  console.log('   1. Перезапустить getOzonPricesOptimized()');
  console.log('   2. Или товар был обновлен в Ozon и цена изменилась');
}
