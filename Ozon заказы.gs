function fetchAndWriteAnalytics() {
  const startTime = new Date();
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();
  const skuRange = sheet.getRange("V2:V" + lastRow);
  const skuRawValues = skuRange.getValues().flat();

  const skuIndexPairs = skuRawValues.map((sku, index) => ({
    sku: sku?.toString().trim() || "",
    rowIndex: index
  }));

  const validSkus = [...new Set(skuIndexPairs.filter(x => x.sku !== "").map(x => x.sku))];

  if (validSkus.length === 0) {
    Logger.log("Нет SKU для обработки");
    return;
  }

  Logger.log(`Общее количество уникальных SKU для обработки: ${validSkus.length}`);

  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);

  const startMonth = new Date(today.getFullYear(), today.getMonth(), 1);
  // const startQuarter = new Date(today.getFullYear(), today.getMonth() - 2, 1);

  function formatDate(d) {
    return d.toISOString().slice(0, 10);
  }

  function postRequest(body) {
    // Logger.log(body)
    const options = {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify(body)
    };
    const response = retryFetch(ozonAnalyticsData(), options);

    if (!response) {
      Logger.log(`❌ Не удалось получить аналитику Ozon`);
      return null;
    }

    // Logger.log(response)
    return JSON.parse(response.getContentText());
  }

  function batchFetchAnalytics(skuList, date_from, date_to, metrics, label) {
    const resultMap = {};
    const batchSize = 1000;
    const totalBatches = Math.ceil(skuList.length / batchSize);

    // Используем более жесткие лимиты в этом скрипте
    const CUSTOM_RPS = 1 / 7;
    let lastRequestTime = Date.now() - 1000 / CUSTOM_RPS;

    // Итерации
    for (let batchIndex = 0; batchIndex < totalBatches; batchIndex++) {
      lastRequestTime = rateLimitRPS(lastRequestTime, CUSTOM_RPS);

      const offset = batchIndex * batchSize;

      const body = {
        date_from: date_from,
        date_to: date_to,
        dimension: ["sku"],
        metrics: metrics,
        limit: batchSize,
        offset: offset
      };
      const response = postRequest(body);

      const data = response?.result?.data || [];
      // Logger.log(data)
      data.forEach(entry => {
        const skuObj = entry.dimensions[0];
        const sku = skuObj?.id?.toString();
        // Logger.log(`SKU: ${sku}, Metrics: ${entry.metrics}`);
        if (sku) {
          resultMap[sku] = entry.metrics;
        }
      });
    }

    // ИСПРАВЛЕНО: правильный подсчёт missing SKU
    let foundCount = 0;
    let missingCount = 0;

    skuList.forEach(sku => {
      if (resultMap.hasOwnProperty(sku)) {
        foundCount++;
      } else {
        missingCount++;
      }
    });

    const extraInResult = Object.keys(resultMap).length - foundCount;
    Logger.log(`[${label}] Найдено: ${foundCount}, Не найдено: ${missingCount} из ${skuList.length}`);
    if (extraInResult > 0) {
      Logger.log(`[${label}] Доп. SKU в API (не из списка): ${extraInResult}`);
    }

    return resultMap;
  }
  const [startDate, endDate] = get3rdTo3rdDateRangeFormatted();
  const [startQuarter, endQuarter] = getLastNDaysRangeFormatted(91);

  Logger.log("Начало периода (месяц назад по сегодня): " + startDate);
  Logger.log("Конец периода: " + endDate);

  // Получаем результаты
  // ИСПРАВЛЕНО: правильные metrics для получения суммы в рублях
  // ordered_units - заказанные единицы (шт)
  // revenue - сумма заказов в рублях (НЕ ordered_sum!)
  const monthMetricsMap = batchFetchAnalytics(validSkus, startDate, endDate,
    ["ordered_units", "revenue"], "Месяц");
  const quarterMetricsMap = batchFetchAnalytics(validSkus, startQuarter, endQuarter, ["ordered_units"], "Квартал");

  // ДИАГНОСТИКА: Проверка конкретного SKU 301854987 (22068-1)
  const testSku = "301854987";
  const testData = monthMetricsMap[testSku];
  Logger.log(`=== ДИАГНОСТИКА 22068-1 (SKU: ${testSku}) ===`);
  if (testData) {
    Logger.log(`✅ ДАННЫЕ НАЙДЕНЫ:`);
    Logger.log(`   Уход Мес: ${testData[0]}`);
    Logger.log(`   Сумма заказов: ${testData[1]}`);
  } else {
    Logger.log(`❌ ДАННЫЕ НЕ НАЙДЕНЫ в monthMetricsMap`);
    Logger.log(`   SKU "${testSku}" отсутствует в API ответе`);
    // Проверяем есть ли SKU в validSkus
    const skuExists = validSkus.includes(testSku);
    Logger.log(`   SKU в validSkus: ${skuExists ? "✅ ДА" : "❌ НЕТ"}`);
  }
  Logger.log("");

  const orderedUnitsMonthList = [];
  const orderedUnitsQuarterList = [];
  const revenueMonthList = [];

  let found22068 = false;
  // testSku уже объявлен выше (строка 114)

  skuIndexPairs.forEach(({ sku }) => {
    // ДИАГНОСТИКА для 22068-1
    if (sku === testSku) {
      found22068 = true;
      const monthMetrics = monthMetricsMap[sku] || [0, 0];
      const quarterMetrics = quarterMetricsMap[sku] || [0];
      Logger.log(`=== ЗАПИСЬ 22068-1 (SKU: ${sku}) ===`);
      Logger.log(`   monthMetrics: ${JSON.stringify(monthMetrics)}`);
      Logger.log(`   quarterMetrics: ${JSON.stringify(quarterMetrics)}`);
      Logger.log(`   Будет записано в I (9): ${monthMetrics[0] || 0}`);
      Logger.log(`   Будет записано в L (12): ${monthMetrics[1] || 0}`);
    }
    if (!sku) {
      orderedUnitsMonthList.push([""]);
      orderedUnitsQuarterList.push([""]);
      revenueMonthList.push([""]);
    } else {
      const monthMetrics = monthMetricsMap[sku] || [0, 0];
      const quarterMetrics = quarterMetricsMap[sku] || [0];

      orderedUnitsMonthList.push([monthMetrics[0] || 0]);
      orderedUnitsQuarterList.push([quarterMetrics[0] || 0]);
      // revenue уже в рублях (API аналитики возвращает в рублях, не в копейках)
      revenueMonthList.push([monthMetrics[1] || 0]);
    }
  });

  // ДИАГНОСТИКА: Проверка что 22068-1 вообще есть в таблице
  Logger.log(`=== ПРОВЕРКА НАЛИЧИЯ 22068-1 ===`);
  Logger.log(`   SKU "${testSku}" найден в skuIndexPairs: ${found22068 ? "✅ ДА" : "❌ НЕТ"}`);
  if (!found22068) {
    Logger.log(`   Возможные причины:`);
    Logger.log(`   1. SKU не заполнен в таблице (колонка V)`);
    Logger.log(`   2. SKU имеет другой формат (пробелы, тип данных)`);
    Logger.log(`   Первые 5 SKU из таблицы:`);
    skuIndexPairs.slice(0, 5).forEach((p, i) => {
      Logger.log(`     [${i}] "${p.sku}" (type: ${typeof p.sku})`);
    });
  }
  Logger.log("");

  sheet.getRange(2, 9, orderedUnitsMonthList.length, 1).setValues(orderedUnitsMonthList);   // I (9): Уход Мес ОЗОН
  sheet.getRange(2, 10, orderedUnitsQuarterList.length, 1).setValues(orderedUnitsQuarterList); // J (10): Уход КВ
  sheet.getRange(2, 12, revenueMonthList.length, 1).setValues(revenueMonthList);              // L (12): Сумма заказов Мес ОЗОН

  // ДИАГНОСТИКА для 22068-1 (SKU: 301854987)
  const testMonthData = monthMetricsMap[testSku] || [0, 0];
  const testQuarterData = quarterMetricsMap[testSku] || [0];
  Logger.log(``);
  Logger.log(`=== ДИАГНОСТИКА 22068-1 (SKU: ${testSku}) ===`);
  Logger.log(`   I (9) Уход Мес ОЗОН: ${testMonthData[0]} (ожидается 1252)`);
  Logger.log(`   J (10) Уход КВ ОЗОН: ${testQuarterData[0]} (ожидается 2452)`);
  Logger.log(`   L (12) Сумма заказов: ${testMonthData[1]} (ожидается 1816419)`);
  const monthOk = testMonthData[0] >= 1250 && testMonthData[1] >= 1810000;
  Logger.log(`${monthOk ? '✅' : '⚠️'} Проверка данных`);

  const endTime = new Date();
  const seconds = Math.round((endTime - startTime) / 1000);
  Logger.log(`✅ Завершено. Время выполнения: ${seconds} сек.`);
}

