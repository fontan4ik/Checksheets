/**
 * OZON UNIT API: начисления + реклама
 *
 * Заполняет лист "UNIT API" по существующим заголовкам.
 * Лист UNIT API должен повторять структуру листа UNIT.
 * - UNIT СУММА = posting.products[].commission.sale_amount из accrual/by-day
 * - UNIT ШТ = восстановленное количество продаж из accrual/by-day: sale_amount / seller_price
 * - ВОЗНАГРАЖДЕНИЕ = posting.products[].commission.commission из accrual/by-day
 * - ЛОГИСТИКА = delivery.services type_id=32 из accrual/by-day
 * - ПЕРЕПЛАТА = отдельная корректировка логистики из листа UNIT API/UNIT, отдельного поля в accrual/by-day нет
 * - ХРАНЕНИЕ = отчёт стоимости размещения /v1/report/placement/by-products/create
 * - ДОП = зелёная группа поартикульных дополнительных услуг из отчёта начислений
 * - ОЗОН ДОП ВОЗНЯ = общие non_item_fee без артикула из accrual/by-day со знаком расхода, кроме кликов и оплаты за заказ
 * - ЗВЕЗДЫ + ЭКВ = синяя группа: Звёздные товары + Premium Pro (%) + Продвижение бренда + Эквайринг
 * - КЛИКИ = реальное количество кликов из Ozon Performance API, groupBy=SKU
 * - ЗАКАЗЫ = non_item_fee type_id=54 из accrual/by-day, распределяется по UNIT СУММА
 *
 * Источники:
 * - POST https://api-seller.ozon.ru/v1/finance/accrual/by-day
 * - POST https://api-performance.ozon.ru/api/client/statistics, groupBy=SKU
 */

const OZON_REPORT65_UNIT_API_SHEET_NAME = "UNIT API";
const OZON_REPORT65_SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI";
const OZON_REPORT65_PERF_BASE_URL = "https://api-performance.ozon.ru";
const OZON_REPORT65_PERF_CLIENT_ID = "92353868-1771409527407@advertising.performance.ozon.ru";
const OZON_REPORT65_PERF_CLIENT_SECRET = "qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw";
const OZON_REPORT65_FINANCE_PAGE_SIZE = 1000;
const OZON_REPORT65_PRODUCT_INFO_BATCH_SIZE = 1000;
const OZON_REPORT65_STORAGE_REPORT_MAX_WAIT_MS = 5 * 60 * 1000;
const OZON_REPORT65_STORAGE_REPORT_POLL_MS = 10000;
const OZON_REPORT65_STORAGE_TEMP_SHEET_NAME = "defolt";
const OZON_REPORT65_CAMPAIGN_BATCH_SIZE = 5;
const OZON_REPORT65_CAMPAIGNS_PER_TRIGGER = 5;
const OZON_REPORT65_PERF_REPORT_MAX_ATTEMPTS = 24;
const OZON_REPORT65_PERF_REPORT_POLL_MS = 5000;
const OZON_REPORT65_PERF_REPORT_MAX_RETRIES = 6;
const OZON_REPORT65_PERF_TRIGGER_GAP_MS = 5 * 60 * 1000;
const OZON_REPORT65_PERF_STATE_KEY = "OZON_REPORT65_PERF_STATE";
const OZON_REPORT65_PERF_TRIGGER_HANDLER = "resumeOzonReport65Performance";
const OZON_REPORT65_HEADER_SCAN_ROWS = 20;
const OZON_REPORT65_COMMON_EXTRA_COEFFICIENT_CELL = "U1";
const OZON_REPORT65_COMMON_EXTRA_COLUMN = 21;
const OZON_REPORT65_CLICKS_SOURCE = "performance";

// UNIT API имеет служебные/расчетные ячейки в строке заголовков (например U1),
// поэтому для Report65 пишем в закрепленные колонки, а не полагаемся на текст шапки.
// T1 должен оставаться визуальным заголовком зеленого поартикульного ДОП.
const OZON_REPORT65_FIXED_COLUMN_BY_HEADER = {
  "артикул": 1,
  "ску oz": 5,
  "unit сумма": 10,
  "упд": 11,
  "unit шт": 13,
  "вознаграждение": 14,
  "логистика": 15,
  "переплата": 16,
  "хранение": 19,
  "доп": 20,
  "озон доп возня": 21,
  "звезды + экв": 22,
  "клики": 24,
  "заказы": 25
};

const OZON_REPORT65_REQUIRED_HEADERS = [
  "Артикул",
  "СКУ OZ",
  "UNIT СУММА",
  "UNIT ШТ",
  "ВОЗНАГРАЖДЕНИЕ",
  "ЛОГИСТИКА",
  "ПЕРЕПЛАТА",
  "ХРАНЕНИЕ",
  "ДОП",
  "ЗВЕЗДЫ + ЭКВ",
  "КЛИКИ",
  "ЗАКАЗЫ"
];

const OZON_REPORT65_COMMON_COSTS_KEY = "__ozon_report65_common_costs__";

function updateOzonReport65() {
  const range = getOzonReport65DefaultDateRange_();
  updateOzonReport65ForDates(range.from, range.to);
}

function updateOzonReport65StorageOnly() {
  const range = getOzonReport65DefaultDateRange_();
  updateOzonReport65StorageOnlyForDates(range.from, range.to);
}

function updateOzonReport65StorageOnlyForDates(dateFrom, dateTo) {
  return withOzonReport65ScriptLock_("updateOzonReport65StorageOnlyForDates", function() {
    const sheet = getOzonReport65UnitApiSheet_();
    const lastRow = sheet.getLastRow();
    if (lastRow < 2) {
      Logger.log("Нет строк для обработки хранения");
      return;
    }

    const headerMap = getOzonReport65HeaderMap_(sheet);
    validateOzonReport65Headers_(headerMap);
    const storageCol = getOzonReport65Column_(headerMap, "ХРАНЕНИЕ");
    if (!storageCol) throw new Error("В UNIT API не найден заголовок: ХРАНЕНИЕ");
    if (lastRow <= headerMap.__headerRow) {
      Logger.log("Нет строк для обработки ниже строки заголовков " + headerMap.__headerRow);
      return;
    }

    const rowItems = readOzonReport65Rows_(sheet, lastRow, headerMap);
    const storageMap = fetchOzonReport65StorageMap_(dateFrom, dateTo);
    const values = rowItems.map(item => [roundOzonReport65Money_(getOzonReport65StorageValue_(storageMap, item))]);
    sheet.getRange(headerMap.__headerRow + 1, storageCol, values.length, 1).setValues(values);
    Logger.log("ХРАНЕНИЕ записано отдельным запуском: строк " + values.length + ", сумма " + roundOzonReport65Money_(values.reduce((sum, row) => sum + (Number(row[0]) || 0), 0)));
  });
}

function updateOzonReport65ForDates(dateFrom, dateTo) {
  return withOzonReport65ScriptLock_("updateOzonReport65ForDates", function() {
  const sheet = getOzonReport65UnitApiSheet_();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет строк для обработки");
    return;
  }

  const headerMap = getOzonReport65HeaderMap_(sheet);
  validateOzonReport65Headers_(headerMap);

  if (lastRow <= headerMap.__headerRow) {
    Logger.log("Нет строк для обработки ниже строки заголовков " + headerMap.__headerRow);
    return;
  }

  const rowItems = readOzonReport65Rows_(sheet, lastRow, headerMap);
  Logger.log("=== OZON UNIT API: начисления + реклама ===");
  Logger.log("Период: " + dateFrom + " -> " + dateTo);
  clearOzonReport65PerfTriggers_();
  deleteOzonReport65PerformanceState_();

  const accrualMap = fetchOzonReport65Accruals_(dateFrom, dateTo);
  const storageMap = fetchOzonReport65StorageMap_(dateFrom, dateTo);
  // ОТКЛЮЧЕНО: получение данных Performance API для КЛИКОВ и ЗАКАЗОВ.
  // const token = getOzonReport65PerfToken_();
  // let campaigns = [];
  // let cpoMap = null;
  //
  // if (token) {
  //   campaigns = getOzonReport65PerfCampaigns_(token);
  //   Logger.log("Performance CPO отключен: ЗАКАЗЫ берутся из accrual/by-day non_item_fee type_id=54");
  // } else {
  //   Logger.log("Performance API token не получен, рекламные колонки не будут обновлены");
  // }
  const cpoMap = null;

  writeOzonReport65FinanceColumns_(sheet, headerMap, rowItems, accrualMap, cpoMap, storageMap);

  // ОТКЛЮЧЕНО: staged-запуск Performance API для КЛИКОВ.
  // if (OZON_REPORT65_CLICKS_SOURCE === "finance") { ... }
  // const clickCampaigns = filterOzonReport65ClickCampaigns_(campaigns);
  // clearOzonReport65ClicksColumn_(sheet, headerMap, rowItems.length);
  // startOzonReport65PerformanceProcessing_(clickCampaigns, dateFrom, dateTo);
  });
}

function restartOzonReport65Clicks() {
  const range = getOzonReport65DefaultDateRange_();
  return restartOzonReport65ClicksForDates(range.from, range.to);
}

function restartOzonReport65ClicksForDates(dateFrom, dateTo) {
  return withOzonReport65ScriptLock_("restartOzonReport65ClicksForDates", function() {
    // ОТКЛЮЧЕНО: ручной перезапуск получения КЛИКОВ из Performance API.
    Logger.log("Получение КЛИКОВ отключено для листа UNIT API");
    return;

    const sheet = getOzonReport65UnitApiSheet_();
    const lastRow = sheet.getLastRow();
    if (lastRow < 2) {
      Logger.log("Нет строк для обновления рекламы");
      return;
    }

    const headerMap = getOzonReport65HeaderMap_(sheet);
    validateOzonReport65Headers_(headerMap);
    if (lastRow <= headerMap.__headerRow) {
      Logger.log("Нет строк для обработки ниже строки заголовков " + headerMap.__headerRow);
      return;
    }

    const rowItems = readOzonReport65Rows_(sheet, lastRow, headerMap);

    if (OZON_REPORT65_CLICKS_SOURCE === "finance") {
      clearOzonReport65PerfTriggers_();
      deleteOzonReport65PerformanceState_();
      const accrualMap = fetchOzonReport65Accruals_(dateFrom, dateTo);
      writeOzonReport65FinanceClicksColumn_(sheet, headerMap, rowItems, accrualMap);
      return;
    }

    clearOzonReport65PerfTriggers_();
    deleteOzonReport65PerformanceState_();

    const token = getOzonReport65PerfToken_();
    if (!token) {
      Logger.log("Performance API token не получен, КЛИКИ не будут обновлены");
      return;
    }

    const campaigns = getOzonReport65PerfCampaigns_(token);
    if (!campaigns.length) {
      Logger.log("Performance кампании не найдены, колонка КЛИКИ не очищена");
      return;
    }

    const clickCampaigns = filterOzonReport65ClickCampaigns_(campaigns);
    if (!clickCampaigns.length) {
      Logger.log("Performance кампании оплаты за клик не найдены, колонка КЛИКИ не очищена");
      return;
    }

    clearOzonReport65ClicksColumn_(sheet, headerMap, rowItems.length);
    startOzonReport65PerformanceProcessing_(clickCampaigns, dateFrom, dateTo);
  });
}

function setOzonReport65PerformanceCredentials(clientId, clientSecret) {
  if (!clientId || !clientSecret) throw new Error("Передайте clientId и clientSecret");
  PropertiesService.getScriptProperties().setProperties({
    OZON_PERFORMANCE_CLIENT_ID: clientId,
    OZON_PERFORMANCE_CLIENT_SECRET: clientSecret
  });
  Logger.log("Performance credentials сохранены в Script Properties");
}

