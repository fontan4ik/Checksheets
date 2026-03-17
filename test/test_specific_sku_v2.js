/**
 * Тестирование API вызова для конкретного SKU 301916350
 * Пробуем разные варианты запроса
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

// Тестируем вызов API для FBO с упрощенным фильтром
async function testOzonSalesFBO() {
  console.log('🔍 Тестируем API вызов для SKU 301916350 (FBO) с упрощенным подходом...');

  const monthRange = getMonthDateRangeForAnalytics();
  console.log(`📅 Диапазон дат: ${formatDateTimeForAPI(monthRange.start)} → ${formatDateTimeForAPI(monthRange.end)}`);

  // Подготовим тело запроса для FBO - попробуем без фильтра по типу исполнения сначала
  const body = {
    date_from: formatDateTimeForAPI(monthRange.start),
    date_to: formatDateTimeForAPI(monthRange.end),
    dimensions: ["sku", "fulfillment_type"], // Включаем обе размерности
    metrics: ["ordered_units"],
    filters: [
      {
        column: "sku",
        operation: "in",
        values: ["301916350"]  // Только фильтр по SKU
      }
    ],
    limit: 1000
  };

  console.log('📋 Тело запроса FBO (фильтр только по SKU):', JSON.stringify(body, null, 2));

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
      console.log(`\n📊 Найдено ${items.length} записей для SKU 301916350:`);

      let totalFBO = 0;
      let totalFBS = 0;

      items.forEach((item, index) => {
        console.log(`${index + 1}. Dimensions:`, item.dimensions);
        console.log(`   Metrics:`, item.metrics);

        // Найдем SKU и fulfillment type в размерностях
        let sku = null;
        let fulfillmentType = null;

        for (const dim of item.dimensions) {
          if (dim.id === "301916350") {
            sku = dim.id;
          }
          if (dim.id === "fbo" || dim.id === "fbs") {
            fulfillmentType = dim.id;
          }
        }

        if (sku && fulfillmentType) {
          if (item.metrics && Array.isArray(item.metrics) && item.metrics.length > 0) {
            const metricValue = item.metrics[0];
            console.log(`   SKU ${sku}, fulfillment: ${fulfillmentType}, Units sold: ${metricValue}`);

            if (fulfillmentType === 'fbo') {
              totalFBO += metricValue;
            } else if (fulfillmentType === 'fbs') {
              totalFBS += metricValue;
            }
          }
        }
        console.log('');
      });

      console.log(`\n📈 Всего FBO для SKU 301916350: ${totalFBO}`);
      console.log(`📈 Всего FBS для SKU 301916350: ${totalFBS}`);
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

// Запуск теста
testOzonSalesFBO()
  .then(() => console.log('\n✅ Тест завершен'))
  .catch(err => console.error('❌ Ошибка:', err));