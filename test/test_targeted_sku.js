/**
 * Тестирование API с конкретным SKU 301916350 и датами 26.01.2026-26.02.2026
 * без дополнительных фильтров для понимания поведения API
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

// Тестируем вызов API для FBO с конкретным SKU и датами без фильтра по SKU на уровне API
async function testOzonSalesFBOWithoutSkuFilter() {
  console.log('🔍 Тестируем API вызов для FBO с датами 26.01.2026-26.02.2026 (без фильтра по SKU на API уровне)...');

  // Устанавливаем конкретные даты
  const dateFrom = new Date('2026-01-26');
  const dateTo = new Date('2026-02-26');

  console.log(`📅 Диапазон дат: ${formatDateTimeForAPI(dateFrom)} → ${formatDateTimeForAPI(dateTo)}`);

  // Подготовим тело запроса для FBO без фильтра по SKU на уровне API
  const body = {
    date_from: formatDateTimeForAPI(dateFrom),
    date_to: formatDateTimeForAPI(dateTo),
    dimension: ["sku"], // Размерность по SKU (используем правильное имя параметра как в документации)
    metrics: ["ordered_units"], // Используем метрики для получения данных о продажах (ordered_units - это проданные единицы)
    filters: [
      {
        column: "fulfillment_type",
        operation: "eq",
        values: ["fbo"]
      }
      // Без фильтра по SKU - будем фильтровать в приложении
    ],
    limit: 1000  // Добавляем лимит, как того требует API
  };

  console.log('📋 Тело запроса FBO (без фильтра по SKU):', JSON.stringify(body, null, 2));

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

        // Проверим, есть ли вообще этот SKU в результатах
        for (let i = 0; i < Math.min(items.length, 10); i++) {
          const item = items[i];
          for (const dim of item.dimensions) {
            if (dim.id) {
              console.log(`   Пример SKU из результата ${i+1}: ${dim.id}`);
              break;
            }
          }
        }
      }

      return { fbo: totalFBO, found: foundTargetSku, value: targetSkuValue, totalRecords: items.length };
    }
  } catch (error) {
    console.error('❌ Ошибка при вызове API (FBO) без фильтра по SKU:');
    if (error.response) {
      console.error('Статус:', error.response.status);
      console.error('Ответ:', error.response.data);
    } else if (error.request) {
      console.error('Запрос был сделан, но не получен ответ:', error.request);
    } else {
      console.error('Ошибка при настройке запроса:', error.message);
    }
  }

  return { fbo: 0, found: false, value: 0, totalRecords: 0 };
}

// Тестируем вызов API для FBS с конкретным SKU и датами без фильтра по SKU на уровне API
async function testOzonSalesFBSWithoutSkuFilter() {
  console.log('\n🔍 Тестируем API вызов для FBS с датами 26.01.2026-26.02.2026 (без фильтра по SKU на API уровне)...');

  // Устанавливаем конкретные даты
  const dateFrom = new Date('2026-01-26');
  const dateTo = new Date('2026-02-26');

  console.log(`📅 Диапазон дат: ${formatDateTimeForAPI(dateFrom)} → ${formatDateTimeForAPI(dateTo)}`);

  // Подготовим тело запроса для FBS без фильтра по SKU на уровне API
  const body = {
    date_from: formatDateTimeForAPI(dateFrom),
    date_to: formatDateTimeForAPI(dateTo),
    dimension: ["sku"], // Размерность по SKU (используем правильное имя параметра как в документации)
    metrics: ["ordered_units"], // Используем метрики для получения данных о продажах (ordered_units - это проданные единицы)
    filters: [
      {
        column: "fulfillment_type",
        operation: "eq",
        values: ["fbs"]
      }
      // Без фильтра по SKU - будем фильтровать в приложении
    ],
    limit: 1000  // Добавляем лимит, как того требует API
  };

  console.log('📋 Тело запроса FBS (без фильтра по SKU):', JSON.stringify(body, null, 2));

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

        // Проверим, есть ли вообще этот SKU в результатах
        for (let i = 0; i < Math.min(items.length, 10); i++) {
          const item = items[i];
          for (const dim of item.dimensions) {
            if (dim.id) {
              console.log(`   Пример SKU из результата ${i+1}: ${dim.id}`);
              break;
            }
          }
        }
      }

      return { fbs: totalFBS, found: foundTargetSku, value: targetSkuValue, totalRecords: items.length };
    }
  } catch (error) {
    console.error('❌ Ошибка при вызове API (FBS) без фильтра по SKU:');
    if (error.response) {
      console.error('Статус:', error.response.status);
      console.error('Ответ:', error.response.data);
    } else if (error.request) {
      console.error('Запрос был сделан, но не получен ответ:', error.request);
    } else {
      console.error('Ошибка при настройке запроса:', error.message);
    }
  }

  return { fbs: 0, found: false, value: 0, totalRecords: 0 };
}

// Запуск тестов
async function runTests() {
  console.log('🚀 Запускаем тесты с конкретными датами 26.01.2026-26.02.2026...');
  console.log('💡 Проверим, получим ли мы ожидаемые значения FBO 40 и FBS 5 для SKU 301916350');
  console.log('💡 Будем использовать подход без фильтрации по SKU на уровне API');

  const fboResult = await testOzonSalesFBOWithoutSkuFilter();
  const fbsResult = await testOzonSalesFBSWithoutSkuFilter();

  console.log(`\n🏁 РЕЗУЛЬТАТЫ С КОНКРЕТНЫМИ ДАТАМИ 26.01.2026-26.02.2026:`);
  console.log(`SKU 301916350:`);
  console.log(`FBO: ${fboResult.fbo} (ожидаемо: 40), найден: ${fboResult.found}, всего записей: ${fboResult.totalRecords}`);
  console.log(`FBS: ${fbsResult.fbs} (ожидаемо: 5), найден: ${fbsResult.found}, всего записей: ${fbsResult.totalRecords}`);

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
  console.log(`FBO: ${fboResult.fbo} ед., найден: ${fboResult.found}, всего записей: ${fboResult.totalRecords}`);
  console.log(`FBS: ${fbsResult.fbs} ед., найден: ${fbsResult.found}, всего записей: ${fbsResult.totalRecords}`);

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
    console.log(`❓ Возможно, данные за указанный период отсутствуют.`);
  }
}

runTests()
  .then(() => console.log('\n✅ Все тесты завершены'))
  .catch(err => console.error('❌ Ошибка:', err));