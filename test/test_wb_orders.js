/**
 * ТЕСТ WB ORDERS API
 * Симуляция ответа от Wildberries API для заказов
 */

console.log('=== ТЕСТ WB ORDERS (Уход Мес ВБ и Сумма заказов) ===\n');

// Симуляция ответа от WB API /api/v1/supplier/orders
const today = new Date('2026-02-03');
const dateFromMonth = new Date('2026-01-03'); // 30 дней назад
const dateFromQuarter = new Date('2025-11-04'); // 91 день назад

const wbOrdersResponse = {
  "orders": [
    {
      "orderId": "12345678",
      "article": "23348",  // Базовый артикул
      "sku": 0,
      "status": 1,  // 1 = новая (не отменена)
      "isCancel": false,
      "date": "2026-01-15T10:30:00",
      "quantity": 5,
      "totalPrice": 1895  // Цена за 5 штук
    },
    {
      "orderId": "12345679",
      "article": "23348",
      "sku": 0,
      "status": 1,
      "isCancel": false,
      "date": "2026-01-20T14:00:00",
      "quantity": 10,
      "totalPrice": 3790
    },
    {
      "orderId": "12345680",
      "article": "23348",
      "sku": 0,
      "status": 1,
      "isCancel": false,
      "date": "2026-01-25T09:15:00",
      "quantity": 20,
      "totalPrice": 7580
    },
    {
      "orderId": "12345681",
      "article": "23348",
      "sku": 0,
      "status": 1,
      "isCancel": false,
      "date": "2026-02-01T11:00:00",
      "quantity": 26,
      "totalPrice": 9854
    },
    // Отмененные заказы (должны игнорироваться)
    {
      "orderId": "12345682",
      "article": "23348",
      "sku": 0,
      "status": 0,  // 0 = отменена
      "isCancel": true,
      "date": "2026-01-28T10:00:00",
      "quantity": 15,
      "totalPrice": 5685
    },
    // Другие товары
    {
      "orderId": "12345683",
      "article": "22068",
      "sku": 0,
      "status": 1,
      "isCancel": false,
      "date": "2026-01-15T10:00:00",
      "quantity": 3,
      "totalPrice": 527
    }
  ]
};

console.log('1. WB API RESPONSE (orders):');
console.log(`   Всего заказов: ${wbOrdersResponse.orders.length}`);
console.log(`   Из них для артикула 23348: ${wbOrdersResponse.orders.filter(o => o.article === '23348').length}`);
console.log('');

// Логика обработки заказов
function processOrders(orders, article, startDate, endDate) {
  const validOrders = orders.filter(order => {
    const orderDate = new Date(order.date);
    const inPeriod = orderDate >= startDate && orderDate <= endDate;
    const rightArticle = order.article === article || order.article === article.split('-')[0];
    const notCancelled = !order.isCancel;
    return inPeriod && rightArticle && notCancelled;
  });

  const totalCount = validOrders.reduce((sum, o) => sum + o.quantity, 0);
  const totalSum = validOrders.reduce((sum, o) => sum + o.totalPrice, 0);

  return { count: totalCount, sum: totalSum, orders: validOrders };
}

console.log('2. ОБРАБОТКА ЗАКАЗОВ ДЛЯ 23348:');
console.log('');

// Месяц (30 дней)
const monthResult = processOrders(wbOrdersResponse.orders, "23348", dateFromMonth, today);
console.log('   МЕСЯЦ (последние 30 дней):');
console.log(`     Заказов (шт): ${monthResult.count}`);
console.log(`     Ожидается: 61`);
console.log(`     ${monthResult.count === 61 ? '✅ ПРАВИЛЬНО' : '❌ НЕПРАВИЛЬНО'}`);
console.log(`     Сумма (руб): ${monthResult.sum}`);
console.log(`     Ожидается: 23119`);
console.log(`     ${monthResult.sum === 23119 ? '✅ ПРАВИЛЬНО' : '❌ НЕПРАВИЛЬНО'}`);
console.log('');
console.log(`     Детали заказов:`);
monthResult.orders.forEach(o => {
  console.log(`       ${o.date}: ${o.quantity} шт. = ${o.totalPrice} руб.`);
});
console.log('');

// Проверка с учетом суффикса артикула
console.log('3. ПРОВЕРКА С УЧЕТОМ СУФФИКСА АРТИКУЛА:');
const articles = ["23348", "23348-1", "23348-2"];

articles.forEach(art => {
  const baseArt = art.split('-')[0];
  const result = processOrders(wbOrdersResponse.orders, art, dateFromMonth, today);

  console.log(`   Артикул "${art}":`);
  console.log(`     Базовый: "${baseArt}"`);
  console.log(`     Заказов: ${result.count} шт.`);
  console.log(`     Сумма: ${result.sum} руб.`);

  if (result.count > 0) {
    console.log(`     ✅ Данные найдены (по базовому артикулу "${baseArt}")`);
  } else {
    console.log(`     ❌ Данные не найдены`);
  }
  console.log('');
});

console.log('=== ВЫВОД ===');
console.log('✅ Логика обработки заказов правильная');
console.log('⚠️  НУЖНО УБИРАТЬ СУФФИКС (-1, -2) при сопоставлении с API!');
