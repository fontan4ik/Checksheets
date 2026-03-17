/**
 * Тестирование API с фильтром по конкретному SKU
 * Проверим, можем ли мы получить более точные данные, если будем фильтровать по SKU на уровне API
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

// Тестируем вызов API для FBO с фильтром по конкретному SKU
async function testOzonSalesFBOWithSkuFilter() {
  console.log('🔍 Тестируем API вызов для SKU 301916350 (FBO) с фильтром по SKU...');

  const dateRange = getSpecificDateRange();
  console.log(`📅 Диапазон дат: ${formatDateTimeForAPI(dateRange.start)} → ${formatDateTimeForAPI(dateRange.end)}`);

  // Подготовим тело запроса для FBO с фильтром по конкретному SKU
  const body = {
    date_from: formatDateTimeForAPI(dateRange.start),
    date_to: formatDateTimeForAPI(dateRange.end),
    dimension: ["sku"], // Правильный параметр как в документации
    metrics: ["ordered_units"],
    filters: [
      {
        column: "fulfillment_type",
        operation: "eq",
        values: ["fbo"]
      },
      {
        column: "sku",
        operation: "eq",  // или "in"?
        values: ["301916350"]
      }
    ],
    limit: 1000
  };

  console.log('📋 Тело запроса FBO (с фильтром по SKU):', JSON.stringify(body, null, 2));

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
      console.log(`\n📊 Найдено ${items.length} записей для FBO после фильтрации по SKU:`);

      let totalFBO = 0;

      // Проходим по всем результатам - теперь должны получить только для конкретного SKU
      for (let i = 0; i < items.length; i++) {
        const item = items[i];

        console.log(`${i + 1}. Dimensions:`, item.dimensions);
        console.log(`   Metrics:`, item.metrics);

        // Ищем SKU в размерностях (хотя он должен быть только один, т.к. фильтровали по нему)
        let sku = null;

        for (const dim of item.dimensions) {
          console.log(`   - Dimension ID: ${dim.id}, Name: ${dim.name || 'N/A'}`);
          if (dim.id === "301916350") {
            sku = dim.id;
            break;
          }
        }

        if (sku === "301916350") {
          if (item.metrics && Array.isArray(item.metrics) && item.metrics.length > 0) {
            const metricValue = item.metrics[0];
            console.log(`   ✅ НАЙДЕНО! SKU 301916350, FBO Units sold: ${metricValue}`);
            totalFBO += metricValue;
          }
        }
        console.log('');
      }

      console.log(`\n🎯 Результаты для SKU 301916350 (FBO) с фильтром по SKU: ${totalFBO} единиц`);
      return { fbo: totalFBO, found: items.length > 0, count: items.length };
    }
  } catch (error) {
    console.error('❌ Ошибка при вызове API (FBO) с фильтром по SKU:');
    if (error.response) {
      console.error('Статус:', error.response.status);
      console.error('Ответ:', error.response.data);
    } else if (error.request) {
      console.error('Запрос был сделан, но не получен ответ:', error.request);
    } else {
      console.error('Ошибка при настройке запроса:', error.message);
    }
  }

  return { fbo: 0, found: false, count: 0 };
}

// Тестируем вызов API для FBS с фильтром по конкретному SKU
async function testOzonSalesFBSWithSkuFilter() {
  console.log('\n🔍 Тестируем API вызов для SKU 301916350 (FBS) с фильтром по SKU...');

  const dateRange = getSpecificDateRange();
  console.log(`📅 Диапазон дат: ${formatDateTimeForAPI(dateRange.start)} → ${formatDateTimeForAPI(dateRange.end)}`);

  // Подготовим тело запроса для FBS с фильтром по конкретному SKU
  const body = {
    date_from: formatDateTimeForAPI(dateRange.start),
    date_to: formatDateTimeForAPI(dateRange.end),
    dimension: ["sku"], // Правильный параметр как в документации
    metrics: ["ordered_units"],
    filters: [
      {
        column: "fulfillment_type",
        operation: "eq",
        values: ["fbs"]
      },
      {
        column: "sku",
        operation: "eq",  // или "in"?
        values: ["301916350"]
      }
    ],
    limit: 1000
  };

  console.log('📋 Тело запроса FBS (с фильтром по SKU):', JSON.stringify(body, null, 2));

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
      console.log(`\n📊 Найдено ${items.length} записей для FBS после фильтрации по SKU:`);

      let totalFBS = 0;

      // Проходим по всем результатам - теперь должны получить только для конкретного SKU
      for (let i = 0; i < items.length; i++) {
        const item = items[i];

        console.log(`${i + 1}. Dimensions:`, item.dimensions);
        console.log(`   Metrics:`, item.metrics);

        // Ищем SKU в размерностях (хотя он должен быть только один, т.к. фильтровали по нему)
        let sku = null;

        for (const dim of item.dimensions) {
          console.log(`   - Dimension ID: ${dim.id}, Name: ${dim.name || 'N/A'}`);
          if (dim.id === "301916350") {
            sku = dim.id;
            break;
          }
        }

        if (sku === "301916350") {
          if (item.metrics && Array.isArray(item.metrics) && item.metrics.length > 0) {
            const metricValue = item.metrics[0];
            console.log(`   ✅ НАЙДЕНО! SKU 301916350, FBS Units sold: ${metricValue}`);
            totalFBS += metricValue;
          }
        }
        console.log('');
      }

      console.log(`\n🎯 Результаты для SKU 301916350 (FBS) с фильтром по SKU: ${totalFBS} единиц`);
      return { fbs: totalFBS, found: items.length > 0, count: items.length };
    }
  } catch (error) {
    console.error('❌ Ошибка при вызове API (FBS) с фильтром по SKU:');
    if (error.response) {
      console.error('Статус:', error.response.status);
      console.error('Ответ:', error.response.data);
    } else if (error.request) {
      console.error('Запрос был сделан, но не получен ответ:', error.request);
    } else {
      console.error('Ошибка при настройке запроса:', error.message);
    }
  }

  return { fbs: 0, found: false, count: 0 };
}

// Запуск тестов
async function runTests() {
  console.log('🚀 Запускаем тесты с фильтром по конкретному SKU...');
  console.log('💡 Попробуем фильтровать по конкретному SKU на уровне API');

  const fboResult = await testOzonSalesFBOWithSkuFilter();
  const fbsResult = await testOzonSalesFBSWithSkuFilter();

  console.log(`\n🏁 РЕЗУЛЬТАТЫ С ФИЛЬТРОМ ПО КОНКРЕТНОМУ SKU:`);
  console.log(`SKU 301916350 за период 26.01.2026-26.02.2026:`);
  console.log(`FBO: ${fboResult.fbo} (ожидаемо: 40)`);
  console.log(`FBS: ${fbsResult.fbs} (ожидаемо: 5)`);

  const totalActual = fboResult.fbo + fbsResult.fbs;
  const totalExpected = 40 + 5; // 45

  if (fboResult.fbo === 40 && fbsResult.fbs === 5) {
    console.log(`🎉 Ура! Получены ожидаемые результаты FBO=40 и FBS=5!`);
  } else {
    console.log(`⚠️  Результаты отличаются от ожидаемых.`);

    if (totalActual === totalExpected) {
      console.log(`📊 Суммарное количество совпадает с ожидаемым: ${totalActual}`);
      console.log(`💡 Возможно, распределение между FBO и FBS изменилось.`);
    } else {
      console.log(`📊 Суммарное количество: ${totalActual} (ожидаем: ${totalExpected})`);
    }
  }

  console.log(`\n📝 Дополнительная информация:`);
  console.log(`FBO: найдено ${fboResult.count} записей, значение: ${fboResult.fbo}`);
  console.log(`FBS: найдено ${fbsResult.count} записей, значение: ${fbsResult.fbs}`);

  if (fboResult.found || fbsResult.found) {
    console.log(`\n✅ SKU 301916350 существует в системе и имеет данные!`);
  } else {
    console.log(`\n❌ SKU 301916350 не найден в системе с примененными фильтрами`);
    console.log(`❓ Возможно, фильтр по SKU не поддерживается в данном контексте или данные отсутствуют.`);
  }

  console.log(`\n💡 Этот подход позволяет точнее фильтровать данные на уровне API.`);
}

runTests()
  .then(() => console.log('\n✅ Все тесты завершены'))
  .catch(err => console.error('❌ Ошибка:', err));