/**
 * Тестирование API вызова для проверки продаж по конкретному SKU
 * SKU: 1058595888
 * offer_id: 301854987
 */

const axios = require('axios');

// Реальные API данные
const clientId = '142355';
const apiKey = 'fe539630-170b-4b48-b222-8ba092907a63';

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
  console.log('🔍 Тестируем реальный API вызов для SKU 1058595888...');

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

  try {
    const response = await axios.post(
      'https://api-seller.ozon.ru/v1/analytics/data',
      body,
      {
        headers: {
          'Client-Id': clientId,
          'Api-Key': apiKey,
          'Content-Type': 'application/json'
        }
      }
    );

    console.log('✅ Успешный ответ от API:');
    console.log(JSON.stringify(response.data, null, 2));

    // Анализируем данные
    if (response.data && response.data.result && response.data.result.data) {
      const items = response.data.result.data;
      console.log(`\n📊 Найдено ${items.length} записей:`);

      items.forEach((item, index) => {
        console.log(`${index + 1}. Dimensions:`, item.dimensions);
        console.log(`   Metrics:`, item.metrics);

        const skuDim = item.dimensions?.find(dim => dim.dimension_type === 'sku');
        const fulfillmentDim = item.dimensions?.find(dim => dim.dimension_type === 'fulfillment_type');

        if (skuDim && fulfillmentDim) {
          console.log(`   SKU: ${skuDim.id}, Fulfillment: ${fulfillmentDim.id}`);

          if (item.metrics && Array.isArray(item.metrics) && item.metrics.length > 0) {
            const metricValue = item.metrics[0];
            console.log(`   Units sold: ${metricValue}`);
          }
        }
        console.log('');
      });
    }
  } catch (error) {
    console.error('❌ Ошибка при вызове API:');
    if (error.response) {
      console.error('Статус:', error.response.status);
      console.error('Заголовки:', error.response.headers);
      console.error('Ответ:', error.response.data);
    } else if (error.request) {
      console.error('Запрос был сделан, но не получен ответ:', error.request);
    } else {
      console.error('Ошибка при настройке запроса:', error.message);
    }
  }
}

// Запуск теста
testOzonSalesAPI()
  .then(() => console.log('\n✅ Тест завершен'))
  .catch(err => console.error('❌ Ошибка:', err));