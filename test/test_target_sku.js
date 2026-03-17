/**
 * Тестирование API вызова для конкретного SKU 301916350
 * Должно вернуть: FBO 40, FBS 5 за месяц
 * Используем общий запрос и фильтруем результаты программно
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

// Тестируем вызов API без фильтрации по SKU, чтобы получить все данные
async function testCompleteData() {
  console.log('🔍 Тестируем API вызов без фильтрации по SKU для получения всех данных...');

  const monthRange = getMonthDateRangeForAnalytics();
  console.log(`📅 Диапазон дат: ${formatDateTimeForAPI(monthRange.start)} → ${formatDateTimeForAPI(monthRange.end)}`);

  // Подготовим тело запроса без фильтрации по SKU (только по типу исполнения)
  const body = {
    date_from: formatDateTimeForAPI(monthRange.start),
    date_to: formatDateTimeForAPI(monthRange.end),
    dimensions: ["sku", "fulfillment_type"], // Обе размерности для правильной группировки
    metrics: ["ordered_units"],
    filters: [
      // Без фильтра по SKU, чтобы получить все данные
    ],
    limit: 1000
  };

  console.log('📋 Тело запроса (без фильтра по SKU):', JSON.stringify(body, null, 2));

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

    console.log('✅ Успешный ответ от API:');
    // Не выводим весь JSON, так как он большой

    // Анализируем данные
    if (response.data && response.data.result && response.data.result.data) {
      const items = response.data.result.data;
      console.log(`\n📊 Найдено ${items.length} записей всего.`);

      // Теперь программно фильтруем результаты для нужного нам SKU
      let fboTotal = 0;
      let fbsTotal = 0;
      let foundTargetSku = false;

      items.forEach((item, index) => {
        // Найдем SKU и тип исполнения в размерностях
        let sku = null;
        let fulfillmentType = null;

        for (const dim of item.dimensions) {
          if (dim.id && !isNaN(parseInt(dim.id))) {
            // Это может быть SKU
            const parsedId = parseInt(dim.id);
            if (parsedId > 0) {
              sku = parsedId;
            }
          }

          // Проверим, является ли это типом исполнения
          if (dim.id === 'fbo' || dim.id === 'fbs') {
            fulfillmentType = dim.id;
          }
        }

        // Проверяем, совпадает ли SKU с целевым
        if (sku === 301916350) {
          foundTargetSku = true;

          if (item.metrics && Array.isArray(item.metrics) && item.metrics.length > 0) {
            const metricValue = item.metrics[0];

            if (fulfillmentType === 'fbo') {
              fboTotal += metricValue;
              console.log(`   SKU ${sku}, fulfillment: ${fulfillmentType}, Units sold: ${metricValue} (FBO)`);
            } else if (fulfillmentType === 'fbs') {
              fbsTotal += metricValue;
              console.log(`   SKU ${sku}, fulfillment: ${fulfillmentType}, Units sold: ${metricValue} (FBS)`);
            }
          }
        }
      });

      if (foundTargetSku) {
        console.log(`\n🎯 Результаты для SKU 301916350:`);
        console.log(`📊 FBO: ${fboTotal}`);
        console.log(`📊 FBS: ${fbsTotal}`);

        if (fboTotal === 40 && fbsTotal === 5) {
          console.log(`✅ Ура! Получены ожидаемые результаты: FBO=${fboTotal}, FBS=${fbsTotal}`);
        } else {
          console.log(`⚠️  Результаты отличаются от ожидаемых. Ожидается: FBO=40, FBS=5`);
        }
      } else {
        console.log(`\n❌ SKU 301916350 не найден в результатах.`);
        console.log(`💡 Возможно, у этого SKU нет продаж за указанный период или он не существует в системе.`);
      }
    }
  } catch (error) {
    console.error('❌ Ошибка при вызове API:');
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
testCompleteData()
  .then(() => console.log('\n✅ Тест завершен'))
  .catch(err => console.error('❌ Ошибка:', err));