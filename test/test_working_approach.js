/**
 * Тестирование API вызова с подходом, аналогичным работающему коду в Ozon заказы.gs
 * Проверим, сможем ли мы получить ожидаемые данные для SKU 301916350 за период 26.01.2026-26.02.2026
 * Ожидаем: FBO 40, FBS 5
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

// Тестируем вызов API для FBO с подходом, аналогичным работающему коду
async function testOzonSalesFBO() {
  console.log('🔍 Тестируем API вызов для SKU 301916350 (FBO) с подходом, аналогичным работающему коду...');

  const dateRange = getSpecificDateRange();
  console.log(`📅 Диапазон дат: ${formatDateTimeForAPI(dateRange.start)} → ${formatDateTimeForAPI(dateRange.end)}`);

  // Подготовим тело запроса для FBO с подходом, как в работающем коде (без фильтрации по SKU на уровне API)
  const body = {
    date_from: formatDateTimeForAPI(dateRange.start),
    date_to: formatDateTimeForAPI(dateRange.end),
    dimension: ["sku"],
    metrics: ["ordered_units"],
    filters: [
      {
        column: "fulfillment_type",
        operation: "eq",
        values: ["fbo"]  // FBO
      }
      // Не фильтруем по SKU на уровне API из-за особенностей работы API
    ],
    limit: 1000
  };

  console.log('📋 Тело запроса FBO (подход как в работающем коде):', JSON.stringify(body, null, 2));

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
      let foundTargetSku = false;
      let targetSkuData = null;

      // Проходим по всем результатам и ищем наш целевой SKU
      for (let i = 0; i < items.length; i++) {
        const item = items[i];

        console.log(`${i + 1}. Dimensions:`, item.dimensions);
        console.log(`   Metrics:`, item.metrics);

        // Ищем целевой SKU в размерностях
        let hasTargetSku = false;
        for (const dim of item.dimensions) {
          if (dim.id === "301916350") {
            hasTargetSku = true;
            break;
          }
        }

        if (hasTargetSku) {
          foundTargetSku = true;

          if (item.metrics && Array.isArray(item.metrics) && item.metrics.length > 0) {
            const metricValue = item.metrics[0];
            console.log(`   ✅ НАЙДЕНО! SKU 301916350, FBO Units sold: ${metricValue}`);
            totalFBO += metricValue;
            targetSkuData = item;
          }
        }
        console.log('');
      }

      console.log(`\n🎯 Результаты для SKU 301916350 (FBO): ${totalFBO}`);

      if (totalFBO === 40) {
        console.log(`✅ Совпадает с ожидаемым значением FBO=40`);
      } else if (totalFBO > 0) {
        console.log(`⚠️  Найдены продажи, но значение (${totalFBO}) отличается от ожидаемого (40)`);
      } else {
        console.log(`❌ Нет продаж для SKU 301916350 (FBO) в текущем запросе`);
        console.log(`💡 Возможно, нужно проверить другие параметры или период`);
      }

      return { fbo: totalFBO, found: foundTargetSku, data: targetSkuData };
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

  return { fbo: 0, found: false, data: null };
}

// Тестируем вызов API для FBS с подходом, аналогичным работающему коду
async function testOzonSalesFBS() {
  console.log('\n🔍 Тестируем API вызов для SKU 301916350 (FBS) с подходом, аналогичным работающему коду...');

  const dateRange = getSpecificDateRange();
  console.log(`📅 Диапазон дат: ${formatDateTimeForAPI(dateRange.start)} → ${formatDateTimeForAPI(dateRange.end)}`);

  // Подготовим тело запроса для FBS с подходом, как в работающем коде (без фильтрации по SKU на уровне API)
  const body = {
    date_from: formatDateTimeForAPI(dateRange.start),
    date_to: formatDateTimeForAPI(dateRange.end),
    dimension: ["sku"],
    metrics: ["ordered_units"],
    filters: [
      {
        column: "fulfillment_type",
        operation: "eq",
        values: ["fbs"]  // FBS
      }
      // Не фильтруем по SKU на уровне API из-за особенностей работы API
    ],
    limit: 1000
  };

  console.log('📋 Тело запроса FBS (подход как в работающем коде):', JSON.stringify(body, null, 2));

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
      let foundTargetSku = false;
      let targetSkuData = null;

      // Проходим по всем результатам и ищем наш целевой SKU
      for (let i = 0; i < items.length; i++) {
        const item = items[i];

        console.log(`${i + 1}. Dimensions:`, item.dimensions);
        console.log(`   Metrics:`, item.metrics);

        // Ищем целевой SKU в размерностях
        let hasTargetSku = false;
        for (const dim of item.dimensions) {
          if (dim.id === "301916350") {
            hasTargetSku = true;
            break;
          }
        }

        if (hasTargetSku) {
          foundTargetSku = true;

          if (item.metrics && Array.isArray(item.metrics) && item.metrics.length > 0) {
            const metricValue = item.metrics[0];
            console.log(`   ✅ НАЙДЕНО! SKU 301916350, FBS Units sold: ${metricValue}`);
            totalFBS += metricValue;
            targetSkuData = item;
          }
        }
        console.log('');
      }

      console.log(`\n🎯 Результаты для SKU 301916350 (FBS): ${totalFBS}`);

      if (totalFBS === 5) {
        console.log(`✅ Совпадает с ожидаемым значением FBS=5`);
      } else if (totalFBS > 0) {
        console.log(`⚠️  Найдены продажи, но значение (${totalFBS}) отличается от ожидаемого (5)`);
      } else {
        console.log(`❌ Нет продаж для SKU 301916350 (FBS) в текущем запросе`);
        console.log(`💡 Возможно, нужно проверить другие параметры или период`);
      }

      return { fbs: totalFBS, found: foundTargetSku, data: targetSkuData };
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

  return { fbs: 0, found: false, data: null };
}

// Запуск тестов
async function runTests() {
  console.log('🚀 Запускаем тесты с подходом, аналогичным работающему коду...');
  console.log('💡 Этот подход не фильтрует по SKU на уровне API, а фильтрует программно');

  const fboResult = await testOzonSalesFBO();
  const fbsResult = await testOzonSalesFBS();

  console.log(`\n🏁 ФИНАЛЬНЫЕ РЕЗУЛЬТАТЫ (подход как в работающем коде):`);
  console.log(`SKU 301916350 за период 26.01.2026-26.02.2026:`);
  console.log(`FBO: ${fboResult.fbo} (ожидается: 40)`);
  console.log(`FBS: ${fbsResult.fbs} (ожидается: 5)`);

  const totalExpected = 40 + 5;  // 45
  const totalActual = fboResult.fbo + fbsResult.fbs;

  if (fboResult.fbo === 40 && fbsResult.fbs === 5) {
    console.log(`🎉 Ура! Получены точные ожидаемые результаты!`);
  } else if (totalActual === totalExpected) {
    console.log(`🎯 Совпадает общее количество (45), но распределение между FBO и FBS отличается`);
  } else {
    console.log(`⚠️  Результаты отличаются от ожидаемых.`);

    // Проверим, близки ли результаты к ожидаемым
    const fboDiff = Math.abs(fboResult.fbo - 40);
    const fbsDiff = Math.abs(fbsResult.fbs - 5);

    if (fboDiff <= 5) {
      console.log(`📈 Значение FBO (${fboResult.fbo}) близко к ожидаемому (40)`);
    }
    if (fbsDiff <= 2) {
      console.log(`📈 Значение FBS (${fbsResult.fbs}) близко к ожидаемому (5)`);
    }
  }

  // Проверим, есть ли вообще какие-то данные для этого SKU
  if (fboResult.found || fbsResult.found) {
    console.log(`\n✅ SKU 301916350 присутствует в данных API`);
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
  .then(() => console.log('\n✅ Все тесты завершены'))
  .catch(err => console.error('❌ Ошибка:', err));