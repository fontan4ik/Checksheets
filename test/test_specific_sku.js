/**
 * Тестирование API вызова для конкретного SKU 301916350
 * Должно вернуть: FBO 40, FBS 5 за месяц
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

// Тестируем вызов API для FBO
async function testOzonSalesFBO() {
  console.log('🔍 Тестируем реальный API вызов для SKU 301916350 (FBO)...');

  const monthRange = getMonthDateRangeForAnalytics();
  console.log(`📅 Диапазон дат: ${formatDateTimeForAPI(monthRange.start)} → ${formatDateTimeForAPI(monthRange.end)}`);

  // Подготовим тело запроса для FBO
  const body = {
    date_from: formatDateTimeForAPI(monthRange.start),
    date_to: formatDateTimeForAPI(monthRange.end),
    dimensions: ["sku"], // Только SKU в размерностях
    metrics: ["ordered_units"], // Используем метрики для получения данных о продажах
    filters: [
      {
        column: "fulfillment_type",
        operation: "eq",
        values: ["fbo"]  // FBO
      },
      {
        column: "sku",
        operation: "in",
        values: ["301916350"]  // Тестируемый SKU
      }
    ],
    limit: 1000  // Добавляем лимит, как того требует API
  };

  console.log('📋 Тело запроса FBO:', JSON.stringify(body, null, 2));

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

    console.log('✅ Успешный ответ от API (FBO):');
    console.log(JSON.stringify(response.data, null, 2));

    // Анализируем данные
    if (response.data && response.data.result && response.data.result.data) {
      const items = response.data.result.data;
      console.log(`\n📊 Найдено ${items.length} записей для FBO:`);

      let totalFBO = 0;
      items.forEach((item, index) => {
        console.log(`${index + 1}. Dimensions:`, item.dimensions);
        console.log(`   Metrics:`, item.metrics);

        const skuDim = item.dimensions?.find(dim => dim.id === '301916350');
        if (skuDim) {
          if (item.metrics && Array.isArray(item.metrics) && item.metrics.length > 0) {
            const metricValue = item.metrics[0];
            console.log(`   SKU 301916350 FBO Units sold: ${metricValue}`);
            totalFBO += metricValue;
          }
        }
        console.log('');
      });

      console.log(`\n📈 Всего FBO для SKU 301916350: ${totalFBO}`);
    }
  } catch (error) {
    console.error('❌ Ошибка при вызове API (FBO):');
    if (error.response) {
      console.error('Статус:', error.response.status);
      console.error('Ответ:', error.response.data);
    } else if (error.request) {
      console.error('Запрос был сделан, но не получен ответ:', error.request);
    } else {
      console.error('Ошибка при настройке запроса:', error.message);
    }
  }
}

// Тестируем вызов API для FBS
async function testOzonSalesFBS() {
  console.log('\n🔍 Тестируем реальный API вызов для SKU 301916350 (FBS)...');

  const monthRange = getMonthDateRangeForAnalytics();
  console.log(`📅 Диапазон дат: ${formatDateTimeForAPI(monthRange.start)} → ${formatDateTimeForAPI(monthRange.end)}`);

  // Подготовим тело запроса для FBS
  const body = {
    date_from: formatDateTimeForAPI(monthRange.start),
    date_to: formatDateTimeForAPI(monthRange.end),
    dimensions: ["sku"], // Только SKU в размерностях
    metrics: ["ordered_units"], // Используем метрики для получения данных о продажах
    filters: [
      {
        column: "fulfillment_type",
        operation: "eq",
        values: ["fbs"]  // FBS
      },
      {
        column: "sku",
        operation: "in",
        values: ["301916350"]  // Тестируемый SKU
      }
    ],
    limit: 1000  // Добавляем лимит, как того требует API
  };

  console.log('📋 Тело запроса FBS:', JSON.stringify(body, null, 2));

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

    console.log('✅ Успешный ответ от API (FBS):');
    console.log(JSON.stringify(response.data, null, 2));

    // Анализируем данные
    if (response.data && response.data.result && response.data.result.data) {
      const items = response.data.result.data;
      console.log(`\n📊 Найдено ${items.length} записей для FBS:`);

      let totalFBS = 0;
      items.forEach((item, index) => {
        console.log(`${index + 1}. Dimensions:`, item.dimensions);
        console.log(`   Metrics:`, item.metrics);

        const skuDim = item.dimensions?.find(dim => dim.id === '301916350');
        if (skuDim) {
          if (item.metrics && Array.isArray(item.metrics) && item.metrics.length > 0) {
            const metricValue = item.metrics[0];
            console.log(`   SKU 301916350 FBS Units sold: ${metricValue}`);
            totalFBS += metricValue;
          }
        }
        console.log('');
      });

      console.log(`\n📈 Всего FBS для SKU 301916350: ${totalFBS}`);
    }
  } catch (error) {
    console.error('❌ Ошибка при вызове API (FBS):');
    if (error.response) {
      console.error('Статус:', error.response.status);
      console.error('Ответ:', error.response.data);
    } else if (error.request) {
      console.error('Запрос был сделан, но не получен ответ:', error.request);
    } else {
      console.error('Ошибка при настройке запроса:', error.message);
    }
  }
}

// Запуск тестов
async function runTests() {
  await testOzonSalesFBO();
  await testOzonSalesFBS();
}

runTests()
  .then(() => console.log('\n✅ Все тесты завершены'))
  .catch(err => console.error('❌ Ошибка:', err));