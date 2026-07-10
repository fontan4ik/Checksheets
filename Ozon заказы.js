const OZON_ANALYTICS_STATE_KEY = "OZON_ANALYTICS_PERIOD_INDEX";
const OZON_ANALYTICS_BATCH_INDEX_KEY = "OZON_ANALYTICS_BATCH_INDEX";
const OZON_ANALYTICS_PERIOD_RETRY_KEY = "OZON_ANALYTICS_PERIOD_RETRY_COUNT";
const OZON_ANALYTICS_RUN_ID_KEY = "OZON_ANALYTICS_RUN_ID";
const OZON_ANALYTICS_TEMP_FILE_ID_KEY = "OZON_ANALYTICS_TEMP_FILE_ID";
const OZON_ANALYTICS_CONTINUATION_HANDLER = "continueFetchAndWriteAnalytics";
const OZON_ANALYTICS_RPS = 1 / 8;
const OZON_ANALYTICS_BATCH_SIZE = 500;
const OZON_ANALYTICS_MAX_RETRIES = 3;
const OZON_ANALYTICS_MAX_RUN_MS = 4.5 * 60 * 1000;
const OZON_ANALYTICS_RETRY_BASE_DELAY_MS = 30000;

function fetchAndWriteAnalytics() {
  fetchAndWriteAnalytics_(false);
}

function startFetchAndWriteAnalytics() {
  fetchAndWriteAnalytics_(true);
}

