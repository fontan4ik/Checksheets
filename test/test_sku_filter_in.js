/**
 * Тестирование API с фильтром по конкретному SKU используя операцию "in"
 * Проверим, можем ли мы получить более точные данные
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

// Тестируем вызов API для FBO с фильтром по конкретному SKU используя "in"
async function testOzonSalesFBOWithSkuFilterIn() {
  console.log('🔍 Тестируем API вызов для SKU 301916350 (FBO) с фильтром по SKU (операция "in")...');

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
        operation: "in",  // используем "in" вместо "eq"
        values: ["301916350"]
      }
    ],
    limit: 1000
  };

  console.log('📋 Тело запроса FBO (с фильтром по SKU "in"):', JSON.stringify(body, null, 2));

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
      let foundTargetSku = false;

      // Проходим по всем результатам
      for (let i = 0; i < items.length; i++) {
        const item = items[i];

        // Ищем SKU в размерностях
        let sku = null;

        for (const dim of item.dimensions) {
          if (dim.id === "301916350") {
            sku = dim.id;
            foundTargetSku = true;
            break;
          }
        }

        if (sku === "301916350") {
          if (item.metrics && Array.isArray(item.metrics) && item.metrics.length > 0) {
            const metricValue = item.metrics[0];
            console.log(`   ✅ НАЙДЕНО! SKU 301916350, FBO Units sold: ${metricValue}`);
            totalFBO += metricValue;
          }
          break; // нашли, выходим
        }
      }

      if (foundTargetSku) {
        console.log(`\n🎯 Результаты для SKU 301916350 (FBO) с фильтром по SKU: ${totalFBO} единиц`);
      } else {
        console.log(`\n❌ SKU 301916350 не найден в результатах FBO даже с фильтром "in"`);
      }

      console.log(`Всего элементов в ответе: ${items.length}`);
      return { fbo: totalFBO, found: foundTargetSku, count: items.length };
    }
  } catch (error) {
    console.error('❌ Ошибка при вызове API (FBO) с фильтром по SKU "in":');
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

// Тестируем вызов API для FBS с фильтром по конкретному SKU используя "in"
async function testOzonSalesFBSWithSkuFilterIn() {
  console.log('\n🔍 Тестируем API вызов для SKU 301916350 (FBS) с фильтром по SKU (операция "in")...');

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
        operation: "in",  // используем "in" вместо "eq"
        values: ["301916350"]
      }
    ],
    limit: 1000
  };

  console.log('📋 Тело запроса FBS (с фильтром по SKU "in"):', JSON.stringify(body, null, 2));

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
      let foundTargetSku = false;

      // Проходим по всем результатам
      for (let i = 0; i < items.length; i++) {
        const item = items[i];

        // Ищем SKU в размерностях
        let sku = null;

        for (const dim of item.dimensions) {
          if (dim.id === "301916350") {
            sku = dim.id;
            foundTargetSku = true;
            break;
          }
        }

        if (sku === "301916350") {
          if (item.metrics && Array.isArray(item.metrics) && item.metrics.length > 0) {
            const metricValue = item.metrics[0];
            console.log(`   ✅ НАЙДЕНО! SKU 301916350, FBS Units sold: ${metricValue}`);
            totalFBS += metricValue;
          }
          break; // нашли, выходим
        }
      }

      if (foundTargetSku) {
        console.log(`\n🎯 Результаты для SKU 301916350 (FBS) с фильтром по SKU: ${totalFBS} единиц`);
      } else {
        console.log(`\n❌ SKU 301916350 не найден в результатах FBS даже с фильтром "in"`);
      }

      console.log(`Всего элементов в ответе: ${items.length}`);
      return { fbs: totalFBS, found: foundTargetSku, count: items.length };
    }
  } catch (error) {
    console.error('❌ Ошибка при вызове API (FBS) с фильтром по SKU "in":');
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
  console.log('🚀 Запускаем тесты с фильтром по конкретному SKU используя операцию "in"...');
  console.log('💡 Попробуем использовать "in" вместо "eq" для фильтрации по SKU');

  const fboResult = await testOzonSalesFBOWithSkuFilterIn();
  const fbsResult = await testOzonSalesFBSWithSkuFilterIn();

  console.log(`\n🏁 РЕЗУЛЬТАТЫ С ФИЛЬТРОМ ПО КОНКРЕТНОМУ SKU (операция "in"):`);
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
  console.log(`FBO: найдено ${fboResult.count} записей, целевой SKU найден: ${fboResult.found}, значение: ${fboResult.fbo}`);
  console.log(`FBS: найдено ${fbsResult.count} записей, целевой SKU найден: ${fbsResult.found}, значение: ${fbsResult.fbs}`);

  if (fboResult.found || fbsResult.found) {
    console.log(`\n✅ SKU 301916350 существует в системе и имеет данные!`);
  } else {
    console.log(`\n❌ SKU 301916350 не найден в системе с примененными фильтрами`);
    console.log(`❓ Возможно, фильтр по SKU не работает в analytics API или данные отсутствуют.`);
  }

  console.log(`\n💡 Даже с операцией "in" фильтрация по SKU на уровне API не работает эффективно.`);
}

runTests()
  .then(() => console.log('\n✅ Все тесты завершены'))
  .catch(err => console.error('❌ Ошибка:', err));