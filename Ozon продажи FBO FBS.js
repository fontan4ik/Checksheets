/**
 * OZON FBO/FBS ПРОДАЖИ (штуки)
 *
 * Заполняет колонки:
 * - AQ (43): Продажи штуки месяц FBO ОЗОН
 * - AR (44): Продажи штуки месяц FBS ОЗОН
 * - AS (45): Продажи штуки квартал FBO ОЗОН
 * - AT (46): Продажи штуки квартал FBS ОЗОН
 *
 * Метод:
 * 1. Общие продажи через v1/analytics/data (dimension: ["sku"], metric: ordered_units)
 * 2. FBS продажи через v3/posting/fbs/list (статусы в обработке/доставке;
 *    cancelled и not_accepted исключены из продаж)
 * 3. FBO = Общие - FBS
 */

function updateOzonFBOSales() {
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

  function postAnalyticsRequest(body) {
    const options = {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify(body)
    };
    const response = retryFetch(ozonAnalyticsData(), options);
    if (!response) return null;
    return JSON.parse(response.getContentText());
  }

  function fetchTotalSales(skuList, date_from, date_to, label) {
    const resultMap = {};
    const batchSize = 1000;
    const totalBatches = Math.ceil(skuList.length / batchSize);

    const CUSTOM_RPS = 1 / 7;
    let lastRequestTime = Date.now() - 1000 / CUSTOM_RPS;

    Logger.log(`[${label}] Общие продажи: ${date_from} → ${date_to}`);

    for (let batchIndex = 0; batchIndex < totalBatches; batchIndex++) {
      lastRequestTime = rateLimitRPS(lastRequestTime, CUSTOM_RPS);

      const body = {
        date_from: date_from,
        date_to: date_to,
        dimension: ["sku"],
        metrics: ["ordered_units"],
        limit: batchSize,
        offset: batchIndex * batchSize
      };

      const response = postAnalyticsRequest(body);
      if (!response || !response.result?.data) continue;

      response.result.data.forEach(entry => {
        const sku = entry.dimensions[0]?.id?.toString();
        if (sku && entry.metrics?.length > 0) {
          resultMap[sku] = (resultMap[sku] || 0) + (entry.metrics[0] || 0);
        }
      });

      Logger.log(`  Пакет ${batchIndex + 1}/${totalBatches}`);
    }

    return resultMap;
  }

  function fetchFBSSales(dateFrom, dateTo, label) {
    const resultMap = {};
    const url = "https://api-seller.ozon.ru/v3/posting/fbs/list";
    const CUSTOM_RPS = 1 / 5;
    let lastRequestTime = Date.now() - 1000 / CUSTOM_RPS;

    const statuses = ["awaiting_packaging", "awaiting_deliver", "last_mile", "delivering", "driver_pickup", "delivered"];

    statuses.forEach(status => {
      let offset = 0;
      let hasMore = true;
      let batchCount = 0;

      Logger.log(`  FBS статус "${status}"...`);

      while (hasMore) {
        lastRequestTime = rateLimitRPS(lastRequestTime, CUSTOM_RPS);

        const body = {
          dir: "ASC",
          filter: {
            since: dateFrom.toISOString(),
            to: dateTo.toISOString(),
            status: status
          },
          limit: 1000,
          offset: offset,
          with: {
            analytics_data: false,
            financial_data: false,
            translit: false
          }
        };

        const options = {
          method: "post",
          contentType: "application/json",
          headers: ozonHeaders(),
          payload: JSON.stringify(body),
          muteHttpExceptions: true
        };

        const response = retryFetch(url, options);
        if (!response) break;

        try {
          const data = JSON.parse(response.getContentText());
          const postings = data.result?.postings || [];
          hasMore = data.result?.has_next || false;

          postings.forEach(posting => {
            if (posting.products) {
              posting.products.forEach(product => {
                const sku = product.sku?.toString();
                const qty = product.quantity || 0;
                if (sku && qty > 0) {
                  resultMap[sku] = (resultMap[sku] || 0) + qty;
                }
              });
            }
          });

          offset += postings.length;
          batchCount++;

          if (batchCount % 10 === 0) {
            Logger.log(`    ${status}: обработано ${offset} постингов...`);
          }
        } catch (e) {
          Logger.log(`    Ошибка парсинга: ${e.message}`);
          break;
        }
      }

      Logger.log(`    ${status}: итого ${Object.keys(resultMap).length} уникальных SKU, ${offset} постингов`);
    });

    return resultMap;
  }

  const [startDate, endDate] = get3rdTo3rdDateRangeFormatted();
  const [startQuarter, endQuarter] = get3rdTo3rdQuarterRangeFormatted();

  const dateFromMonth = new Date(startDate);
  const dateToMonth = new Date(endDate);
  const dateFromQuarter = new Date(startQuarter);
  const dateToQuarter = new Date(endQuarter);

  Logger.log(`Месяц: ${startDate} → ${endDate}`);
  Logger.log(`Квартал: ${startQuarter} → ${endQuarter}`);

  const monthTotalSales = fetchTotalSales(validSkus, startDate, endDate, "Месяц");
  const quarterTotalSales = fetchTotalSales(validSkus, startQuarter, endQuarter, "Квартал");

  Logger.log(`Общие продажи месяц: ${Object.keys(monthTotalSales).length} SKU`);
  Logger.log(`Общие продажи квартал: ${Object.keys(quarterTotalSales).length} SKU`);

  const monthFBSSales = fetchFBSSales(dateFromMonth, dateToMonth, "Месяц");
  const quarterFBSSales = fetchFBSSales(dateFromQuarter, dateToQuarter, "Квартал");

  Logger.log(`FBS продажи месяц: ${Object.keys(monthFBSSales).length} SKU`);
  Logger.log(`FBS продажи квартал: ${Object.keys(quarterFBSSales).length} SKU`);

  const fboMonthList = [];
  const fbsMonthList = [];
  const fboQuarterList = [];
  const fbsQuarterList = [];

  let totalFboMonth = 0, totalFbsMonth = 0, totalFboQuarter = 0, totalFbsQuarter = 0;
  let skuWithFboMonth = 0, skuWithFbsMonth = 0;

  skuIndexPairs.forEach(({ sku }) => {
    if (!sku) {
      fboMonthList.push([""]);
      fbsMonthList.push([""]);
      fboQuarterList.push([""]);
      fbsQuarterList.push([""]);
    } else {
      const monthTotal = monthTotalSales[sku] || 0;
      const monthFBS = monthFBSSales[sku] || 0;
      const quarterTotal = quarterTotalSales[sku] || 0;
      const quarterFBS = quarterFBSSales[sku] || 0;

      const monthFBO = Math.max(0, monthTotal - monthFBS);
      const quarterFBO = Math.max(0, quarterTotal - quarterFBS);

      fboMonthList.push([monthFBO]);
      fbsMonthList.push([monthFBS]);
      fboQuarterList.push([quarterFBO]);
      fbsQuarterList.push([quarterFBS]);

      totalFboMonth += monthFBO;
      totalFbsMonth += monthFBS;
      totalFboQuarter += quarterFBO;
      totalFbsQuarter += quarterFBS;

      if (monthFBO > 0) skuWithFboMonth++;
      if (monthFBS > 0) skuWithFbsMonth++;
    }
  });

  sheet.getRange(2, 43, fboMonthList.length, 1).setValues(fboMonthList);
  sheet.getRange(2, 44, fbsMonthList.length, 1).setValues(fbsMonthList);
  sheet.getRange(2, 45, fboQuarterList.length, 1).setValues(fboQuarterList);
  sheet.getRange(2, 46, fbsQuarterList.length, 1).setValues(fbsQuarterList);

  Logger.log(`✅ Обновление завершено!`);
  Logger.log(`📊 Статистика:`);
  Logger.log(`   FBO месяц: ${totalFboMonth} шт (${skuWithFboMonth} SKU)`);
  Logger.log(`   FBS месяц: ${totalFbsMonth} шт (${skuWithFbsMonth} SKU)`);
  Logger.log(`   FBO квартал: ${totalFboQuarter} шт`);
  Logger.log(`   FBS квартал: ${totalFbsQuarter} шт`);

  const endTime = new Date();
  const seconds = Math.round((endTime - startTime) / 1000);
  Logger.log(`⏱️ Время выполнения: ${seconds} сек.`);
}