function fetchAndWriteAnalytics_(resetState) {
  const startTime = new Date();
  const lock = LockService.getScriptLock();

  if (!lock.tryLock(5000)) {
    Logger.log("fetchAndWriteAnalytics уже выполняется. Повторный запуск пропущен.");
    return;
  }

  try {
  const props = PropertiesService.getScriptProperties();
  if (resetState) {
    props.deleteProperty(OZON_ANALYTICS_STATE_KEY);
    props.deleteProperty(OZON_ANALYTICS_BATCH_INDEX_KEY);
    props.deleteProperty(OZON_ANALYTICS_PERIOD_RETRY_KEY);
    props.setProperty(OZON_ANALYTICS_RUN_ID_KEY, String(Date.now()));
    clearOzonAnalyticsTempStorage_();
    deleteOzonAnalyticsContinuationTriggers_();
    Logger.log("Состояние Ozon analytics сброшено: начинается новый полный цикл");
  }

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

  function postRequest(body) {
    // Logger.log(body)
    const options = {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify(body),
      muteHttpExceptions: true
    };
    const response = fetchOzonAnalyticsResponse_(ozonAnalyticsData(), options, OZON_ANALYTICS_MAX_RETRIES);

    if (!response) {
      Logger.log(`Пакет Ozon analytics временно не получен, будет повторён следующим запуском`);
      return { ok: false, retryable: true };
    }

    const responseCode = response.getResponseCode();
    if (responseCode < 200 || responseCode >= 300) {
      const retryable = responseCode === 429 || responseCode >= 500;
      Logger.log(`Ozon analytics вернул HTTP ${responseCode}: ${response.getContentText().substring(0, 500)}`);
      return { ok: false, retryable: retryable };
    }

    // Logger.log(response)
    return { ok: true, data: JSON.parse(response.getContentText()) };
  }

  function batchFetchAnalytics(skuList, date_from, date_to, metrics, label, periodIndex, runId, startBatchIndex) {
    const batchSize = OZON_ANALYTICS_BATCH_SIZE;
    const totalBatches = Math.ceil(skuList.length / batchSize);
    let batchIndex = startBatchIndex || 0;

    let lastRequestTime = Date.now() - 1000 / OZON_ANALYTICS_RPS;

    Logger.log(`[${label}] Период: ${date_from} → ${date_to}`);
    Logger.log(`[${label}] SKU: ${skuList.length}, Пакетов: ${totalBatches}, Темп: ${OZON_ANALYTICS_RPS} RPS`);
    Logger.log(`[${label}] Продолжение с пакета ${batchIndex + 1}/${totalBatches}`);

    // Итерации
    for (; batchIndex < totalBatches; batchIndex++) {
      if (Date.now() - startTime > OZON_ANALYTICS_MAX_RUN_MS) {
        Logger.log(`[${label}] Достигнут безопасный лимит времени. Продолжим с пакета ${batchIndex + 1}/${totalBatches}`);
        return {
          complete: false,
          retryable: true,
          nextBatchIndex: batchIndex,
          totalBatches: totalBatches
        };
      }

      lastRequestTime = rateLimitRPS(lastRequestTime, OZON_ANALYTICS_RPS);

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

      if (!response.ok) {
        Logger.log(`[${label}] Пакет ${batchIndex + 1}/${totalBatches} не обработан. Продолжим с него после паузы`);
        return {
          complete: false,
          retryable: response.retryable,
          nextBatchIndex: batchIndex,
          totalBatches: totalBatches
        };
      }

      const data = response.data?.result?.data || [];
      const tempRows = [];
      // Logger.log(data)
      data.forEach(entry => {
        const skuObj = entry.dimensions[0];
        const sku = skuObj?.id?.toString();
        // Logger.log(`SKU: ${sku}, Metrics: ${entry.metrics}`);
        if (sku) {
          const entryMetrics = entry.metrics || [];
          tempRows.push([runId, periodIndex, sku, entryMetrics[0] || 0, entryMetrics.length > 1 ? entryMetrics[1] || 0 : ""]);
        }
      });

      appendOzonAnalyticsTempRows_(tempRows);
      props.setProperty(OZON_ANALYTICS_BATCH_INDEX_KEY, String(batchIndex + 1));
      Logger.log(`[${label}] Пакет ${batchIndex + 1}/${totalBatches} обработан, строк: ${data.length}`);
    }

    const resultMap = loadOzonAnalyticsTempMap_(runId, periodIndex);

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

    return {
      complete: true,
      data: resultMap,
      nextBatchIndex: totalBatches,
      totalBatches: totalBatches
    };
  }
  const [startDate, endDate] = get3rdTo3rdDateRangeFormatted();
  const [startQuarter, endQuarter] = getFixedQuarterRangeFormatted();
  const [startYear, endYear] = getYearDateRangeFormatted();
  const periods = [
    {
      label: "Месяц",
      from: startDate,
      to: endDate,
      metrics: ["ordered_units", "revenue"],
      write: function (metricsMap) {
        const orderedUnitsMonthList = [];
        const revenueMonthList = [];

        skuIndexPairs.forEach(({ sku }) => {
          if (!sku) {
            orderedUnitsMonthList.push([""]);
            revenueMonthList.push([""]);
          } else {
            const monthMetrics = metricsMap[sku] || [0, 0];
            orderedUnitsMonthList.push([monthMetrics[0] || 0]);
            revenueMonthList.push([monthMetrics[1] || 0]);
          }
        });

        sheet.getRange(2, 9, orderedUnitsMonthList.length, 1).setValues(orderedUnitsMonthList);
        sheet.getRange(2, 12, revenueMonthList.length, 1).setValues(revenueMonthList);
      }
    },
    {
      label: "Квартал",
      from: startQuarter,
      to: endQuarter,
      metrics: ["ordered_units"],
      write: function (metricsMap) {
        const orderedUnitsQuarterList = [];

        skuIndexPairs.forEach(({ sku }) => {
          if (!sku) {
            orderedUnitsQuarterList.push([""]);
          } else {
            const quarterMetrics = metricsMap[sku] || [0];
            orderedUnitsQuarterList.push([quarterMetrics[0] || 0]);
          }
        });

        sheet.getRange(2, 10, orderedUnitsQuarterList.length, 1).setValues(orderedUnitsQuarterList);
      }
    },
    {
      label: "Год",
      from: startYear,
      to: endYear,
      metrics: ["revenue"],
      write: function (metricsMap) {
        const revenueYearList = [];

        skuIndexPairs.forEach(({ sku }) => {
          if (!sku) {
            revenueYearList.push([""]);
          } else {
            const yearMetrics = metricsMap[sku] || [0];
            revenueYearList.push([yearMetrics[0] || 0]);
          }
        });

        sheet.getRange(2, 41, revenueYearList.length, 1).setValues(revenueYearList);
      }
    }
  ];

  Logger.log("Начало периода (месяц назад по вчера): " + startDate);
  Logger.log("Конец периода: " + endDate);

  const periodIndex = Math.max(0, Math.min(Number(props.getProperty(OZON_ANALYTICS_STATE_KEY)) || 0, periods.length - 1));
  const startBatchIndex = Math.max(0, Number(props.getProperty(OZON_ANALYTICS_BATCH_INDEX_KEY)) || 0);
  const runId = props.getProperty(OZON_ANALYTICS_RUN_ID_KEY) || String(Date.now());
  props.setProperty(OZON_ANALYTICS_RUN_ID_KEY, runId);
  const period = periods[periodIndex];

  Logger.log(`Обрабатывается период ${periodIndex + 1}/${periods.length}: ${period.label}`);
  const result = batchFetchAnalytics(validSkus, period.from, period.to, period.metrics, period.label, periodIndex, runId, startBatchIndex);

  if (!result.complete) {
    props.setProperty(OZON_ANALYTICS_STATE_KEY, String(periodIndex));
    props.setProperty(OZON_ANALYTICS_BATCH_INDEX_KEY, String(result.nextBatchIndex));
    const retryCount = (Number(props.getProperty(OZON_ANALYTICS_PERIOD_RETRY_KEY)) || 0) + 1;
    props.setProperty(OZON_ANALYTICS_PERIOD_RETRY_KEY, String(retryCount));

    const delayMs = result.retryable ? 5 * 60 * 1000 : 60 * 1000;
    scheduleOzonAnalyticsContinuation_(delayMs);
    Logger.log(`[${period.label}] Пауза перед продолжением. Следующий запуск начнёт с пакета ${result.nextBatchIndex + 1}/${result.totalBatches}`);
    return;
  }

  if (result.complete) {
    if (Object.keys(result.data || {}).length === 0) {
      props.setProperty(OZON_ANALYTICS_STATE_KEY, String(periodIndex));
      props.deleteProperty(OZON_ANALYTICS_BATCH_INDEX_KEY);
      clearOzonAnalyticsTempStorage_();
      scheduleOzonAnalyticsContinuation_(5 * 60 * 1000);
      Logger.log(`[${period.label}] Получено 0 строк аналитики. Запись нулей отменена, период будет повторён с начала`);
      return;
    }

    props.deleteProperty(OZON_ANALYTICS_PERIOD_RETRY_KEY);
    props.deleteProperty(OZON_ANALYTICS_BATCH_INDEX_KEY);
    period.write(result.data);
    Logger.log(`[${period.label}] Данные записаны в таблицу`);
  }

  if (periodIndex < periods.length - 1) {
    props.setProperty(OZON_ANALYTICS_STATE_KEY, String(periodIndex + 1));
    scheduleOzonAnalyticsContinuation_();
    Logger.log(`Следующий период будет обработан отдельным запуском: ${periods[periodIndex + 1].label}`);
  } else {
    props.deleteProperty(OZON_ANALYTICS_STATE_KEY);
    props.deleteProperty(OZON_ANALYTICS_BATCH_INDEX_KEY);
    props.deleteProperty(OZON_ANALYTICS_PERIOD_RETRY_KEY);
    props.deleteProperty(OZON_ANALYTICS_RUN_ID_KEY);
    deleteOzonAnalyticsContinuationTriggers_();
    clearOzonAnalyticsTempStorage_();
    Logger.log("Все периоды Ozon analytics обработаны");
  }

  const endTime = new Date();
  const seconds = Math.round((endTime - startTime) / 1000);
  Logger.log(`✅ Завершено. Время выполнения: ${seconds} сек.`);
  } finally {
    lock.releaseLock();
  }
}

