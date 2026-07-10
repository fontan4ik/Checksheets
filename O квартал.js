/**
 * OZON UNIT API: начисления + реклама
 *
 * Заполняет лист "UNIT API квартал" по существующим заголовкам.
 * Лист UNIT API квартал должен повторять структуру листа UNIT.
 * - UNIT СУММА = posting.products[].commission.sale_amount из accrual/by-day
 * - UNIT ШТ = восстановленное количество продаж из accrual/by-day: sale_amount / seller_price
 * - ВОЗНАГРАЖДЕНИЕ = posting.products[].commission.commission из accrual/by-day
 * - ЛОГИСТИКА = delivery.services type_id=32 из accrual/by-day
 * - ПЕРЕПЛАТА = отдельная корректировка логистики из листа UNIT API квартал/UNIT, отдельного поля в accrual/by-day нет
 * - ХРАНЕНИЕ = отчёт стоимости размещения /v1/report/placement/by-products/create
 * - ДОП = зелёная группа поартикульных дополнительных услуг из отчёта начислений
 * - ОЗОН ДОП ВОЗНЯ = общие non_item_fee без артикула из accrual/by-day со знаком расхода, кроме кликов и оплаты за заказ
 * - ЗВЕЗДЫ + ЭКВ = синяя группа: Звёздные товары + Premium Pro (%) + Продвижение бренда + Эквайринг
 * - КЛИКИ = Performance overview / расход по кампаниям оплаты за клик
 * - ЗАКАЗЫ = non_item_fee type_id=54 из accrual/by-day, распределяется по UNIT СУММА
 *
 * Источники:
 * - POST https://api-seller.ozon.ru/v1/finance/accrual/by-day
 * - POST https://api-performance.ozon.ru/api/client/statistics, groupBy=SKU
 */

const OZON_REPORT_QUARTER_UNIT_API_SHEET_NAME = "UNIT API квартал";
const OZON_REPORT_QUARTER_UNIT_API_SHEET_ID = 217651682;
const OZON_REPORT_QUARTER_SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI";
const OZON_REPORT_QUARTER_FIXED_DATE_FROM = "2026-03-23";
const OZON_REPORT_QUARTER_FIXED_DATE_TO = "2026-06-22";
const OZON_REPORT_QUARTER_PERF_BASE_URL = "https://api-performance.ozon.ru";
const OZON_REPORT_QUARTER_PERF_CLIENT_ID = "92353868-1771409527407@advertising.performance.ozon.ru";
const OZON_REPORT_QUARTER_PERF_CLIENT_SECRET = "qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw";
const OZON_REPORT_QUARTER_FINANCE_PAGE_SIZE = 1000;
const OZON_REPORT_QUARTER_PRODUCT_INFO_BATCH_SIZE = 1000;
const OZON_REPORT_QUARTER_STORAGE_REPORT_MAX_WAIT_MS = 5 * 60 * 1000;
const OZON_REPORT_QUARTER_STORAGE_REPORT_POLL_MS = 10000;
const OZON_REPORT_QUARTER_STORAGE_TEMP_SHEET_NAME = "defolt";
const OZON_REPORT_QUARTER_CAMPAIGN_BATCH_SIZE = 5;
const OZON_REPORT_QUARTER_CAMPAIGNS_PER_TRIGGER = 5;
const OZON_REPORT_QUARTER_PERF_REPORT_MAX_ATTEMPTS = 24;
const OZON_REPORT_QUARTER_PERF_REPORT_POLL_MS = 5000;
const OZON_REPORT_QUARTER_PERF_REPORT_MAX_RETRIES = 6;
const OZON_REPORT_QUARTER_PERF_TRIGGER_GAP_MS = 5 * 60 * 1000;
const OZON_REPORT_QUARTER_PERF_MAX_PERIOD_DAYS = 62;
const OZON_REPORT_QUARTER_PERF_STATE_KEY = "OZON_REPORT_QUARTER_PERF_STATE";
const OZON_REPORT_QUARTER_PERF_TRIGGER_HANDLER = "resumeOzonReportQuarterPerformance";
const OZON_REPORT_QUARTER_FINANCE_STATE_KEY = "OZON_REPORT_QUARTER_FINANCE_STATE";
const OZON_REPORT_QUARTER_FINANCE_TRIGGER_HANDLER = "resumeOzonReportQuarterFinance";
const OZON_REPORT_QUARTER_FINANCE_DAYS_PER_TRIGGER = 5;
const OZON_REPORT_QUARTER_STORAGE_STATE_KEY = "OZON_REPORT_QUARTER_STORAGE_STATE";
const OZON_REPORT_QUARTER_STORAGE_TRIGGER_HANDLER = "resumeOzonReportQuarterStorage";
const OZON_REPORT_QUARTER_STAGE_TRIGGER_GAP_MS = 60 * 1000;
const OZON_REPORT_QUARTER_HEADER_SCAN_ROWS = 20;
const OZON_REPORT_QUARTER_COMMON_EXTRA_COEFFICIENT_CELL = "T1";
const OZON_REPORT_QUARTER_COMMON_EXTRA_COLUMN = 20;
const OZON_REPORT_QUARTER_STORAGE_MAP_CHUNK_PREFIX = "OZON_REPORT_QUARTER_STORAGE_MAP_CHUNK_";
const OZON_REPORT_QUARTER_STORAGE_MAP_CHUNK_COUNT_KEY = "OZON_REPORT_QUARTER_STORAGE_MAP_CHUNK_COUNT";
const OZON_REPORT_QUARTER_STORAGE_MAP_CHUNK_SIZE = 8000;
const OZON_REPORT_QUARTER_STORAGE_WRITE_BATCH_SIZE = 1000;

const OZON_REPORT_QUARTER_REQUIRED_HEADERS = [
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

const OZON_REPORT_QUARTER_COMMON_COSTS_KEY = "__OZON_REPORT_QUARTER_common_costs__";

function updateOzonReportQuarter() {
  updateOzonReportQuarterForDates(OZON_REPORT_QUARTER_FIXED_DATE_FROM, OZON_REPORT_QUARTER_FIXED_DATE_TO);
}

function updateOzonReportQuarterStorageOnly() {
  updateOzonReportQuarterStorageOnlyForDates(OZON_REPORT_QUARTER_FIXED_DATE_FROM, OZON_REPORT_QUARTER_FIXED_DATE_TO);
}

function updateOzonReportQuarterStorageOnlyForDates(dateFrom, dateTo) {
  return withOzonReportQuarterScriptLock_("updateOzonReportQuarterStorageOnlyForDates", function() {
    const sheet = getOzonReportQuarterUnitApiSheet_();
    const lastRow = sheet.getLastRow();
    if (lastRow < 2) {
      Logger.log("Нет строк для обработки хранения");
      return;
    }

    const headerMap = getOzonReportQuarterHeaderMap_(sheet);
    validateOzonReportQuarterHeaders_(headerMap);
    const storageCol = getOzonReportQuarterColumn_(headerMap, "ХРАНЕНИЕ");
    if (!storageCol) throw new Error("В UNIT API квартал не найден заголовок: ХРАНЕНИЕ");
    if (lastRow <= headerMap.__headerRow) {
      Logger.log("Нет строк для обработки ниже строки заголовков " + headerMap.__headerRow);
      return;
    }

    clearOzonReportQuarterStorageTriggers_();
    deleteOzonReportQuarterStageState_(OZON_REPORT_QUARTER_STORAGE_STATE_KEY);
    deleteOzonReportQuarterPendingStorageMap_();

    const rowCount = lastRow - headerMap.__headerRow;
    const zeroValues = Array.from({ length: rowCount }, () => [0]);
    sheet.getRange(headerMap.__headerRow + 1, storageCol, rowCount, 1).setValues(zeroValues);

    const periods = buildOzonReportQuarterStoragePeriods_(dateFrom, dateTo);
    saveOzonReportQuarterStageState_(OZON_REPORT_QUARTER_STORAGE_STATE_KEY, {
      dateFrom: dateFrom,
      dateTo: dateTo,
      periods: periods,
      offset: 0,
      storageOnly: true
    });

    Logger.log("ХРАНЕНИЕ-only поставлено в очередь: " + periods.length + " периодов; колонка очищена");
    processOzonReportQuarterStorageStage_();
  });
}

function updateOzonReportQuarterForDates(dateFrom, dateTo) {
  return startOzonReportQuarterStagedRun_(dateFrom, dateTo);
}

function resumeOzonReportQuarterFinance() {
  return withOzonReportQuarterScriptLock_("resumeOzonReportQuarterFinance", function() {
    clearOzonReportQuarterFinanceTriggers_();
    processOzonReportQuarterFinanceStage_();
  });
}

function resumeOzonReportQuarterStorage() {
  return withOzonReportQuarterScriptLock_("resumeOzonReportQuarterStorage", function() {
    clearOzonReportQuarterStorageTriggers_();
    processOzonReportQuarterStorageStage_();
  });
}

function stopOzonReportQuarterStagedRun() {
  return withOzonReportQuarterScriptLock_("stopOzonReportQuarterStagedRun", function() {
    clearOzonReportQuarterFinanceTriggers_();
    clearOzonReportQuarterStorageTriggers_();
    clearOzonReportQuarterPerfTriggers_();
    deleteOzonReportQuarterStageState_(OZON_REPORT_QUARTER_FINANCE_STATE_KEY);
    deleteOzonReportQuarterStageState_(OZON_REPORT_QUARTER_STORAGE_STATE_KEY);
    deleteOzonReportQuarterPerformanceState_();
    deleteOzonReportQuarterPendingStorageMap_();
    Logger.log("Квартальная обработка остановлена, состояния и триггеры очищены");
  });
}

function restartOzonReportQuarterClicks() {
  return restartOzonReportQuarterClicksForDates(OZON_REPORT_QUARTER_FIXED_DATE_FROM, OZON_REPORT_QUARTER_FIXED_DATE_TO);
}

function restartOzonReportQuarterClicksForDates(dateFrom, dateTo) {
  return withOzonReportQuarterScriptLock_("restartOzonReportQuarterClicks", function() {
    clearOzonReportQuarterPerfTriggers_();
    deleteOzonReportQuarterPerformanceState_();
    startOzonReportQuarterPerformanceStage_(dateFrom, dateTo);
  });
}

function checkOzonReportQuarterStagedRun() {
  const financeState = getOzonReportQuarterStageState_(OZON_REPORT_QUARTER_FINANCE_STATE_KEY, false);
  const storageState = getOzonReportQuarterStageState_(OZON_REPORT_QUARTER_STORAGE_STATE_KEY, false);
  Logger.log("Finance triggers active: " + countOzonReportQuarterTriggersByHandler_(OZON_REPORT_QUARTER_FINANCE_TRIGGER_HANDLER));
  Logger.log("Storage triggers active: " + countOzonReportQuarterTriggersByHandler_(OZON_REPORT_QUARTER_STORAGE_TRIGGER_HANDLER));
  Logger.log("Performance triggers active: " + countOzonReportQuarterPerfTriggers_());
  Logger.log("Finance state: " + (financeState ? JSON.stringify(financeState) : "empty"));
  Logger.log("Storage state: " + (storageState ? JSON.stringify(storageState) : "empty"));
  checkOzonReportQuarterPerformanceState();
}

function updateOzonReportQuarterForDatesSingleRun_(dateFrom, dateTo) {
  return withOzonReportQuarterScriptLock_("updateOzonReportQuarterForDates", function() {
  const sheet = getOzonReportQuarterUnitApiSheet_();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет строк для обработки");
    return;
  }

  const headerMap = getOzonReportQuarterHeaderMap_(sheet);
  validateOzonReportQuarterHeaders_(headerMap);

  if (lastRow <= headerMap.__headerRow) {
    Logger.log("Нет строк для обработки ниже строки заголовков " + headerMap.__headerRow);
    return;
  }

  const rowItems = readOzonReportQuarterRows_(sheet, lastRow, headerMap);
  Logger.log("=== OZON UNIT API квартал: начисления + реклама ===");
  Logger.log("Период: " + dateFrom + " -> " + dateTo);
  clearOzonReportQuarterPerfTriggers_();
  deleteOzonReportQuarterPerformanceState_();

  const accrualMap = fetchOzonReportQuarterAccruals_(dateFrom, dateTo);
  const storageMap = fetchOzonReportQuarterStorageMap_(dateFrom, dateTo);
  const token = getOzonReportQuarterPerfToken_();
  let campaigns = [];
  let cpoMap = null;

  if (token) {
    campaigns = getOzonReportQuarterPerfCampaigns_(token);
    Logger.log("Performance CPO отключен: ЗАКАЗЫ берутся из accrual/by-day non_item_fee type_id=54");
  } else {
    Logger.log("Performance API token не получен, рекламные колонки не будут обновлены");
  }

  writeOzonReportQuarterFinanceColumns_(sheet, headerMap, rowItems, accrualMap, cpoMap, storageMap);

  if (!token) return;

  if (!campaigns.length) {
    Logger.log("Performance кампании не найдены, колонка КЛИКИ не очищена");
    return;
  }

  const clickCampaigns = filterOzonReportQuarterClickCampaigns_(campaigns);
  if (!clickCampaigns.length) {
    Logger.log("Performance кампании оплаты за клик не найдены, колонка КЛИКИ не очищена");
    return;
  }

  clearOzonReportQuarterClicksColumn_(sheet, headerMap, rowItems.length);
  startOzonReportQuarterPerformanceProcessing_(clickCampaigns, dateFrom, dateTo);
  });
}

