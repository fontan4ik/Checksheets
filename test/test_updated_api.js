/**
 * Тестирование обновленного подхода к API с правильной структурой dimensions
 * Проверим, как теперь работает API с правильной структурой
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

// Тестируем вызов API для FBO с обновленной структурой
async function testOzonSalesFBO() {
  console.log('🔍 Тестируем API вызов для SKU 301916350 (FBO) с обновленной структурой...');

  const dateRange = getSpecificDateRange();
  console.log(`📅 Диапазон дат: ${formatDateTimeForAPI(dateRange.start)} → ${formatDateTimeForAPI(dateRange.end)}`);

  // Подготовим тело запроса для FBO с обновленной структурой (dimensions вместо dimension)
  const body = {
    date_from: formatDateTimeForAPI(dateRange.start),
    date_to: formatDateTimeForAPI(dateRange.end),
    dimensions: ["sku"], // Правильный параметр
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

  console.log('📋 Тело запроса FBO (обновленная структура):', JSON.stringify(body, null, 2));

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
      let targetSkuValue = 0;

      // Проходим по всем результатам и ищем наш целевой SKU
      for (let i = 0; i < items.length; i++) {
        const item = items[i];

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
            totalFBO += metricValue;
            targetSkuValue = metricValue;
          }
          break; // нашли, выходим
        }
      }

      if (foundTargetSku) {
        console.log(`\n🎯 Найдены данные для SKU 301916350 (FBO): ${totalFBO} единиц`);
      } else {
        console.log(`\n❌ SKU 301916350 не найден в результатах FBO`);
      }

      return { fbo: totalFBO, found: foundTargetSku, value: targetSkuValue };
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

// Тестируем вызов API для FBS с обновленной структурой
async function testOzonSalesFBS() {
  console.log('\n🔍 Тестируем API вызов для SKU 301916350 (FBS) с обновленной структурой...');

  const dateRange = getSpecificDateRange();
  console.log(`📅 Диапазон дат: ${formatDateTimeForAPI(dateRange.start)} → ${formatDateTimeForAPI(dateRange.end)}`);

  // Подготовим тело запроса для FBS с обновленной структурой (dimensions вместо dimension)
  const body = {
    date_from: formatDateTimeForAPI(dateRange.start),
    date_to: formatDateTimeForAPI(dateRange.end),
    dimensions: ["sku"], // Правильный параметр
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

  console.log('📋 Тело запроса FBS (обновленная структура):', JSON.stringify(body, null, 2));

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
      let targetSkuValue = 0;

      // Проходим по всем результатам и ищем наш целевой SKU
      for (let i = 0; i < items.length; i++) {
        const item = items[i];

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
            totalFBS += metricValue;
            targetSkuValue = metricValue;
          }
          break; // нашли, выходим
        }
      }

      if (foundTargetSku) {
        console.log(`\n🎯 Найдены данные для SKU 301916350 (FBS): ${totalFBS} единиц`);
      } else {
        console.log(`\n❌ SKU 301916350 не найден в результатах FBS`);
      }

      return { fbs: totalFBS, found: foundTargetSku, value: targetSkuValue };
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
  console.log('🚀 Запускаем тесты с обновленной структурой API...');
  console.log('💡 Используем правильный параметр dimensions вместо dimension');

  const fboResult = await testOzonSalesFBO();
  const fbsResult = await testOzonSalesFBS();

  console.log(`\n🏁 РЕЗУЛЬТАТЫ С ОБНОВЛЕННОЙ СТРУКТУРОЙ:`);
  console.log(`SKU 301916350 за период 26.01.2026-26.02.2026:`);
  console.log(`FBO: ${fboResult.fbo} (ранее: 45, ожидаемо: 40)`);
  console.log(`FBS: ${fbsResult.fbs} (ранее: 45, ожидаемо: 5)`);

  const totalPrevious = 45 + 45; // 90 (предыдущие значения)
  const totalCurrent = fboResult.fbo + fbsResult.fbs;
  const totalExpected = 40 + 5; // 45 (ожидаемые значения)

  if (fboResult.fbo === 40 && fbsResult.fbs === 5) {
    console.log(`🎉 Ура! Получены ожидаемые результаты FBO=40 и FBS=5!`);
  } else {
    console.log(`⚠️  Результаты отличаются от ожидаемых.`);

    if (totalCurrent === totalPrevious) {
      console.log(`📊 Суммарное количество совпадает с предыдущими результатами: ${totalCurrent}`);
    } else if (totalCurrent === totalExpected) {
      console.log(`📊 Суммарное количество совпадает с ожидаемыми результатами: ${totalCurrent}`);
    } else {
      console.log(`📊 Суммарное количество: ${totalCurrent} (ожидаем: ${totalExpected}, предыдущее: ${totalPrevious})`);
    }
  }

  // Проверим, есть ли вообще какие-то данные для этого SKU
  if (fboResult.found || fbsResult.found) {
    console.log(`\n✅ SKU 301916350 существует в системе и имеет данные!`);
    if (fboResult.found) {
      console.log(`   FBO продаж: ${fboResult.value} единиц`);
    }
    if (fbsResult.found) {
      console.log(`   FBS продаж: ${fbsResult.value} единиц`);
    }
  } else {
    console.log(`\n❌ SKU 301916350 не найден в системе за текущий период`);
    console.log(`❓ Возможные причины:`);
    console.log(`   - SKU не существует в системе`);
    console.log(`   - SKU не имеет продаж за указанный период`);
    console.log(`   - SKU принадлежит другому поставщику`);
    console.log(`   - Номер SKU указан неправильно`);
  }

  console.log(`\n💡 Обновленная структура API (dimensions вместо dimension) позволяет корректно отправлять запросы.`);
}

runTests()
  .then(() => console.log('\n✅ Все тесты завершены'))
  .catch(err => console.error('❌ Ошибка:', err));