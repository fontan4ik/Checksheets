/**
 * OZON ОТМЕНЫ И ВОЗВРАТЫ
 *
 * Заполняет колонки:
 * - BH (60): Отмены Озон (cancellations) — количество отменённых товаров за месяц
 * - BI (61): Возвраты Озон (returns) — количество возвращённых товаров за месяц
 *
 * Метод: v1/analytics/data (dimension: ["sku"], metrics: ["cancellations", "returns"])
 * Оба значения получаются за один запрос к API.
 *
 * Время выполнения зависит от числа строк аналитики; Ozon ограничивает
 * запросы примерно одним запросом в 7 секунд.
 */

/**
 * Основная функция: обновляет отмены (BH) и возвраты (BI) через analytics API.
 */
function updateOzonCancellationsAndReturns() {
  return runWithTelegramAlertGAS_('updateOzonCancellationsAndReturns', updateOzonCancellationsAndReturns_);
}

function updateOzonCancellationsAndReturns_() {
  const startTime = new Date();
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет данных для обработки");
    return;
  }

  SpreadsheetApp.getActiveSpreadsheet().toast("Запуск: отмены и возвраты Озон...", "Озон", 3);

  // Читаем SKU из колонки V (22)
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

  // Получаем диапазон дат — месяц (как в других функциях аналитики)
  const [startDate, endDate] = get3rdTo3rdDateRangeFormatted();
  Logger.log(`Период: ${startDate} → ${endDate}`);

  // API возвращает агрегированные данные по кабинету, поэтому количество
  // страниц не выводим из числа SKU на листе. Оставляем запас времени до
  // лимита Apps Script и не записываем частичную выдачу.
  const batchSize = 1000;
  const maxPages = 50;
  const maxRuntimeMs = 4 * 60 * 1000;
  const CUSTOM_RPS = 1 / 7; // 1 запрос в 7 секунд (аналитика Ozon)
  let lastRequestTime = Date.now() - 1000 / CUSTOM_RPS;

  // Карты: SKU → cancellations, SKU → returns
  const cancelMap = Object.create(null);
  const returnsMap = Object.create(null);
  let pageCount = 0;
  let receivedAllPages = false;

  for (let pageIndex = 0; pageIndex < maxPages; pageIndex++) {
    if (Date.now() - startTime.getTime() >= maxRuntimeMs) {
      throw new Error('Ozon analytics exceeded the safe runtime; refusing to write incomplete data');
    }
    lastRequestTime = rateLimitRPS(lastRequestTime, CUSTOM_RPS);

    const offset = pageIndex * batchSize;

    // API возвращает агрегированную выдачу кабинета с пагинацией.
    const body = {
      date_from: startDate,
      date_to: endDate,
      dimension: ["sku"],
      metrics: ["cancellations", "returns"],
      limit: batchSize,
      offset: offset
    };

    const options = {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify(body),
      muteHttpExceptions: true
    };

    const response = retryFetch(ozonAnalyticsData(), options);
    if (!response) {
      throw new Error(`Ozon analytics: no response for offset ${offset}; refusing to write incomplete data`);
    }

    const responseCode = response.getResponseCode();
    if (responseCode < 200 || responseCode >= 300) {
      throw new Error(`Ozon analytics: HTTP ${responseCode} for offset ${offset}; refusing to write incomplete data`);
    }

    const data = JSON.parse(response.getContentText());
    if (!Array.isArray(data.result?.data)) {
      throw new Error(`Ozon analytics response has no result.data array for offset ${offset}; refusing to write incomplete data`);
    }

    const items = data.result.data;
    items.forEach(entry => {
      const sku = entry?.dimensions?.[0]?.id?.toString();
      if (!sku || !Array.isArray(entry.metrics) || entry.metrics.length < 2) {
        throw new Error(`Ozon analytics has an incomplete row at offset ${offset}; refusing to write incomplete data`);
      }

      // metrics[0] = cancellations, metrics[1] = returns
      const cancellations = Number(entry.metrics[0] || 0);
      const returns = Number(entry.metrics[1] || 0);
      if (!Number.isFinite(cancellations) || !Number.isFinite(returns)) {
        throw new Error(`Ozon analytics has invalid metrics for SKU ${sku}; refusing to write incomplete data`);
      }
      if (cancellations > 0) cancelMap[sku] = (cancelMap[sku] || 0) + cancellations;
      if (returns > 0) returnsMap[sku] = (returnsMap[sku] || 0) + returns;
    });

    pageCount++;
    Logger.log(`  Страница ${pageCount}: ${items.length} записей (offset ${offset})`);

    // Если API вернул меньше batchSize — данные кончились.
    if (items.length < batchSize) {
      receivedAllPages = true;
      Logger.log(`  Данные закончились на странице ${pageCount}`);
      break;
    }
  }

  if (!receivedAllPages) {
    throw new Error(`Ozon analytics did not reach the end of the result within ${maxPages} pages; refusing to write incomplete data`);
  }

  Logger.log(`Отмены: ${Object.keys(cancelMap).length} SKU, Возвраты: ${Object.keys(returnsMap).length} SKU`);

  // Формируем массивы для записи
  const values = [];
  let totalCancellations = 0;
  let totalReturns = 0;

  skuIndexPairs.forEach(({ sku }) => {
    if (!sku) {
      values.push(["", ""]);
    } else {
      const cancelCount = cancelMap[sku] || 0;
      const returnsCount = returnsMap[sku] || 0;
      values.push([cancelCount, returnsCount]);
      totalCancellations += cancelCount;
      totalReturns += returnsCount;
    }
  });

  // Оба заголовка должны быть смежными, чтобы обновить их одним вызовом.
  const cancellationsColumn = columnByHeader_(sheet, 'Отмены Озон');
  const returnsColumn = columnByHeader_(sheet, 'Возвраты Озон');
  if (returnsColumn !== cancellationsColumn + 1) {
    throw new Error('Колонки «Отмены Озон» и «Возвраты Озон» должны идти рядом; запись отменена');
  }
  sheet.getRange(2, cancellationsColumn, values.length, 2).setValues(values);

  Logger.log(`✅ Отмены записаны в колонку ${cancellationsColumn}. Всего: ${totalCancellations} шт`);
  Logger.log(`✅ Возвраты записаны в колонку ${returnsColumn}. Всего: ${totalReturns} шт`);

  const endTime = new Date();
  const seconds = Math.round((endTime - startTime) / 1000);
  Logger.log(`⏱️ Время выполнения: ${seconds} сек.`);

  SpreadsheetApp.getActiveSpreadsheet().toast(`Отмены и возвраты обновлены (${seconds} сек)`, "Готово", 3);
}
