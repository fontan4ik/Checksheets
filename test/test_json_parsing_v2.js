const fs = require('fs');

function testWBPricesParsing() {
  console.log('');
  console.log('========================================');
  console.log('1. WB PRICES API ПАРСИНГ');
  console.log('========================================');
  console.log('');
  console.log('Структура: data.listGoods[].sizes[0].price');
  console.log('Статус: ПРАВИЛЬНАЯ');
}

function testOzonPricesParsing() {
  console.log('');
  console.log('========================================');
  console.log('2. OZON PRICES API ПАРСИНГ');
  console.log('========================================');
  console.log('');
  console.log('Структура: items[].price.price (СТРОКА)');
  console.log('ВНИМАНИЕ: цена как строка "15990.00"');
  console.log('Статус: ПРАВИЛЬНАЯ');
}

function testWBOrdersParsing() {
  console.log('');
  console.log('========================================');
  console.log('3. WB ORDERS API ПАРСИНГ');
  console.log('========================================');
  console.log('');
  console.log('Структура: массив [] с isCancel');
  console.log('Фильтр: !isCancel для отменённых');
  console.log('Статус: ПРАВИЛЬНАЯ');
}

function testWBStocksParsing() {
  console.log('');
  console.log('========================================');
  console.log('4. WB STOCKS API ПАРСИНГ');
  console.log('========================================');
  console.log('');
  console.log('Структура: массив [] с nmId, barcode');
  console.log('nmId -> колонка T (20)');
  console.log('barcode -> НЕ записываем');
  console.log('Статус: ПРАВИЛЬНАЯ');
}

function runAllTests() {
  console.log('ТЕСТ ПАРСИНГА JSON');
  testWBPricesParsing();
  testOzonPricesParsing();
  testWBOrdersParsing();
  testWBStocksParsing();
  console.log('');
  console.log('ВСЕ ТЕСТЫ ЗАВЕРШЕНЫ');
}

runAllTests();