function startOzonReportQuarterStagedRun_(dateFrom, dateTo) {
  return withOzonReportQuarterScriptLock_("startOzonReportQuarterStagedRun", function() {
    const sheet = getOzonReportQuarterUnitApiSheet_();
    const lastRow = sheet.getLastRow();

    if (lastRow < 2) {
      Logger.log("Нет строк для обработки");
      return;
    }

    const headerMap = getOzonReportQuarterHeaderMap_(sheet);
    validateOzonReportQuarterHeaders_(headerMap);

    if (lastRow <= headerMap.__headerRow) {
      Logger.log("Нет строк для обработки ниже строки заголовков " + headerMap.__headerRow);
      return;
    }

    const rowItems = readOzonReportQuarterRows_(sheet, lastRow, headerMap);
    const overpaymentValues = getOzonReportQuarterOverpaymentValues_(sheet, headerMap, rowItems);

    clearOzonReportQuarterFinanceTriggers_();
    clearOzonReportQuarterStorageTriggers_();
    clearOzonReportQuarterPerfTriggers_();
    deleteOzonReportQuarterStageState_(OZON_REPORT_QUARTER_FINANCE_STATE_KEY);
    deleteOzonReportQuarterStageState_(OZON_REPORT_QUARTER_STORAGE_STATE_KEY);
    deleteOzonReportQuarterPerformanceState_();
    deleteOzonReportQuarterPendingStorageMap_();

    initializeOzonReportQuarterStagedColumns_(sheet, headerMap, rowItems.length, overpaymentValues);

    saveOzonReportQuarterStageState_(OZON_REPORT_QUARTER_FINANCE_STATE_KEY, {
      dateFrom: dateFrom,
      dateTo: dateTo,
      nextDate: dateFrom,
      cpoPayment: 0,
      commonExtra: 0,
      clicksPayment: 0,
      chunksDone: 0
    });

    Logger.log("=== OZON UNIT API квартал: staged-запуск ===");
    Logger.log("Лист: " + OZON_REPORT_QUARTER_UNIT_API_SHEET_NAME);
    Logger.log("Период: " + dateFrom + " -> " + dateTo);
    Logger.log("Начисления будут обработаны кусками по " + OZON_REPORT_QUARTER_FINANCE_DAYS_PER_TRIGGER + " дней, затем хранение месячными кусками, затем клики пачками кампаний");
    processOzonReportQuarterFinanceStage_();
  });
}

function initializeOzonReportQuarterStagedColumns_(sheet, headerMap, rowCount, overpaymentValues) {
  const zeroHeaders = [
    "UNIT СУММА",
    "UNIT ШТ",
    "ВОЗНАГРАЖДЕНИЕ",
    "ЛОГИСТИКА",
    "ХРАНЕНИЕ",
    "ДОП",
    "ОЗОН ДОП ВОЗНЯ",
    "ЗВЕЗДЫ + ЭКВ",
    "ЗАКАЗЫ",
    "КЛИКИ"
  ];
  const zeroValues = Array.from({ length: rowCount }, () => [0]);

  zeroHeaders.forEach(header => {
    const col = getOzonReportQuarterColumn_(headerMap, header);
    if (col) sheet.getRange(headerMap.__headerRow + 1, col, rowCount, 1).setValues(zeroValues);
  });

  const overpaymentCol = getOzonReportQuarterColumn_(headerMap, "ПЕРЕПЛАТА");
  const values = overpaymentValues.map(row => [roundOzonReportQuarterMoney_(parseOzonReportQuarterMoney_(row && row[0]))]);
  sheet.getRange(headerMap.__headerRow + 1, overpaymentCol, rowCount, 1).setValues(values);
  Logger.log("Колонки квартального запуска очищены, ПЕРЕПЛАТА подготовлена: " + roundOzonReportQuarterMoney_(values.reduce((sum, row) => sum + (Number(row[0]) || 0), 0)));
}

function processOzonReportQuarterFinanceStage_() {
  const state = getOzonReportQuarterStageState_(OZON_REPORT_QUARTER_FINANCE_STATE_KEY);
  if (!state) {
    Logger.log("Нет состояния квартальных начислений");
    return;
  }

  const nextDate = parseOzonReportQuarterDate_(state.nextDate);
  const endDate = parseOzonReportQuarterDate_(state.dateTo);
  if (nextDate.getTime() > endDate.getTime()) {
    finalizeOzonReportQuarterFinanceStage_(state);
    return;
  }

  const chunkEndDate = minOzonReportQuarterDate_(addOzonReportQuarterDays_(nextDate, OZON_REPORT_QUARTER_FINANCE_DAYS_PER_TRIGGER - 1), endDate);
  const chunkFrom = formatOzonReportQuarterDate_(nextDate);
  const chunkTo = formatOzonReportQuarterDate_(chunkEndDate);

  Logger.log("Finance stage chunk: " + chunkFrom + " -> " + chunkTo);
  const accrualMap = fetchOzonReportQuarterAccruals_(chunkFrom, chunkTo);
  addOzonReportQuarterFinanceChunkToSheet_(accrualMap);

  const commonCosts = accrualMap[OZON_REPORT_QUARTER_COMMON_COSTS_KEY] || createOzonReportQuarterAccrualBucket_();
  state.cpoPayment = roundOzonReportQuarterMoney_((Number(state.cpoPayment) || 0) + (Number(commonCosts.cpoPayment) || 0));
  state.commonExtra = roundOzonReportQuarterMoney_((Number(state.commonExtra) || 0) + (Number(commonCosts.commonExtra) || 0));
  state.clicksPayment = roundOzonReportQuarterMoney_((Number(state.clicksPayment) || 0) + (Number(commonCosts.clicksPayment) || 0));
  state.chunksDone = (Number(state.chunksDone) || 0) + 1;

  const nextChunkDate = addOzonReportQuarterDays_(chunkEndDate, 1);
  if (nextChunkDate.getTime() <= endDate.getTime()) {
    state.nextDate = formatOzonReportQuarterDate_(nextChunkDate);
    saveOzonReportQuarterStageState_(OZON_REPORT_QUARTER_FINANCE_STATE_KEY, state);
    scheduleOzonReportQuarterFinanceTrigger_();
    Logger.log("Finance stage chunk готов. Следующий запуск с " + state.nextDate);
    return;
  }

  state.nextDate = formatOzonReportQuarterDate_(addOzonReportQuarterDays_(endDate, 1));
  saveOzonReportQuarterStageState_(OZON_REPORT_QUARTER_FINANCE_STATE_KEY, state);
  finalizeOzonReportQuarterFinanceStage_(state);
}

function addOzonReportQuarterFinanceChunkToSheet_(accrualMap) {
  const sheet = getOzonReportQuarterUnitApiSheet_();
  const lastRow = sheet.getLastRow();
  const headerMap = getOzonReportQuarterHeaderMap_(sheet);
  validateOzonReportQuarterHeaders_(headerMap);
  const rowItems = readOzonReportQuarterRows_(sheet, lastRow, headerMap);
  const dataStartRow = headerMap.__headerRow + 1;
  const columns = [
    { header: "UNIT СУММА", field: "unitSum" },
    { header: "UNIT ШТ", field: "unitQty" },
    { header: "ВОЗНАГРАЖДЕНИЕ", field: "reward" },
    { header: "ЛОГИСТИКА", field: "logistics" },
    { header: "ДОП", field: "extra" },
    { header: "ЗВЕЗДЫ + ЭКВ", field: "starsAndAcquiring" }
  ].map(column => ({
    header: column.header,
    field: column.field,
    col: getOzonReportQuarterColumn_(headerMap, column.header),
    values: sheet.getRange(dataStartRow, getOzonReportQuarterColumn_(headerMap, column.header), rowItems.length, 1).getValues()
  }));

  let matched = 0;
  rowItems.forEach((item, index) => {
    const accrual = accrualMap[item.article] || accrualMap[item.sku] || createOzonReportQuarterAccrualBucket_();
    if (accrual.unitSum || accrual.unitQty || accrual.reward || accrual.logistics || accrual.extra || accrual.starsAndAcquiring) matched++;

    columns.forEach(column => {
      const current = parseOzonReportQuarterMoney_(column.values[index][0]);
      const value = current + (Number(accrual[column.field]) || 0);
      column.values[index][0] = column.field === "unitQty"
        ? Math.round(value)
        : roundOzonReportQuarterMoney_(value);
    });
  });

  columns.forEach(column => {
    if (!column.col) throw new Error("Не найден заголовок для записи: " + column.header);
    sheet.getRange(dataStartRow, column.col, rowItems.length, 1).setValues(column.values);
  });
  Logger.log("Finance stage chunk записан, сопоставлено строк: " + matched);
}

function finalizeOzonReportQuarterFinanceStage_(state) {
  const sheet = getOzonReportQuarterUnitApiSheet_();
  const lastRow = sheet.getLastRow();
  const headerMap = getOzonReportQuarterHeaderMap_(sheet);
  validateOzonReportQuarterHeaders_(headerMap);
  const rowItems = readOzonReportQuarterRows_(sheet, lastRow, headerMap);
  const dataStartRow = headerMap.__headerRow + 1;
  const rowCount = rowItems.length;
  const logisticsCol = getOzonReportQuarterColumn_(headerMap, "ЛОГИСТИКА");
  const overpaymentCol = getOzonReportQuarterColumn_(headerMap, "ПЕРЕПЛАТА");
  const unitSumCol = getOzonReportQuarterColumn_(headerMap, "UNIT СУММА");
  const commonExtraCol = getOzonReportQuarterColumn_(headerMap, "ОЗОН ДОП ВОЗНЯ");
  const cpoCol = getOzonReportQuarterColumn_(headerMap, "ЗАКАЗЫ");

  const logisticsValues = sheet.getRange(dataStartRow, logisticsCol, rowCount, 1).getValues();
  const overpaymentValues = getOzonReportQuarterOverpaymentValues_(sheet, headerMap, rowItems);
  const unitSumValues = sheet.getRange(dataStartRow, unitSumCol, rowCount, 1).getValues();
  const totalUnitSum = unitSumValues.reduce((sum, row) => sum + parseOzonReportQuarterMoney_(row[0]), 0);
  const commonExtraRate = totalUnitSum ? (Number(state.commonExtra) || 0) / totalUnitSum : 0;
  const cpoRate = totalUnitSum ? (Number(state.cpoPayment) || 0) / totalUnitSum : 0;
  writeOzonReportQuarterCommonExtraCoefficient_(sheet, commonExtraRate);
  const commonExtraValues = [];
  const cpoValues = [];
  let totalLogistics = 0;
  let totalOverpayment = 0;
  let totalCommonExtra = 0;
  let totalCpo = 0;

  for (let i = 0; i < rowCount; i++) {
    const overpayment = parseOzonReportQuarterMoney_(overpaymentValues[i] && overpaymentValues[i][0]);
    logisticsValues[i][0] = roundOzonReportQuarterMoney_(parseOzonReportQuarterMoney_(logisticsValues[i][0]) - overpayment);
    overpaymentValues[i][0] = roundOzonReportQuarterMoney_(overpayment);
    commonExtraValues.push([roundOzonReportQuarterMoney_(parseOzonReportQuarterMoney_(unitSumValues[i][0]) * commonExtraRate)]);
    cpoValues.push([roundOzonReportQuarterMoney_(-(parseOzonReportQuarterMoney_(unitSumValues[i][0]) * cpoRate))]);
    totalLogistics += Number(logisticsValues[i][0]) || 0;
    totalOverpayment += Number(overpaymentValues[i][0]) || 0;
    totalCommonExtra += Number(commonExtraValues[i][0]) || 0;
    totalCpo += Number(cpoValues[i][0]) || 0;
  }

  sheet.getRange(dataStartRow, logisticsCol, rowCount, 1).setValues(logisticsValues);
  sheet.getRange(dataStartRow, overpaymentCol, rowCount, 1).setValues(overpaymentValues);
  if (commonExtraCol) sheet.getRange(dataStartRow, commonExtraCol, rowCount, 1).setValues(commonExtraValues);
  if (cpoCol) sheet.getRange(dataStartRow, cpoCol, rowCount, 1).setValues(cpoValues);

  Logger.log("Finance stage завершён. Кусков: " + (Number(state.chunksDone) || 0));
  Logger.log("UNIT СУММА total: " + roundOzonReportQuarterMoney_(totalUnitSum));
  Logger.log("ЛОГИСТИКА после вычета ПЕРЕПЛАТЫ: " + roundOzonReportQuarterMoney_(totalLogistics));
  Logger.log("ПЕРЕПЛАТА: " + roundOzonReportQuarterMoney_(totalOverpayment));
  Logger.log("Оплата за заказ из accrual/by-day: " + roundOzonReportQuarterMoney_(state.cpoPayment || 0) + "; записано в ЗАКАЗЫ: " + roundOzonReportQuarterMoney_(totalCpo));
  Logger.log("Общие расходы без артикула для ОЗОН ДОП ВОЗНЯ: " + roundOzonReportQuarterMoney_(state.commonExtra || 0) + "; процент: " + (commonExtraRate * 100).toFixed(4) + "%; коэффициент: " + (1 + commonExtraRate).toFixed(4) + "; записано: " + roundOzonReportQuarterMoney_(totalCommonExtra));
  Logger.log("Оплата за клик из accrual/by-day для контроля: " + roundOzonReportQuarterMoney_(state.clicksPayment || 0));

  deleteOzonReportQuarterStageState_(OZON_REPORT_QUARTER_FINANCE_STATE_KEY);
  startOzonReportQuarterStorageStage_(state.dateFrom, state.dateTo);
}

function startOzonReportQuarterStorageStage_(dateFrom, dateTo) {
  const periods = buildOzonReportQuarterStoragePeriods_(dateFrom, dateTo);
  saveOzonReportQuarterStageState_(OZON_REPORT_QUARTER_STORAGE_STATE_KEY, {
    dateFrom: dateFrom,
    dateTo: dateTo,
    periods: periods,
    offset: 0
  });
  scheduleOzonReportQuarterStorageTrigger_();
  Logger.log("ХРАНЕНИЕ поставлено в очередь: " + periods.length + " периодов. Первый период будет обработан отдельным запуском");
}

