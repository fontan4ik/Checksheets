/**
 * Тестирование правильного подхода к работе с Ozon Analytics API
 * API возвращает данные по каждой комбинации размерностей отдельно
 * Поэтому для получения FBO и FBS данных нужно запросить обе размерности и правильно их обработать
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

// Тестируем вызов API с обеими размерностями и правильной обработкой
async function testOzonSalesCorrectApproach() {
  console.log('🔍 Тестируем правильный подход к API с обеими размерностями...');

  const dateRange = getSpecificDateRange();
  console.log(`📅 Диапазон дат: ${formatDateTimeForAPI(dateRange.start)} → ${formatDateTimeForAPI(dateRange.end)}`);

  // Подготовим тело запроса с обеими размерностями
  const body = {
    date_from: formatDateTimeForAPI(dateRange.start),
    date_to: formatDateTimeForAPI(dateRange.end),
    dimensions: ["sku", "fulfillment_type"],
    metrics: ["ordered_units"],
    filters: [], // Без фильтров, чтобы получить все данные
    limit: 1000
  };

  console.log('📋 Тело запроса (обе размерности):', JSON.stringify(body, null, 2));

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

    console.log('✅ Успешный ответ от API (обе размерности):');

    // Анализируем данные
    if (response.data && response.data.result && response.data.result.data) {
      const items = response.data.result.data;
      console.log(`\n📊 Найдено ${items.length} записей всего:`);

      // Создаем объект для хранения данных по SKU и типу исполнения
      const skuData = {};

      // Проходим по всем результатам
      for (let i = 0; i < items.length; i++) {
        const item = items[i];

        console.log(`${i + 1}. Dimensions:`, item.dimensions);
        console.log(`   Metrics:`, item.metrics);

        // Ищем SKU и тип исполнения в размерностях
        let sku = null;
        let fulfillmentType = null;

        for (const dim of item.dimensions) {
          // SKU - числовое значение
          if (!isNaN(dim.id) && parseInt(dim.id) > 0) {
            sku = dim.id;
          }
          // fulfillment_type - строковое значение fbo или fbs
          else if (dim.id === "fbo" || dim.id === "fbs") {
            fulfillmentType = dim.id;
          }
        }

        if (sku && fulfillmentType) {
          // Инициализируем объект для этого SKU, если его еще нет
          if (!skuData[sku]) {
            skuData[sku] = { fbo: 0, fbs: 0 };
          }

          // Получаем значение метрики
          let metricValue = 0;
          if (item.metrics && Array.isArray(item.metrics) && item.metrics.length > 0) {
            metricValue = item.metrics[0];
          }

          // Сохраняем значение в зависимости от типа исполнения
          if (fulfillmentType === "fbo") {
            skuData[sku].fbo += metricValue;
          } else if (fulfillmentType === "fbs") {
            skuData[sku].fbs += metricValue;
          }

          console.log(`   Запись: SKU ${sku}, fulfillment: ${fulfillmentType}, units: ${metricValue}`);
        }
        console.log('');
      }

      // Теперь выводим результаты для целевого SKU
      const targetSku = "301916350";
      const targetData = skuData[targetSku];

      console.log(`\n🎯 Результаты для SKU ${targetSku}:`);
      if (targetData) {
        console.log(`FBO: ${targetData.fbo} (ожидается: 40)`);
        console.log(`FBS: ${targetData.fbs} (ожидается: 5)`);

        if (targetData.fbo === 40 && targetData.fbs === 5) {
          console.log(`🎉 Ура! Получены точные ожидаемые результаты!`);
        } else {
          console.log(`⚠️  Результаты отличаются от ожидаемых.`);

          if (targetData.fbo === 40) {
            console.log(`✅ Значение FBO совпадает с ожидаемым!`);
          }

          if (targetData.fbs === 5) {
            console.log(`✅ Значение FBS совпадает с ожидаемым!`);
          }
        }

        return {
          fbo: targetData.fbo,
          fbs: targetData.fbs,
          found: true
        };
      } else {
        console.log(`❌ SKU ${targetSku} не найден в результатах`);
        console.log(`Всего уникальных SKU в результатах:`, Object.keys(skuData).length);

        // Показать несколько примеров SKU из результата
        const sampleSkus = Object.keys(skuData).slice(0, 5);
        console.log(`Примеры SKU из результата:`, sampleSkus);

        return {
          fbo: 0,
          fbs: 0,
          found: false
        };
      }
    }
  } catch (error) {
    console.error('❌ Ошибка при вызове API (правильный подход):');
    if (error.response) {
      console.error('Статус:', error.response.status);
      console.error('Ответ:', error.response.data);
    } else if (error.request) {
      console.error('Запрос был сделан, но не получен ответ:', error.request);
    } else {
      console.error('Ошибка при настройке запроса:', error.message);
    }
  }

  return { fbo: 0, fbs: 0, found: false };
}

// Запуск теста
async function runTest() {
  console.log('🚀 Запускаем тест с правильным подходом...');
  console.log('💡 API возвращает каждую комбинацию (sku, fulfillment_type) отдельно');

  const result = await testOzonSalesCorrectApproach();

  console.log(`\n🏁 ФИНАЛЬНЫЕ РЕЗУЛЬТАТЫ:`);
  console.log(`SKU 301916350 за период 26.01.2026-26.02.2026:`);
  console.log(`FBO: ${result.fbo} (ожидается: 40)`);
  console.log(`FBS: ${result.fbs} (ожидается: 5)`);

  if (result.fbo === 40 && result.fbs === 5) {
    console.log(`🎉 Ура! Получены точные ожидаемые результаты!`);
  } else if (result.found) {
    console.log(`⚠️  Результаты отличаются от ожидаемых.`);

    const totalExpected = 40 + 5;  // 45
    const totalActual = result.fbo + result.fbs;

    if (totalActual === totalExpected) {
      console.log(`🎯 Совпадает общее количество (45), но распределение между FBO и FBS отличается`);
    }
  } else {
    console.log(`❌ SKU 301916350 не найден в данных API за указанный период`);
    console.log(`❓ Возможные причины:`);
    console.log(`   - SKU не существует в системе`);
    console.log(`   - У SKU нет продаж за указанный период`);
    console.log(`   - SKU принадлежит другому поставщику`);
    console.log(`   - Период дат неверен или данные еще не доступны`);
  }
}

runTest()
  .then(() => console.log('\n✅ Тест завершен'))
  .catch(err => console.error('❌ Ошибка:', err));