function get3rdTo3rdQuarterRangeFormatted() {
  const today = new Date();

  function formatDate(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  const startDate = new Date(today.getFullYear(), today.getMonth() - 3, today.getDate());
  const endDate = today;

  Logger.log(`Диапазон квартала (3 месяца назад по сегодня): ${formatDate(startDate)} → ${formatDate(endDate)}`);
  return [formatDate(startDate), formatDate(endDate)];
}

/**
 * ОТМЕНЫ ТОВАРОВ (cancellations) — отдельная функция
 *
 * Заполняет колонку BH (60): Отмены товаров за месяц
 * Метод: v1/analytics/data (dimension: ["sku"], metric: cancellations)
 */
function updateOzonCancellations() {
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

  Logger.log(`Уникальных SKU: ${validSkus.length}`);

  const [startDate, endDate] = get3rdTo3rdDateRangeFormatted();
  Logger.log(`Период: ${startDate} → ${endDate}`);

  const batchSize = 1000;
  const totalBatches = Math.ceil(validSkus.length / batchSize);
  const CUSTOM_RPS = 1 / 7;
  let lastRequestTime = Date.now() - 1000 / CUSTOM_RPS;

  // SKU → cancellations map
  const cancelMap = {};

  for (let batchIndex = 0; batchIndex < totalBatches; batchIndex++) {
    lastRequestTime = rateLimitRPS(lastRequestTime, CUSTOM_RPS);

    const body = {
      date_from: startDate,
      date_to: endDate,
      dimension: ["sku"],
      metrics: ["cancellations"],
      limit: batchSize,
      offset: batchIndex * batchSize
    };

    const options = {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify(body)
    };

    const response = retryFetch(ozonAnalyticsData(), options);
    if (!response) continue;

    const data = JSON.parse(response.getContentText());
    if (!data.result?.data) continue;

    data.result.data.forEach(entry => {
      const sku = entry.dimensions[0]?.id?.toString();
      if (sku && entry.metrics?.length > 0) {
        cancelMap[sku] = (cancelMap[sku] || 0) + (entry.metrics[0] || 0);
      }
    });

    Logger.log(`  Пакет ${batchIndex + 1}/${totalBatches}`);
  }

  Logger.log(`Получено отмен: ${Object.keys(cancelMap).length} SKU`);

  // Собираем массив для записи
  const values = [];
  let totalCancellations = 0;

  skuIndexPairs.forEach(({ sku }) => {
    if (!sku) {
      values.push([""]);
    } else {
      const count = cancelMap[sku] || 0;
      values.push([count]);
      totalCancellations += count;
    }
  });

  sheet.getRange(2, 60, values.length, 1).setValues(values);

  Logger.log(`✅ Отмены записаны в BH (60). Всего: ${totalCancellations} шт`);

  const endTime = new Date();
  const seconds = Math.round((endTime - startTime) / 1000);
  Logger.log(`⏱️ Время выполнения: ${seconds} сек.`);
}