function processOzonReportQuarterStorageStage_() {
  const state = getOzonReportQuarterStageState_(OZON_REPORT_QUARTER_STORAGE_STATE_KEY);
  if (!state) {
    Logger.log("Нет состояния квартального хранения");
    return;
  }

  const periods = Array.isArray(state.periods) ? state.periods : [];
  const offset = Number(state.offset) || 0;
  if (offset >= periods.length) {
    finishOzonReportQuarterStorageStage_(state);
    return;
  }

  const period = periods[offset];
  Logger.log("Storage stage chunk: " + period.from + " -> " + period.to + " (" + (offset + 1) + "/" + periods.length + ")");
  let storageMap = null;
  if (state.pendingStorageMapOffset === offset) {
    storageMap = readOzonReportQuarterPendingStorageMap_();
    Logger.log("Storage stage: найден сохраненный map для записи, offset " + offset);
  } else {
    storageMap = fetchOzonReportQuarterStorageMap_(period.from, period.to);
    saveOzonReportQuarterPendingStorageMap_(storageMap);
    state.pendingStorageMapOffset = offset;
    saveOzonReportQuarterStageState_(OZON_REPORT_QUARTER_STORAGE_STATE_KEY, state);
    scheduleOzonReportQuarterStorageTrigger_();
    Logger.log("Storage stage chunk получен и сохранен. Запись в таблицу будет следующим запуском, offset " + offset);
    return;
  }

  addOzonReportQuarterStorageMapToSheet_(storageMap);
  deleteOzonReportQuarterPendingStorageMap_();
  delete state.pendingStorageMapOffset;

  state.offset = offset + 1;
  saveOzonReportQuarterStageState_(OZON_REPORT_QUARTER_STORAGE_STATE_KEY, state);

  if (state.offset < periods.length) {
    scheduleOzonReportQuarterStorageTrigger_();
    Logger.log("Storage stage chunk готов. Следующий период: " + periods[state.offset].from + " -> " + periods[state.offset].to);
  } else {
    finishOzonReportQuarterStorageStage_(state);
  }
}

function addOzonReportQuarterStorageMapToSheet_(storageMap) {
  const sheet = getOzonReportQuarterUnitApiSheet_();
  const lastRow = sheet.getLastRow();
  const headerMap = getOzonReportQuarterHeaderMap_(sheet);
  validateOzonReportQuarterHeaders_(headerMap);
  const rowItems = readOzonReportQuarterRows_(sheet, lastRow, headerMap);
  const storageCol = getOzonReportQuarterColumn_(headerMap, "ХРАНЕНИЕ");
  const range = sheet.getRange(headerMap.__headerRow + 1, storageCol, rowItems.length, 1);
  const values = range.getValues();
  let matchedStorage = 0;
  let writtenStorage = 0;

  rowItems.forEach((item, index) => {
    const storage = getOzonReportQuarterStorageValue_(storageMap, item);
    if (!storage) return;
    values[index][0] = roundOzonReportQuarterMoney_(parseOzonReportQuarterMoney_(values[index][0]) + storage);
    matchedStorage++;
    writtenStorage += storage;
  });

  for (let offset = 0; offset < values.length; offset += OZON_REPORT_QUARTER_STORAGE_WRITE_BATCH_SIZE) {
    const batch = values.slice(offset, offset + OZON_REPORT_QUARTER_STORAGE_WRITE_BATCH_SIZE);
    sheet.getRange(headerMap.__headerRow + 1 + offset, storageCol, batch.length, 1).setValues(batch);
  }
  Logger.log("ХРАНЕНИЕ chunk записано: строк " + matchedStorage + ", сумма " + roundOzonReportQuarterMoney_(writtenStorage));
}

function finishOzonReportQuarterStorageStage_(state) {
  deleteOzonReportQuarterPendingStorageMap_();
  deleteOzonReportQuarterStageState_(OZON_REPORT_QUARTER_STORAGE_STATE_KEY);
  Logger.log("ХРАНЕНИЕ за квартал завершено");
  if (state && state.storageOnly) {
    Logger.log("Storage-only режим завершён, Performance не запускается");
    return;
  }
  startOzonReportQuarterPerformanceStage_(state.dateFrom, state.dateTo);
}

function startOzonReportQuarterPerformanceStage_(dateFrom, dateTo) {
  const token = getOzonReportQuarterPerfToken_();
  if (!token) {
    Logger.log("Performance API token не получен, КЛИКИ не будут обновлены");
    return;
  }

  const campaigns = getOzonReportQuarterPerfCampaigns_(token);
  if (!campaigns.length) {
    Logger.log("Performance кампании не найдены, колонка КЛИКИ не очищена");
    return;
  }

  const clickCampaigns = filterOzonReportQuarterClickCampaigns_(campaigns);
  if (!clickCampaigns.length) {
    Logger.log("Performance кампании оплаты за клик не найдены, колонка КЛИКИ не очищена");
    return;
  }

  const sheet = getOzonReportQuarterUnitApiSheet_();
  const headerMap = getOzonReportQuarterHeaderMap_(sheet);
  validateOzonReportQuarterHeaders_(headerMap);
  const rowCount = sheet.getLastRow() - headerMap.__headerRow;
  clearOzonReportQuarterClicksColumn_(sheet, headerMap, rowCount);
  startOzonReportQuarterPerformanceProcessing_(clickCampaigns, dateFrom, dateTo);
}

function buildOzonReportQuarterStoragePeriods_(dateFrom, dateTo) {
  const periods = [];
  let current = parseOzonReportQuarterDate_(dateFrom);
  const end = parseOzonReportQuarterDate_(dateTo);

  while (current.getTime() <= end.getTime()) {
    const periodEnd = minOzonReportQuarterDate_(addOzonReportQuarterMonthsMinusOneDay_(current), end);
    periods.push({
      from: formatOzonReportQuarterDate_(current),
      to: formatOzonReportQuarterDate_(periodEnd)
    });
    current = addOzonReportQuarterDays_(periodEnd, 1);
  }

  return periods;
}

function scheduleOzonReportQuarterFinanceTrigger_() {
  clearOzonReportQuarterFinanceTriggers_();
  ScriptApp.newTrigger(OZON_REPORT_QUARTER_FINANCE_TRIGGER_HANDLER)
    .timeBased()
    .after(OZON_REPORT_QUARTER_STAGE_TRIGGER_GAP_MS)
    .create();
  Logger.log("Finance stage trigger создан");
}

function scheduleOzonReportQuarterStorageTrigger_() {
  clearOzonReportQuarterStorageTriggers_();
  ScriptApp.newTrigger(OZON_REPORT_QUARTER_STORAGE_TRIGGER_HANDLER)
    .timeBased()
    .after(OZON_REPORT_QUARTER_STAGE_TRIGGER_GAP_MS)
    .create();
  Logger.log("Storage stage trigger создан");
}

function clearOzonReportQuarterFinanceTriggers_() {
  clearOzonReportQuarterTriggersByHandler_(OZON_REPORT_QUARTER_FINANCE_TRIGGER_HANDLER);
}

function clearOzonReportQuarterStorageTriggers_() {
  clearOzonReportQuarterTriggersByHandler_(OZON_REPORT_QUARTER_STORAGE_TRIGGER_HANDLER);
}

function clearOzonReportQuarterTriggersByHandler_(handler) {
  ScriptApp.getProjectTriggers().forEach(trigger => {
    if (trigger.getHandlerFunction() === handler) ScriptApp.deleteTrigger(trigger);
  });
}

function countOzonReportQuarterTriggersByHandler_(handler) {
  return ScriptApp.getProjectTriggers().filter(trigger => trigger.getHandlerFunction() === handler).length;
}

function saveOzonReportQuarterStageState_(key, state) {
  PropertiesService.getScriptProperties().setProperty(key, JSON.stringify(state));
}

function saveOzonReportQuarterPendingStorageMap_(storageMap) {
  deleteOzonReportQuarterPendingStorageMap_();
  const props = PropertiesService.getScriptProperties();
  const raw = JSON.stringify(storageMap || {});
  const chunks = [];
  for (let offset = 0; offset < raw.length; offset += OZON_REPORT_QUARTER_STORAGE_MAP_CHUNK_SIZE) {
    chunks.push(raw.slice(offset, offset + OZON_REPORT_QUARTER_STORAGE_MAP_CHUNK_SIZE));
  }
  chunks.forEach((chunk, index) => {
    props.setProperty(OZON_REPORT_QUARTER_STORAGE_MAP_CHUNK_PREFIX + index, chunk);
  });
  props.setProperty(OZON_REPORT_QUARTER_STORAGE_MAP_CHUNK_COUNT_KEY, String(chunks.length));
  Logger.log("Storage map сохранен во временные свойства: chunks " + chunks.length + ", chars " + raw.length);
}

function readOzonReportQuarterPendingStorageMap_() {
  const props = PropertiesService.getScriptProperties();
  const count = Number(props.getProperty(OZON_REPORT_QUARTER_STORAGE_MAP_CHUNK_COUNT_KEY)) || 0;
  if (!count) throw new Error("Нет сохраненного storage map для записи");
  let raw = "";
  for (let i = 0; i < count; i++) {
    raw += props.getProperty(OZON_REPORT_QUARTER_STORAGE_MAP_CHUNK_PREFIX + i) || "";
  }
  return JSON.parse(raw || "{}");
}

function deleteOzonReportQuarterPendingStorageMap_() {
  const props = PropertiesService.getScriptProperties();
  const count = Number(props.getProperty(OZON_REPORT_QUARTER_STORAGE_MAP_CHUNK_COUNT_KEY)) || 0;
  for (let i = 0; i < count; i++) {
    props.deleteProperty(OZON_REPORT_QUARTER_STORAGE_MAP_CHUNK_PREFIX + i);
  }
  props.deleteProperty(OZON_REPORT_QUARTER_STORAGE_MAP_CHUNK_COUNT_KEY);
}

function getOzonReportQuarterStageState_(key, cleanupInvalid) {
  const raw = PropertiesService.getScriptProperties().getProperty(key);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (e) {
    if (cleanupInvalid !== false) {
      deleteOzonReportQuarterStageState_(key);
      Logger.log("Некорректное состояние " + key + " очищено");
    } else {
      Logger.log("Состояние " + key + " содержит некорректный JSON");
    }
    return null;
  }
}

function deleteOzonReportQuarterStageState_(key) {
  PropertiesService.getScriptProperties().deleteProperty(key);
}

function addOzonReportQuarterDays_(date, days) {
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate() + days));
}

function addOzonReportQuarterMonthsMinusOneDay_(date) {
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate() - 1));
}

function minOzonReportQuarterDate_(a, b) {
  return a.getTime() <= b.getTime() ? a : b;
}

function setOzonReportQuarterPerformanceCredentials(clientId, clientSecret) {
  if (!clientId || !clientSecret) throw new Error("Передайте clientId и clientSecret");
  PropertiesService.getScriptProperties().setProperties({
    OZON_PERFORMANCE_CLIENT_ID: clientId,
    OZON_PERFORMANCE_CLIENT_SECRET: clientSecret
  });
  Logger.log("Performance credentials сохранены в Script Properties");
}

function resumeOzonReportQuarterPerformance() {
  return withOzonReportQuarterScriptLock_("resumeOzonReportQuarterPerformance", function() {
  clearOzonReportQuarterPerfTriggers_();

  const state = getOzonReportQuarterPerformanceState_();
  if (!state) {
    Logger.log("Нет сохраненного состояния Performance-обработки");
    return;
  }

  const sheet = getOzonReportQuarterUnitApiSheet_();
  const lastRow = sheet.getLastRow();
  const headerMap = getOzonReportQuarterHeaderMap_(sheet);
  validateOzonReportQuarterHeaders_(headerMap);

  if (lastRow <= headerMap.__headerRow) {
    clearOzonReportQuarterPerformanceState();
    Logger.log("Нет строк для обработки ниже строки заголовков " + headerMap.__headerRow);
    return;
  }

  const token = getOzonReportQuarterPerfToken_();
  if (!token) {
    scheduleOzonReportQuarterPerformanceTrigger_();
    Logger.log("Performance API token не получен, следующий trigger создан для повторной попытки");
    return;
  }

  const rowItems = readOzonReportQuarterRows_(sheet, lastRow, headerMap);
  const campaignIds = Array.isArray(state.campaignIds) ? state.campaignIds : [];
  const periods = getOzonReportQuarterPerformancePeriodsFromState_(state);
  const periodOffset = Number(state.periodOffset) || 0;
  const period = periods[periodOffset] || { from: state.dateFrom, to: state.dateTo };
  processOzonReportQuarterPerformanceBatch_(sheet, headerMap, rowItems, token, campaignIds, periods, periodOffset, period.from, period.to, Number(state.offset) || 0, Number(state.retryCount) || 0, state.pendingOverviewReportUuid || "");
  });
}

function clearOzonReportQuarterPerformanceState() {
  clearOzonReportQuarterPerfTriggers_();
  deleteOzonReportQuarterPerformanceState_();
  Logger.log("Состояние Performance-обработки очищено");
}

function stopOzonReportQuarterPerformanceTriggers() {
  return withOzonReportQuarterScriptLock_("stopOzonReportQuarterPerformanceTriggers", function() {
    const beforeCount = countOzonReportQuarterPerfTriggers_();
    clearOzonReportQuarterPerfTriggers_();
    deleteOzonReportQuarterPerformanceState_();
    const afterCount = countOzonReportQuarterPerfTriggers_();
    Logger.log("Performance обработка остановлена. Удалено триггеров: " + beforeCount + ". Активно после остановки: " + afterCount);
  });
}

function checkOzonReportQuarterPerformanceState() {
  const state = getOzonReportQuarterPerformanceState_(false);
  const triggerCount = countOzonReportQuarterPerfTriggers_();

  Logger.log("Performance triggers active: " + triggerCount);
  if (!state) {
    Logger.log("Performance state: empty");
    return;
  }

  const total = Number(state.total) || (Array.isArray(state.campaignIds) ? state.campaignIds.length : 0);
  Logger.log("Performance state offset: " + (Number(state.offset) || 0) + " / " + total);
  Logger.log("Performance state retry count: " + (Number(state.retryCount) || 0));
  Logger.log("Performance state period: " + state.dateFrom + " -> " + state.dateTo);
  if (Array.isArray(state.periods)) {
    Logger.log("Performance state date chunk: " + ((Number(state.periodOffset) || 0) + 1) + " / " + state.periods.length);
  }
  Logger.log("Performance state campaign IDs: " + (Array.isArray(state.campaignIds) ? state.campaignIds.length : 0));
  if (Array.isArray(state.campaignIds)) {
    const offset = Number(state.offset) || 0;
    const batch = state.campaignIds.slice(offset, Math.min(offset + OZON_REPORT_QUARTER_CAMPAIGNS_PER_TRIGGER, state.campaignIds.length));
    Logger.log("Performance state current batch IDs: " + batch.join(", "));
  }
  Logger.log("Performance state pending UUID: " + (state.pendingOverviewReportUuid || "нет"));
}