function continueFetchAndWriteAnalytics() {
  fetchAndWriteAnalytics();
}

function stopOzonAnalyticsTriggers() {
  const props = PropertiesService.getScriptProperties();
  props.deleteProperty(OZON_ANALYTICS_STATE_KEY);
  props.deleteProperty(OZON_ANALYTICS_BATCH_INDEX_KEY);
  props.deleteProperty(OZON_ANALYTICS_PERIOD_RETRY_KEY);
  props.deleteProperty(OZON_ANALYTICS_RUN_ID_KEY);
  props.deleteProperty(OZON_ANALYTICS_TEMP_FILE_ID_KEY);

  deleteOzonAnalyticsContinuationTriggers_();
  clearOzonAnalyticsTempStorage_();
  Logger.log("Ozon analytics остановлен: триггеры продолжения, состояние и временные данные очищены");
}

function fetchOzonAnalyticsResponse_(url, options, maxRetries) {
  const retries = maxRetries || 2;

  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      const response = UrlFetchApp.fetch(url, options);
      const responseCode = response.getResponseCode();

      if (responseCode >= 200 && responseCode < 300) {
        return response;
      }

      const body = response.getContentText();
      Logger.log(`⚠️ Ozon analytics HTTP ${responseCode}. Попытка ${attempt}/${retries}. Ответ: ${body.substring(0, 500)}`);

      if (responseCode < 500 && responseCode !== 429) {
        return response;
      }
    } catch (e) {
      Logger.log(`⚠️ Ошибка запроса Ozon analytics. Попытка ${attempt}/${retries}: ${e.toString()}`);
    }

    if (attempt < retries) {
      const waitTime = Math.pow(2, attempt - 1) * OZON_ANALYTICS_RETRY_BASE_DELAY_MS;
      Logger.log(`Пауза перед повтором Ozon analytics: ${Math.round(waitTime / 1000)} сек`);
      Utilities.sleep(waitTime);
    }
  }

  Logger.log(`Max retries reached for URL: ${url}`);
  return null;
}