function resumeOzonReport65Performance() {
  return withOzonReport65ScriptLock_("resumeOzonReport65Performance", function() {
  // ОТКЛЮЧЕНО: продолжение отложенной загрузки КЛИКОВ из Performance API.
  Logger.log("Отложенная загрузка КЛИКОВ отключена для листа UNIT API");
  return;

  clearOzonReport65PerfTriggers_();

  const state = getOzonReport65PerformanceState_();
  if (!state) {
    Logger.log("Нет сохраненного состояния Performance-обработки");
    return;
  }

  const sheet = getOzonReport65UnitApiSheet_();
  const lastRow = sheet.getLastRow();
  const headerMap = getOzonReport65HeaderMap_(sheet);
  validateOzonReport65Headers_(headerMap);

  if (lastRow <= headerMap.__headerRow) {
    clearOzonReport65PerformanceState();
    Logger.log("Нет строк для обработки ниже строки заголовков " + headerMap.__headerRow);
    return;
  }

  const token = getOzonReport65PerfToken_();
  if (!token) {
    Logger.log("Performance API token не получен, следующий триггер не создан");
    return;
  }

  const rowItems = readOzonReport65Rows_(sheet, lastRow, headerMap);
  const campaignIds = Array.isArray(state.campaignIds) ? state.campaignIds : [];
  processOzonReport65PerformanceBatch_(sheet, headerMap, rowItems, token, campaignIds, state.dateFrom, state.dateTo, Number(state.offset) || 0, Number(state.retryCount) || 0, state.pendingOverviewReportUuid || "");
  });
}

function clearOzonReport65PerformanceState() {
  clearOzonReport65PerfTriggers_();
  deleteOzonReport65PerformanceState_();
  Logger.log("Состояние Performance-обработки очищено");
}

function stopOzonReport65PerformanceTriggers() {
  return withOzonReport65ScriptLock_("stopOzonReport65PerformanceTriggers", function() {
    const beforeCount = countOzonReport65PerfTriggers_();
    clearOzonReport65PerfTriggers_();
    deleteOzonReport65PerformanceState_();
    const afterCount = countOzonReport65PerfTriggers_();
    Logger.log("Performance обработка остановлена. Удалено триггеров: " + beforeCount + ". Активно после остановки: " + afterCount);
  });
}

function checkOzonReport65PerformanceState() {
  const state = getOzonReport65PerformanceState_(false);
  const triggerCount = countOzonReport65PerfTriggers_();

  Logger.log("Performance triggers active: " + triggerCount);
  if (!state) {
    Logger.log("Performance state: empty");
    return;
  }

  const total = Number(state.total) || (Array.isArray(state.campaignIds) ? state.campaignIds.length : 0);
  Logger.log("Performance state offset: " + (Number(state.offset) || 0) + " / " + total);
  Logger.log("Performance state retry count: " + (Number(state.retryCount) || 0));
  Logger.log("Performance state period: " + state.dateFrom + " -> " + state.dateTo);
  Logger.log("Performance state campaign IDs: " + (Array.isArray(state.campaignIds) ? state.campaignIds.length : 0));
  if (Array.isArray(state.campaignIds)) {
    const offset = Number(state.offset) || 0;
    const batch = state.campaignIds.slice(offset, Math.min(offset + OZON_REPORT65_CAMPAIGNS_PER_TRIGGER, state.campaignIds.length));
    Logger.log("Performance state current batch IDs: " + batch.join(", "));
  }
  Logger.log("Performance state pending UUID: " + (state.pendingOverviewReportUuid || "нет"));
}

function withOzonReport65ScriptLock_(label, callback) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) {
    throw new Error("Не удалось получить lock для " + label + ". Другой запуск еще выполняется");
  }

  try {
    return callback();
  } finally {
    lock.releaseLock();
  }
}

function startOzonReport65PerformanceProcessing_(campaigns, dateFrom, dateTo) {
  const campaignIds = campaigns.map(campaign => String(campaign.id || campaign)).filter(Boolean);

  if (!campaignIds.length) {
    deleteOzonReport65PerformanceState_();
    Logger.log("Performance кампании не найдены");
    return;
  }

  saveOzonReport65PerformanceState_({
    offset: 0,
    total: campaignIds.length,
    campaignIds: campaignIds,
    dateFrom: dateFrom,
    dateTo: dateTo,
    retryCount: 0
  });
  scheduleOzonReport65PerformanceTrigger_();
  Logger.log("Performance обработка запущена: " + campaignIds.length + " кампаний, первый trigger создан");
}

function processOzonReport65PerformanceBatch_(sheet, headerMap, rowItems, token, campaignIds, dateFrom, dateTo, offset, retryCount, pendingOverviewReportUuid) {
  if (!campaignIds.length) {
    deleteOzonReport65PerformanceState_();
    Logger.log("Performance кампании не найдены");
    return;
  }

  if (offset >= campaignIds.length) {
    deleteOzonReport65PerformanceState_();
    Logger.log("Performance кампании обработаны полностью: " + campaignIds.length);
    return;
  }

  const nextOffset = Math.min(offset + OZON_REPORT65_CAMPAIGNS_PER_TRIGGER, campaignIds.length);
  const batch = campaignIds.slice(offset, nextOffset);
  Logger.log("Performance campaign batch: " + (offset + 1) + "-" + nextOffset + " / " + campaignIds.length);

  const overviewResult = fetchOzonReport65OverviewStats_(token, batch, dateFrom, dateTo, pendingOverviewReportUuid);
  if (overviewResult.stats === null) {
    const nextRetryCount = retryCount + 1;
    if (nextRetryCount >= OZON_REPORT65_PERF_REPORT_MAX_RETRIES) {
      Logger.log("Performance пачка пропущена после " + nextRetryCount + " попыток: offset " + offset + ", UUID " + (overviewResult.pendingOverviewReportUuid || pendingOverviewReportUuid || "нет"));
      if (nextOffset < campaignIds.length) {
        saveOzonReport65PerformanceState_({
          offset: nextOffset,
          total: campaignIds.length,
          campaignIds: campaignIds,
          dateFrom: dateFrom,
          dateTo: dateTo,
          retryCount: 0,
          pendingOverviewReportUuid: ""
        });
        scheduleOzonReport65PerformanceTrigger_();
        Logger.log("Следующий Performance trigger запланирован с offset " + nextOffset);
      } else {
        deleteOzonReport65PerformanceState_();
        Logger.log("Performance кампании обработаны полностью: " + campaignIds.length);
      }
      return;
    }

    saveOzonReport65PerformanceState_({
      offset: offset,
      total: campaignIds.length,
      campaignIds: campaignIds,
      dateFrom: dateFrom,
      dateTo: dateTo,
      retryCount: nextRetryCount,
      pendingOverviewReportUuid: overviewResult.pendingOverviewReportUuid || pendingOverviewReportUuid || ""
    });
    scheduleOzonReport65PerformanceTrigger_();
    Logger.log("Performance пачка не готова, offset " + offset + " будет повторен следующим триггером, попытка " + nextRetryCount);
    return;
  }

  writeOzonReport65AdClicksBatch_(sheet, headerMap, rowItems, overviewResult.stats);

  if (nextOffset < campaignIds.length) {
    saveOzonReport65PerformanceState_({
      offset: nextOffset,
      total: campaignIds.length,
      campaignIds: campaignIds,
      dateFrom: dateFrom,
      dateTo: dateTo,
      retryCount: 0
    });
    scheduleOzonReport65PerformanceTrigger_();
    Logger.log("Следующий Performance trigger запланирован с offset " + nextOffset);
  } else {
    deleteOzonReport65PerformanceState_();
    Logger.log("Performance кампании обработаны полностью: " + campaignIds.length);
  }
}

function scheduleOzonReport65PerformanceTrigger_() {
  clearOzonReport65PerfTriggers_();
  ScriptApp.newTrigger(OZON_REPORT65_PERF_TRIGGER_HANDLER)
    .timeBased()
    .after(OZON_REPORT65_PERF_TRIGGER_GAP_MS)
    .create();
  Logger.log("Performance triggers active after create: " + countOzonReport65PerfTriggers_());
}

function clearOzonReport65PerfTriggers_() {
  ScriptApp.getProjectTriggers().forEach(trigger => {
    if (trigger.getHandlerFunction() === OZON_REPORT65_PERF_TRIGGER_HANDLER) {
      ScriptApp.deleteTrigger(trigger);
    }
  });
}

function countOzonReport65PerfTriggers_() {
  return ScriptApp.getProjectTriggers().filter(trigger => trigger.getHandlerFunction() === OZON_REPORT65_PERF_TRIGGER_HANDLER).length;
}

function saveOzonReport65PerformanceState_(state) {
  PropertiesService.getScriptProperties().setProperty(OZON_REPORT65_PERF_STATE_KEY, JSON.stringify(state));
}