function withOzonReportQuarterScriptLock_(label, callback) {
  const lock = LockService.getUserLock();
  if (!lock.tryLock(30000)) {
    throw new Error("Не удалось получить квартальный lock для " + label + ". Другой квартальный запуск еще выполняется");
  }

  try {
    return callback();
  } finally {
    lock.releaseLock();
  }
}

function startOzonReportQuarterPerformanceProcessing_(campaigns, dateFrom, dateTo) {
  const campaignIds = campaigns.map(campaign => String(campaign.id || campaign)).filter(Boolean);
  const periods = buildOzonReportQuarterPerformancePeriods_(dateFrom, dateTo);

  if (!campaignIds.length) {
    deleteOzonReportQuarterPerformanceState_();
    Logger.log("Performance кампании не найдены");
    return;
  }

  saveOzonReportQuarterPerformanceState_({
    offset: 0,
    total: campaignIds.length,
    campaignIds: campaignIds,
    dateFrom: dateFrom,
    dateTo: dateTo,
    periods: periods,
    periodOffset: 0,
    retryCount: 0
  });
  scheduleOzonReportQuarterPerformanceTrigger_();
  Logger.log("Performance обработка запущена: " + campaignIds.length + " кампаний, периодов дат: " + periods.length + ", первый trigger создан");
}

function processOzonReportQuarterPerformanceBatch_(sheet, headerMap, rowItems, token, campaignIds, periods, periodOffset, dateFrom, dateTo, offset, retryCount, pendingOverviewReportUuid) {
  if (!campaignIds.length) {
    deleteOzonReportQuarterPerformanceState_();
    Logger.log("Performance кампании не найдены");
    return;
  }

  if (offset >= campaignIds.length) {
    finishOrScheduleNextOzonReportQuarterPerformancePeriod_(campaignIds, periods, periodOffset, dateFrom, dateTo);
    return;
  }

  const nextOffset = Math.min(offset + OZON_REPORT_QUARTER_CAMPAIGNS_PER_TRIGGER, campaignIds.length);
  const batch = campaignIds.slice(offset, nextOffset);
  Logger.log("Performance date chunk: " + (periodOffset + 1) + "/" + periods.length + " (" + dateFrom + " -> " + dateTo + ")");
  Logger.log("Performance campaign batch: " + (offset + 1) + "-" + nextOffset + " / " + campaignIds.length);

  const overviewResult = fetchOzonReportQuarterOverviewStats_(token, batch, dateFrom, dateTo, pendingOverviewReportUuid);
  if (overviewResult.stats === null) {
    const nextRetryCount = retryCount + 1;
    if (nextRetryCount >= OZON_REPORT_QUARTER_PERF_REPORT_MAX_RETRIES) {
      Logger.log("Performance пачка пропущена после " + nextRetryCount + " попыток: offset " + offset + ", UUID " + (overviewResult.pendingOverviewReportUuid || pendingOverviewReportUuid || "нет"));
      if (nextOffset < campaignIds.length) {
        saveOzonReportQuarterPerformanceState_({
          offset: nextOffset,
          total: campaignIds.length,
          campaignIds: campaignIds,
          dateFrom: periods[0].from,
          dateTo: periods[periods.length - 1].to,
          periods: periods,
          periodOffset: periodOffset,
          retryCount: 0,
          pendingOverviewReportUuid: ""
        });
        scheduleOzonReportQuarterPerformanceTrigger_();
          Logger.log("Следующий Performance trigger запланирован с offset " + nextOffset);
      } else {
        finishOrScheduleNextOzonReportQuarterPerformancePeriod_(campaignIds, periods, periodOffset, dateFrom, dateTo);
      }
      return;
    }

    saveOzonReportQuarterPerformanceState_({
      offset: offset,
      total: campaignIds.length,
      campaignIds: campaignIds,
      dateFrom: periods[0].from,
      dateTo: periods[periods.length - 1].to,
      periods: periods,
      periodOffset: periodOffset,
      retryCount: nextRetryCount,
      pendingOverviewReportUuid: overviewResult.pendingOverviewReportUuid || pendingOverviewReportUuid || ""
    });
    scheduleOzonReportQuarterPerformanceTrigger_();
    Logger.log("Performance пачка не готова, offset " + offset + " будет повторен следующим триггером, попытка " + nextRetryCount);
    return;
  }

  writeOzonReportQuarterAdClicksBatch_(sheet, headerMap, rowItems, overviewResult.stats);

  if (nextOffset < campaignIds.length) {
    saveOzonReportQuarterPerformanceState_({
      offset: nextOffset,
      total: campaignIds.length,
      campaignIds: campaignIds,
      dateFrom: periods[0].from,
      dateTo: periods[periods.length - 1].to,
      periods: periods,
      periodOffset: periodOffset,
      retryCount: 0
    });
    scheduleOzonReportQuarterPerformanceTrigger_();
    Logger.log("Следующий Performance trigger запланирован с offset " + nextOffset);
  } else {
    finishOrScheduleNextOzonReportQuarterPerformancePeriod_(campaignIds, periods, periodOffset, dateFrom, dateTo);
  }
}

function finishOrScheduleNextOzonReportQuarterPerformancePeriod_(campaignIds, periods, periodOffset, dateFrom, dateTo) {
  const nextPeriodOffset = periodOffset + 1;
  if (nextPeriodOffset < periods.length) {
    saveOzonReportQuarterPerformanceState_({
      offset: 0,
      total: campaignIds.length,
      campaignIds: campaignIds,
      dateFrom: periods[0].from,
      dateTo: periods[periods.length - 1].to,
      periods: periods,
      periodOffset: nextPeriodOffset,
      retryCount: 0,
      pendingOverviewReportUuid: ""
    });
    scheduleOzonReportQuarterPerformanceTrigger_();
    Logger.log("Performance период обработан: " + dateFrom + " -> " + dateTo + ". Следующий период: " + periods[nextPeriodOffset].from + " -> " + periods[nextPeriodOffset].to);
    return;
  }

  deleteOzonReportQuarterPerformanceState_();
  Logger.log("Performance кампании обработаны полностью по всем периодам: " + campaignIds.length + ", периодов: " + periods.length);
}

function getOzonReportQuarterPerformancePeriodsFromState_(state) {
  if (Array.isArray(state.periods) && state.periods.length) return state.periods;
  return buildOzonReportQuarterPerformancePeriods_(state.dateFrom, state.dateTo);
}

function buildOzonReportQuarterPerformancePeriods_(dateFrom, dateTo) {
  const periods = [];
  let current = parseOzonReportQuarterDate_(dateFrom);
  const end = parseOzonReportQuarterDate_(dateTo);

  while (current.getTime() <= end.getTime()) {
    const periodEnd = minOzonReportQuarterDate_(addOzonReportQuarterDays_(current, OZON_REPORT_QUARTER_PERF_MAX_PERIOD_DAYS - 1), end);
    periods.push({
      from: formatOzonReportQuarterDate_(current),
      to: formatOzonReportQuarterDate_(periodEnd)
    });
    current = addOzonReportQuarterDays_(periodEnd, 1);
  }

  return periods;
}

function scheduleOzonReportQuarterPerformanceTrigger_() {
  clearOzonReportQuarterPerfTriggers_();
  ScriptApp.newTrigger(OZON_REPORT_QUARTER_PERF_TRIGGER_HANDLER)
    .timeBased()
    .after(OZON_REPORT_QUARTER_PERF_TRIGGER_GAP_MS)
    .create();
  Logger.log("Performance triggers active after create: " + countOzonReportQuarterPerfTriggers_());
}

function clearOzonReportQuarterPerfTriggers_() {
  ScriptApp.getProjectTriggers().forEach(trigger => {
    if (trigger.getHandlerFunction() === OZON_REPORT_QUARTER_PERF_TRIGGER_HANDLER) {
      ScriptApp.deleteTrigger(trigger);
    }
  });
}

function countOzonReportQuarterPerfTriggers_() {
  return ScriptApp.getProjectTriggers().filter(trigger => trigger.getHandlerFunction() === OZON_REPORT_QUARTER_PERF_TRIGGER_HANDLER).length;
}

function saveOzonReportQuarterPerformanceState_(state) {
  PropertiesService.getScriptProperties().setProperty(OZON_REPORT_QUARTER_PERF_STATE_KEY, JSON.stringify(state));
}

