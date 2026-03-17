/**
 * Тестирование правильного подхода к работе с Ozon Analytics API
 * Проверим, как API возвращает данные при использовании фильтра по fulfillment_type
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

// Тестируем вызов API для FBO с правильной обработкой
async function testOzonSalesFBO() {
  console.log('🔍 Тестируем API вызов для FBO с фильтром...');

  const dateRange = getSpecificDateRange();
  console.log(`📅 Диапазон дат: ${formatDateTimeForAPI(dateRange.start)} → ${formatDateTimeForAPI(dateRange.end)}`);

  // Подготовим тело запроса для FBO с фильтром по типу исполнения
  const body = {
    date_from: formatDateTimeForAPI(dateRange.start),
    date_to: formatDateTimeForAPI(dateRange.end),
    dimensions: ["sku"],
    metrics: ["ordered_units"],
    filters: [
      {
        column: "fulfillment_type",
        operation: "eq",
        values: ["fbo"]
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

      let fboTotal = 0;
      let foundTargetSku = false;
      let targetSkuValue = 0;

      // Проходим по всем результатам и ищем наш целевой SKU
      for (let i = 0; i < items.length; i++) {
        const item = items[i];

        console.log(`${i + 1}. Dimensions:`, item.dimensions);
        console.log(`   Metrics:`, item.metrics);

        // Ищем целевой SKU в размерностях
        let sku = null;

        for (const dim of item.dimensions) {
          if (dim.id === "301916350") {
            sku = dim.id;
            break;
          }
        }

        if (sku === "301916350") {
          foundTargetSku = true;

          if (item.metrics && Array.isArray(item.metrics) && item.metrics.length > 0) {
            const metricValue = item.metrics[0];
            console.log(`   ✅ НАЙДЕНО! SKU 301916350, FBO Units sold: ${metricValue}`);
            fboTotal += metricValue;
            targetSkuValue = metricValue;
          }
        }
        console.log('');
      }

      console.log(`\n🎯 Результаты для SKU 301916350 (FBO): ${fboTotal}`);
      return { fbo: fboTotal, found: foundTargetSku, value: targetSkuValue };
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

  return { fbo: 0, found: false, value: 0 };
}

// Тестируем вызов API для FBS с правильной обработкой
async function testOzonSalesFBS() {
  console.log('\n🔍 Тестируем API вызов для FBS с фильтром...');

  const dateRange = getSpecificDateRange();
  console.log(`📅 Диапазон дат: ${formatDateTimeForAPI(dateRange.start)} → ${formatDateTimeForAPI(dateRange.end)}`);

  // Подготовим тело запроса для FBS с фильтром по типу исполнения
  const body = {
    date_from: formatDateTimeForAPI(dateRange.start),
    date_to: formatDateTimeForAPI(dateRange.end),
    dimensions: ["sku"],
    metrics: ["ordered_units"],
    filters: [
      {
        column: "fulfillment_type",
        operation: "eq",
        values: ["fbs"]
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

      let fbsTotal = 0;
      let foundTargetSku = false;
      let targetSkuValue = 0;

      // Проходим по всем результатам и ищем наш целевой SKU
      for (let i = 0; i < items.length; i++) {
        const item = items[i];

        console.log(`${i + 1}. Dimensions:`, item.dimensions);
        console.log(`   Metrics:`, item.metrics);

        // Ищем целевой SKU в размерностях
        let sku = null;

        for (const dim of item.dimensions) {
          if (dim.id === "301916350") {
            sku = dim.id;
            break;
          }
        }

        if (sku === "301916350") {
          foundTargetSku = true;

          if (item.metrics && Array.isArray(item.metrics) && item.metrics.length > 0) {
            const metricValue = item.metrics[0];
            console.log(`   ✅ НАЙДЕНО! SKU 301916350, FBS Units sold: ${metricValue}`);
            fbsTotal += metricValue;
            targetSkuValue = metricValue;
          }
        }
        console.log('');
      }

      console.log(`\n🎯 Результаты для SKU 301916350 (FBS): ${fbsTotal}`);
      return { fbs: fbsTotal, found: foundTargetSku, value: targetSkuValue };
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

  return { fbs: 0, found: false, value: 0 };
}

// Запуск тестов
async function runTests() {
  console.log('🚀 Запускаем тесты с правильным подходом...');
  console.log('💡 Мы используем фильтр по fulfillment_type и ищем нужный SKU в результатах');

  const fboResult = await testOzonSalesFBO();
  const fbsResult = await testOzonSalesFBS();

  console.log(`\n🏁 ФИНАЛЬНЫЕ РЕЗУЛЬТАТЫ:`);
  console.log(`SKU 301916350 за период 26.01.2026-26.02.2026:`);
  console.log(`FBO: ${fboResult.fbo} (ожидается: 40)`);
  console.log(`FBS: ${fbsResult.fbs} (ожидается: 5)`);

  if (fboResult.fbo === 40 && fbsResult.fbs === 5) {
    console.log(`🎉 Ура! Получены точные ожидаемые результаты!`);
  } else {
    console.log(`⚠️  Результаты отличаются от ожидаемых.`);

    const totalExpected = 40 + 5;  // 45
    const totalActual = fboResult.fbo + fbsResult.fbs;

    if (totalActual === totalExpected) {
      console.log(`🎯 Совпадает общее количество (45), но распределение между FBO и FBS отличается`);
    }
  }

  // Проверим, есть ли вообще какие-то данные для этого SKU
  if (fboResult.found || fbsResult.found) {
    console.log(`\n✅ SKU 301916350 присутствует в данных API`);
    if (fboResult.found) {
      console.log(`   FBO продаж: ${fboResult.value} единиц`);
    }
    if (fbsResult.found) {
      console.log(`   FBS продаж: ${fbsResult.value} единиц`);
    }
  } else {
    console.log(`\n❌ SKU 301916350 не найден в данных API за указанный период`);
    console.log(`❓ Возможные причины:`);
    console.log(`   - SKU не существует в системе`);
    console.log(`   - У SKU нет продаж за указанный период`);
    console.log(`   - SKU принадлежит другому поставщику`);
    console.log(`   - Период дат неверен или данные еще не доступны`);
  }
}

runTests()
  .then(() => console.log('\n✅ Тесты завершены'))
  .catch(err => console.error('❌ Ошибка:', err));