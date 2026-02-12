/**
 * ТЕСТ WB STOCKS API
 * Симуляция ответа от Wildberries API для остатков
 */

console.log('=== ТЕСТ WB STOCKS (Остатки ФБО и ФБС) ===\n');

// Симуляция ответа от WB API /api/v1/supplier/stocks
const wbStocksResponse = {
  "stocks": [
    {
      "sku": "23348",
      "supplierArticle": "23348",
      "warehouseId": 1449484,  // Коледино - ФБО
      "quantity": 128,  // Остаток ФБО = 128
      "inWayToClient": 0,
      "inWayFromClient": 0,
      "nmId": 0,
      "subject": "Светильники",
      "category": "Светильники",
      "brand": "Feron",
      "techSize": "0",
      "incomeDate": "2025-01-15T10:00:00"
    },
    {
      "sku": "23348",
      "supplierArticle": "23348",
      "warehouseId": 798761,  // ФБС склад
      "quantity": 0,  // Остаток ФБС = 0
      "inWayToClient": 0,
      "inWayFromClient": 0,
      "nmId": 0,
      "subject": "Светильники",
      "category": "Светильники",
      "brand": "Feron",
      "techSize": "0",
      "incomeDate": "2025-01-15T10:00:00"
    },
    // Другие товары
    {
      "sku": "22068",
      "supplierArticle": "22068",
      "warehouseId": 1449484,
      "quantity": 50,
      "inWayToClient": 0,
      "inWayFromClient": 0,
      "nmId": 0,
      "subject": "Датчики",
      "category": "Датчики",
      "brand": "Feron",
      "techSize": "0"
    }
  ]
};

console.log('1. WB API RESPONSE (stocks):');
console.log(JSON.stringify(wbStocksResponse, null, 2));
console.log('');

// Логика из updateStockFromWB()
function processStocks(stocks, warehouseId, article) {
  // Ищем остаток для артикула на складе
  const stock = stocks.find(s =>
    s.supplierArticle === article &&
    s.warehouseId === warehouseId
  );
  return stock ? stock.quantity : 0;
}

const testArticle = "23348";
const fboWarehouseId = 1449484;  // Коледино - ФБО
const fbsWarehouseId = 798761;    // ФБС

console.log('2. ОБРАБОТКА ДЛЯ 23348-1:');
console.log(`   Артикул: ${testArticle}`);
console.log(`   Склад ФБО (ID: ${fboWarehouseId}):`);
const fboStock = processStocks(wbStocksResponse.stocks, fboWarehouseId, testArticle);
console.log(`      Остаток: ${fboStock} шт. ${fboStock === 128 ? '✅' : '❌ (ожидается 128)'}`);
console.log('');
console.log(`   Склад ФБС (ID: ${fbsWarehouseId}):`);
const fbsStock = processStocks(wbStocksResponse.stocks, fbsWarehouseId, testArticle);
console.log(`      Остаток: ${fbsStock} шт. ${fbsStock === 0 ? '✅' : '❌ (ожидается 0)'}`);
console.log('');

// Проверка логики из ВБ.gs
console.log('3. ЛОГИКА ИЗ ВБ.gs (updateStockFromWB):');
console.log('   Функция читает артикулы из колонки A (1)');
console.log('   Формирует массив articles');
console.log('   Дергает API для склада 1449484');
console.log('   Записывает в O (15): Остаток ФБО ВБ');
console.log('   Дергает API для склада 798761');
console.log('   Записывает в P (16): Остаток ФБС ВБ');
console.log('');

// Проблема: что если API возвращает артикул с суффиксом?
console.log('4. ВОЗМОЖНАЯ ПРОБЛЕМА - формат артикула:');
const articlesFromTable = ["23348-1", "23348-2", "23348"];  // Из таблицы
const articlesFromApi = ["23348", "22068"];  // Из API

console.log('   Артикулы из таблицы (A):');
articlesFromTable.forEach(a => console.log(`     "${a}"`));
console.log('');
console.log('   Артикулы из API:');
articlesFromApi.forEach(a => console.log(`     "${a}"`));
console.log('');
console.log('   Сопоставление:');
articlesFromTable.forEach(article => {
  // Логика: ищем по полному совпадению
  const found = wbStocksResponse.stocks.find(s => s.supplierArticle === article);
  if (found) {
    console.log(`     "${article}" → ✅ НАЙДЕН (количество: ${found.quantity})`);
  } else {
    // Пробуем найти по первой части (до дефиса)
    const baseArticle = article.split('-')[0];
    const foundByBase = wbStocksResponse.stocks.find(s => s.supplierArticle === baseArticle);
    if (foundByBase) {
      console.log(`     "${article}" → ⚠️  НЕ НАЙДЕН, но есть "${baseArticle}" (количество: ${foundByBase.quantity})`);
    } else {
      console.log(`     "${article}" → ❌ НЕ НАЙДЕН`);
    }
  }
});
console.log('');

console.log('=== ВЫВОД ===');
console.log('Если в таблице артикулы с суффиксом (23348-1, 23348-2),');
console.log('а API возвращает базовые артикулы (23348),');
console.log('ТО НУЖНО УБРАТЬ СУФФИКСЫ ПРИ ПОИСКЕ!');