// Диапазон: сегодняшнее число прошлого месяца по сегодня
// Пример: если сегодня 11.02.2026, то диапазон с 2026-01-11 по 2026-02-11
function get3rdTo3rdDateRangeFormatted() {
  const today = new Date();

  // Форматирование даты
  function formatDate(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  // Начало: тот же день, но месяц назад
  const startDate = new Date(today.getFullYear(), today.getMonth() - 1, today.getDate());
  const endDate = today;

  Logger.log(`Диапазон (месяц назад по сегодня): ${formatDate(startDate)} → ${formatDate(endDate)}`);
  return [formatDate(startDate), formatDate(endDate)];
}

// function getLast3MonthsDateRangeFormatted() {
//   const today = new Date();

//   // Начало месяца 3 месяца назад
//   const startOfQuarter = new Date(today.getFullYear(), today.getMonth() - 2, 1);

//   // Форматирование в YYYY-MM-DD
//   function formatDate(date) {
//     return date.toISOString().slice(0, 10);
//   }

//   return [formatDate(startOfQuarter), formatDate(today)];
// }

function getLastNDaysRangeFormatted(days) {
  const today = new Date();
  const pastDate = new Date(today);
  pastDate.setDate(today.getDate() - days);

  function formatDate(date) {
    return date.toISOString().slice(0, 10);
  }
  Logger.log(pastDate)
  Logger.log(today)
  return [formatDate(pastDate), formatDate(today)];
}

