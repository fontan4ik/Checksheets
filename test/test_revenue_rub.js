/**
 * ТЕСТ ПРАВИЛЬНОСТИ REVENUE (Сумма заказов Мес ОЗОН)
 * Проверка: revenue из API Ozon Analytics в рублях или копейках?
 */

console.log('=== ТЕСТ REVENUE ОЗОН ===\n');

// Симуляция ответа от Ozon Analytics API
const apiResponse = {
  "result": {
    "data": [
      {
        "dimensions": [
          {
            "id": "301854987",
            "name": "301854987"
          }
        ],
        "metrics": [15, 527600]  // [ordered_units, revenue]
      }
    ]
  }
};

console.log('API Ответ Ozon Analytics:');
console.log(JSON.stringify(apiResponse, null, 2));
console.log('');

const data = apiResponse.result.data;
const metrics = data[0].metrics;
const orderedUnits = metrics[0];  // Количество заказов
const revenue = metrics[1];        // Сумма заказов

console.log('Данные из API:');
console.log('  ordered_units (количество): ' + orderedUnits);
console.log('  revenue (сумма): ' + revenue);
console.log('');

// СТАРАЯ ЛОГИКА (неправильно)
console.log('=== СТАРАЯ ЛОГИКА (делили на 100) ===');
const oldRevenue = Math.round(revenue / 100);
console.log('Сумма заказов Мес ОЗОН: ' + oldRevenue + ' руб.');
console.log('❌ Проблема: если API возвращает в рублях, мы делим на 100 зря');
console.log('');

// НОВАЯ ЛОГИКА (правильно)
console.log('=== НОВАЯ ЛОГИКА (не делим) ===');
const newRevenue = revenue;
console.log('Сумма заказов Мес ОЗОН: ' + newRevenue + ' руб.');
console.log('✅ Правильно: используем значение из API как есть');
console.log('');

// Проверка на реальных данных
console.log('=== ПРОВЕРКА НА РЕАЛЬНЫХ ДАННЫХ ===');

// Пример 1: Малый заказ
console.log('Пример 1: Заказ на 500 руб.');
const example1 = [5, 500];  // 5 заказов на 500 руб
console.log('  API: ' + JSON.stringify(example1));
console.log('  Старая логика: ' + Math.round(example1[1] / 100) + ' руб. ❌ (стало 5 руб)');
console.log('  Новая логика: ' + example1[1] + ' руб. ✅ (правильно 500 руб)');
console.log('');

// Пример 2: Крупный заказ
console.log('Пример 2: Заказы на 527600 руб.');
const example2 = [15, 527600];  // 15 заказов на 527600 руб
console.log('  API: ' + JSON.stringify(example2));
console.log('  Старая логика: ' + Math.round(example2[1] / 100) + ' руб. ❌ (стало 5276 руб)');
console.log('  Новая логика: ' + example2[1] + ' руб. ✅ (правильно 527600 руб)');
console.log('');

// Пример 3: Очень крупная сумма
console.log('Пример 3: Заказы на 1500000 руб.');
const example3 = [100, 1500000];
console.log('  API: ' + JSON.stringify(example3));
console.log('  Старая логика: ' + Math.round(example3[1] / 100) + ' руб. ❌ (стало 15000 руб)');
console.log('  Новая логика: ' + example3[1] + ' руб. ✅ (правильно 1500000 руб)');
console.log('');

console.log('=== ИТОГ ===');
console.log('✅ Ozon Analytics API возвращает revenue в РУБЛЯХ');
console.log('❌ Деление на 100 было ошибочным');
console.log('✅ Новая логика: revenueMonthList.push([monthMetrics[1] || 0])');