function getOzonReportQuarterPerformanceState_(cleanupInvalid) {
  const raw = PropertiesService.getScriptProperties().getProperty(OZON_REPORT_QUARTER_PERF_STATE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (e) {
    if (cleanupInvalid !== false) {
      deleteOzonReportQuarterPerformanceState_();
      Logger.log("Некорректное состояние Performance-обработки очищено");
    } else {
      Logger.log("Performance state содержит некорректный JSON");
    }
    return null;
  }
}

function deleteOzonReportQuarterPerformanceState_() {
  PropertiesService.getScriptProperties().deleteProperty(OZON_REPORT_QUARTER_PERF_STATE_KEY);
}

function getOzonReportQuarterUnitApiSheet_() {
  const spreadsheet = SpreadsheetApp.openById(OZON_REPORT_QUARTER_SPREADSHEET_ID);
  const sheets = spreadsheet.getSheets();
  let sheet = null;
  for (let i = 0; i < sheets.length; i++) {
    if (sheets[i].getSheetId && sheets[i].getSheetId() === OZON_REPORT_QUARTER_UNIT_API_SHEET_ID) {
      sheet = sheets[i];
      break;
    }
  }
  if (!sheet) sheet = spreadsheet.getSheetByName(OZON_REPORT_QUARTER_UNIT_API_SHEET_NAME);
  if (!sheet) throw new Error("Не найден лист " + OZON_REPORT_QUARTER_UNIT_API_SHEET_NAME + " / gid " + OZON_REPORT_QUARTER_UNIT_API_SHEET_ID);
  return sheet;
}

function getOzonReportQuarterHeaderMap_(sheet) {
  const maxRows = Math.min(OZON_REPORT_QUARTER_HEADER_SCAN_ROWS, sheet.getLastRow());
  const rows = sheet.getRange(1, 1, maxRows, sheet.getLastColumn()).getDisplayValues();
  let bestRowIndex = 0;
  let bestScore = -1;

  rows.forEach((headers, rowIndex) => {
    const normalized = headers.map(normalizeOzonReportQuarterHeader_);
    const score = OZON_REPORT_QUARTER_REQUIRED_HEADERS.filter(header => normalized.indexOf(normalizeOzonReportQuarterHeader_(header)) !== -1).length;
    if (score > bestScore) {
      bestScore = score;
      bestRowIndex = rowIndex;
    }
  });

  const headers = rows[bestRowIndex];
  const map = {};
  headers.forEach((header, index) => {
    const key = normalizeOzonReportQuarterHeader_(header);
    if (key && !map[key]) map[key] = index + 1;
  });
  map.__headerRow = bestRowIndex + 1;
  Logger.log("Строка заголовков UNIT API квартал: " + map.__headerRow);
  return map;
}

function validateOzonReportQuarterHeaders_(headerMap) {
  const missing = OZON_REPORT_QUARTER_REQUIRED_HEADERS.filter(header => !headerMap[normalizeOzonReportQuarterHeader_(header)]);
  if (missing.length) throw new Error("В UNIT API квартал не найдены заголовки: " + missing.join(", "));
}

function getOzonReportQuarterColumn_(headerMap, header) {
  if (normalizeOzonReportQuarterHeader_(header) === normalizeOzonReportQuarterHeader_("ОЗОН ДОП ВОЗНЯ")) {
    return headerMap[normalizeOzonReportQuarterHeader_(header)] || OZON_REPORT_QUARTER_COMMON_EXTRA_COLUMN;
  }
  return headerMap[normalizeOzonReportQuarterHeader_(header)] || 0;
}

function writeOzonReportQuarterCommonExtraCoefficient_(sheet, commonExtraRate) {
  const coefficient = Math.round((1 + (Number(commonExtraRate) || 0)) * 10000) / 10000;
  sheet.getRange(OZON_REPORT_QUARTER_COMMON_EXTRA_COEFFICIENT_CELL)
    .setValue(coefficient)
    .setNumberFormat("0.0000");
  Logger.log("Коэффициент ОЗОН ДОП ВОЗНЯ записан в " + OZON_REPORT_QUARTER_COMMON_EXTRA_COEFFICIENT_CELL + ": " + coefficient.toFixed(4));
}

function readOzonReportQuarterRows_(sheet, lastRow, headerMap) {
  const articleCol = getOzonReportQuarterColumn_(headerMap, "Артикул");
  const skuCol = getOzonReportQuarterColumn_(headerMap, "СКУ OZ");
  const dataStartRow = headerMap.__headerRow + 1;
  const rowCount = lastRow - headerMap.__headerRow;
  const articles = sheet.getRange(dataStartRow, articleCol, rowCount, 1).getValues().flat();
  const skus = sheet.getRange(dataStartRow, skuCol, rowCount, 1).getValues().flat();
  return articles.map((article, index) => ({
    article: normalizeOzonReportQuarterKey_(article),
    sku: normalizeOzonReportQuarterKey_(skus[index])
  }));
}

function fetchOzonReportQuarterAccruals_(dateFrom, dateTo) {
  const result = {};
  const unknownTypes = {};
  let loaded = 0;
  let days = 0;
  let lastRequestTime = Date.now() - 1000 / RPS();
  let current = parseOzonReportQuarterDate_(dateFrom);
  const end = parseOzonReportQuarterDate_(dateTo);

  while (current.getTime() <= end.getTime()) {
    const day = formatOzonReportQuarterDate_(current);
    let lastId = "";
    let dayLoaded = 0;
    let rateLimitRetries = 0;
    const seenLastIds = {};
    Logger.log("Finance accrual/by-day: " + day);

    while (true) {
      lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

      const response = retryFetch(OzonReportQuarterFinanceAccrualByDayURL_(), {
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
        aggregateOzonReportQuarterByDayAccrual_(result, unknownTypes, accrual);
      });

      loaded += accruals.length;
      dayLoaded += accruals.length;

      const nextLastId = normalizeOzonReportQuarterKey_(json.last_id || "");
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
  enrichOzonReportQuarterAccrualsWithOfferIds_(result);
  Logger.log("Finance accrual keys: " + Object.keys(result).length);
  logOzonReportQuarterUnknownTypes_(unknownTypes);
  return result;
}

function OzonReportQuarterFinanceAccrualByDayURL_() {
  return "https://api-seller.ozon.ru/v1/finance/accrual/by-day";
}

function aggregateOzonReportQuarterByDayAccrual_(result, unknownTypes, accrual) {
  const posting = accrual && accrual.posting ? accrual.posting : {};
  const products = Array.isArray(posting.products) ? posting.products : [];

  products.forEach(product => {
    const sku = normalizeOzonReportQuarterKey_(product && product.sku);
    if (!sku) return;

    const commission = product.commission || {};
    const saleAmount = parseOzonReportQuarterMoney_(commission.sale_amount);
    const sellerPrice = parseOzonReportQuarterMoney_(commission.seller_price);
    addOzonReportQuarterSkuAmount_(result, unknownTypes, sku, "commission.sale_amount", "unitSum", saleAmount);
    addOzonReportQuarterSkuAmount_(result, unknownTypes, sku, "commission.unit_qty", "unitQty", calculateOzonReportQuarterUnitQty_(saleAmount, sellerPrice, product));
    addOzonReportQuarterSkuAmount_(result, unknownTypes, sku, "commission.commission", "reward", parseOzonReportQuarterMoney_(commission.commission));

    const delivery = product.delivery || {};
    const services = Array.isArray(delivery.services) ? delivery.services : [];
    services.forEach(service => {
      const typeId = normalizeOzonReportQuarterKey_(service && service.type_id);
      const amount = parseOzonReportQuarterMoney_(service && service.accrued);
      if (typeId === "32" && amount > 0) {
        addOzonReportQuarterSkuAmount_(result, unknownTypes, sku, "delivery:32:extra_reversal", "extra", amount);
        return;
      }

      const group = getOzonReportQuarterDeliveryFeeGroup_(typeId, amount);
      addOzonReportQuarterSkuAmount_(result, unknownTypes, sku, "delivery:" + typeId, group, amount);
    });
  });

  const itemFees = accrual && accrual.item_fees && Array.isArray(accrual.item_fees.fees)
    ? accrual.item_fees.fees
    : [];
  itemFees.forEach(itemFee => {
    const sku = normalizeOzonReportQuarterKey_(itemFee && itemFee.sku);
    if (!sku) return;

    const fees = Array.isArray(itemFee.fees) ? itemFee.fees : [];
    fees.forEach(fee => {
      const typeId = normalizeOzonReportQuarterKey_(fee && fee.type_id);
      const amount = parseOzonReportQuarterMoney_(fee && fee.accrued);
      const group = getOzonReportQuarterItemFeeGroup_(typeId);
      addOzonReportQuarterSkuAmount_(result, unknownTypes, sku, "item_fee:" + typeId, group, amount);
    });
  });

  aggregateOzonReportQuarterByDayNonItemFee_(result, unknownTypes, accrual && accrual.non_item_fee);
}

function addOzonReportQuarterSkuAmount_(result, unknownTypes, sku, typeName, group, amount) {
  if (!amount) return;
  if (!group) {
    unknownTypes[typeName] = (unknownTypes[typeName] || 0) + amount;
    return;
  }

  if (!result[sku]) result[sku] = createOzonReportQuarterAccrualBucket_();
  result[sku][group] += amount;
}

function calculateOzonReportQuarterUnitQty_(saleAmount, sellerPrice, product) {
  if (!shouldCountOzonReportQuarterUnitQty_(saleAmount, sellerPrice, product)) return 0;

  const quantity = Math.abs(saleAmount / sellerPrice);
  if (!isFinite(quantity) || quantity <= 0) return 0;

  return Math.round(quantity);
}

function shouldCountOzonReportQuarterUnitQty_(saleAmount, sellerPrice, product) {
  if (saleAmount > 0 && sellerPrice > 0) return true;
  if (!(saleAmount < 0) || !(sellerPrice < 0)) return false;

  const services = product && product.delivery && Array.isArray(product.delivery.services)
    ? product.delivery.services
    : [];
  return services.some(service => parseOzonReportQuarterMoney_(service && service.accrued) > 0);
}

function getOzonReportQuarterItemFeeGroup_(typeId) {
  if (["1", "3", "51", "74"].indexOf(typeId) !== -1) return "starsAndAcquiring";
  if (typeId) return "extra";
  return "";
}

function getOzonReportQuarterDeliveryFeeGroup_(typeId) {
  if (typeId === "32") return "logistics";
  if (typeId) return "extra";
  return "";
}

function aggregateOzonReportQuarterByDayNonItemFee_(result, unknownTypes, nonItemFee) {
  if (!nonItemFee || nonItemFee.type_id === null || nonItemFee.type_id === undefined) return;

  const typeId = normalizeOzonReportQuarterKey_(nonItemFee.type_id);
  const amount = parseOzonReportQuarterMoney_(nonItemFee.accrued);
  if (!amount) return;

  if (!result[OZON_REPORT_QUARTER_COMMON_COSTS_KEY]) result[OZON_REPORT_QUARTER_COMMON_COSTS_KEY] = createOzonReportQuarterAccrualBucket_();
  const common = result[OZON_REPORT_QUARTER_COMMON_COSTS_KEY];

  if (typeId === "41") {
    common.clicksPayment += amount;
  } else if (typeId === "54") {
    common.cpoPayment += amount;
  } else {
    common.commonExtra += amount;
  }

}

function enrichOzonReportQuarterAccrualsWithOfferIds_(result) {
  const skuKeys = Object.keys(result).filter(key => key !== OZON_REPORT_QUARTER_COMMON_COSTS_KEY && /^\d+$/.test(key));
  if (!skuKeys.length) return;

  const skuToOffer = {};
  let lastRequestTime = Date.now() - 1000 / RPS();

  for (let offset = 0; offset < skuKeys.length; offset += OZON_REPORT_QUARTER_PRODUCT_INFO_BATCH_SIZE) {
    const batch = skuKeys.slice(offset, offset + OZON_REPORT_QUARTER_PRODUCT_INFO_BATCH_SIZE);
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

    const response = retryFetch(OzonReportQuarterProductInfoListURL_(), {
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
    items.forEach(item => addOzonReportQuarterProductInfoSkuAliases_(skuToOffer, item));
  }

  let merged = 0;
  Object.keys(skuToOffer).forEach(sku => {
    const offerId = skuToOffer[sku];
    if (!offerId || !result[sku]) return;
    if (!result[offerId]) result[offerId] = createOzonReportQuarterAccrualBucket_();
    mergeOzonReportQuarterAccrualBucket_(result[offerId], result[sku]);
    merged++;
  });

  Logger.log("Product info SKU -> offer_id сопоставлено: " + merged + " / " + skuKeys.length);
}

function OzonReportQuarterProductInfoListURL_() {
  return "https://api-seller.ozon.ru/v3/product/info/list";
}

function fetchOzonReportQuarterStorageMap_(dateFrom, dateTo) {
  Logger.log("=== OZON UNIT API квартал: хранение / стоимость размещения ===");
  Logger.log("Период хранения: " + dateFrom + " -> " + dateTo);

  const reportCode = createOzonReportQuarterPlacementByProductsReport_(dateFrom, dateTo);
  if (!reportCode) return createOzonReportQuarterStorageMap_();

  const fileUrl = waitOzonReportQuarterFileUrl_(reportCode);
  if (!fileUrl) return createOzonReportQuarterStorageMap_();

  const storageResult = downloadAndBuildOzonReportQuarterStorageMap_(fileUrl);
  const storageMap = storageResult.storageMap || createOzonReportQuarterStorageMap_();
  if (!storageResult.rowCount && !Object.keys(storageMap.bySku).length && !Object.keys(storageMap.byOfferId).length) {
    Logger.log("Отчёт хранения скачан, но строки не распознаны");
    return storageMap;
  }

  Logger.log("Хранение: строк отчёта " + storageResult.rowCount);
  Logger.log("Хранение: SKU " + Object.keys(storageMap.bySku).length + ", артикулов " + Object.keys(storageMap.byOfferId).length);
  Logger.log("Хранение: сумма отчёта " + roundOzonReportQuarterMoney_(sumOzonReportQuarterStorageMap_(storageMap)));
  return storageMap;
}

function createOzonReportQuarterStorageMap_() {
  return { bySku: {}, byOfferId: {} };
}

function createOzonReportQuarterPlacementByProductsReport_(dateFrom, dateTo) {
  const response = retryFetch(OzonReportQuarterPlacementByProductsReportURL_(), {
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

function waitOzonReportQuarterFileUrl_(reportCode) {
  const startedAt = Date.now();
  let attempt = 1;

  while (Date.now() - startedAt < OZON_REPORT_QUARTER_STORAGE_REPORT_MAX_WAIT_MS) {
    const info = getOzonReportQuarterReportInfo_(reportCode);
    if (!info) return "";

    const status = normalizeOzonReportQuarterText_(info.status || info.state || "");
    const fileUrl = info.file || info.file_url || info.download_url || info.url || "";
    Logger.log("Отчёт хранения " + reportCode + ": попытка " + attempt + ", статус " + (status || "без статуса"));

    if (fileUrl) return fileUrl;
    if (status === "error" || status === "failed") {
      Logger.log("Ozon вернул ошибку формирования отчёта хранения: " + JSON.stringify(info).slice(0, 1000));
      return "";
    }

    Utilities.sleep(OZON_REPORT_QUARTER_STORAGE_REPORT_POLL_MS);
    attempt++;
  }

  Logger.log("Истекло время ожидания отчёта хранения");
  return "";
}

function getOzonReportQuarterReportInfo_(reportCode) {
  const response = retryFetch(OzonReportQuarterReportInfoURL_(), {
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

function downloadAndBuildOzonReportQuarterStorageMap_(fileUrl) {
  const response = UrlFetchApp.fetch(fileUrl, { muteHttpExceptions: true });
  const code = response.getResponseCode();
  if (code !== 200) {
    Logger.log("Скачивание отчёта хранения HTTP " + code + ": " + response.getContentText().slice(0, 1000));
    return { storageMap: createOzonReportQuarterStorageMap_(), rowCount: 0 };
  }

  const blob = response.getBlob();
  const bytes = blob.getBytes();
  if (bytes.length > 1 && bytes[0] === 0x50 && bytes[1] === 0x4B) {
    Logger.log("Формат отчёта хранения: XLSX");
    try {
      const rows = parseOzonReportQuarterXlsxRows_(blob);
      return {
        storageMap: buildOzonReportQuarterStorageMapFromRows_(rows),
        rowCount: rows.length
      };
    } catch (error) {
      Logger.log("XLSX слишком большой для ZIP-парсера Apps Script, пробую конвертацию через Google Sheets: " + error);
      return buildOzonReportQuarterStorageMapViaGoogleSheets_(blob);
    }
  }

  Logger.log("Формат отчёта хранения: CSV/TSV");
  const rows = parseOzonReportQuarterDelimitedRows_(response.getContentText("UTF-8"));
  return {
    storageMap: buildOzonReportQuarterStorageMapFromRows_(rows),
    rowCount: rows.length
  };
}

function buildOzonReportQuarterStorageMapFromRows_(rows) {
  const storageMap = createOzonReportQuarterStorageMap_();
  if (!rows.length) return storageMap;

  const headerIndex = findOzonReportQuarterStorageHeaderRowIndex_(rows);
  if (headerIndex < 0) {
    Logger.log("Не нашёл строку заголовков в отчёте хранения: " + JSON.stringify(rows.slice(0, 5)).slice(0, 1000));
    return storageMap;
  }

  const headers = rows[headerIndex].map(normalizeOzonReportQuarterHeader_);
  const skuIndex = findOzonReportQuarterHeaderIndex_(headers, ["sku"]);
  const offerIndex = findOzonReportQuarterHeaderIndex_(headers, ["артикул", "offer"]);
  const amountIndex = findOzonReportQuarterPreferredHeaderIndex_(headers,
    ["стоимость размещения", "начисленная стоимость размещения", "размещ", "хран", "storage", "placement"],
    ["начислено", "сумма", "итого"]
  );

  Logger.log("Колонки хранения: sku=" + skuIndex + ", артикул=" + offerIndex + ", сумма=" + amountIndex);
  if (amountIndex < 0 || (skuIndex < 0 && offerIndex < 0)) return storageMap;

  for (let i = headerIndex + 1; i < rows.length; i++) {
    const row = rows[i] || [];
    const sku = skuIndex >= 0 ? normalizeOzonReportQuarterKey_(row[skuIndex]) : "";
    const offerId = offerIndex >= 0 ? normalizeOzonReportQuarterKey_(row[offerIndex]) : "";
    const amount = Math.abs(parseOzonReportQuarterMoney_(row[amountIndex]));
    if (!amount) continue;

    if (sku) storageMap.bySku[sku] = (storageMap.bySku[sku] || 0) + amount;
    if (offerId) storageMap.byOfferId[offerId] = (storageMap.byOfferId[offerId] || 0) + amount;
  }

  return storageMap;
}

function buildOzonReportQuarterStorageMapViaGoogleSheets_(blob) {
  const tempName = OZON_REPORT_QUARTER_STORAGE_TEMP_SHEET_NAME + "_" + Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyyMMdd_HHmmss");
  const xlsxBlob = blob.copyBlob()
    .setName(tempName + ".xlsx")
    .setContentType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  let tempFileId = "";

  try {
    tempFileId = uploadOzonReportQuarterXlsxAsGoogleSheet_(xlsxBlob, tempName);
    Logger.log("Временная Google-таблица отчёта хранения: " + tempFileId);

    const tempSpreadsheet = SpreadsheetApp.openById(tempFileId);
    const sheet = tempSpreadsheet.getSheets()[0];
    const lastRow = sheet.getLastRow();
    const lastCol = sheet.getLastColumn();
    if (!lastRow || !lastCol) return { storageMap: createOzonReportQuarterStorageMap_(), rowCount: 0 };

    const probeRows = sheet.getRange(1, 1, Math.min(lastRow, 50), lastCol).getDisplayValues();
    const headerIndex = findOzonReportQuarterStorageHeaderRowIndex_(probeRows);
    if (headerIndex < 0) {
      Logger.log("Не нашёл строку заголовков в сконвертированном отчёте хранения");
      return { storageMap: createOzonReportQuarterStorageMap_(), rowCount: lastRow };
    }

    const headers = probeRows[headerIndex].map(normalizeOzonReportQuarterHeader_);
    const skuIndex = findOzonReportQuarterHeaderIndex_(headers, ["sku"]);
    const offerIndex = findOzonReportQuarterHeaderIndex_(headers, ["артикул", "offer"]);
    const amountIndex = findOzonReportQuarterPreferredHeaderIndex_(headers,
      ["стоимость размещения", "начисленная стоимость размещения", "размещ", "хран", "storage", "placement"],
      ["начислено", "сумма", "итого"]
    );

    Logger.log("Колонки хранения (Google Sheets): sku=" + skuIndex + ", артикул=" + offerIndex + ", сумма=" + amountIndex);
    if (amountIndex < 0 || (skuIndex < 0 && offerIndex < 0)) {
      return { storageMap: createOzonReportQuarterStorageMap_(), rowCount: lastRow };
    }

    const storageMap = createOzonReportQuarterStorageMap_();
    const chunkSize = 10000;
    let processedRows = 0;

    for (let startRow = headerIndex + 2; startRow <= lastRow; startRow += chunkSize) {
      const numRows = Math.min(chunkSize, lastRow - startRow + 1);
      const values = sheet.getRange(startRow, 1, numRows, lastCol).getDisplayValues();
      addOzonReportQuarterStorageRowsToMap_(storageMap, values, skuIndex, offerIndex, amountIndex);
      processedRows += values.length;
      if (processedRows % 50000 === 0) Logger.log("Хранение обработано строк: " + processedRows + " / " + (lastRow - headerIndex - 1));
    }

    return { storageMap, rowCount: lastRow };
  } catch (error) {
    Logger.log("Не удалось обработать отчёт хранения через Google Sheets: " + error);
    return { storageMap: createOzonReportQuarterStorageMap_(), rowCount: 0 };
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

function addOzonReportQuarterStorageRowsToMap_(storageMap, rows, skuIndex, offerIndex, amountIndex) {
  rows.forEach(row => {
    const sku = skuIndex >= 0 ? normalizeOzonReportQuarterKey_(row[skuIndex]) : "";
    const offerId = offerIndex >= 0 ? normalizeOzonReportQuarterKey_(row[offerIndex]) : "";
    const amount = Math.abs(parseOzonReportQuarterMoney_(row[amountIndex]));
    if (!amount) return;

    if (sku) storageMap.bySku[sku] = (storageMap.bySku[sku] || 0) + amount;
    if (offerId) storageMap.byOfferId[offerId] = (storageMap.byOfferId[offerId] || 0) + amount;
  });
}

function uploadOzonReportQuarterXlsxAsGoogleSheet_(blob, name) {
  const boundary = "OZON_REPORT_QUARTER_storage_" + Date.now();
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

function getOzonReportQuarterStorageValue_(storageMap, item) {
  if (!storageMap) return 0;
  if (item.sku && Object.prototype.hasOwnProperty.call(storageMap.bySku || {}, item.sku)) return storageMap.bySku[item.sku];
  if (item.article && Object.prototype.hasOwnProperty.call(storageMap.byOfferId || {}, item.article)) return storageMap.byOfferId[item.article];
  return 0;
}

function sumOzonReportQuarterStorageMap_(storageMap) {
  return Object.values(storageMap.bySku || {}).reduce((sum, value) => sum + (Number(value) || 0), 0);
}

function findOzonReportQuarterStorageHeaderRowIndex_(rows) {
  for (let i = 0; i < Math.min(rows.length, 50); i++) {
    const joined = (rows[i] || []).map(normalizeOzonReportQuarterHeader_).join(" | ");
    if ((joined.indexOf("sku") !== -1 || joined.indexOf("артикул") !== -1 || joined.indexOf("offer") !== -1) &&
        (joined.indexOf("хран") !== -1 || joined.indexOf("размещ") !== -1 || joined.indexOf("storage") !== -1 || joined.indexOf("placement") !== -1)) {
      return i;
    }
  }
  return -1;
}

function findOzonReportQuarterPreferredHeaderIndex_(headers, preferredMarkers, fallbackMarkers) {
  const preferred = findOzonReportQuarterHeaderIndex_(headers, preferredMarkers);
  if (preferred >= 0) return preferred;
  return findOzonReportQuarterHeaderIndex_(headers, fallbackMarkers);
}

function parseOzonReportQuarterDelimitedRows_(text) {
  const cleaned = String(text || "").replace(/^\uFEFF/, "");
  const firstLine = cleaned.split(/\r?\n/)[0] || "";
  const delimiter = firstLine.indexOf(";") !== -1 ? ";" : firstLine.indexOf("\t") !== -1 ? "\t" : ",";
  return Utilities.parseCsv(cleaned, delimiter)
    .filter(row => row.some(cell => String(cell || "").trim() !== ""));
}

function parseOzonReportQuarterXlsxRows_(blob) {
  const files = Utilities.unzip(blob);
  const fileMap = {};
  files.forEach(file => {
    fileMap[file.getName()] = file.getDataAsString("UTF-8");
  });

  const sharedStrings = parseOzonReportQuarterXlsxSharedStrings_(fileMap["xl/sharedStrings.xml"]);
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
        const columnIndex = xlsxOzonReportQuarterColumnRefToIndex_(ref.replace(/[0-9]/g, ""));
        row[columnIndex] = readOzonReportQuarterXlsxCellValue_(cell, namespace, sharedStrings);
      });
      return row.map(value => value === undefined ? "" : value);
    })
    .filter(row => row.some(cell => String(cell || "").trim() !== ""));
}

function parseOzonReportQuarterXlsxSharedStrings_(xml) {
  if (!xml) return [];
  const document = XmlService.parse(xml);
  const root = document.getRootElement();
  const namespace = root.getNamespace();
  return root.getChildren("si", namespace).map(item => collectOzonReportQuarterXlsxTexts_(item, namespace).join(""));
}

function collectOzonReportQuarterXlsxTexts_(node, namespace) {
  let parts = [];
  const text = node.getChildText("t", namespace);
  if (text !== null) parts.push(text);
  node.getChildren().forEach(child => {
    parts = parts.concat(collectOzonReportQuarterXlsxTexts_(child, namespace));
  });
  return parts;
}

function readOzonReportQuarterXlsxCellValue_(cell, namespace, sharedStrings) {
  const type = cell.getAttribute("t") ? cell.getAttribute("t").getValue() : "";
  const valueNode = cell.getChild("v", namespace);

  if (type === "inlineStr") {
    const inline = cell.getChild("is", namespace);
    return inline ? collectOzonReportQuarterXlsxTexts_(inline, namespace).join("") : "";
  }

  const raw = valueNode ? valueNode.getText() : "";
  if (type === "s") return sharedStrings[Number(raw)] || "";
  return raw;
}

function xlsxOzonReportQuarterColumnRefToIndex_(ref) {
  const letters = String(ref || "").replace(/[0-9]/g, "");
  let index = 0;
  for (let i = 0; i < letters.length; i++) {
    index = index * 26 + letters.charCodeAt(i) - 64;
  }
  return Math.max(index - 1, 0);
}

function OzonReportQuarterPlacementByProductsReportURL_() {
  return "https://api-seller.ozon.ru/v1/report/placement/by-products/create";
}

function OzonReportQuarterReportInfoURL_() {
  return "https://api-seller.ozon.ru/v1/report/info";
}

function addOzonReportQuarterProductInfoSkuAliases_(skuToOffer, item) {
  if (!item) return;
  const offerId = normalizeOzonReportQuarterKey_(item.offer_id);
  if (!offerId) return;

  addOzonReportQuarterSkuOfferAlias_(skuToOffer, item.sku, offerId);
  addOzonReportQuarterSkuOfferAlias_(skuToOffer, item.fbo_sku, offerId);
  addOzonReportQuarterSkuOfferAlias_(skuToOffer, item.fbs_sku, offerId);

  const sources = Array.isArray(item.sources) ? item.sources : [];
  sources.forEach(source => {
    addOzonReportQuarterSkuOfferAlias_(skuToOffer, source && source.sku, offerId);
    addOzonReportQuarterSkuOfferAlias_(skuToOffer, source && source.fbo_sku, offerId);
    addOzonReportQuarterSkuOfferAlias_(skuToOffer, source && source.fbs_sku, offerId);
  });
}

function addOzonReportQuarterSkuOfferAlias_(skuToOffer, sku, offerId) {
  const key = normalizeOzonReportQuarterKey_(sku);
  if (key) skuToOffer[key] = offerId;
}

function mergeOzonReportQuarterAccrualBucket_(target, source) {
  ["unitSum", "unitQty", "reward", "logistics", "extra", "starsAndAcquiring", "commonExtra", "cpoPayment", "clicksPayment"].forEach(field => {
    target[field] += Number(source[field]) || 0;
  });
}

function splitOzonReportQuarterFinanceDateRange_(dateFrom, dateTo) {
  const chunks = [];
  let current = parseOzonReportQuarterDate_(dateFrom);
  const end = parseOzonReportQuarterDate_(dateTo);

  while (current.getTime() <= end.getTime()) {
    const chunkEnd = new Date(current.getTime());
    chunkEnd.setUTCDate(chunkEnd.getUTCDate() + 29);
    if (chunkEnd.getTime() > end.getTime()) chunkEnd.setTime(end.getTime());

    chunks.push({
      from: formatOzonReportQuarterDate_(current),
      to: formatOzonReportQuarterDate_(chunkEnd)
    });

    current = new Date(chunkEnd.getTime());
    current.setUTCDate(current.getUTCDate() + 1);
  }

  return chunks;
}

function parseOzonReportQuarterDate_(value) {
  const parts = String(value).split("-").map(Number);
  return new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
}

function formatOzonReportQuarterDate_(date) {
  return Utilities.formatDate(date, "UTC", "yyyy-MM-dd");
}

function aggregateOzonReportQuarterOperation_(result, unknownTypes, operation) {
  const itemAliases = extractOzonReportQuarterOperationAliases_(operation);
  if (!itemAliases.length) {
    aggregateOzonReportQuarterCommonCost_(result, operation);
    return;
  }

  const operationName = normalizeOzonReportQuarterText_(operation.operation_type_name || operation.operation_type || operation.type || "");
  const accrualsForSale = parseOzonReportQuarterMoney_(operation.accruals_for_sale || 0);
  const saleCommission = parseOzonReportQuarterMoney_(operation.sale_commission || 0);

  addOzonReportQuarterAmount_(result, unknownTypes, itemAliases, operationName || "выручка", "unitSum", accrualsForSale);
  addOzonReportQuarterAmount_(result, unknownTypes, itemAliases, "вознаграждение за продажу", "reward", saleCommission);

  const services = Array.isArray(operation.services) ? operation.services : [];

  if (services.length) {
    services.forEach(service => {
      const serviceName = normalizeOzonReportQuarterText_(service.name || service.service_name || service.type || "");
      const group = classifyOzonReportQuarterCharge_(serviceName);
      const amount = parseOzonReportQuarterMoney_(service.price || service.amount || service.total || 0);
      addOzonReportQuarterAmount_(result, unknownTypes, itemAliases, serviceName, group, amount);
    });
    return;
  }

  const group = classifyOzonReportQuarterCharge_(operationName);
  const amount = parseOzonReportQuarterMoney_(operation.amount || operation.price || 0);
  if ((group === "unitSum" && !accrualsForSale) ||
      (group === "reward" && !saleCommission) ||
      (group && group !== "unitSum" && group !== "reward")) {
    addOzonReportQuarterAmount_(result, unknownTypes, itemAliases, operationName, group, amount);
  }
}

function extractOzonReportQuarterOperationAliases_(operation) {
  const aliases = [];
  const items = Array.isArray(operation.items) ? operation.items : [];

  items.forEach(item => {
    const keys = [];
    [item.offer_id, item.sku].forEach(value => {
      const key = normalizeOzonReportQuarterKey_(value);
      if (key && keys.indexOf(key) === -1) keys.push(key);
    });
    if (keys.length) aliases.push(keys);
  });

  if (!aliases.length && operation.posting && operation.posting.offer_id) {
    const key = normalizeOzonReportQuarterKey_(operation.posting.offer_id);
    if (key) aliases.push([key]);
  }

  return aliases;
}

function addOzonReportQuarterAmount_(result, unknownTypes, itemAliases, typeName, group, amount) {
  if (!amount || !group) {
    if (typeName && !group) unknownTypes[typeName] = (unknownTypes[typeName] || 0) + amount;
    return;
  }

  const perItemAmount = amount / itemAliases.length;
  itemAliases.forEach(keys => {
    keys.forEach(key => {
      if (!result[key]) result[key] = createOzonReportQuarterAccrualBucket_();
      result[key][group] += perItemAmount;
    });
  });
}

function aggregateOzonReportQuarterCommonCost_(result, operation) {
  const operationName = normalizeOzonReportQuarterText_(operation.operation_type_name || operation.operation_type || operation.type || "");
  if (isOzonReportQuarterCommonAdvertisingCost_(operationName)) return;

  const amount = parseOzonReportQuarterMoney_(operation.amount || operation.price || 0);
  if (!amount) return;

  if (!result[OZON_REPORT_QUARTER_COMMON_COSTS_KEY]) result[OZON_REPORT_QUARTER_COMMON_COSTS_KEY] = createOzonReportQuarterAccrualBucket_();
  result[OZON_REPORT_QUARTER_COMMON_COSTS_KEY].commonExtra += amount;
}

function isOzonReportQuarterCommonAdvertisingCost_(operationName) {
  return containsAnyOzonReportQuarter_(operationName, [
    "оплата за клик",
    "продвижение с оплатой за заказ"
  ]);
}

function createOzonReportQuarterAccrualBucket_() {
  return { unitSum: 0, unitQty: 0, reward: 0, logistics: 0, extra: 0, starsAndAcquiring: 0, commonExtra: 0, cpoPayment: 0, clicksPayment: 0 };
}

function classifyOzonReportQuarterCharge_(text) {
  if (!text) return "";

  if (containsAnyOzonReportQuarter_(text, [
    "программы партнёров",
    "программы партнеров",
    "баллы за скидки",
    "cashbackindividualpoints",
    "возврат выручки",
    "выручка"
  ])) return "unitSum";

  if (containsAnyOzonReportQuarter_(text, [
    "бонусы продавца",
    "возврат вознаграждения",
    "вознаграждение за продажу",
    "salecommission"
  ])) return "reward";

  if (containsAnyOzonReportQuarter_(text, [
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

  if (containsAnyOzonReportQuarter_(text, [
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
      containsAnyOzonReportQuarter_(text, [
        "marketplaceserviceitemdirectflowlogistic"
      ])) return "logistics";

  return "";
}

function getOzonReportQuarterPerfToken_() {
  const props = PropertiesService.getScriptProperties();
  const clientId = props.getProperty("OZON_PERFORMANCE_CLIENT_ID") || OZON_REPORT_QUARTER_PERF_CLIENT_ID;
  const clientSecret = props.getProperty("OZON_PERFORMANCE_CLIENT_SECRET") || OZON_REPORT_QUARTER_PERF_CLIENT_SECRET;

  if (!clientId || !clientSecret) {
    if (typeof getPerfToken === "function") {
      Logger.log("Script Properties не заданы, использую legacy getPerfToken() из старого файла рекламы");
      return getPerfToken();
    }

    Logger.log("Не заданы Script Properties OZON_PERFORMANCE_CLIENT_ID/OZON_PERFORMANCE_CLIENT_SECRET и не найден legacy getPerfToken()");
    return "";
  }

  let response = null;
  try {
    response = UrlFetchApp.fetch(OZON_REPORT_QUARTER_PERF_BASE_URL + "/api/client/token", {
      method: "post",
      contentType: "application/json",
      payload: JSON.stringify({
        client_id: clientId,
        client_secret: clientSecret,
        grant_type: "client_credentials"
      }),
      muteHttpExceptions: true
    });
  } catch (e) {
    Logger.log("Performance token fetch failed: " + e.toString());
    return "";
  }

  if (response.getResponseCode() !== 200) {
    Logger.log("Performance token HTTP " + response.getResponseCode());
    return "";
  }

  const data = JSON.parse(response.getContentText());
  return data.access_token || "";
}

function getOzonReportQuarterPerfCampaigns_(token) {
  const response = UrlFetchApp.fetch(OZON_REPORT_QUARTER_PERF_BASE_URL + "/api/client/campaign", {
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

function filterOzonReportQuarterCpoCampaigns_(campaigns) {
  const filtered = campaigns.filter(isOzonReportQuarterCpoCampaign_);
  Logger.log("Performance CPO кампании: " + filtered.length + " / " + campaigns.length);
  return filtered;
}

function filterOzonReportQuarterClickCampaigns_(campaigns) {
  const filtered = campaigns.filter(campaign => !isOzonReportQuarterCpoCampaign_(campaign));
  Logger.log("Performance оплата за клик кампании: " + filtered.length + " / " + campaigns.length);
  return filtered;
}

function isOzonReportQuarterCpoCampaign_(campaign) {
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
  const text = normalizeOzonReportQuarterText_(values.filter(Boolean).join(" "));
  return text.indexOf("оплата за заказ") !== -1 ||
    text.indexOf("оплата за заказы") !== -1 ||
    text.indexOf("cpo") !== -1;
}

function fetchOzonReportQuarterOverviewStats_(token, campaigns, dateFrom, dateTo, pendingOverviewReportUuid) {
  const stats = {};
  let failed = false;
  let pendingUuid = "";

  for (let i = 0; i < campaigns.length; i += OZON_REPORT_QUARTER_CAMPAIGN_BATCH_SIZE) {
    const campaignIds = campaigns.slice(i, i + OZON_REPORT_QUARTER_CAMPAIGN_BATCH_SIZE).map(campaign => String(campaign.id || campaign));
    const result = fetchOzonReportQuarterOverviewCampaignIds_(
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

    mergeOzonReportQuarterStats_(stats, result.stats);

    if (i + OZON_REPORT_QUARTER_CAMPAIGN_BATCH_SIZE < campaigns.length) Utilities.sleep(5000);
  }

  if (failed && !Object.keys(stats).length) {
    return { stats: null, pendingOverviewReportUuid: pendingUuid };
  }

  Logger.log("Overview ad SKUs: " + Object.keys(stats).length);
  return { stats: stats, pendingOverviewReportUuid: "" };
}

function fetchOzonReportQuarterOverviewCampaignIds_(token, campaignIds, dateFrom, dateTo, pendingOverviewReportUuid) {
  const uuid = pendingOverviewReportUuid
    ? pendingOverviewReportUuid
    : createOzonReportQuarterOverviewReport_(token, campaignIds, dateFrom, dateTo);

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

    const left = fetchOzonReportQuarterOverviewCampaignIds_(token, leftIds, dateFrom, dateTo, "");
    if (left.stats === null) return left;

    const right = fetchOzonReportQuarterOverviewCampaignIds_(token, rightIds, dateFrom, dateTo, "");
    if (right.stats === null) return right;

    const stats = {};
    mergeOzonReportQuarterStats_(stats, left.stats);
    mergeOzonReportQuarterStats_(stats, right.stats);
    return { stats: stats, pendingOverviewReportUuid: "" };
  }

  if (!uuid) return { stats: null, pendingOverviewReportUuid: "" };

  if (pendingOverviewReportUuid) {
    Logger.log("Продолжаем ожидание Performance отчета " + uuid);
  }

  const blob = waitOzonReportQuarterPerformanceReport_(token, uuid, [
    OZON_REPORT_QUARTER_PERF_BASE_URL + "/api/client/statistics/" + uuid
  ], [
    OZON_REPORT_QUARTER_PERF_BASE_URL + "/api/client/statistics/report?UUID=" + uuid + "&download=1",
    OZON_REPORT_QUARTER_PERF_BASE_URL + "/api/client/statistics/report?UUID=" + uuid
  ]);

  if (!blob) return { stats: null, pendingOverviewReportUuid: uuid };

  return { stats: parseOzonReportQuarterOverviewBlob_(blob), pendingOverviewReportUuid: "" };
}

function createOzonReportQuarterOverviewReport_(token, campaignIds, dateFrom, dateTo) {
  const response = fetchOzonReportQuarterPerformanceUrl_(OZON_REPORT_QUARTER_PERF_BASE_URL + "/api/client/statistics", {
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

function fetchOzonReportQuarterCpoPaymentStats_(token, dateFrom, dateTo, campaigns) {
  const campaignIds = (campaigns || []).map(campaign => String(campaign.id || campaign)).filter(Boolean);
  if (!campaignIds.length) {
    Logger.log("CPO payment кампании не найдены, колонка ЗАКАЗЫ не будет обновлена");
    return null;
  }

  const uuid = createOzonReportQuarterCpoPaymentReport_(token, dateFrom, dateTo, campaignIds);
  if (!uuid) return null;

  const blob = waitOzonReportQuarterPerformanceReport_(token, uuid, [
    OZON_REPORT_QUARTER_PERF_BASE_URL + "/api/client/statistics/orders/" + uuid,
    OZON_REPORT_QUARTER_PERF_BASE_URL + "/api/client/statistics/orders/status?UUID=" + uuid,
    OZON_REPORT_QUARTER_PERF_BASE_URL + "/api/client/statistic/orders/" + uuid,
    OZON_REPORT_QUARTER_PERF_BASE_URL + "/api/client/statistic/orders/status?UUID=" + uuid,
    OZON_REPORT_QUARTER_PERF_BASE_URL + "/api/client/statistics/" + uuid
  ], [
    OZON_REPORT_QUARTER_PERF_BASE_URL + "/api/client/statistics/orders/download?UUID=" + uuid,
    OZON_REPORT_QUARTER_PERF_BASE_URL + "/api/client/statistic/orders/download?UUID=" + uuid,
    OZON_REPORT_QUARTER_PERF_BASE_URL + "/api/client/statistics/report?UUID=" + uuid + "&download=1",
    OZON_REPORT_QUARTER_PERF_BASE_URL + "/api/client/statistics/report?UUID=" + uuid
  ]);

  if (!blob) {
    Logger.log("CPO payment report не получен, колонка ЗАКАЗЫ не будет обновлена");
    return null;
  }

  const stats = parseOzonReportQuarterCpoPaymentBlob_(blob);
  Logger.log("CPO payment SKUs: " + Object.keys(stats).length);
  Logger.log("CPO payment total spend: " + roundOzonReportQuarterMoney_(sumOzonReportQuarterStats_(stats, "spend")));
  return stats;
}

function createOzonReportQuarterCpoPaymentReport_(token, dateFrom, dateTo, campaignIds) {
  const payload = JSON.stringify({
    campaigns: campaignIds,
    dateFrom: dateFrom,
    dateTo: dateTo
  });
  const urls = [
    OZON_REPORT_QUARTER_PERF_BASE_URL + "/api/client/statistics/orders/generate",
    OZON_REPORT_QUARTER_PERF_BASE_URL + "/api/client/statistic/orders/generate"
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

function waitOzonReportQuarterPerformanceReport_(token, uuid, statusUrls, downloadUrls) {
  for (let attempt = 1; attempt <= OZON_REPORT_QUARTER_PERF_REPORT_MAX_ATTEMPTS; attempt++) {
    Utilities.sleep(OZON_REPORT_QUARTER_PERF_REPORT_POLL_MS);

    for (let i = 0; i < statusUrls.length; i++) {
      const statusResponse = fetchOzonReportQuarterPerformanceUrl_(statusUrls[i], {
        method: "get",
        headers: { Authorization: "Bearer " + token },
        muteHttpExceptions: true
      }, "status " + uuid);
      if (!statusResponse) continue;

      const statusCode = statusResponse.getResponseCode();
      const statusBlob = statusResponse.getBlob();
      if (statusCode === 200 && isOzonReportQuarterBlobReport_(statusBlob)) return statusBlob;
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
          const linked = downloadOzonReportQuarterPerfBlob_(token, OZON_REPORT_QUARTER_PERF_BASE_URL + data.link);
          if (linked) return linked;
        }

        for (let j = 0; j < downloadUrls.length; j++) {
          const downloaded = downloadOzonReportQuarterPerfBlob_(token, downloadUrls[j]);
          if (downloaded) return downloaded;
        }
      }

      if (data && data.state === "ERROR") {
        Logger.log("Performance report error: " + uuid);
        return null;
      }
    }

    if (attempt % 6 === 0) Logger.log("Ожидание Performance отчета " + uuid + ": " + attempt + "/" + OZON_REPORT_QUARTER_PERF_REPORT_MAX_ATTEMPTS);
  }

  Logger.log("Performance report timeout: " + uuid);
  return null;
}

function downloadOzonReportQuarterPerfBlob_(token, url) {
  const response = fetchOzonReportQuarterPerformanceUrl_(url, {
    method: "get",
    headers: { Authorization: "Bearer " + token },
    muteHttpExceptions: true
  }, "download");
  if (!response) return null;

  if (response.getResponseCode() !== 200) return null;

  const blob = response.getBlob();
  return isOzonReportQuarterBlobReport_(blob) ? blob : null;
}

function fetchOzonReportQuarterPerformanceUrl_(url, options, label) {
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

function isOzonReportQuarterBlobReport_(blob) {
  const bytes = blob.getBytes();
  if (bytes.length < 2) return false;
  if (bytes[0] === 0x50 && bytes[1] === 0x4B) return true;

  const text = blob.getDataAsString().replace(/^\uFEFF/, "").trim();
  return text.indexOf(";") !== -1 && (text.toLowerCase().indexOf("sku") !== -1 || text.toLowerCase().indexOf("артикул") !== -1);
}

function parseOzonReportQuarterOverviewBlob_(blob) {
  return parseOzonReportQuarterCsvStats_(blob, {
    sku: ["sku", "артикул"],
    clicks: ["клики", "clicks"],
    spend: ["расход", "spend"],
    orders: ["продано товаров", "заказы", "orders"],
    revenue: ["продажи в продвижении", "выручка", "revenue"]
  });
}

function parseOzonReportQuarterCpoPaymentBlob_(blob) {
  return parseOzonReportQuarterCsvStats_(blob, {
    sku: ["sku продвигаемого товара", "ozon id", "sku", "артикул"],
    clicks: ["количество кликов", "клики", "clicks"],
    spend: ["расход, ₽", "расход", "spend"],
    orders: ["количество заказов", "количество", "заказы", "orders"],
    revenue: ["стоимость продажи", "сумма заказов", "выручка", "revenue", "sum"]
  });
}

function parseOzonReportQuarterCsvStats_(blob, markers) {
  const blobs = unzipOzonReportQuarterBlobs_(blob);
  const stats = {};

  blobs.forEach(fileBlob => {
    const text = fileBlob.getDataAsString().replace(/^\uFEFF/, "");
    const rows = Utilities.parseCsv(text, ";").filter(row => row.some(cell => String(cell || "").trim() !== ""));
    const headerIndex = findOzonReportQuarterCsvHeaderIndex_(rows);
    if (headerIndex < 0) return;

    const headers = rows[headerIndex].map(normalizeOzonReportQuarterText_);
    const skuIndex = findOzonReportQuarterHeaderIndex_(headers, markers.sku);
    const clicksIndex = findOzonReportQuarterHeaderIndex_(headers, markers.clicks);
    const spendIndex = findOzonReportQuarterHeaderIndex_(headers, markers.spend);
    const ordersIndex = findOzonReportQuarterHeaderIndex_(headers, markers.orders);
    const revenueIndex = findOzonReportQuarterHeaderIndex_(headers, markers.revenue);

    if (skuIndex < 0) return;

    for (let i = headerIndex + 1; i < rows.length; i++) {
      const row = rows[i];
      const sku = normalizeOzonReportQuarterKey_(row[skuIndex]);
      if (!sku || sku.toLowerCase() === "всего") continue;

      if (!stats[sku]) stats[sku] = { clicks: 0, orders: 0, revenue: 0, spend: 0 };
      stats[sku].clicks += clicksIndex >= 0 ? parseInt(parseOzonReportQuarterMoney_(row[clicksIndex]), 10) || 0 : 0;
      stats[sku].orders += ordersIndex >= 0 ? parseInt(parseOzonReportQuarterMoney_(row[ordersIndex]), 10) || 0 : 0;
      stats[sku].revenue += revenueIndex >= 0 ? parseOzonReportQuarterMoney_(row[revenueIndex]) : 0;
      stats[sku].spend += spendIndex >= 0 ? parseOzonReportQuarterMoney_(row[spendIndex]) : 0;
    }
  });

  return stats;
}

function unzipOzonReportQuarterBlobs_(blob) {
  const bytes = blob.getBytes();
  if (bytes.length > 2 && bytes[0] === 0x50 && bytes[1] === 0x4B) {
    return Utilities.unzip(blob);
  }
  return [blob];
}

function findOzonReportQuarterCsvHeaderIndex_(rows) {
  for (let i = 0; i < Math.min(rows.length, 10); i++) {
    const joined = rows[i].map(normalizeOzonReportQuarterText_).join(";");
    if ((joined.indexOf("sku") !== -1 || joined.indexOf("артикул") !== -1) &&
        (joined.indexOf("клики") !== -1 || joined.indexOf("заказ") !== -1 || joined.indexOf("расход") !== -1)) {
      return i;
    }
  }
  return -1;
}

function findOzonReportQuarterHeaderIndex_(headers, markers) {
  for (let j = 0; j < markers.length; j++) {
    const marker = normalizeOzonReportQuarterText_(markers[j]);
    for (let i = 0; i < headers.length; i++) {
      if (headers[i].indexOf(marker) !== -1) return i;
    }
  }
  return -1;
}

function mergeOzonReportQuarterStats_(target, source) {
  Object.keys(source).forEach(sku => {
    if (!target[sku]) target[sku] = { clicks: 0, orders: 0, revenue: 0, spend: 0 };
    target[sku].clicks += source[sku].clicks || 0;
    target[sku].orders += source[sku].orders || 0;
    target[sku].revenue += source[sku].revenue || 0;
    target[sku].spend += source[sku].spend || 0;
  });
}

function sumOzonReportQuarterStats_(stats, field) {
  return Object.keys(stats || {}).reduce((sum, sku) => sum + (Number(stats[sku][field]) || 0), 0);
}

function getOzonReportQuarterOverpaymentValues_(sheet, headerMap, rowItems) {
  const overpaymentCol = getOzonReportQuarterColumn_(headerMap, "ПЕРЕПЛАТА");
  if (overpaymentCol) {
    const currentValues = sheet.getRange(headerMap.__headerRow + 1, overpaymentCol, rowItems.length, 1).getValues();
    const hasCurrentValues = currentValues.some(row => {
      const raw = row && row[0];
      return raw !== "" && raw !== null && raw !== undefined && parseOzonReportQuarterMoney_(raw) !== 0;
    });
    if (hasCurrentValues) return currentValues;
    Logger.log("Колонка ПЕРЕПЛАТА на текущем листе пустая, пробую взять значения с листа UNIT");
  }

  const sourceSheet = sheet.getParent().getSheetByName("UNIT");
  if (!sourceSheet || sourceSheet.getName() === sheet.getName()) {
    Logger.log("Колонка ПЕРЕПЛАТА не найдена, корректировка логистики не применяется");
    return [];
  }

  const sourceHeaderMap = getOzonReportQuarterHeaderMap_(sourceSheet);
  const sourceOverpaymentCol = getOzonReportQuarterColumn_(sourceHeaderMap, "ПЕРЕПЛАТА");
  const sourceArticleCol = getOzonReportQuarterColumn_(sourceHeaderMap, "Артикул");
  const sourceSkuCol = getOzonReportQuarterColumn_(sourceHeaderMap, "СКУ OZ");
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
    const article = normalizeOzonReportQuarterKey_(row[sourceArticleCol - 1]);
    const sku = normalizeOzonReportQuarterKey_(row[sourceSkuCol - 1]);
    const amount = parseOzonReportQuarterMoney_(row[sourceOverpaymentCol - 1]);
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

function writeOzonReportQuarterFinanceColumns_(sheet, headerMap, rowItems, accrualMap, cpoMap, storageMap) {
  const overpaymentValues = getOzonReportQuarterOverpaymentValues_(sheet, headerMap, rowItems);
  const commonCosts = accrualMap[OZON_REPORT_QUARTER_COMMON_COSTS_KEY] || createOzonReportQuarterAccrualBucket_();
  const totalUnitSum = rowItems.reduce((sum, item) => {
    const accrual = accrualMap[item.article] || accrualMap[item.sku] || createOzonReportQuarterAccrualBucket_();
    return sum + (Number(accrual.unitSum) || 0);
  }, 0);
  const commonExtraRate = totalUnitSum ? (Number(commonCosts.commonExtra) || 0) / totalUnitSum : 0;
  const commonCpoRate = totalUnitSum ? (Number(commonCosts.cpoPayment) || 0) / totalUnitSum : 0;
  writeOzonReportQuarterCommonExtraCoefficient_(sheet, commonExtraRate);
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

  if (getOzonReportQuarterColumn_(headerMap, "ЗАКАЗЫ")) {
    columns.push({ header: "ЗАКАЗЫ", getter: data => data.cpoPayment });
  }

  const columnValues = columns.map(column => ({
    col: getOzonReportQuarterColumn_(headerMap, column.header),
    values: [],
    getter: column.getter,
    header: column.header
  }));

  let matchedAccrual = 0;
  let matchedCpo = 0;
  let matchedStorage = 0;
  let writtenCpoSpend = 0;
  let writtenStorage = 0;

  rowItems.forEach((item, index) => {
    const accrual = accrualMap[item.article] || accrualMap[item.sku] || createOzonReportQuarterAccrualBucket_();
    const cpo = cpoMap ? (cpoMap[item.sku] || cpoMap[item.article] || { spend: 0 }) : { spend: 0 };
    const overpayment = overpaymentValues[index]
      ? parseOzonReportQuarterMoney_(overpaymentValues[index][0])
      : 0;
    const storage = getOzonReportQuarterStorageValue_(storageMap, item);

    if (accrual.unitSum || accrual.unitQty || accrual.reward || accrual.logistics || accrual.extra || accrual.starsAndAcquiring) matchedAccrual++;
    const cpoPayment = cpoMap ? (Number(cpo.spend) || 0) : -((Number(accrual.unitSum) || 0) * commonCpoRate);
    if (cpoPayment) matchedCpo++;
    if (storage) matchedStorage++;
    if (cpoPayment) writtenCpoSpend += cpoPayment;
    if (storage) writtenStorage += storage;

    const data = {
      unitSum: roundOzonReportQuarterMoney_(accrual.unitSum || 0),
      unitQty: Math.round(Number(accrual.unitQty) || 0),
      reward: roundOzonReportQuarterMoney_(accrual.reward || 0),
      logistics: roundOzonReportQuarterMoney_((accrual.logistics || 0) - overpayment),
      overpayment: roundOzonReportQuarterMoney_(overpayment),
      storage: roundOzonReportQuarterMoney_(storage),
      extra: roundOzonReportQuarterMoney_(accrual.extra || 0),
      starsAndAcquiring: roundOzonReportQuarterMoney_(accrual.starsAndAcquiring || 0),
      commonExtra: roundOzonReportQuarterMoney_((accrual.unitSum || 0) * commonExtraRate),
      cpoPayment: roundOzonReportQuarterMoney_(cpoPayment)
    };

    columnValues.forEach(column => column.values.push([column.getter(data)]));
  });

  columnValues.forEach(column => {
    if (!column.col) throw new Error("Не найден заголовок для записи: " + column.header);
    sheet.getRange(headerMap.__headerRow + 1, column.col, column.values.length, 1).setValues(column.values);
  });

  Logger.log("Начисления сопоставлены: " + matchedAccrual + " строк");
  Logger.log("ПЕРЕПЛАТА записана из листа UNIT API квартал/UNIT: " + roundOzonReportQuarterMoney_(overpaymentValues.reduce((sum, row) => sum + parseOzonReportQuarterMoney_(row && row[0]), 0)));
  Logger.log("ХРАНЕНИЕ сопоставлено: " + matchedStorage + " строк; записано " + roundOzonReportQuarterMoney_(writtenStorage));
  Logger.log("Общие расходы без артикула для ОЗОН ДОП ВОЗНЯ: " + roundOzonReportQuarterMoney_(commonCosts.commonExtra || 0) + "; процент: " + (commonExtraRate * 100).toFixed(4) + "%; коэффициент: " + (1 + commonExtraRate).toFixed(4));
  Logger.log("Оплата за заказ из accrual/by-day: " + roundOzonReportQuarterMoney_(commonCosts.cpoPayment || 0) + "; процент: " + (commonCpoRate * 100).toFixed(4) + "%");
  Logger.log("Оплата за клик из accrual/by-day для контроля: " + roundOzonReportQuarterMoney_(commonCosts.clicksPayment || 0));
  if (!matchedAccrual && Object.keys(accrualMap).length) {
    Logger.log("Finance sample keys: " + Object.keys(accrualMap).slice(0, 10).join(", "));
    Logger.log("Sheet sample article keys: " + rowItems.map(item => item.article).filter(Boolean).slice(0, 10).join(", "));
    Logger.log("Sheet sample SKU keys: " + rowItems.map(item => item.sku).filter(Boolean).slice(0, 10).join(", "));
  }
  if (cpoMap) {
    Logger.log("CPO заказы сопоставлены: " + matchedCpo + " строк");
    Logger.log("CPO расход в отчете: " + roundOzonReportQuarterMoney_(sumOzonReportQuarterStats_(cpoMap, "spend")) + "; записано в ЗАКАЗЫ: " + roundOzonReportQuarterMoney_(writtenCpoSpend));
    if (!matchedCpo && Object.keys(cpoMap).length) {
      Logger.log("CPO sample keys: " + Object.keys(cpoMap).slice(0, 10).join(", "));
    }
  } else {
    Logger.log("CPO заказы распределены по UNIT СУММА из accrual/by-day; записано в ЗАКАЗЫ: " + roundOzonReportQuarterMoney_(writtenCpoSpend));
  }
}

function clearOzonReportQuarterClicksColumn_(sheet, headerMap, rowCount) {
  const clicksCol = getOzonReportQuarterColumn_(headerMap, "КЛИКИ");
  if (!clicksCol || !rowCount) return;

  const zeros = Array.from({ length: rowCount }, () => [0]);
  sheet.getRange(headerMap.__headerRow + 1, clicksCol, rowCount, 1).setValues(zeros);
  Logger.log("Колонка КЛИКИ очищена для накопительной записи расхода по оплате за клик");
}

function writeOzonReportQuarterAdClicksBatch_(sheet, headerMap, rowItems, overviewMap) {
  const clicksCol = getOzonReportQuarterColumn_(headerMap, "КЛИКИ");
  if (!clicksCol) throw new Error("Не найден заголовок для записи: КЛИКИ");

  const range = sheet.getRange(headerMap.__headerRow + 1, clicksCol, rowItems.length, 1);
  const values = range.getValues();
  let matchedSpendRows = 0;
  let writtenSpend = 0;

  rowItems.forEach((item, index) => {
    const overview = overviewMap[item.sku] || overviewMap[item.article] || { spend: 0 };
    const spend = Number(overview.spend) || 0;
    if (!spend) return;

    values[index][0] = roundOzonReportQuarterMoney_(parseOzonReportQuarterMoney_(values[index][0]) + spend);
    matchedSpendRows++;
    writtenSpend += spend;
  });

  range.setValues(values);
  Logger.log("КЛИКИ расход пачки: в отчете " + roundOzonReportQuarterMoney_(sumOzonReportQuarterStats_(overviewMap, "spend")) + "; записано " + roundOzonReportQuarterMoney_(writtenSpend) + "; строк " + matchedSpendRows);
}

function getOzonReportQuarterDefaultDateRange_() {
  const today = new Date();
  const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
  const fromDate = new Date(today.getFullYear(), today.getMonth() - 1, today.getDate());

  return {
    from: Utilities.formatDate(fromDate, Session.getScriptTimeZone(), "yyyy-MM-dd"),
    to: Utilities.formatDate(yesterday, Session.getScriptTimeZone(), "yyyy-MM-dd")
  };
}

function logOzonReportQuarterUnknownTypes_(unknownTypes) {
  const entries = Object.keys(unknownTypes)
    .filter(key => unknownTypes[key])
    .sort((a, b) => Math.abs(unknownTypes[b]) - Math.abs(unknownTypes[a]))
    .slice(0, 30);

  if (!entries.length) return;

  Logger.log("Не классифицированные типы начислений (первые 30):");
  entries.forEach(key => Logger.log(key + ": " + roundOzonReportQuarterMoney_(unknownTypes[key])));
}

function containsAnyOzonReportQuarter_(text, needles) {
  return needles.some(needle => text.indexOf(normalizeOzonReportQuarterText_(needle)) !== -1);
}

function normalizeOzonReportQuarterKey_(value) {
  if (value === null || value === undefined) return "";
  return decodeOzonReportQuarterXmlEntities_(String(value)).trim();
}

function normalizeOzonReportQuarterText_(value) {
  return normalizeOzonReportQuarterKey_(value).toLowerCase().replace(/\s+/g, " ");
}

function normalizeOzonReportQuarterHeader_(value) {
  return normalizeOzonReportQuarterText_(value).replace(/ё/g, "е");
}

function parseOzonReportQuarterMoney_(value) {
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

function roundOzonReportQuarterMoney_(value) {
  const num = Number(value) || 0;
  return Math.round(num * 100) / 100;
}

function decodeOzonReportQuarterXmlEntities_(value) {
  return String(value || "")
    .replace(/&#x([0-9a-f]+);/gi, function(_, hex) {
      return String.fromCharCode(parseInt(hex, 16));
    })
    .replace(/&#([0-9]+);/g, function(_, dec) {
      return String.fromCharCode(parseInt(dec, 10));
    });
}