function getOzonReport65PerformanceState_(cleanupInvalid) {
  const raw = PropertiesService.getScriptProperties().getProperty(OZON_REPORT65_PERF_STATE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (e) {
    if (cleanupInvalid !== false) {
      deleteOzonReport65PerformanceState_();
      Logger.log("Некорректное состояние Performance-обработки очищено");
    } else {
      Logger.log("Performance state содержит некорректный JSON");
    }
    return null;
  }
}

function deleteOzonReport65PerformanceState_() {
  PropertiesService.getScriptProperties().deleteProperty(OZON_REPORT65_PERF_STATE_KEY);
}

function getOzonReport65UnitApiSheet_() {
  const spreadsheet = SpreadsheetApp.openById(OZON_REPORT65_SPREADSHEET_ID);
  const sheet = spreadsheet.getSheetByName(OZON_REPORT65_UNIT_API_SHEET_NAME);
  if (!sheet) throw new Error("Не найден лист " + OZON_REPORT65_UNIT_API_SHEET_NAME);
  return sheet;
}

function getOzonReport65HeaderMap_(sheet) {
  const maxRows = Math.min(OZON_REPORT65_HEADER_SCAN_ROWS, sheet.getLastRow());
  const rows = sheet.getRange(1, 1, maxRows, sheet.getLastColumn()).getDisplayValues();
  let bestRowIndex = 0;
  let bestScore = -1;

  rows.forEach((headers, rowIndex) => {
    const normalized = headers.map(normalizeOzonReport65Header_);
    const score = OZON_REPORT65_REQUIRED_HEADERS.filter(header => normalized.indexOf(normalizeOzonReport65Header_(header)) !== -1).length;
    if (score > bestScore) {
      bestScore = score;
      bestRowIndex = rowIndex;
    }
  });

  const headers = rows[bestRowIndex];
  const map = {};
  headers.forEach((header, index) => {
    const key = normalizeOzonReport65Header_(header);
    if (key && !map[key]) map[key] = index + 1;
  });
  map.__headerRow = bestRowIndex + 1;
  Logger.log("Строка заголовков UNIT API: " + map.__headerRow);
  return map;
}

function validateOzonReport65Headers_(headerMap) {
  const missing = OZON_REPORT65_REQUIRED_HEADERS.filter(header => !getOzonReport65Column_(headerMap, header));
  if (missing.length) throw new Error("В UNIT API не найдены заголовки/закрепленные колонки: " + missing.join(", "));
}

function getOzonReport65Column_(headerMap, header) {
  const key = normalizeOzonReport65Header_(header);
  if (OZON_REPORT65_FIXED_COLUMN_BY_HEADER[key]) return OZON_REPORT65_FIXED_COLUMN_BY_HEADER[key];
  if (key === normalizeOzonReport65Header_("ОЗОН ДОП ВОЗНЯ")) {
    return headerMap[key] || OZON_REPORT65_COMMON_EXTRA_COLUMN;
  }
  return headerMap[key] || 0;
}

function writeOzonReport65CommonExtraCoefficient_(sheet, commonExtraRate) {
  const coefficient = Math.round((1 + (Number(commonExtraRate) || 0)) * 10000) / 10000;
  sheet.getRange(OZON_REPORT65_COMMON_EXTRA_COEFFICIENT_CELL)
    .setValue(coefficient)
    .setNumberFormat("0.0000");
  Logger.log("Коэффициент ОЗОН ДОП ВОЗНЯ записан в " + OZON_REPORT65_COMMON_EXTRA_COEFFICIENT_CELL + ": " + coefficient.toFixed(4));
}

function readOzonReport65Rows_(sheet, lastRow, headerMap) {
  const articleCol = getOzonReport65Column_(headerMap, "Артикул");
  const skuCol = getOzonReport65Column_(headerMap, "СКУ OZ");
  const updCol = getOzonReport65Column_(headerMap, "УПД");
  const dataStartRow = headerMap.__headerRow + 1;
  const rowCount = lastRow - headerMap.__headerRow;
  const articles = sheet.getRange(dataStartRow, articleCol, rowCount, 1).getValues().flat();
  const skus = sheet.getRange(dataStartRow, skuCol, rowCount, 1).getValues().flat();
  const updValues = updCol ? sheet.getRange(dataStartRow, updCol, rowCount, 1).getValues().flat() : [];
  return articles.map((article, index) => ({
    article: normalizeOzonReport65Key_(article),
    sku: normalizeOzonReport65Key_(skus[index]),
    upd: parseOzonReport65Money_(updValues[index])
  }));
}

function fetchOzonReport65Accruals_(dateFrom, dateTo) {
  const result = {};
  const unknownTypes = {};
  let loaded = 0;
  let days = 0;
  let lastRequestTime = Date.now() - 1000 / RPS();
  let current = parseOzonReport65Date_(dateFrom);
  const end = parseOzonReport65Date_(dateTo);

  while (current.getTime() <= end.getTime()) {
    const day = formatOzonReport65Date_(current);
    let lastId = "";
    let dayLoaded = 0;
    let rateLimitRetries = 0;
    const seenLastIds = {};
    Logger.log("Finance accrual/by-day: " + day);

    while (true) {
      lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

      const response = retryFetch(ozonReport65FinanceAccrualByDayURL_(), {
        method: "post",
        contentType: "application/json",
        headers: ozonHeaders(),
        payload: JSON.stringify({ date: day, last_id: lastId }),
        muteHttpExceptions: true
      }, 3);

      if (!response) throw new Error("Finance accrual/by-day не вернул ответ");

      const code = response.getResponseCode();
      const text = response.getContentText();
      if (code === 429 && rateLimitRetries < 6) {
        rateLimitRetries++;
        Logger.log("Finance accrual/by-day HTTP 429, пауза перед повтором " + day + " (" + rateLimitRetries + "/6)");
        Utilities.sleep(10000);
        continue;
      }

      if (code !== 200) {
        Logger.log("Finance accrual/by-day HTTP " + code + ": " + text.slice(0, 1000));
        throw new Error("Finance accrual/by-day HTTP " + code + ": " + text.slice(0, 500));
      }

      rateLimitRetries = 0;
      const json = JSON.parse(text);
      const accruals = Array.isArray(json.accruals) ? json.accruals : [];

      accruals.forEach(accrual => {
        aggregateOzonReport65ByDayAccrual_(result, unknownTypes, accrual);
      });

      loaded += accruals.length;
      dayLoaded += accruals.length;

      const nextLastId = normalizeOzonReport65Key_(json.last_id || "");
      if (!nextLastId || nextLastId === lastId || seenLastIds[nextLastId]) break;
      seenLastIds[nextLastId] = true;
      lastId = nextLastId;
    }

    days++;
    Logger.log("Finance accrual/by-day loaded for " + day + ": " + dayLoaded);
    current.setUTCDate(current.getUTCDate() + 1);
  }

  Logger.log("Finance accrual/by-day days loaded: " + days);
  Logger.log("Finance accrual/by-day accruals loaded: " + loaded);
  enrichOzonReport65AccrualsWithOfferIds_(result);
  Logger.log("Finance accrual keys: " + Object.keys(result).length);
  logOzonReport65UnknownTypes_(unknownTypes);
  return result;
}

function ozonReport65FinanceAccrualByDayURL_() {
  return "https://api-seller.ozon.ru/v1/finance/accrual/by-day";
}

function aggregateOzonReport65ByDayAccrual_(result, unknownTypes, accrual) {
  const posting = accrual && accrual.posting ? accrual.posting : {};
  const products = Array.isArray(posting.products) ? posting.products : [];

  products.forEach(product => {
    const sku = normalizeOzonReport65Key_(product && product.sku);
    if (!sku) return;

    const commission = product.commission || {};
    const saleAmount = parseOzonReport65Money_(commission.sale_amount);
    const sellerPrice = parseOzonReport65Money_(commission.seller_price);
    addOzonReport65SkuAmount_(result, unknownTypes, sku, "commission.sale_amount", "unitSum", saleAmount);
    addOzonReport65SkuAmount_(result, unknownTypes, sku, "commission.unit_qty", "unitQty", calculateOzonReport65UnitQty_(saleAmount, sellerPrice, product));
    addOzonReport65SkuAmount_(result, unknownTypes, sku, "commission.commission", "reward", parseOzonReport65Money_(commission.commission));

    const delivery = product.delivery || {};
    const services = Array.isArray(delivery.services) ? delivery.services : [];
    services.forEach(service => {
      const typeId = normalizeOzonReport65Key_(service && service.type_id);
      const amount = parseOzonReport65Money_(service && service.accrued);
      if (typeId === "32" && amount > 0) {
        addOzonReport65SkuAmount_(result, unknownTypes, sku, "delivery:32:extra_reversal", "extra", amount);
        return;
      }

      const group = getOzonReport65DeliveryFeeGroup_(typeId, amount);
      addOzonReport65SkuAmount_(result, unknownTypes, sku, "delivery:" + typeId, group, amount);
    });
  });

  const itemFees = accrual && accrual.item_fees && Array.isArray(accrual.item_fees.fees)
    ? accrual.item_fees.fees
    : [];
  itemFees.forEach(itemFee => {
    const sku = normalizeOzonReport65Key_(itemFee && itemFee.sku);
    if (!sku) return;

    const fees = Array.isArray(itemFee.fees) ? itemFee.fees : [];
    fees.forEach(fee => {
      const typeId = normalizeOzonReport65Key_(fee && fee.type_id);
      const amount = parseOzonReport65Money_(fee && fee.accrued);
      const group = getOzonReport65ItemFeeGroup_(typeId);
      addOzonReport65SkuAmount_(result, unknownTypes, sku, "item_fee:" + typeId, group, amount);
    });
  });

  aggregateOzonReport65ByDayNonItemFee_(result, unknownTypes, accrual && accrual.non_item_fee);
}

function addOzonReport65SkuAmount_(result, unknownTypes, sku, typeName, group, amount) {
  if (!amount) return;
  if (!group) {
    unknownTypes[typeName] = (unknownTypes[typeName] || 0) + amount;
    return;
  }

  if (!result[sku]) result[sku] = createOzonReport65AccrualBucket_();
  result[sku][group] += amount;
}

function calculateOzonReport65UnitQty_(saleAmount, sellerPrice, product) {
  if (!shouldCountOzonReport65UnitQty_(saleAmount, sellerPrice, product)) return 0;

  const quantity = Math.abs(saleAmount / sellerPrice);
  if (!isFinite(quantity) || quantity <= 0) return 0;

  return Math.round(quantity);
}

function shouldCountOzonReport65UnitQty_(saleAmount, sellerPrice, product) {
  if (saleAmount > 0 && sellerPrice > 0) return true;
  if (!(saleAmount < 0) || !(sellerPrice < 0)) return false;

  const services = product && product.delivery && Array.isArray(product.delivery.services)
    ? product.delivery.services
    : [];
  return services.some(service => parseOzonReport65Money_(service && service.accrued) > 0);
}

function getOzonReport65ItemFeeGroup_(typeId) {
  if (["1", "3", "51", "74"].indexOf(typeId) !== -1) return "starsAndAcquiring";
  if (typeId) return "extra";
  return "";
}

function getOzonReport65DeliveryFeeGroup_(typeId) {
  if (typeId === "32") return "logistics";
  if (typeId) return "extra";
  return "";
}

function aggregateOzonReport65ByDayNonItemFee_(result, unknownTypes, nonItemFee) {
  if (!nonItemFee || nonItemFee.type_id === null || nonItemFee.type_id === undefined) return;

  const typeId = normalizeOzonReport65Key_(nonItemFee.type_id);
  const amount = parseOzonReport65Money_(nonItemFee.accrued);
  if (!amount) return;

  if (!result[OZON_REPORT65_COMMON_COSTS_KEY]) result[OZON_REPORT65_COMMON_COSTS_KEY] = createOzonReport65AccrualBucket_();
  const common = result[OZON_REPORT65_COMMON_COSTS_KEY];

  if (typeId === "41") {
    common.clicksPayment += amount;
  } else if (typeId === "54") {
    common.cpoPayment += amount;
  } else {
    common.commonExtra += amount;
  }

}

function enrichOzonReport65AccrualsWithOfferIds_(result) {
  const skuKeys = Object.keys(result).filter(key => key !== OZON_REPORT65_COMMON_COSTS_KEY && /^\d+$/.test(key));
  if (!skuKeys.length) return;

  const skuToOffer = {};
  let lastRequestTime = Date.now() - 1000 / RPS();

  for (let offset = 0; offset < skuKeys.length; offset += OZON_REPORT65_PRODUCT_INFO_BATCH_SIZE) {
    const batch = skuKeys.slice(offset, offset + OZON_REPORT65_PRODUCT_INFO_BATCH_SIZE);
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

    const response = retryFetch(ozonReport65ProductInfoListURL_(), {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify({ sku: batch }),
      muteHttpExceptions: true
    }, 3);

    if (!response) {
      Logger.log("Product info/list не вернул ответ для пачки SKU");
      continue;
    }

    const code = response.getResponseCode();
    const text = response.getContentText();
    if (code !== 200) {
      Logger.log("Product info/list HTTP " + code + ": " + text.slice(0, 500));
      continue;
    }

    const json = JSON.parse(text);
    const items = Array.isArray(json.items) ? json.items : (json.result && Array.isArray(json.result.items) ? json.result.items : []);
    items.forEach(item => addOzonReport65ProductInfoSkuAliases_(skuToOffer, item));
  }

  let merged = 0;
  Object.keys(skuToOffer).forEach(sku => {
    const offerId = skuToOffer[sku];
    if (!offerId || !result[sku]) return;
    if (!result[offerId]) result[offerId] = createOzonReport65AccrualBucket_();
    mergeOzonReport65AccrualBucket_(result[offerId], result[sku]);
    merged++;
  });

  Logger.log("Product info SKU -> offer_id сопоставлено: " + merged + " / " + skuKeys.length);
}

function ozonReport65ProductInfoListURL_() {
  return "https://api-seller.ozon.ru/v3/product/info/list";
}

function fetchOzonReport65StorageMap_(dateFrom, dateTo) {
  Logger.log("=== OZON UNIT API: хранение / стоимость размещения ===");
  Logger.log("Период хранения: " + dateFrom + " -> " + dateTo);

  const reportCode = createOzonReport65PlacementByProductsReport_(dateFrom, dateTo);
  if (!reportCode) return createOzonReport65StorageMap_();

  const fileUrl = waitOzonReport65FileUrl_(reportCode);
  if (!fileUrl) return createOzonReport65StorageMap_();

  const storageResult = downloadAndBuildOzonReport65StorageMap_(fileUrl);
  const storageMap = storageResult.storageMap || createOzonReport65StorageMap_();
  if (!storageResult.rowCount && !Object.keys(storageMap.bySku).length && !Object.keys(storageMap.byOfferId).length) {
    Logger.log("Отчёт хранения скачан, но строки не распознаны");
    return storageMap;
  }

  Logger.log("Хранение: строк отчёта " + storageResult.rowCount);
  Logger.log("Хранение: SKU " + Object.keys(storageMap.bySku).length + ", артикулов " + Object.keys(storageMap.byOfferId).length);
  Logger.log("Хранение: сумма отчёта " + roundOzonReport65Money_(sumOzonReport65StorageMap_(storageMap)));
  return storageMap;
}

function createOzonReport65StorageMap_() {
  return { bySku: {}, byOfferId: {} };
}

function createOzonReport65PlacementByProductsReport_(dateFrom, dateTo) {
  const response = retryFetch(ozonReport65PlacementByProductsReportURL_(), {
    method: "post",
    contentType: "application/json",
    headers: ozonHeaders(),
    payload: JSON.stringify({ date_from: dateFrom, date_to: dateTo }),
    muteHttpExceptions: true
  }, 3);

  if (!response) {
    Logger.log("Не удалось создать отчёт стоимости размещения");
    return "";
  }

  const code = response.getResponseCode();
  const text = response.getContentText();
  if (code !== 200) {
    Logger.log("Создание отчёта хранения HTTP " + code + ": " + text.slice(0, 1000));
    return "";
  }

  const json = JSON.parse(text);
  const reportCode = json.code || (json.result && json.result.code) || "";
  if (!reportCode) {
    Logger.log("Ozon не вернул code отчёта хранения: " + text.slice(0, 1000));
    return "";
  }

  Logger.log("Отчёт хранения создан, code: " + reportCode);
  return reportCode;
}

function waitOzonReport65FileUrl_(reportCode) {
  const startedAt = Date.now();
  let attempt = 1;

  while (Date.now() - startedAt < OZON_REPORT65_STORAGE_REPORT_MAX_WAIT_MS) {
    const info = getOzonReport65ReportInfo_(reportCode);
    if (!info) return "";

    const status = normalizeOzonReport65Text_(info.status || info.state || "");
    const fileUrl = info.file || info.file_url || info.download_url || info.url || "";
    Logger.log("Отчёт хранения " + reportCode + ": попытка " + attempt + ", статус " + (status || "без статуса"));

    if (fileUrl) return fileUrl;
    if (status === "error" || status === "failed") {
      Logger.log("Ozon вернул ошибку формирования отчёта хранения: " + JSON.stringify(info).slice(0, 1000));
      return "";
    }

    Utilities.sleep(OZON_REPORT65_STORAGE_REPORT_POLL_MS);
    attempt++;
  }

  Logger.log("Истекло время ожидания отчёта хранения");
  return "";
}

function getOzonReport65ReportInfo_(reportCode) {
  const response = retryFetch(ozonReport65ReportInfoURL_(), {
    method: "post",
    contentType: "application/json",
    headers: ozonHeaders(),
    payload: JSON.stringify({ code: reportCode }),
    muteHttpExceptions: true
  }, 3);

  if (!response) return null;

  const code = response.getResponseCode();
  const text = response.getContentText();
  if (code !== 200) {
    Logger.log("report/info HTTP " + code + ": " + text.slice(0, 1000));
    return null;
  }

  const json = JSON.parse(text);
  return json.result || json;
}

function downloadAndBuildOzonReport65StorageMap_(fileUrl) {
  const response = UrlFetchApp.fetch(fileUrl, { muteHttpExceptions: true });
  const code = response.getResponseCode();
  if (code !== 200) {
    Logger.log("Скачивание отчёта хранения HTTP " + code + ": " + response.getContentText().slice(0, 1000));
    return { storageMap: createOzonReport65StorageMap_(), rowCount: 0 };
  }

  const blob = response.getBlob();
  const bytes = blob.getBytes();
  if (bytes.length > 1 && bytes[0] === 0x50 && bytes[1] === 0x4B) {
    Logger.log("Формат отчёта хранения: XLSX");
    try {
      const rows = parseOzonReport65XlsxRows_(blob);
      return {
        storageMap: buildOzonReport65StorageMapFromRows_(rows),
        rowCount: rows.length
      };
    } catch (error) {
      Logger.log("XLSX слишком большой для ZIP-парсера Apps Script, пробую конвертацию через Google Sheets: " + error);
      return buildOzonReport65StorageMapViaGoogleSheets_(blob);
    }
  }

  Logger.log("Формат отчёта хранения: CSV/TSV");
  const rows = parseOzonReport65DelimitedRows_(response.getContentText("UTF-8"));
  return {
    storageMap: buildOzonReport65StorageMapFromRows_(rows),
    rowCount: rows.length
  };
}

function buildOzonReport65StorageMapFromRows_(rows) {
  const storageMap = createOzonReport65StorageMap_();
  if (!rows.length) return storageMap;

  const headerIndex = findOzonReport65StorageHeaderRowIndex_(rows);
  if (headerIndex < 0) {
    Logger.log("Не нашёл строку заголовков в отчёте хранения: " + JSON.stringify(rows.slice(0, 5)).slice(0, 1000));
    return storageMap;
  }

  const headers = rows[headerIndex].map(normalizeOzonReport65Header_);
  const skuIndex = findOzonReport65HeaderIndex_(headers, ["sku"]);
  const offerIndex = findOzonReport65HeaderIndex_(headers, ["артикул", "offer"]);
  const amountIndex = findOzonReport65PreferredHeaderIndex_(headers,
    ["стоимость размещения", "начисленная стоимость размещения", "размещ", "хран", "storage", "placement"],
    ["начислено", "сумма", "итого"]
  );

  Logger.log("Колонки хранения: sku=" + skuIndex + ", артикул=" + offerIndex + ", сумма=" + amountIndex);
  if (amountIndex < 0 || (skuIndex < 0 && offerIndex < 0)) return storageMap;

  for (let i = headerIndex + 1; i < rows.length; i++) {
    const row = rows[i] || [];
    const sku = skuIndex >= 0 ? normalizeOzonReport65Key_(row[skuIndex]) : "";
    const offerId = offerIndex >= 0 ? normalizeOzonReport65Key_(row[offerIndex]) : "";
    const amount = Math.abs(parseOzonReport65Money_(row[amountIndex]));
    if (!amount) continue;

    if (sku) storageMap.bySku[sku] = (storageMap.bySku[sku] || 0) + amount;
    if (offerId) storageMap.byOfferId[offerId] = (storageMap.byOfferId[offerId] || 0) + amount;
  }

  return storageMap;
}

function buildOzonReport65StorageMapViaGoogleSheets_(blob) {
  const tempName = OZON_REPORT65_STORAGE_TEMP_SHEET_NAME + "_" + Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyyMMdd_HHmmss");
  const xlsxBlob = blob.copyBlob()
    .setName(tempName + ".xlsx")
    .setContentType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  let tempFileId = "";

  try {
    tempFileId = uploadOzonReport65XlsxAsGoogleSheet_(xlsxBlob, tempName);
    Logger.log("Временная Google-таблица отчёта хранения: " + tempFileId);

    const tempSpreadsheet = SpreadsheetApp.openById(tempFileId);
    const sheet = tempSpreadsheet.getSheets()[0];
    const lastRow = sheet.getLastRow();
    const lastCol = sheet.getLastColumn();
    if (!lastRow || !lastCol) return { storageMap: createOzonReport65StorageMap_(), rowCount: 0 };

    const probeRows = sheet.getRange(1, 1, Math.min(lastRow, 50), lastCol).getDisplayValues();
    const headerIndex = findOzonReport65StorageHeaderRowIndex_(probeRows);
    if (headerIndex < 0) {
      Logger.log("Не нашёл строку заголовков в сконвертированном отчёте хранения");
      return { storageMap: createOzonReport65StorageMap_(), rowCount: lastRow };
    }

    const headers = probeRows[headerIndex].map(normalizeOzonReport65Header_);
    const skuIndex = findOzonReport65HeaderIndex_(headers, ["sku"]);
    const offerIndex = findOzonReport65HeaderIndex_(headers, ["артикул", "offer"]);
    const amountIndex = findOzonReport65PreferredHeaderIndex_(headers,
      ["стоимость размещения", "начисленная стоимость размещения", "размещ", "хран", "storage", "placement"],
      ["начислено", "сумма", "итого"]
    );

    Logger.log("Колонки хранения (Google Sheets): sku=" + skuIndex + ", артикул=" + offerIndex + ", сумма=" + amountIndex);
    if (amountIndex < 0 || (skuIndex < 0 && offerIndex < 0)) {
      return { storageMap: createOzonReport65StorageMap_(), rowCount: lastRow };
    }

    const storageMap = createOzonReport65StorageMap_();
    const chunkSize = 10000;
    let processedRows = 0;

    for (let startRow = headerIndex + 2; startRow <= lastRow; startRow += chunkSize) {
      const numRows = Math.min(chunkSize, lastRow - startRow + 1);
      const values = sheet.getRange(startRow, 1, numRows, lastCol).getDisplayValues();
      addOzonReport65StorageRowsToMap_(storageMap, values, skuIndex, offerIndex, amountIndex);
      processedRows += values.length;
      if (processedRows % 50000 === 0) Logger.log("Хранение обработано строк: " + processedRows + " / " + (lastRow - headerIndex - 1));
    }

    return { storageMap, rowCount: lastRow };
  } catch (error) {
    Logger.log("Не удалось обработать отчёт хранения через Google Sheets: " + error);
    return { storageMap: createOzonReport65StorageMap_(), rowCount: 0 };
  } finally {
    if (tempFileId) {
      try {
        DriveApp.getFileById(tempFileId).setTrashed(true);
        Logger.log("Временная Google-таблица отчёта хранения удалена в корзину");
      } catch (cleanupError) {
        Logger.log("Не удалось удалить временную Google-таблицу отчёта хранения: " + cleanupError);
      }
    }
  }
}

function addOzonReport65StorageRowsToMap_(storageMap, rows, skuIndex, offerIndex, amountIndex) {
  rows.forEach(row => {
    const sku = skuIndex >= 0 ? normalizeOzonReport65Key_(row[skuIndex]) : "";
    const offerId = offerIndex >= 0 ? normalizeOzonReport65Key_(row[offerIndex]) : "";
    const amount = Math.abs(parseOzonReport65Money_(row[amountIndex]));
    if (!amount) return;

    if (sku) storageMap.bySku[sku] = (storageMap.bySku[sku] || 0) + amount;
    if (offerId) storageMap.byOfferId[offerId] = (storageMap.byOfferId[offerId] || 0) + amount;
  });
}

function uploadOzonReport65XlsxAsGoogleSheet_(blob, name) {
  const boundary = "ozon_report65_storage_" + Date.now();
  const delimiter = "\r\n--" + boundary + "\r\n";
  const closeDelimiter = "\r\n--" + boundary + "--";
  const metadata = {
    name,
    mimeType: MimeType.GOOGLE_SHEETS
  };
  const payloadBytes = []
    .concat(Utilities.newBlob(delimiter + "Content-Type: application/json; charset=UTF-8\r\n\r\n" + JSON.stringify(metadata)).getBytes())
    .concat(Utilities.newBlob(delimiter + "Content-Type: " + blob.getContentType() + "\r\n\r\n").getBytes())
    .concat(blob.getBytes())
    .concat(Utilities.newBlob(closeDelimiter).getBytes());

  const response = UrlFetchApp.fetch("https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id", {
    method: "post",
    contentType: "multipart/related; boundary=" + boundary,
    headers: {
      Authorization: "Bearer " + ScriptApp.getOAuthToken()
    },
    payload: payloadBytes,
    muteHttpExceptions: true
  });
  const code = response.getResponseCode();
  const text = response.getContentText();

  if (code < 200 || code >= 300) {
    throw new Error("Drive upload HTTP " + code + ": " + text.slice(0, 1000));
  }

  const json = JSON.parse(text);
  if (!json.id) throw new Error("Drive upload не вернул id: " + text.slice(0, 1000));
  return json.id;
}

function getOzonReport65StorageValue_(storageMap, item) {
  if (!storageMap) return 0;
  if (item.sku && Object.prototype.hasOwnProperty.call(storageMap.bySku || {}, item.sku)) return storageMap.bySku[item.sku];
  if (item.article && Object.prototype.hasOwnProperty.call(storageMap.byOfferId || {}, item.article)) return storageMap.byOfferId[item.article];
  return 0;
}

function sumOzonReport65StorageMap_(storageMap) {
  return Object.values(storageMap.bySku || {}).reduce((sum, value) => sum + (Number(value) || 0), 0);
}

function findOzonReport65StorageHeaderRowIndex_(rows) {
  for (let i = 0; i < Math.min(rows.length, 50); i++) {
    const joined = (rows[i] || []).map(normalizeOzonReport65Header_).join(" | ");
    if ((joined.indexOf("sku") !== -1 || joined.indexOf("артикул") !== -1 || joined.indexOf("offer") !== -1) &&
        (joined.indexOf("хран") !== -1 || joined.indexOf("размещ") !== -1 || joined.indexOf("storage") !== -1 || joined.indexOf("placement") !== -1)) {
      return i;
    }
  }
  return -1;
}

function findOzonReport65PreferredHeaderIndex_(headers, preferredMarkers, fallbackMarkers) {
  const preferred = findOzonReport65HeaderIndex_(headers, preferredMarkers);
  if (preferred >= 0) return preferred;
  return findOzonReport65HeaderIndex_(headers, fallbackMarkers);
}

function parseOzonReport65DelimitedRows_(text) {
  const cleaned = String(text || "").replace(/^\uFEFF/, "");
  const firstLine = cleaned.split(/\r?\n/)[0] || "";
  const delimiter = firstLine.indexOf(";") !== -1 ? ";" : firstLine.indexOf("\t") !== -1 ? "\t" : ",";
  return Utilities.parseCsv(cleaned, delimiter)
    .filter(row => row.some(cell => String(cell || "").trim() !== ""));
}

function parseOzonReport65XlsxRows_(blob) {
  const files = Utilities.unzip(blob);
  const fileMap = {};
  files.forEach(file => {
    fileMap[file.getName()] = file.getDataAsString("UTF-8");
  });

  const sharedStrings = parseOzonReport65XlsxSharedStrings_(fileMap["xl/sharedStrings.xml"]);
  const sheetName = Object.keys(fileMap)
    .filter(name => /^xl\/worksheets\/sheet\d+\.xml$/.test(name))
    .sort()[0];
  if (!sheetName) return [];

  const document = XmlService.parse(fileMap[sheetName]);
  const root = document.getRootElement();
  const namespace = root.getNamespace();
  const sheetData = root.getChild("sheetData", namespace);
  if (!sheetData) return [];

  return sheetData.getChildren("row", namespace)
    .map(rowNode => {
      const row = [];
      rowNode.getChildren("c", namespace).forEach(cell => {
        const ref = cell.getAttribute("r") ? cell.getAttribute("r").getValue() : "";
        const columnIndex = xlsxOzonReport65ColumnRefToIndex_(ref.replace(/[0-9]/g, ""));
        row[columnIndex] = readOzonReport65XlsxCellValue_(cell, namespace, sharedStrings);
      });
      return row.map(value => value === undefined ? "" : value);
    })
    .filter(row => row.some(cell => String(cell || "").trim() !== ""));
}

function parseOzonReport65XlsxSharedStrings_(xml) {
  if (!xml) return [];
  const document = XmlService.parse(xml);
  const root = document.getRootElement();
  const namespace = root.getNamespace();
  return root.getChildren("si", namespace).map(item => collectOzonReport65XlsxTexts_(item, namespace).join(""));
}

function collectOzonReport65XlsxTexts_(node, namespace) {
  let parts = [];
  const text = node.getChildText("t", namespace);
  if (text !== null) parts.push(text);
  node.getChildren().forEach(child => {
    parts = parts.concat(collectOzonReport65XlsxTexts_(child, namespace));
  });
  return parts;
}

function readOzonReport65XlsxCellValue_(cell, namespace, sharedStrings) {
  const type = cell.getAttribute("t") ? cell.getAttribute("t").getValue() : "";
  const valueNode = cell.getChild("v", namespace);

  if (type === "inlineStr") {
    const inline = cell.getChild("is", namespace);
    return inline ? collectOzonReport65XlsxTexts_(inline, namespace).join("") : "";
  }

  const raw = valueNode ? valueNode.getText() : "";
  if (type === "s") return sharedStrings[Number(raw)] || "";
  return raw;
}

function xlsxOzonReport65ColumnRefToIndex_(ref) {
  const letters = String(ref || "").replace(/[0-9]/g, "");
  let index = 0;
  for (let i = 0; i < letters.length; i++) {
    index = index * 26 + letters.charCodeAt(i) - 64;
  }
  return Math.max(index - 1, 0);
}

function ozonReport65PlacementByProductsReportURL_() {
  return "https://api-seller.ozon.ru/v1/report/placement/by-products/create";
}

function ozonReport65ReportInfoURL_() {
  return "https://api-seller.ozon.ru/v1/report/info";
}

function addOzonReport65ProductInfoSkuAliases_(skuToOffer, item) {
  if (!item) return;
  const offerId = normalizeOzonReport65Key_(item.offer_id);
  if (!offerId) return;

  addOzonReport65SkuOfferAlias_(skuToOffer, item.sku, offerId);
  addOzonReport65SkuOfferAlias_(skuToOffer, item.fbo_sku, offerId);
  addOzonReport65SkuOfferAlias_(skuToOffer, item.fbs_sku, offerId);

  const sources = Array.isArray(item.sources) ? item.sources : [];
  sources.forEach(source => {
    addOzonReport65SkuOfferAlias_(skuToOffer, source && source.sku, offerId);
    addOzonReport65SkuOfferAlias_(skuToOffer, source && source.fbo_sku, offerId);
    addOzonReport65SkuOfferAlias_(skuToOffer, source && source.fbs_sku, offerId);
  });
}

function addOzonReport65SkuOfferAlias_(skuToOffer, sku, offerId) {
  const key = normalizeOzonReport65Key_(sku);
  if (key) skuToOffer[key] = offerId;
}

function mergeOzonReport65AccrualBucket_(target, source) {
  ["unitSum", "unitQty", "reward", "logistics", "extra", "starsAndAcquiring", "commonExtra", "cpoPayment", "clicksPayment"].forEach(field => {
    target[field] += Number(source[field]) || 0;
  });
}

function splitOzonReport65FinanceDateRange_(dateFrom, dateTo) {
  const chunks = [];
  let current = parseOzonReport65Date_(dateFrom);
  const end = parseOzonReport65Date_(dateTo);

  while (current.getTime() <= end.getTime()) {
    const chunkEnd = new Date(current.getTime());
    chunkEnd.setUTCDate(chunkEnd.getUTCDate() + 29);
    if (chunkEnd.getTime() > end.getTime()) chunkEnd.setTime(end.getTime());

    chunks.push({
      from: formatOzonReport65Date_(current),
      to: formatOzonReport65Date_(chunkEnd)
    });

    current = new Date(chunkEnd.getTime());
    current.setUTCDate(current.getUTCDate() + 1);
  }

  return chunks;
}

function parseOzonReport65Date_(value) {
  const parts = String(value).split("-").map(Number);
  return new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
}

function formatOzonReport65Date_(date) {
  return Utilities.formatDate(date, "UTC", "yyyy-MM-dd");
}

function aggregateOzonReport65Operation_(result, unknownTypes, operation) {
  const itemAliases = extractOzonReport65OperationAliases_(operation);
  if (!itemAliases.length) {
    aggregateOzonReport65CommonCost_(result, operation);
    return;
  }

  const operationName = normalizeOzonReport65Text_(operation.operation_type_name || operation.operation_type || operation.type || "");
  const accrualsForSale = parseOzonReport65Money_(operation.accruals_for_sale || 0);
  const saleCommission = parseOzonReport65Money_(operation.sale_commission || 0);

  addOzonReport65Amount_(result, unknownTypes, itemAliases, operationName || "выручка", "unitSum", accrualsForSale);
  addOzonReport65Amount_(result, unknownTypes, itemAliases, "вознаграждение за продажу", "reward", saleCommission);

  const services = Array.isArray(operation.services) ? operation.services : [];

  if (services.length) {
    services.forEach(service => {
      const serviceName = normalizeOzonReport65Text_(service.name || service.service_name || service.type || "");
      const group = classifyOzonReport65Charge_(serviceName);
      const amount = parseOzonReport65Money_(service.price || service.amount || service.total || 0);
      addOzonReport65Amount_(result, unknownTypes, itemAliases, serviceName, group, amount);
    });
    return;
  }

  const group = classifyOzonReport65Charge_(operationName);
  const amount = parseOzonReport65Money_(operation.amount || operation.price || 0);
  if ((group === "unitSum" && !accrualsForSale) ||
      (group === "reward" && !saleCommission) ||
      (group && group !== "unitSum" && group !== "reward")) {
    addOzonReport65Amount_(result, unknownTypes, itemAliases, operationName, group, amount);
  }
}

function extractOzonReport65OperationAliases_(operation) {
  const aliases = [];
  const items = Array.isArray(operation.items) ? operation.items : [];

  items.forEach(item => {
    const keys = [];
    [item.offer_id, item.sku].forEach(value => {
      const key = normalizeOzonReport65Key_(value);
      if (key && keys.indexOf(key) === -1) keys.push(key);
    });
    if (keys.length) aliases.push(keys);
  });

  if (!aliases.length && operation.posting && operation.posting.offer_id) {
    const key = normalizeOzonReport65Key_(operation.posting.offer_id);
    if (key) aliases.push([key]);
  }

  return aliases;
}

function addOzonReport65Amount_(result, unknownTypes, itemAliases, typeName, group, amount) {
  if (!amount || !group) {
    if (typeName && !group) unknownTypes[typeName] = (unknownTypes[typeName] || 0) + amount;
    return;
  }

  const perItemAmount = amount / itemAliases.length;
  itemAliases.forEach(keys => {
    keys.forEach(key => {
      if (!result[key]) result[key] = createOzonReport65AccrualBucket_();
      result[key][group] += perItemAmount;
    });
  });
}

function aggregateOzonReport65CommonCost_(result, operation) {
  const operationName = normalizeOzonReport65Text_(operation.operation_type_name || operation.operation_type || operation.type || "");
  if (isOzonReport65CommonAdvertisingCost_(operationName)) return;

  const amount = parseOzonReport65Money_(operation.amount || operation.price || 0);
  if (!amount) return;

  if (!result[OZON_REPORT65_COMMON_COSTS_KEY]) result[OZON_REPORT65_COMMON_COSTS_KEY] = createOzonReport65AccrualBucket_();
  result[OZON_REPORT65_COMMON_COSTS_KEY].commonExtra += amount;
}

function isOzonReport65CommonAdvertisingCost_(operationName) {
  return containsAnyOzonReport65_(operationName, [
    "оплата за клик",
    "продвижение с оплатой за заказ"
  ]);
}

function createOzonReport65AccrualBucket_() {
  return { unitSum: 0, unitQty: 0, reward: 0, logistics: 0, extra: 0, starsAndAcquiring: 0, commonExtra: 0, cpoPayment: 0, clicksPayment: 0 };
}

function classifyOzonReport65Charge_(text) {
  if (!text) return "";

  if (containsAnyOzonReport65_(text, [
    "программы партнёров",
    "программы партнеров",
    "баллы за скидки",
    "cashbackindividualpoints",
    "возврат выручки",
    "выручка"
  ])) return "unitSum";

  if (containsAnyOzonReport65_(text, [
    "бонусы продавца",
    "возврат вознаграждения",
    "вознаграждение за продажу",
    "salecommission"
  ])) return "reward";

  if (containsAnyOzonReport65_(text, [
    "звездные товары",
    "звёздные товары",
    "premium pro (процент",
    "premiummembershipcommission",
    "starsmembership",
    "продвижение бренда",
    "brandcommission",
    "эквайринг",
    "acquiring"
  ])) return "starsAndAcquiring";

  if (containsAnyOzonReport65_(text, [
    "временное размещение товара в сц/пвз",
    "временное размещение товара партнерами",
    "вывоз товара со склада силами ozon: доставка до сц",
    "вывоз товара со склада силами ozon: доставка курьером",
    "выдача товара - отмена начисления",
    "дополнительная обработка овх",
    "доставка до места выдачи",
    "доставка до места выдачи - отмена начисления",
    "доставка до места выдачи силами ozon",
    "логистика - отмена начисления",
    "обеспечение материалами для упаковки товара",
    "обработка возвратов, отмен и невыкупов партнёрами",
    "обработка возвратов, отмен и невыкупов партнерами",
    "обработка отправления drop-off (пвз)",
    "обработка отправления drop-off (ппз)",
    "обработка отправления drop-off (сц)",
    "обработка отправления drop-off партнёрами (пвз)",
    "обработка отправления drop-off партнерами (пвз)",
    "обработка отправления drop-off партнёрами (ппз)",
    "обработка отправления drop-off партнерами (ппз)",
    "обратная логистика",
    "подготовка товара к вывозу: брак",
    "подготовка товара к вывозу: валид",
    "рассылка пуш-уведомлений",
    "упаковка товара партнёрами",
    "упаковка товара партнерами",
    "утилизация товара: повреждённые из-за упаковки",
    "утилизация товара: поврежденные из-за упаковки",
    "утилизация товара: повреждённые, были у покупателя",
    "утилизация товара: поврежденные, были у покупателя",
    "marketplaceserviceitemtemporarystorageredistribution",
    "marketplaceserviceitemtemporarystorage",
    "marketplaceserviceproductmovementfromwarehouse",
    "marketplaceserviceitemredistributionreturnspvz",
    "marketplaceservicevolumeweightcharacsprocessing",
    "marketplaceserviceitemredistributionlastmilecourier",
    "marketplaceserviceitemdeliverytohandoverplaceozon",
    "marketplaceserviceitemreturnflowlogistic",
    "marketplaceserviceitempackagematerialsprovision",
    "marketplaceserviceitemdropoffpvz",
    "marketplaceserviceitemdropoffppz",
    "marketplaceserviceitemdropoffsc",
    "marketplaceserviceitemredistributiondropoffapvz",
    "marketplaceserviceitemredistributiondropoffappz",
    "marketplaceserviceitempackageredistribution",
    "marketplaceservicesellerreturnscargoassortment",
    "marketplaceserviceitemredistributionlastmilepvz"
  ])) return "extra";

  if (text === "логистика" ||
      text === "логистика - отмена начисления" ||
      containsAnyOzonReport65_(text, [
        "marketplaceserviceitemdirectflowlogistic"
      ])) return "logistics";

  return "";
}

function getOzonReport65PerfToken_() {
  const props = PropertiesService.getScriptProperties();
  const clientId = props.getProperty("OZON_PERFORMANCE_CLIENT_ID") || OZON_REPORT65_PERF_CLIENT_ID;
  const clientSecret = props.getProperty("OZON_PERFORMANCE_CLIENT_SECRET") || OZON_REPORT65_PERF_CLIENT_SECRET;

  if (!clientId || !clientSecret) {
    if (typeof getPerfToken === "function") {
      Logger.log("Script Properties не заданы, использую legacy getPerfToken() из старого файла рекламы");
      return getPerfToken();
    }

    Logger.log("Не заданы Script Properties OZON_PERFORMANCE_CLIENT_ID/OZON_PERFORMANCE_CLIENT_SECRET и не найден legacy getPerfToken()");
    return "";
  }

  const response = UrlFetchApp.fetch(OZON_REPORT65_PERF_BASE_URL + "/api/client/token", {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify({
      client_id: clientId,
      client_secret: clientSecret,
      grant_type: "client_credentials"
    }),
    muteHttpExceptions: true
  });

  if (response.getResponseCode() !== 200) {
    Logger.log("Performance token HTTP " + response.getResponseCode());
    return "";
  }

  const data = JSON.parse(response.getContentText());
  return data.access_token || "";
}

function getOzonReport65PerfCampaigns_(token) {
  const response = UrlFetchApp.fetch(OZON_REPORT65_PERF_BASE_URL + "/api/client/campaign", {
    method: "get",
    headers: { Authorization: "Bearer " + token },
    muteHttpExceptions: true
  });

  if (response.getResponseCode() !== 200) {
    Logger.log("Performance campaign HTTP " + response.getResponseCode());
    return [];
  }

  const data = JSON.parse(response.getContentText());
  return data.list || [];
}

function filterOzonReport65CpoCampaigns_(campaigns) {
  const filtered = campaigns.filter(isOzonReport65CpoCampaign_);
  Logger.log("Performance CPO кампании: " + filtered.length + " / " + campaigns.length);
  return filtered;
}

function filterOzonReport65ClickCampaigns_(campaigns) {
  const filtered = campaigns.filter(campaign => !isOzonReport65CpoCampaign_(campaign));
  Logger.log("Performance оплата за клик кампании: " + filtered.length + " / " + campaigns.length);
  return filtered;
}

function isOzonReport65CpoCampaign_(campaign) {
  const values = [
    campaign && campaign.title,
    campaign && campaign.name,
    campaign && campaign.paymentType,
    campaign && campaign.payment_type,
    campaign && campaign.pricingModel,
    campaign && campaign.pricing_model,
    campaign && campaign.advObjectType,
    campaign && campaign.adv_object_type
  ];
  const text = normalizeOzonReport65Text_(values.filter(Boolean).join(" "));
  return text.indexOf("оплата за заказ") !== -1 ||
    text.indexOf("оплата за заказы") !== -1 ||
    text.indexOf("cpo") !== -1;
}

function fetchOzonReport65OverviewStats_(token, campaigns, dateFrom, dateTo, pendingOverviewReportUuid) {
  const stats = {};
  let failed = false;
  let pendingUuid = "";

  for (let i = 0; i < campaigns.length; i += OZON_REPORT65_CAMPAIGN_BATCH_SIZE) {
    const campaignIds = campaigns.slice(i, i + OZON_REPORT65_CAMPAIGN_BATCH_SIZE).map(campaign => String(campaign.id || campaign));
    const result = fetchOzonReport65OverviewCampaignIds_(
      token,
      campaignIds,
      dateFrom,
      dateTo,
      pendingOverviewReportUuid && i === 0 ? pendingOverviewReportUuid : ""
    );

    if (result.stats === null) {
      failed = true;
      pendingUuid = result.pendingOverviewReportUuid || "";
      continue;
    }

    mergeOzonReport65Stats_(stats, result.stats);

    if (i + OZON_REPORT65_CAMPAIGN_BATCH_SIZE < campaigns.length) Utilities.sleep(5000);
  }

  if (failed && !Object.keys(stats).length) {
    return { stats: null, pendingOverviewReportUuid: pendingUuid };
  }

  Logger.log("Overview ad SKUs: " + Object.keys(stats).length);
  return { stats: stats, pendingOverviewReportUuid: "" };
}

function fetchOzonReport65OverviewCampaignIds_(token, campaignIds, dateFrom, dateTo, pendingOverviewReportUuid) {
  const uuid = pendingOverviewReportUuid
    ? pendingOverviewReportUuid
    : createOzonReport65OverviewReport_(token, campaignIds, dateFrom, dateTo);

  if (uuid === null) {
    if (pendingOverviewReportUuid) {
      Logger.log("Performance pending report стал невосстановимым: " + pendingOverviewReportUuid);
      return { stats: {}, pendingOverviewReportUuid: "" };
    }

    if (campaignIds.length === 1) {
      Logger.log("Performance campaign пропущена из-за HTTP 400: " + campaignIds[0]);
      return { stats: {}, pendingOverviewReportUuid: "" };
    }

    const splitAt = Math.ceil(campaignIds.length / 2);
    const leftIds = campaignIds.slice(0, splitAt);
    const rightIds = campaignIds.slice(splitAt);
    Logger.log("Performance overview HTTP 400: разбиваем пачку " + campaignIds.join(", ") + " на " + leftIds.join(", ") + " / " + rightIds.join(", "));

    const left = fetchOzonReport65OverviewCampaignIds_(token, leftIds, dateFrom, dateTo, "");
    if (left.stats === null) return left;

    const right = fetchOzonReport65OverviewCampaignIds_(token, rightIds, dateFrom, dateTo, "");
    if (right.stats === null) return right;

    const stats = {};
    mergeOzonReport65Stats_(stats, left.stats);
    mergeOzonReport65Stats_(stats, right.stats);
    return { stats: stats, pendingOverviewReportUuid: "" };
  }

  if (!uuid) return { stats: null, pendingOverviewReportUuid: "" };

  if (pendingOverviewReportUuid) {
    Logger.log("Продолжаем ожидание Performance отчета " + uuid);
  }

  const blob = waitOzonReport65PerformanceReport_(token, uuid, [
    OZON_REPORT65_PERF_BASE_URL + "/api/client/statistics/" + uuid
  ], [
    OZON_REPORT65_PERF_BASE_URL + "/api/client/statistics/report?UUID=" + uuid + "&download=1",
    OZON_REPORT65_PERF_BASE_URL + "/api/client/statistics/report?UUID=" + uuid
  ]);

  if (!blob) return { stats: null, pendingOverviewReportUuid: uuid };

  return { stats: parseOzonReport65OverviewBlob_(blob), pendingOverviewReportUuid: "" };
}

function createOzonReport65OverviewReport_(token, campaignIds, dateFrom, dateTo) {
  const response = fetchOzonReport65PerformanceUrl_(OZON_REPORT65_PERF_BASE_URL + "/api/client/statistics", {
    method: "post",
    contentType: "application/json",
    headers: { Authorization: "Bearer " + token },
    payload: JSON.stringify({
      campaigns: campaignIds,
      dateFrom: dateFrom,
      dateTo: dateTo,
      groupBy: "SKU"
    }),
    muteHttpExceptions: true
  }, "create overview " + campaignIds.join(","));

  if (!response) return "";

  if (response.getResponseCode() !== 200) {
    const responseText = response.getContentText();
    Logger.log("Overview report HTTP " + response.getResponseCode() + " for campaign IDs: " + campaignIds.join(", "));
    if (responseText) Logger.log("Overview report response: " + responseText);
    return response.getResponseCode() === 400 ? null : "";
  }

  const data = JSON.parse(response.getContentText());
  return data.UUID || "";
}

function fetchOzonReport65CpoPaymentStats_(token, dateFrom, dateTo, campaigns) {
  const campaignIds = (campaigns || []).map(campaign => String(campaign.id || campaign)).filter(Boolean);
  if (!campaignIds.length) {
    Logger.log("CPO payment кампании не найдены, колонка ЗАКАЗЫ не будет обновлена");
    return null;
  }

  const uuid = createOzonReport65CpoPaymentReport_(token, dateFrom, dateTo, campaignIds);
  if (!uuid) return null;

  const blob = waitOzonReport65PerformanceReport_(token, uuid, [
    OZON_REPORT65_PERF_BASE_URL + "/api/client/statistics/orders/" + uuid,
    OZON_REPORT65_PERF_BASE_URL + "/api/client/statistics/orders/status?UUID=" + uuid,
    OZON_REPORT65_PERF_BASE_URL + "/api/client/statistic/orders/" + uuid,
    OZON_REPORT65_PERF_BASE_URL + "/api/client/statistic/orders/status?UUID=" + uuid,
    OZON_REPORT65_PERF_BASE_URL + "/api/client/statistics/" + uuid
  ], [
    OZON_REPORT65_PERF_BASE_URL + "/api/client/statistics/orders/download?UUID=" + uuid,
    OZON_REPORT65_PERF_BASE_URL + "/api/client/statistic/orders/download?UUID=" + uuid,
    OZON_REPORT65_PERF_BASE_URL + "/api/client/statistics/report?UUID=" + uuid + "&download=1",
    OZON_REPORT65_PERF_BASE_URL + "/api/client/statistics/report?UUID=" + uuid
  ]);

  if (!blob) {
    Logger.log("CPO payment report не получен, колонка ЗАКАЗЫ не будет обновлена");
    return null;
  }

  const stats = parseOzonReport65CpoPaymentBlob_(blob);
  Logger.log("CPO payment SKUs: " + Object.keys(stats).length);
  Logger.log("CPO payment total spend: " + roundOzonReport65Money_(sumOzonReport65Stats_(stats, "spend")));
  return stats;
}

function createOzonReport65CpoPaymentReport_(token, dateFrom, dateTo, campaignIds) {
  const payload = JSON.stringify({
    campaigns: campaignIds,
    dateFrom: dateFrom,
    dateTo: dateTo
  });
  const urls = [
    OZON_REPORT65_PERF_BASE_URL + "/api/client/statistics/orders/generate",
    OZON_REPORT65_PERF_BASE_URL + "/api/client/statistic/orders/generate"
  ];

  for (let i = 0; i < urls.length; i++) {
    const response = UrlFetchApp.fetch(urls[i], {
      method: "post",
      contentType: "application/json",
      headers: { Authorization: "Bearer " + token },
      payload: payload,
      muteHttpExceptions: true
    });

    if (response.getResponseCode() === 200) {
      const data = JSON.parse(response.getContentText());
      Logger.log("CPO payment report created via " + urls[i]);
      return data.UUID || "";
    }

    Logger.log("CPO payment report HTTP " + response.getResponseCode() + " via " + urls[i]);
    const text = response.getContentText();
    if (text) Logger.log("CPO payment report response: " + text.slice(0, 1000));
  }

  return "";
}

function waitOzonReport65PerformanceReport_(token, uuid, statusUrls, downloadUrls) {
  for (let attempt = 1; attempt <= OZON_REPORT65_PERF_REPORT_MAX_ATTEMPTS; attempt++) {
    Utilities.sleep(OZON_REPORT65_PERF_REPORT_POLL_MS);

    for (let i = 0; i < statusUrls.length; i++) {
      const statusResponse = fetchOzonReport65PerformanceUrl_(statusUrls[i], {
        method: "get",
        headers: { Authorization: "Bearer " + token },
        muteHttpExceptions: true
      }, "status " + uuid);
      if (!statusResponse) continue;

      const statusCode = statusResponse.getResponseCode();
      const statusBlob = statusResponse.getBlob();
      if (statusCode === 200 && isOzonReport65BlobReport_(statusBlob)) return statusBlob;
      if (statusCode !== 200) continue;

      const text = statusResponse.getContentText();
      let data = null;
      try {
        data = JSON.parse(text);
      } catch (e) {
        data = null;
      }

      if (data && data.state === "OK") {
        if (data.link) {
          const linked = downloadOzonReport65PerfBlob_(token, OZON_REPORT65_PERF_BASE_URL + data.link);
          if (linked) return linked;
        }

        for (let j = 0; j < downloadUrls.length; j++) {
          const downloaded = downloadOzonReport65PerfBlob_(token, downloadUrls[j]);
          if (downloaded) return downloaded;
        }
      }

      if (data && data.state === "ERROR") {
        Logger.log("Performance report error: " + uuid);
        return null;
      }
    }

    if (attempt % 6 === 0) Logger.log("Ожидание Performance отчета " + uuid + ": " + attempt + "/" + OZON_REPORT65_PERF_REPORT_MAX_ATTEMPTS);
  }

  Logger.log("Performance report timeout: " + uuid);
  return null;
}

function downloadOzonReport65PerfBlob_(token, url) {
  const response = fetchOzonReport65PerformanceUrl_(url, {
    method: "get",
    headers: { Authorization: "Bearer " + token },
    muteHttpExceptions: true
  }, "download");
  if (!response) return null;

  if (response.getResponseCode() !== 200) return null;

  const blob = response.getBlob();
  return isOzonReport65BlobReport_(blob) ? blob : null;
}

function fetchOzonReport65PerformanceUrl_(url, options, label) {
  try {
    return UrlFetchApp.fetch(url, options);
  } catch (e) {
    Logger.log("Performance fetch failed (" + label + "): " + e.toString());
    Utilities.sleep(2000);
  }

  try {
    return UrlFetchApp.fetch(url, options);
  } catch (e) {
    Logger.log("Performance fetch retry failed (" + label + "): " + e.toString());
    return null;
  }
}

function isOzonReport65BlobReport_(blob) {
  const bytes = blob.getBytes();
  if (bytes.length < 2) return false;
  if (bytes[0] === 0x50 && bytes[1] === 0x4B) return true;

  const text = blob.getDataAsString().replace(/^\uFEFF/, "").trim();
  return text.indexOf(";") !== -1 && (text.toLowerCase().indexOf("sku") !== -1 || text.toLowerCase().indexOf("артикул") !== -1);
}

function parseOzonReport65OverviewBlob_(blob) {
  return parseOzonReport65CsvStats_(blob, {
    sku: ["sku", "артикул"],
    clicks: ["клики", "clicks"],
    spend: ["расход", "spend"],
    orders: ["продано товаров", "заказы", "orders"],
    revenue: ["продажи в продвижении", "выручка", "revenue"]
  });
}

function parseOzonReport65CpoPaymentBlob_(blob) {
  return parseOzonReport65CsvStats_(blob, {
    sku: ["sku продвигаемого товара", "ozon id", "sku", "артикул"],
    clicks: ["количество кликов", "клики", "clicks"],
    spend: ["расход, ₽", "расход", "spend"],
    orders: ["количество заказов", "количество", "заказы", "orders"],
    revenue: ["стоимость продажи", "сумма заказов", "выручка", "revenue", "sum"]
  });
}

function parseOzonReport65CsvStats_(blob, markers) {
  const blobs = unzipOzonReport65Blobs_(blob);
  const stats = {};

  blobs.forEach(fileBlob => {
    const text = fileBlob.getDataAsString().replace(/^\uFEFF/, "");
    const rows = Utilities.parseCsv(text, ";").filter(row => row.some(cell => String(cell || "").trim() !== ""));
    const headerIndex = findOzonReport65CsvHeaderIndex_(rows);
    if (headerIndex < 0) return;

    const headers = rows[headerIndex].map(normalizeOzonReport65Text_);
    const skuIndex = findOzonReport65HeaderIndex_(headers, markers.sku);
    const clicksIndex = findOzonReport65HeaderIndex_(headers, markers.clicks);
    const spendIndex = findOzonReport65HeaderIndex_(headers, markers.spend);
    const ordersIndex = findOzonReport65HeaderIndex_(headers, markers.orders);
    const revenueIndex = findOzonReport65HeaderIndex_(headers, markers.revenue);

    if (skuIndex < 0) return;

    for (let i = headerIndex + 1; i < rows.length; i++) {
      const row = rows[i];
      const sku = normalizeOzonReport65Key_(row[skuIndex]);
      if (!sku || sku.toLowerCase() === "всего") continue;

      if (!stats[sku]) stats[sku] = { clicks: 0, orders: 0, revenue: 0, spend: 0 };
      stats[sku].clicks += clicksIndex >= 0 ? parseInt(parseOzonReport65Money_(row[clicksIndex]), 10) || 0 : 0;
      stats[sku].orders += ordersIndex >= 0 ? parseInt(parseOzonReport65Money_(row[ordersIndex]), 10) || 0 : 0;
      stats[sku].revenue += revenueIndex >= 0 ? parseOzonReport65Money_(row[revenueIndex]) : 0;
      stats[sku].spend += spendIndex >= 0 ? parseOzonReport65Money_(row[spendIndex]) : 0;
    }
  });

  return stats;
}

function unzipOzonReport65Blobs_(blob) {
  const bytes = blob.getBytes();
  if (bytes.length > 2 && bytes[0] === 0x50 && bytes[1] === 0x4B) {
    return Utilities.unzip(blob);
  }
  return [blob];
}

function findOzonReport65CsvHeaderIndex_(rows) {
  for (let i = 0; i < Math.min(rows.length, 10); i++) {
    const joined = rows[i].map(normalizeOzonReport65Text_).join(";");
    if ((joined.indexOf("sku") !== -1 || joined.indexOf("артикул") !== -1) &&
        (joined.indexOf("клики") !== -1 || joined.indexOf("заказ") !== -1 || joined.indexOf("расход") !== -1)) {
      return i;
    }
  }
  return -1;
}

function findOzonReport65HeaderIndex_(headers, markers) {
  for (let j = 0; j < markers.length; j++) {
    const marker = normalizeOzonReport65Text_(markers[j]);
    for (let i = 0; i < headers.length; i++) {
      if (headers[i].indexOf(marker) !== -1) return i;
    }
  }
  return -1;
}

function mergeOzonReport65Stats_(target, source) {
  Object.keys(source).forEach(sku => {
    if (!target[sku]) target[sku] = { clicks: 0, orders: 0, revenue: 0, spend: 0 };
    target[sku].clicks += source[sku].clicks || 0;
    target[sku].orders += source[sku].orders || 0;
    target[sku].revenue += source[sku].revenue || 0;
    target[sku].spend += source[sku].spend || 0;
  });
}

function sumOzonReport65Stats_(stats, field) {
  return Object.keys(stats || {}).reduce((sum, sku) => sum + (Number(stats[sku][field]) || 0), 0);
}

function getOzonReport65OverpaymentValues_(sheet, headerMap, rowItems) {
  const overpaymentCol = getOzonReport65Column_(headerMap, "ПЕРЕПЛАТА");
  if (overpaymentCol) {
    return sheet.getRange(headerMap.__headerRow + 1, overpaymentCol, rowItems.length, 1).getValues();
  }

  const sourceSheet = sheet.getParent().getSheetByName("UNIT");
  if (!sourceSheet || sourceSheet.getName() === sheet.getName()) {
    Logger.log("Колонка ПЕРЕПЛАТА не найдена, корректировка логистики не применяется");
    return [];
  }

  const sourceHeaderMap = getOzonReport65HeaderMap_(sourceSheet);
  const sourceOverpaymentCol = getOzonReport65Column_(sourceHeaderMap, "ПЕРЕПЛАТА");
  const sourceArticleCol = getOzonReport65Column_(sourceHeaderMap, "Артикул");
  const sourceSkuCol = getOzonReport65Column_(sourceHeaderMap, "СКУ OZ");
  if (!sourceOverpaymentCol || !sourceArticleCol || !sourceSkuCol) {
    Logger.log("На листе UNIT не найдены Артикул/СКУ OZ/ПЕРЕПЛАТА, корректировка логистики не применяется");
    return [];
  }

  const rowCount = sourceSheet.getLastRow() - sourceHeaderMap.__headerRow;
  if (rowCount <= 0) return [];

  const width = Math.max(sourceArticleCol, sourceSkuCol, sourceOverpaymentCol);
  const rows = sourceSheet.getRange(sourceHeaderMap.__headerRow + 1, 1, rowCount, width).getValues();
  const overpaymentByKey = {};

  rows.forEach(row => {
    const article = normalizeOzonReport65Key_(row[sourceArticleCol - 1]);
    const sku = normalizeOzonReport65Key_(row[sourceSkuCol - 1]);
    const amount = parseOzonReport65Money_(row[sourceOverpaymentCol - 1]);
    if (article || sku) overpaymentByKey[article + "|" + sku] = amount;
    if (article && overpaymentByKey[article + "|"] === undefined) overpaymentByKey[article + "|"] = amount;
  });

  Logger.log("ПЕРЕПЛАТА взята с листа UNIT: " + Object.keys(overpaymentByKey).length + " ключей");
  return rowItems.map(item => {
    const exactKey = item.article + "|" + item.sku;
    const articleKey = item.article + "|";
    const amount = overpaymentByKey[exactKey] !== undefined ? overpaymentByKey[exactKey] : (overpaymentByKey[articleKey] || 0);
    return [amount];
  });
}

function getOzonReport65CommonExtraBase_(accrual, item) {
  return (Number(accrual && accrual.unitSum) || 0) + (Number(item && item.upd) || 0);
}

function writeOzonReport65FinanceColumns_(sheet, headerMap, rowItems, accrualMap, cpoMap, storageMap) {
  const overpaymentValues = getOzonReport65OverpaymentValues_(sheet, headerMap, rowItems);
  const commonCosts = accrualMap[OZON_REPORT65_COMMON_COSTS_KEY] || createOzonReport65AccrualBucket_();
  const totalCommonExtraBase = rowItems.reduce((sum, item) => {
    const accrual = accrualMap[item.article] || accrualMap[item.sku] || createOzonReport65AccrualBucket_();
    return sum + getOzonReport65CommonExtraBase_(accrual, item);
  }, 0);
  const totalUnitSum = rowItems.reduce((sum, item) => {
    const accrual = accrualMap[item.article] || accrualMap[item.sku] || createOzonReport65AccrualBucket_();
    return sum + (Number(accrual.unitSum) || 0);
  }, 0);
  const commonExtraRate = totalCommonExtraBase ? (Number(commonCosts.commonExtra) || 0) / totalCommonExtraBase : 0;
  const commonCpoRate = totalUnitSum ? (Number(commonCosts.cpoPayment) || 0) / totalUnitSum : 0;
  const commonClicksRate = totalUnitSum ? (Number(commonCosts.clicksPayment) || 0) / totalUnitSum : 0;
  writeOzonReport65CommonExtraCoefficient_(sheet, commonExtraRate);
  const columns = [
    { header: "UNIT СУММА", getter: data => data.unitSum },
    { header: "UNIT ШТ", getter: data => data.unitQty },
    { header: "ВОЗНАГРАЖДЕНИЕ", getter: data => data.reward },
    { header: "ЛОГИСТИКА", getter: data => data.logistics },
    { header: "ПЕРЕПЛАТА", getter: data => data.overpayment },
    { header: "ХРАНЕНИЕ", getter: data => data.storage },
    { header: "ДОП", getter: data => data.extra },
    { header: "ОЗОН ДОП ВОЗНЯ", getter: data => data.commonExtra },
    { header: "ЗВЕЗДЫ + ЭКВ", getter: data => data.starsAndAcquiring }
  ];

  // ОТКЛЮЧЕНО: запись ЗАКАЗОВ в колонку Y.
  // if (getOzonReport65Column_(headerMap, "ЗАКАЗЫ")) {
  //   columns.push({ header: "ЗАКАЗЫ", getter: data => data.cpoPayment });
  // }

  // ОТКЛЮЧЕНО: запись КЛИКОВ в колонку X.
  // if (OZON_REPORT65_CLICKS_SOURCE === "finance" && getOzonReport65Column_(headerMap, "КЛИКИ")) {
  //   columns.push({ header: "КЛИКИ", getter: data => data.clicksPayment });
  // }

  const columnValues = columns.map(column => ({
    col: getOzonReport65Column_(headerMap, column.header),
    values: [],
    getter: column.getter,
    header: column.header
  }));

  let matchedAccrual = 0;
  let matchedCpo = 0;
  let matchedStorage = 0;
  let writtenCpoSpend = 0;
  let writtenClicksSpend = 0;
  let writtenStorage = 0;

  rowItems.forEach((item, index) => {
    const accrual = accrualMap[item.article] || accrualMap[item.sku] || createOzonReport65AccrualBucket_();
    const cpo = cpoMap ? (cpoMap[item.sku] || cpoMap[item.article] || { spend: 0 }) : { spend: 0 };
    const overpayment = overpaymentValues[index]
      ? parseOzonReport65Money_(overpaymentValues[index][0])
      : 0;
    const storage = getOzonReport65StorageValue_(storageMap, item);

    if (accrual.unitSum || accrual.unitQty || accrual.reward || accrual.logistics || accrual.extra || accrual.starsAndAcquiring) matchedAccrual++;
    const cpoPayment = cpoMap ? (Number(cpo.spend) || 0) : -((Number(accrual.unitSum) || 0) * commonCpoRate);
    const clicksPayment = -((Number(accrual.unitSum) || 0) * commonClicksRate);
    if (cpoPayment) matchedCpo++;
    if (storage) matchedStorage++;
    if (cpoPayment) writtenCpoSpend += cpoPayment;
    if (clicksPayment) writtenClicksSpend += clicksPayment;
    if (storage) writtenStorage += storage;

    const data = {
      unitSum: roundOzonReport65Money_(accrual.unitSum || 0),
      unitQty: Math.round(Number(accrual.unitQty) || 0),
      reward: roundOzonReport65Money_(accrual.reward || 0),
      logistics: roundOzonReport65Money_((accrual.logistics || 0) - overpayment),
      overpayment: roundOzonReport65Money_(overpayment),
      storage: roundOzonReport65Money_(storage),
      extra: roundOzonReport65Money_(accrual.extra || 0),
      starsAndAcquiring: roundOzonReport65Money_(accrual.starsAndAcquiring || 0),
      commonExtra: roundOzonReport65Money_(getOzonReport65CommonExtraBase_(accrual, item) * commonExtraRate),
      cpoPayment: roundOzonReport65Money_(cpoPayment),
      clicksPayment: roundOzonReport65Money_(clicksPayment)
    };

    columnValues.forEach(column => column.values.push([column.getter(data)]));
  });

  columnValues.forEach(column => {
    if (!column.col) throw new Error("Не найден заголовок для записи: " + column.header);
    sheet.getRange(headerMap.__headerRow + 1, column.col, column.values.length, 1).setValues(column.values);
  });

  Logger.log("Начисления сопоставлены: " + matchedAccrual + " строк");
  Logger.log("ПЕРЕПЛАТА записана из листа UNIT API/UNIT: " + roundOzonReport65Money_(overpaymentValues.reduce((sum, row) => sum + parseOzonReport65Money_(row && row[0]), 0)));
  Logger.log("ХРАНЕНИЕ сопоставлено: " + matchedStorage + " строк; записано " + roundOzonReport65Money_(writtenStorage));
  Logger.log("Общие расходы без артикула для ОЗОН ДОП ВОЗНЯ: " + roundOzonReport65Money_(commonCosts.commonExtra || 0) + "; база UNIT СУММА + УПД: " + roundOzonReport65Money_(totalCommonExtraBase) + "; процент: " + (commonExtraRate * 100).toFixed(4) + "%; коэффициент: " + (1 + commonExtraRate).toFixed(4));
  Logger.log("Оплата за заказ из accrual/by-day: " + roundOzonReport65Money_(commonCosts.cpoPayment || 0) + "; процент: " + (commonCpoRate * 100).toFixed(4) + "%");
  Logger.log("Оплата за клик из accrual/by-day: " + roundOzonReport65Money_(commonCosts.clicksPayment || 0) + "; процент: " + (commonClicksRate * 100).toFixed(4) + "%; записано в КЛИКИ: " + roundOzonReport65Money_(writtenClicksSpend));
  if (!matchedAccrual && Object.keys(accrualMap).length) {
    Logger.log("Finance sample keys: " + Object.keys(accrualMap).slice(0, 10).join(", "));
    Logger.log("Sheet sample article keys: " + rowItems.map(item => item.article).filter(Boolean).slice(0, 10).join(", "));
    Logger.log("Sheet sample SKU keys: " + rowItems.map(item => item.sku).filter(Boolean).slice(0, 10).join(", "));
  }
  if (cpoMap) {
    Logger.log("CPO заказы сопоставлены: " + matchedCpo + " строк");
    Logger.log("CPO расход в отчете: " + roundOzonReport65Money_(sumOzonReport65Stats_(cpoMap, "spend")) + "; записано в ЗАКАЗЫ: " + roundOzonReport65Money_(writtenCpoSpend));
    if (!matchedCpo && Object.keys(cpoMap).length) {
      Logger.log("CPO sample keys: " + Object.keys(cpoMap).slice(0, 10).join(", "));
    }
  } else {
    Logger.log("CPO заказы распределены по UNIT СУММА из accrual/by-day; записано в ЗАКАЗЫ: " + roundOzonReport65Money_(writtenCpoSpend));
  }
}

function writeOzonReport65FinanceClicksColumn_(sheet, headerMap, rowItems, accrualMap) {
  const clicksCol = getOzonReport65Column_(headerMap, "КЛИКИ");
  if (!clicksCol) throw new Error("Не найден заголовок для записи: КЛИКИ");

  const commonCosts = accrualMap[OZON_REPORT65_COMMON_COSTS_KEY] || createOzonReport65AccrualBucket_();
  const totalUnitSum = rowItems.reduce((sum, item) => {
    const accrual = accrualMap[item.article] || accrualMap[item.sku] || createOzonReport65AccrualBucket_();
    return sum + (Number(accrual.unitSum) || 0);
  }, 0);
  const commonClicksRate = totalUnitSum ? (Number(commonCosts.clicksPayment) || 0) / totalUnitSum : 0;
  let writtenClicksSpend = 0;

  const values = rowItems.map(item => {
    const accrual = accrualMap[item.article] || accrualMap[item.sku] || createOzonReport65AccrualBucket_();
    const clicksPayment = -((Number(accrual.unitSum) || 0) * commonClicksRate);
    if (clicksPayment) writtenClicksSpend += clicksPayment;
    return [roundOzonReport65Money_(clicksPayment)];
  });

  sheet.getRange(headerMap.__headerRow + 1, clicksCol, values.length, 1).setValues(values);
  Logger.log("КЛИКИ перезаписаны из accrual/by-day type_id=41: " + roundOzonReport65Money_(commonCosts.clicksPayment || 0) + "; процент: " + (commonClicksRate * 100).toFixed(4) + "%; записано: " + roundOzonReport65Money_(writtenClicksSpend));
}

function clearOzonReport65ClicksColumn_(sheet, headerMap, rowCount) {
  const clicksCol = getOzonReport65Column_(headerMap, "КЛИКИ");
  if (!clicksCol || !rowCount) return;

  const zeros = Array.from({ length: rowCount }, () => [0]);
  sheet.getRange(headerMap.__headerRow + 1, clicksCol, rowCount, 1).setValues(zeros);
  Logger.log("Колонка КЛИКИ очищена для накопительной записи фактических кликов из Performance API");
}

function writeOzonReport65AdClicksBatch_(sheet, headerMap, rowItems, overviewMap) {
  const clicksCol = getOzonReport65Column_(headerMap, "КЛИКИ");
  if (!clicksCol) throw new Error("Не найден заголовок для записи: КЛИКИ");

  const range = sheet.getRange(headerMap.__headerRow + 1, clicksCol, rowItems.length, 1);
  const values = range.getValues();
  let matchedClickRows = 0;
  let writtenClicks = 0;

  rowItems.forEach((item, index) => {
    const overview = overviewMap[item.sku] || overviewMap[item.article] || { clicks: 0 };
    const clicks = Math.round(Number(overview.clicks) || 0);
    if (!clicks) return;

    values[index][0] = Math.round(parseOzonReport65Money_(values[index][0]) + clicks);
    matchedClickRows++;
    writtenClicks += clicks;
  });

  range.setValues(values);
  Logger.log("КЛИКИ пачки: в отчете " + Math.round(sumOzonReport65Stats_(overviewMap, "clicks")) + "; записано " + Math.round(writtenClicks) + "; строк " + matchedClickRows);
}

function getOzonReport65DefaultDateRange_() {
  const today = new Date();
  const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
  const fromDate = new Date(today.getFullYear(), today.getMonth() - 1, today.getDate());

  return {
    from: Utilities.formatDate(fromDate, Session.getScriptTimeZone(), "yyyy-MM-dd"),
    to: Utilities.formatDate(yesterday, Session.getScriptTimeZone(), "yyyy-MM-dd")
  };
}

function logOzonReport65UnknownTypes_(unknownTypes) {
  const entries = Object.keys(unknownTypes)
    .filter(key => unknownTypes[key])
    .sort((a, b) => Math.abs(unknownTypes[b]) - Math.abs(unknownTypes[a]))
    .slice(0, 30);

  if (!entries.length) return;

  Logger.log("Не классифицированные типы начислений (первые 30):");
  entries.forEach(key => Logger.log(key + ": " + roundOzonReport65Money_(unknownTypes[key])));
}

function containsAnyOzonReport65_(text, needles) {
  return needles.some(needle => text.indexOf(normalizeOzonReport65Text_(needle)) !== -1);
}

function normalizeOzonReport65Key_(value) {
  if (value === null || value === undefined) return "";
  return decodeOzonReport65XmlEntities_(String(value)).trim();
}

function normalizeOzonReport65Text_(value) {
  return normalizeOzonReport65Key_(value).toLowerCase().replace(/\s+/g, " ");
}

function normalizeOzonReport65Header_(value) {
  return normalizeOzonReport65Text_(value).replace(/ё/g, "е");
}

function parseOzonReport65Money_(value) {
  if (value && typeof value === "object" && value.amount !== undefined) value = value.amount;
  if (value === null || value === undefined || value === "") return 0;
  let normalized = String(value)
    .replace(/\u00A0/g, "")
    .replace(/\s+/g, "")
    .replace(/руб/gi, "")
    .replace(/[₽р]/gi, "");

  if (normalized.indexOf(",") !== -1 && normalized.indexOf(".") !== -1) {
    normalized = normalized.replace(/\./g, "").replace(",", ".");
  } else {
    normalized = normalized.replace(",", ".");
  }

  const num = Number(normalized);
  return Number.isFinite(num) ? num : 0;
}

function roundOzonReport65Money_(value) {
  const num = Number(value) || 0;
  return Math.round(num * 100) / 100;
}

function decodeOzonReport65XmlEntities_(value) {
  return String(value || "")
    .replace(/&#x([0-9a-f]+);/gi, function(_, hex) {
      return String.fromCharCode(parseInt(hex, 16));
    })
    .replace(/&#([0-9]+);/g, function(_, dec) {
      return String.fromCharCode(parseInt(dec, 10));
    });
}
