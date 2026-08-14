/**
 * OZON ОТМЕНЫ И ВОЗВРАТЫ
 *
 * Заполняет колонки:
 * - BH (61): Отмены Озон (cancellations) — количество отменённых товаров за месяц
 * - BI (62): Возвраты Озон (returns) — количество возвращённых товаров за месяц
 *
 * Метод: v1/analytics/data (dimension: ["sku"], metrics: ["cancellations", "returns"])
 * Оба значения получаются за один запрос к API.
 *
 * Время выполнения: зависит от числа SKU: запросы выполняются пачками по 1000 SKU.
 */

/**
 * Основная функция: обновляет отмены (BH) и возвраты (BI) через analytics API.
 */
function updateOzonCancellationsAndReturns() {
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

  // Параметры batch-запроса
  const batchSize = 1000;
  const totalBatches = Math.ceil(validSkus.length / batchSize);
  const CUSTOM_RPS = 1 / 7; // 1 запрос в 7 секунд (аналитика Ozon)
  let lastRequestTime = Date.now() - 1000 / CUSTOM_RPS;

  // Карты: SKU → cancellations, SKU → returns
  const cancelMap = {};
  const returnsMap = {};

  for (let batchIndex = 0; batchIndex < totalBatches; batchIndex++) {
    lastRequestTime = rateLimitRPS(lastRequestTime, CUSTOM_RPS);

    const skuBatch = validSkus.slice(batchIndex * batchSize, (batchIndex + 1) * batchSize);

    // Важно: offset не фильтрует товары. Без filters API возвращает общую
    // сортированную выдачу кабинета, и часть SKU из листа может не попасть в неё.
    // Поэтому каждый запрос ограничиваем своей пачкой SKU.
    const body = {
      date_from: startDate,
      date_to: endDate,
      dimension: ["sku"],
      metrics: ["cancellations", "returns"],
      filters: [{
        field: "sku",
        values: skuBatch,
        type: "INCLUDE"
      }],
      limit: batchSize,
      offset: 0
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
      Logger.log(`  Пакет ${batchIndex + 1}/${totalBatches}: нет ответа, пропускаем`);
      continue;
    }

    const responseCode = response.getResponseCode();
    if (responseCode < 200 || responseCode >= 300) {
      Logger.log(`  Пакет ${batchIndex + 1}/${totalBatches}: HTTP ${responseCode}: ${response.getContentText()}`);
      continue;
    }

    const data = JSON.parse(response.getContentText());
    if (!data.result?.data) {
      Logger.log(`  Пакет ${batchIndex + 1}/${totalBatches}: пустой ответ, пропускаем`);
      continue;
    }

    const items = data.result.data;
    items.forEach(entry => {
      const sku = entry.dimensions[0]?.id?.toString();
      if (sku && entry.metrics?.length >= 2) {
        // metrics[0] = cancellations, metrics[1] = returns
        const cancellations = entry.metrics[0] || 0;
        const returns = entry.metrics[1] || 0;

        if (cancellations > 0) {
          cancelMap[sku] = (cancelMap[sku] || 0) + cancellations;
        }
        if (returns > 0) {
          returnsMap[sku] = (returnsMap[sku] || 0) + returns;
        }
      }
    });

    Logger.log(`  Пакет ${batchIndex + 1}/${totalBatches}: ${items.length} записей`);

    // Неполная пачка означает лишь отсутствие движений у части SKU этой пачки,
    // а не окончание данных в следующих пачках.
  }

  Logger.log(`Отмены: ${Object.keys(cancelMap).length} SKU, Возвраты: ${Object.keys(returnsMap).length} SKU`);

  // Формируем массивы для записи
  const cancelValues = [];
  const returnsValues = [];
  let totalCancellations = 0;
  let totalReturns = 0;

  skuIndexPairs.forEach(({ sku }) => {
    if (!sku) {
      cancelValues.push([""]);
      returnsValues.push([""]);
    } else {
      const cancelCount = cancelMap[sku] || 0;
      const returnsCount = returnsMap[sku] || 0;
      cancelValues.push([cancelCount]);
      returnsValues.push([returnsCount]);
      totalCancellations += cancelCount;
      totalReturns += returnsCount;
    }
  });

  // Записываем в таблицу
  sheet.getRange(2, 60, cancelValues.length, 1).setValues(cancelValues);   // BH (60) — Отмены
  sheet.getRange(2, 61, returnsValues.length, 1).setValues(returnsValues); // BI (61) — Возвраты

  Logger.log(`✅ Отмены записаны в BH (60). Всего: ${totalCancellations} шт`);
  Logger.log(`✅ Возвраты записаны в BI (61). Всего: ${totalReturns} шт`);

  const endTime = new Date();
  const seconds = Math.round((endTime - startTime) / 1000);
  Logger.log(`⏱️ Время выполнения: ${seconds} сек.`);

  SpreadsheetApp.getActiveSpreadsheet().toast(`Отмены и возвраты обновлены (${seconds} сек)`, "Готово", 3);
}
