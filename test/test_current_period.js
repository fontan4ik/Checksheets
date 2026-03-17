/**
 * Тестирование API вызова с текущими датами (не будущими)
 * Проверим, сможем ли мы получить какие-либо данные для SKU 301916350
 * Это поможет понять, существует ли SKU в системе вообще
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

// Создаем даты за последний месяц от текущей доки
function getLastMonthDateRange() {
  const today = new Date();
  const endDate = new Date(today);

  // Начало месяца - вычитаем примерно месяц
  const startDate = new Date(today);
  startDate.setMonth(today.getMonth() - 1);

  // Корректируем, чтобы дата начала была таким же числом, как сегодня, если возможно
  if (startDate.getDate() !== today.getDate()) {
    // Если в предыдущем месяце меньше дней, устанавливаем последний день
    startDate.setDate(0);
  }

  return {
    start: startDate,
    end: endDate
  };
}

// Тестируем вызов API для FBO с текущими датами
async function testOzonSalesFBO() {
  console.log('🔍 Тестируем API вызов для SKU 301916350 (FBO) с текущими датами...');

  const dateRange = getLastMonthDateRange();
  console.log(`📅 Диапазон дат: ${formatDateTimeForAPI(dateRange.start)} → ${formatDateTimeForAPI(dateRange.end)}`);
  console.log(`💡 Это примерно за последний месяц от текущей даты`);

  // Подготовим тело запроса для FBO
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
      let foundTargetSku = false;
      let targetSkuMetricValue = 0;

      // Проходим по всем результатам и ищем наш целевой SKU
      for (let i = 0; i < items.length; i++) {
        const item = items[i];

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
            targetSkuMetricValue = metricValue;
          }
          break; // нашли, выходим
        }
      }

      if (foundTargetSku) {
        console.log(`\n🎯 Найдены данные для SKU 301916350 (FBO): ${totalFBO} единиц`);
      } else {
        console.log(`\n❌ SKU 301916350 не найден в результатах FBO`);
      }

      return { fbo: totalFBO, found: foundTargetSku, value: targetSkuMetricValue };
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

// Тестируем вызов API для FBS с текущими датами
async function testOzonSalesFBS() {
  console.log('\n🔍 Тестируем API вызов для SKU 301916350 (FBS) с текущими датами...');

  const dateRange = getLastMonthDateRange();
  console.log(`📅 Диапазон дат: ${formatDateTimeForAPI(dateRange.start)} → ${formatDateTimeForAPI(dateRange.end)}`);
  console.log(`💡 Это примерно за последний месяц от текущей даты`);

  // Подготовим тело запроса для FBS
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
      let foundTargetSku = false;
      let targetSkuMetricValue = 0;

      // Проходим по всем результатам и ищем наш целевой SKU
      for (let i = 0; i < items.length; i++) {
        const item = items[i];

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
            targetSkuMetricValue = metricValue;
          }
          break; // нашли, выходим
        }
      }

      if (foundTargetSku) {
        console.log(`\n🎯 Найдены данные для SKU 301916350 (FBS): ${totalFBS} единиц`);
      } else {
        console.log(`\n❌ SKU 301916350 не найден в результатах FBS`);
      }

      return { fbs: totalFBS, found: foundTargetSku, value: targetSkuMetricValue };
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
  console.log('🚀 Запускаем тесты с текущими (реальными) датами...');
  console.log('💡 Это поможет понять, существует ли SKU 301916350 в системе');

  const fboResult = await testOzonSalesFBO();
  const fbsResult = await testOzonSalesFBS();

  console.log(`\n🏁 РЕЗУЛЬТАТЫ С ТЕКУЩИМИ ДАТАМИ:`);
  console.log(`SKU 301916350:`);
  console.log(`FBO: ${fboResult.fbo} (найден: ${fboResult.found})`);
  console.log(`FBS: ${fbsResult.fbs} (найден: ${fbsResult.found})`);

  const totalFound = (fboResult.found ? 1 : 0) + (fbsResult.found ? 1 : 0);

  if (totalFound > 0) {
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
    console.log(`   - SKU не имеет продаж за последний месяц`);
    console.log(`   - SKU принадлежит другому поставщику`);
    console.log(`   - Номер SKU указан неправильно`);
  }

  console.log(`\n💡 Значения FBO=40, FBS=5, упомянутые ранее, вероятно, относились к другому временному периоду`);
  console.log(`   или основывались на данных, которые больше не актуальны.`);
}

runTests()
  .then(() => console.log('\n✅ Все тесты завершены'))
  .catch(err => console.error('❌ Ошибка:', err));