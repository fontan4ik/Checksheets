/**
 * Тестирование API вызова для конкретного SKU 301916350
 * Период: 26.01.2026-26.02.2026
 * Должно вернуть: FBO 40, FBS 5
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

// Создаем даты вручную для периода 26.01.2026-26.02.2026
function getSpecificDateRange() {
  const startDate = new Date('2026-01-26');
  const endDate = new Date('2026-02-26');

  return {
    start: startDate,
    end: endDate
  };
}

// Тестируем вызов API для FBO
async function testOzonSalesFBO() {
  console.log('🔍 Тестируем API вызов для SKU 301916350 (FBO) за период 26.01.2026-26.02.2026...');

  const dateRange = getSpecificDateRange();
  console.log(`📅 Диапазон дат: ${formatDateTimeForAPI(dateRange.start)} → ${formatDateTimeForAPI(dateRange.end)}`);

  // Подготовим тело запроса для FBO
  const body = {
    date_from: formatDateTimeForAPI(dateRange.start),
    date_to: formatDateTimeForAPI(dateRange.end),
    dimensions: ["sku", "fulfillment_type"], // Обе размерности
    metrics: ["ordered_units"],
    filters: [
      {
        column: "fulfillment_type",
        operation: "eq",
        values: ["fbo"]  // FBO
      },
      {
        column: "sku",
        operation: "in",
        values: ["301916350"]  // Целевой SKU
      }
    ],
    limit: 1000
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

    // Анализируем данные
    if (response.data && response.data.result && response.data.result.data) {
      const items = response.data.result.data;
      console.log(`\n📊 Найдено ${items.length} записей для FBO:`);

      let totalFBO = 0;
      let foundItem = false;

      items.forEach((item, index) => {
        console.log(`${index + 1}. Dimensions:`, item.dimensions);
        console.log(`   Metrics:`, item.metrics);

        // Найдем SKU и тип исполнения в размерностях
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

        if (sku === "301916350" && fulfillmentType === "fbo") {
          foundItem = true;

          if (item.metrics && Array.isArray(item.metrics) && item.metrics.length > 0) {
            const metricValue = item.metrics[0];
            console.log(`   ✅ SKU ${sku}, fulfillment: ${fulfillmentType}, Units sold: ${metricValue}`);
            totalFBO += metricValue;
          }
        }
        console.log('');
      });

      console.log(`\n🎯 Результаты для SKU 301916350 (FBO): ${totalFBO}`);

      if (totalFBO === 40) {
        console.log(`✅ Совпадает с ожидаемым значением FBO=40`);
      } else {
        console.log(`⚠️  Отличается от ожидаемого значения FBO=40`);
      }

      return { fbo: totalFBO, found: foundItem };
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

  return { fbo: 0, found: false };
}

// Тестируем вызов API для FBS
async function testOzonSalesFBS() {
  console.log('\n🔍 Тестируем API вызов для SKU 301916350 (FBS) за период 26.01.2026-26.02.2026...');

  const dateRange = getSpecificDateRange();
  console.log(`📅 Диапазон дат: ${formatDateTimeForAPI(dateRange.start)} → ${formatDateTimeForAPI(dateRange.end)}`);

  // Подготовим тело запроса для FBS
  const body = {
    date_from: formatDateTimeForAPI(dateRange.start),
    date_to: formatDateTimeForAPI(dateRange.end),
    dimensions: ["sku", "fulfillment_type"], // Обе размерности
    metrics: ["ordered_units"],
    filters: [
      {
        column: "fulfillment_type",
        operation: "eq",
        values: ["fbs"]  // FBS
      },
      {
        column: "sku",
        operation: "in",
        values: ["301916350"]  // Целевой SKU
      }
    ],
    limit: 1000
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

    // Анализируем данные
    if (response.data && response.data.result && response.data.result.data) {
      const items = response.data.result.data;
      console.log(`\n📊 Найдено ${items.length} записей для FBS:`);

      let totalFBS = 0;
      let foundItem = false;

      items.forEach((item, index) => {
        console.log(`${index + 1}. Dimensions:`, item.dimensions);
        console.log(`   Metrics:`, item.metrics);

        // Найдем SKU и тип исполнения в размерностях
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

        if (sku === "301916350" && fulfillmentType === "fbs") {
          foundItem = true;

          if (item.metrics && Array.isArray(item.metrics) && item.metrics.length > 0) {
            const metricValue = item.metrics[0];
            console.log(`   ✅ SKU ${sku}, fulfillment: ${fulfillmentType}, Units sold: ${metricValue}`);
            totalFBS += metricValue;
          }
        }
        console.log('');
      });

      console.log(`\n🎯 Результаты для SKU 301916350 (FBS): ${totalFBS}`);

      if (totalFBS === 5) {
        console.log(`✅ Совпадает с ожидаемым значением FBS=5`);
      } else {
        console.log(`⚠️  Отличается от ожидаемого значения FBS=5`);
      }

      return { fbs: totalFBS, found: foundItem };
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

  return { fbs: 0, found: false };
}

// Запуск тестов
async function runTests() {
  const fboResult = await testOzonSalesFBO();
  const fbsResult = await testOzonSalesFBS();

  console.log(`\n🏁 ФИНАЛЬНЫЕ РЕЗУЛЬТАТЫ:`);
  console.log(`SKU 301916350 за период 26.01.2026-26.02.2026:`);
  console.log(`FBO: ${fboResult.fbo} (ожидается: 40)`);
  console.log(`FBS: ${fbsResult.fbs} (ожидается: 5)`);

  if (fboResult.fbo === 40 && fbsResult.fbs === 5) {
    console.log(`🎉 Ура! Получены ожидаемые результаты!`);
  } else {
    console.log(`⚠️  Результаты отличаются от ожидаемых.`);
  }
}

runTests()
  .then(() => console.log('\n✅ Все тесты завершены'))
  .catch(err => console.error('❌ Ошибка:', err));