function appendOzonAnalyticsTempRows_(rows) {
  if (!rows || rows.length === 0) return;

  const payload = readOzonAnalyticsTempPayload_();
  payload.rows = payload.rows.concat(rows);
  writeOzonAnalyticsTempPayload_(payload);
}

function loadOzonAnalyticsTempMap_(runId, periodIndex) {
  const result = {};
  const payload = readOzonAnalyticsTempPayload_();

  payload.rows.forEach(row => {
    if (String(row[0]) !== String(runId) || Number(row[1]) !== Number(periodIndex)) return;

    const sku = row[2]?.toString();
    if (!sku) return;

    result[sku] = row[4] === "" ? [row[3] || 0] : [row[3] || 0, row[4] || 0];
  });

  return result;
}

function readOzonAnalyticsTempPayload_() {
  const props = PropertiesService.getScriptProperties();
  const fileId = props.getProperty(OZON_ANALYTICS_TEMP_FILE_ID_KEY);

  if (!fileId) {
    return { rows: [] };
  }

  try {
    const text = DriveApp.getFileById(fileId).getBlob().getDataAsString();
    return JSON.parse(text || '{"rows":[]}');
  } catch (e) {
    Logger.log(`Не удалось прочитать временный файл Ozon analytics: ${e.toString()}`);
    return { rows: [] };
  }
}

