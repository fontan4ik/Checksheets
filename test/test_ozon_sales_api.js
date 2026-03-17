/**
 * Тестирование API вызова для проверки продаж по конкретному SKU
 * SKU: 1058595888
 * offer_id: 301854987
 */

const fs = require('fs');
const path = require('path');

// Эмуляция функций Google Apps Script для локального тестирования
function formatDateTimeForAPI(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  const seconds = String(date.getSeconds()).padStart(2, '0');
  return `${year}-${month}-${day}T${hours}:${minutes}:${seconds}Z`;
}

// Получить диапазон дат для месяца (от сегодня до того же дня прошлого месяца)
function getMonthDateRangeForAnalytics() {
  const today = new Date();
  const startDate = new Date(today);

  // Вычитаем 1 месяц
  startDate.setMonth(startDate.getMonth() - 1);

  // Если в предыдущем месяце меньше дней, чем в текущем,
  // то установим последний день предыдущего месяца
  if (startDate.getDate() !== today.getDate()) {
    // Вернемся к последнему дню предыдущего месяца
    startDate.setDate(0);
  }

  return {
    start: startDate,
    end: today
  };
}

// Тестируем вызов API
async function testOzonSalesAPI() {
  console.log('🔍 Тестируем API вызов для SKU 1058595888...');

  const monthRange = getMonthDateRangeForAnalytics();
  console.log(`📅 Диапазон дат: ${formatDateTimeForAPI(monthRange.start)} → ${formatDateTimeForAPI(monthRange.end)}`);

  // Подготовим тело запроса
  const body = {
    date_from: formatDateTimeForAPI(monthRange.start),
    date_to: formatDateTimeForAPI(monthRange.end),
    dimensions: ["sku", "fulfillment_type"], // Требуется указать размерности
    metrics: ["ordered_units"], // Используем метрики для получения данных о продажах (ordered_units - это проданные единицы)
    filters: [
      {
        column: "fulfillment_type",
        operation: "eq",
        values: ["fbo"]  // Проверим сначала FBO
      },
      {
        column: "sku",
        operation: "in",
        values: ["1058595888"]  // Тестируемый SKU
      }
    ],
    limit: 1000  // Добавляем лимит, как того требует API
  };

  console.log('📋 Тело запроса:', JSON.stringify(body, null, 2));

  // Здесь должен быть реальный вызов API
  // Но так как мы не можем сделать реальный вызов без ключей API,
  // создадим заглушку для демонстрации

  console.log('\n⚠️  Для настоящего тестирования необходимо использовать реальные API ключи.');
  console.log('💡 Пожалуйста, проверьте настройки API ключей в вашем приложении.');

  // Симулируем возможный ответ API
  console.log('\n🔄 Симуляция ответа API:');
  console.log('Предполагаемый формат ответа:');
  console.log(JSON.stringify({
    "result": {
      "data": [
        {
          "dimensions": [
            {
              "dimension_type": "sku",
              "id": "1058595888"
            },
            {
              "dimension_type": "fulfillment_type",
              "id": "fbo"
            }
          ],
          "metrics": [15]  // 15 проданных единиц
        }
      ]
    }
  }, null, 2));
}

// Запуск теста
testOzonSalesAPI()
  .then(() => console.log('\n✅ Тест завершен'))
  .catch(err => console.error('❌ Ошибка:', err));