function writeOzonAnalyticsTempPayload_(payload) {
  const props = PropertiesService.getScriptProperties();
  let fileId = props.getProperty(OZON_ANALYTICS_TEMP_FILE_ID_KEY);
  const content = JSON.stringify(payload);

  if (fileId) {
    DriveApp.getFileById(fileId).setContent(content);
    return;
  }

  const runId = props.getProperty(OZON_ANALYTICS_RUN_ID_KEY) || String(Date.now());
  const file = DriveApp.createFile(`ozon_analytics_tmp_${runId}.json`, content, MimeType.PLAIN_TEXT);
  props.setProperty(OZON_ANALYTICS_TEMP_FILE_ID_KEY, file.getId());
}

function clearOzonAnalyticsTempStorage_() {
  const props = PropertiesService.getScriptProperties();
  const fileId = props.getProperty(OZON_ANALYTICS_TEMP_FILE_ID_KEY);

  if (fileId) {
    try {
      DriveApp.getFileById(fileId).setTrashed(true);
    } catch (e) {
      Logger.log(`Не удалось удалить временный файл Ozon analytics: ${e.toString()}`);
    }
  }

  props.deleteProperty(OZON_ANALYTICS_TEMP_FILE_ID_KEY);
}

function scheduleOzonAnalyticsContinuation_(delayMs) {
  deleteOzonAnalyticsContinuationTriggers_();
  ScriptApp.newTrigger(OZON_ANALYTICS_CONTINUATION_HANDLER)
    .timeBased()
    .after(delayMs || 60 * 1000)
    .create();
}

function deleteOzonAnalyticsContinuationTriggers_() {
  ScriptApp.getProjectTriggers().forEach(trigger => {
    if (trigger.getHandlerFunction && trigger.getHandlerFunction() === OZON_ANALYTICS_CONTINUATION_HANDLER) {
      ScriptApp.deleteTrigger(trigger);
    }
  });
}

// Диапазон: месяц назад по вчера.
// Данные Ozon analytics за текущую дату могут быть ещё не рассчитаны.
// Пример: если сегодня 11.02.2026, то диапазон с 2026-01-10 по 2026-02-10
function get3rdTo3rdDateRangeFormatted() {
  const today = new Date();
  const endDate = new Date(today);
  endDate.setDate(today.getDate() - 1);

  // Форматирование даты
  function formatDate(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  // Начало: тот же день, что и конечная дата, но месяц назад
  const startDate = new Date(endDate.getFullYear(), endDate.getMonth() - 1, endDate.getDate());

  Logger.log(`Диапазон (месяц назад по вчера): ${formatDate(startDate)} → ${formatDate(endDate)}`);
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

// Функция для получения фиксированного диапазона дат для квартала: 2025-11-25 → 2026-02-25
function getFixedQuarterRangeFormatted() {
  // Фиксированные даты: 2025-11-25 → 2026-02-25
  const startDate = new Date('2025-11-25');
  const endDate = new Date('2026-02-25');

  function formatDate(date) {
    return date.toISOString().slice(0, 10);
  }

  Logger.log(`Фиксированный диапазон квартала: ${formatDate(startDate)} → ${formatDate(endDate)}`);
  return [formatDate(startDate), formatDate(endDate)];
}

// Диапазон за год: последние 365 дней по вчера.
// Пример: если сегодня 17.02.2026, то диапазон с 2025-02-16 по 2026-02-16
// ОГРАНИЧЕНИЕ API: "cannot get more than one year" (максимум 365 дней)
function getYearDateRangeFormatted() {
  const today = new Date();
  const endDate = new Date(today);
  endDate.setDate(today.getDate() - 1);

  // Начало: 365 дней назад
  const startOfYear = new Date(endDate);
  startOfYear.setDate(endDate.getDate() - 365);

  function formatDate(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  Logger.log(`Диапазон (год, 365 дней по вчера): ${formatDate(startOfYear)} → ${formatDate(endDate)}`);
  return [formatDate(startOfYear), formatDate(endDate)];
}
