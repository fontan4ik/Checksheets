/**
 * Расчёт показателей листа «ОБОР» без формул.
 *
 * Скрипт читает источники, агрегирует значения по базовому артикулу,
 * учитывает числовой суффикс после последнего дефиса и записывает готовые
 * значения в ОБОР в колонках с заголовками «Озон ост», «Уход месяц»,
 * «Факт выкупа месяц», «ВБ всего», «ВБ ост», «ВБ Ух» и
 * «ВБ факт выкуп месяц».
 *
 * Пример: 55222-10 и 55222-5 превращаются в 10 × значение и 5 × значение.
 *
 * Источники:
 * - J «Озон ост»            ← ТЕСТ!F, Остаток ФБО ОЗОН
 * - K «СДЭК Остаток»        ← ОТКЛЮЧЕНО (Ozon FBS API / склад «КГТ СДЭК»)
 * - N «Уход месяц»          ← ТЕСТ!AQ+AR−BH, продажи Ozon FBO+FBS без отмен
 * - O «Факт выкупа месяц»   ← UNIT API!M, UNIT ШТ
 * - «ВБ всего»              ← WB Analytics products, metrics.stockCount
 *                                 («Всего находится на складах»)
 * - «ВБ ост»                ← WB Analytics groups, warehouses[].quantity
 *                                 по складу «Склад WB РФ»
 * - Y «ВБ Ух»               ← ТЕСТ!AV+AW, продажи WB FBO+FBS
 * - Z «ВБ факт выкуп месяц» ← UNIT WB!AP, ВЫКУП ШТ API
 *
 * Основной ручной запуск: calculateOborValues().
 * updateOborWbStockDirect() обновляет обе WB-колонки W и X из разных API-полей.
 * updateOborSummary() оставлен как короткий совместимый алиас.
 * Скрипт не создаёт триггеры.
 */

const OBOR_VALUES_TARGET_SHEET = "ОБОР";
const OBOR_VALUES_SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI";
const OBOR_VALUES_SOURCE_SHEET = "ТЕСТ";
const OBOR_CDEK_WAREHOUSE_NAME = "КГТ СДЭК";
const OBOR_CDEK_WAREHOUSE_ID = 1020002321437000;
const OBOR_CDEK_STOCKS_URL = "https://api-seller.ozon.ru/v2/product/info/stocks-by-warehouse/fbs";
const OBOR_CDEK_BATCH_SIZE = 1000;
const OBOR_CDEK_REQUEST_INTERVAL_MS = 1000;
const OBOR_WB_ANALYTICS_PAGE_LIMIT = 1000;
const OBOR_WB_ANALYTICS_REQUEST_INTERVAL_MS = 12000;
// Для ручного WB-запуска обновляются колонки W и X листа «ОБОР».
const OBOR_WB_STOCK_TARGET_COLUMN = "W";
const OBOR_WB_STOCK_SECOND_TARGET_COLUMN = "X";
const OBOR_WB_STOCK_SECOND_WAREHOUSE_NAME = "Склад WB РФ";

const OBOR_VALUE_CONFIG = [
  {
    key: "ozonStock",
    targetHeader: "Озон ост",
    sourceSheet: "ТЕСТ",
    sourceArticleColumn: "A",
    sourceValueColumns: ["F"],
    subtractValueColumns: [],
    note: "Остаток ФБО ОЗОН; отмены не участвуют"
  },
  /*
  // Временно отключено по запросу: K «СДЭК Остаток» не рассчитывается.
  {
    key: "cdekStock",
    targetHeader: "СДЭК Остаток",
    sourceSheet: null,
    sourceArticleColumn: null,
    sourceValueColumns: [],
    note: "Ozon FBS API / КГТ СДЭК"
  },
  */
  {
    key: "ozonMonthWithdrawal",
    targetHeader: "Уход месяц",
    sourceSheet: "ТЕСТ",
    sourceArticleColumn: "A",
    sourceValueColumns: ["AQ", "AR"],
    subtractValueColumns: ["BH"],
    note: "Продажи FBO + FBS ОЗОН − отмены"
  },
  {
    key: "ozonMonthBuyout",
    targetHeader: "Факт выкупа месяц",
    sourceSheet: "UNIT API",
    sourceArticleColumn: "A",
    sourceValueColumns: ["M"],
    subtractValueColumns: [],
    note: "UNIT ШТ; фактические выкупы Ozon"
  },
  {
    key: "wbStock",
    targetHeader: "ВБ всего",
    sourceType: "wbAnalyticsStocks",
    sourceMapKey: "wbStockTotalApi",
    sourceSheet: null,
    sourceArticleColumn: null,
    sourceValueColumns: [],
    subtractValueColumns: [],
    note: "WB Analytics; metrics.stockCount = «Всего находится на складах»"
  },
  {
    key: "wbStockObor",
    targetHeader: "ВБ ост",
    sourceType: "wbAnalyticsWarehouseStocks",
    sourceMapKey: "wbStockWbRfApi",
    sourceSheet: null,
    sourceArticleColumn: null,
    sourceValueColumns: [],
    subtractValueColumns: [],
    warehouseName: OBOR_WB_STOCK_SECOND_WAREHOUSE_NAME,
    note: "WB Analytics groups; warehouses[].quantity по складу «Склад WB РФ»"
  },
  {
    key: "wbMonthWithdrawal",
    targetHeader: "ВБ Ух",
    sourceSheet: "ТЕСТ",
    sourceArticleColumn: "A",
    sourceValueColumns: ["AV", "AW"],
    subtractValueColumns: [],
    note: "Продажи FBO + FBS ВБ без отмен"
  },
  {
    key: "wbMonthBuyout",
    targetHeader: "ВБ факт выкуп месяц",
    sourceSheet: "UNIT WB",
    sourceArticleColumn: "A",
    sourceValueColumns: ["AP"],
    subtractValueColumns: [],
    note: "ВЫКУП ШТ API"
  }
];

/**
 * Полностью пересчитать и записать семь активных целевых показателей.
 * Запись начинается только после успешного чтения всех источников и API.
 */
function calculateOborValues() {
  const spreadsheet = SpreadsheetApp.openById(OBOR_VALUES_SPREADSHEET_ID);
  const targetSheet = spreadsheet.getSheetByName(OBOR_VALUES_TARGET_SHEET);
  if (!targetSheet) throw new Error("Не найден лист: " + OBOR_VALUES_TARGET_SHEET);

  const targetHeaderMap = getOborHeaderMap_(targetSheet);
  validateOborTargetHeaders_(targetHeaderMap);
  validateOborSources_(spreadsheet);

  const sourceMaps = {};
  const sourceMapCache = {};
  OBOR_VALUE_CONFIG.forEach(item => {
    if (item.sourceType === "wbAnalyticsStocks" || item.sourceType === "wbAnalyticsWarehouseStocks") {
      const sourceMapKey = item.sourceMapKey || item.key;
      if (!Object.prototype.hasOwnProperty.call(sourceMapCache, sourceMapKey)) {
        sourceMapCache[sourceMapKey] = item.sourceType === "wbAnalyticsWarehouseStocks"
          ? fetchOborWbWarehouseStockByArticle_(item.warehouseName)
          : fetchOborWbStockByArticle_();
      }
      sourceMaps[item.key] = sourceMapCache[sourceMapKey];
      return;
    }
    if (!item.sourceSheet) return;
    sourceMaps[item.key] = buildOborValueMap_(spreadsheet, item);
  });

  // API читается до первой записи, чтобы ошибка API не оставила полурасчёт.
  // Временно отключено по запросу: не вызывать Ozon FBS API для КГТ СДЭК.
  // sourceMaps.cdekStock = fetchOborCdekStockByArticle_(spreadsheet);

  const targetLastRow = targetSheet.getLastRow();
  if (targetLastRow < 2) {
    Logger.log("ОБОР: нет строк для записи");
    return { rows: 0, nonZero: {} };
  }

  const targetArticles = targetSheet
    .getRange(2, 1, targetLastRow - 1, 1)
    .getValues();
  const nonZero = {};

  OBOR_VALUE_CONFIG.forEach(item => {
    const valueMap = sourceMaps[item.key] || {};
    const values = targetArticles.map(row => {
      const article = normalizeOborArticle_(row[0]);
      if (!article) return [""];
      // API агрегирует строки по базовому артикулу: 23348-1 → 23348.
      const parsed = parseOborArticle_(article);
      const value = roundOborValue_(valueMap[parsed.base] || 0);
      if (Number(value) !== 0) nonZero[item.key] = (nonZero[item.key] || 0) + 1;
      return [value];
    });

    const targetColumn = targetHeaderMap[normalizeOborHeader_(item.targetHeader)];
    // Перезаписываем заголовок обычным текстом — это удаляет старую формулу из J1.
    targetSheet.getRange(1, targetColumn).setValue(item.targetHeader);
    targetSheet.getRange(2, targetColumn, values.length, 1).setValues(values);

    const source = item.sourceType === "wbAnalyticsStocks"
      ? "WB Analytics products / metrics.stockCount («Всего находится на складах»)"
      : item.sourceType === "wbAnalyticsWarehouseStocks"
        ? "WB Analytics groups / warehouses[].quantity («" + item.warehouseName + "»)"
        : (item.sourceSheet || "Ozon FBS API");
    Logger.log(
      "Записано: " + item.targetHeader +
      "; источник: " + source +
      "; ненулевых строк: " + (nonZero[item.key] || 0) +
      "; " + item.note
    );
  });

  SpreadsheetApp.flush();
  Logger.log(
    "ОБОР: расчёт завершён; строк=" + (targetLastRow - 1) +
    "; СДЭК Остаток отключён"
  );
  return { rows: targetLastRow - 1, nonZero: nonZero };
}

/**
 * Обновить колонки «ВБ всего» и «ВБ ост» прямой выгрузкой WB.
 * Остальные колонки листа «ОБОР» не изменяются.
 */
function updateOborWbStockDirect() {
  const spreadsheet = SpreadsheetApp.openById(OBOR_VALUES_SPREADSHEET_ID);
  const targetSheet = spreadsheet.getSheetByName(OBOR_VALUES_TARGET_SHEET);
  if (!targetSheet) throw new Error("Не найден лист: " + OBOR_VALUES_TARGET_SHEET);

  // Целевые столбцы для этого ручного запуска зафиксированы явно: W (23) и X (24).
  const targetColumns = [
    columnToNumberObor_(OBOR_WB_STOCK_TARGET_COLUMN),
    columnToNumberObor_(OBOR_WB_STOCK_SECOND_TARGET_COLUMN)
  ];

  const totalValueMap = fetchOborWbStockByArticle_();
  const warehouseValueMap = fetchOborWbWarehouseStockByArticle_(OBOR_WB_STOCK_SECOND_WAREHOUSE_NAME);
  const targetLastRow = targetSheet.getLastRow();
  if (targetLastRow < 2) return { rows: 0, nonZero: 0 };

  const targetArticles = targetSheet
    .getRange(2, 1, targetLastRow - 1, 1)
    .getValues();
  const valuesByColumn = [totalValueMap, warehouseValueMap].map(valueMap => targetArticles.map(row => {
    const article = normalizeOborArticle_(row[0]);
    if (!article) return [""];
    // WB-ответ агрегируется по базовому артикулу, поэтому 23348-1
    // должен читать значение по ключу 23348, а не искать ключ 23348-1.
    const parsed = parseOborArticle_(article);
    return [roundOborValue_(valueMap[parsed.base] || 0)];
  }));

  targetColumns.forEach((targetColumn, index) => {
    targetSheet.getRange(2, targetColumn, valuesByColumn[index].length, 1)
      .setValues(valuesByColumn[index]);
  });
  SpreadsheetApp.flush();

  const totalNonZero = valuesByColumn[0].filter(row => Number(row[0]) !== 0).length;
  const warehouseNonZero = valuesByColumn[1].filter(row => Number(row[0]) !== 0).length;
  Logger.log(
    "ОБОР: «ВБ всего» и «ВБ ост» обновлены из разных WB Analytics-показателей" +
    "; строк=" + valuesByColumn[0].length +
    "; ненулевых W=" + totalNonZero +
    "; ненулевых X=" + warehouseNonZero
  );
  return {
    rows: valuesByColumn[0].length,
    nonZero: { total: totalNonZero, warehouse: warehouseNonZero }
  };
}

/** Совместимый короткий запуск. Также считает только значения, не формулы. */
function updateOborSummary() {
  return calculateOborValues();
}

/** Старое имя оставлено для обратной совместимости, но формулы не устанавливает. */
function installOborArrayFormulas() {
  Logger.log("installOborArrayFormulas: legacy alias → расчёт значений без формул");
  return calculateOborValues();
}

/** Проверка конфигурации без записи и без вызова API. */
function previewOborValues() {
  OBOR_VALUE_CONFIG.forEach(item => {
    const source = item.sourceType === "wbAnalyticsStocks"
      ? "прямой WB Analytics stocks / metrics.stockCount («Склад WB РФ»)"
      : (item.sourceSheet || "Ozon FBS API");
    Logger.log(
      item.targetHeader +
      ": " + source +
      " / " + (item.sourceValueColumns.join("+") || OBOR_CDEK_WAREHOUSE_NAME) +
      "; " + item.note
    );
  });
  Logger.log("Расчёт выполняется скриптом; формулы не используются");
}

/** Старое имя preview оставлено только как совместимый алиас. */
function previewOborArrayFormulas() {
  return previewOborValues();
}

function buildOborValueMap_(spreadsheet, item) {
  const sheet = spreadsheet.getSheetByName(item.sourceSheet);
  if (!sheet) throw new Error("Не найден лист источника: " + item.sourceSheet);

  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return {};

  const maxColumn = Math.max(
    columnToNumberObor_(item.sourceArticleColumn),
    ...item.sourceValueColumns.map(columnToNumberObor_),
    ...(item.subtractValueColumns || []).map(columnToNumberObor_)
  );
  const rows = sheet.getRange(2, 1, lastRow - 1, maxColumn).getValues();
  const articleIndex = columnToNumberObor_(item.sourceArticleColumn) - 1;
  const valueIndexes = item.sourceValueColumns.map(column => columnToNumberObor_(column) - 1);
  const subtractIndexes = (item.subtractValueColumns || [])
    .map(column => columnToNumberObor_(column) - 1);
  const result = {};

  rows.forEach(row => {
    const article = normalizeOborArticle_(row[articleIndex]);
    if (!article) return;

    const parsed = parseOborArticle_(article);
    const value = valueIndexes.reduce((sum, index) => {
      return sum + parseOborNumber_(row[index]);
    }, 0);
    const subtractValue = subtractIndexes.reduce((sum, index) => {
      return sum + parseOborNumber_(row[index]);
    }, 0);
    const multiplier = item.applyArticleMultiplier === false ? 1 : parsed.multiplier;
    result[parsed.base] = (result[parsed.base] || 0)
      + Math.max(0, value - subtractValue) * multiplier;
  });

  return result;
}

/**
 * Получить показатель «Всего находится на складах» через WB Analytics API
 * и подготовить источник для «ВБ всего».
 *
 * В актуальном ответе WB: vendorCode = «Артикул продавца»,
 * metrics.stockCount = «Всего находится на складах» при stockType="wb".
 */
function fetchOborWbStockByArticle_() {
  const dateRange = getOborWbAnalyticsDateRange_();
  const allItems = [];
  let offset = 0;

  while (true) {
    const response = retryFetch(
      wbAnalyticsStocksURL(),
      {
        method: "post",
        headers: wbAnalyticsHeaders(),
        contentType: "application/json",
        payload: JSON.stringify({
          nmIDs: [],
          currentPeriod: {
            start: dateRange.dateFrom,
            end: dateRange.dateTo
          },
          stockType: "wb",
          skipDeletedNm: false,
          availabilityFilters: [],
          orderBy: {
            field: "ordersCount",
            mode: "desc"
          },
          limit: OBOR_WB_ANALYTICS_PAGE_LIMIT,
          offset: offset
        }),
        muteHttpExceptions: true
      },
      3
    );

    if (!response) {
      throw new Error("WB Analytics stocks: пустой ответ API");
    }

    const responseCode = response.getResponseCode();
    const responseText = response.getContentText() || "";
    if (responseCode < 200 || responseCode >= 300) {
      throw new Error(
        "WB Analytics stocks: HTTP " + responseCode + ": " +
        responseText.substring(0, 300)
      );
    }

    let payload;
    try {
      payload = JSON.parse(responseText);
    } catch (error) {
      throw new Error("WB Analytics stocks: ответ не является JSON: " + error.message);
    }

    const items = payload && payload.data && Array.isArray(payload.data.items)
      ? payload.data.items
      : null;
    if (!items) {
      throw new Error("WB Analytics stocks: в data.items ожидался массив");
    }

    allItems.push.apply(allItems, items);
    if (items.length < OBOR_WB_ANALYTICS_PAGE_LIMIT) break;

    offset += items.length;
    Utilities.sleep(OBOR_WB_ANALYTICS_REQUEST_INTERVAL_MS);
  }

  const aggregated = aggregateOborWbStockRows_(allItems);
  Logger.log(
    "WB Analytics stocks: товаров=" + allItems.length +
    "; валидных артикулов=" + aggregated.validRows +
    "; агрегированных артикулов=" + Object.keys(aggregated.values).length
  );
  return aggregated.values;
}

function fetchOborWbWarehouseStockByArticle_(warehouseName) {
  if (!warehouseName) throw new Error("WB Analytics groups: не задано имя склада");

  const dateRange = getOborWbAnalyticsDateRange_();
  const allItems = [];
  let offset = 0;

  while (true) {
    const response = retryFetch(
      wbAnalyticsStocksGroupsURL(),
      {
        method: "post",
        headers: wbAnalyticsHeaders(),
        contentType: "application/json",
        payload: JSON.stringify({
          nmIDs: [],
          currentPeriod: {
            start: dateRange.dateFrom,
            end: dateRange.dateTo
          },
          stockType: "wb",
          skipDeletedNm: false,
          availabilityFilters: [],
          orderBy: {
            field: "ordersCount",
            mode: "desc"
          },
          limit: OBOR_WB_ANALYTICS_PAGE_LIMIT,
          offset: offset
        }),
        muteHttpExceptions: true
      },
      3
    );

    if (!response) throw new Error("WB Analytics groups: пустой ответ API");

    const responseCode = response.getResponseCode();
    const responseText = response.getContentText() || "";
    if (responseCode < 200 || responseCode >= 300) {
      throw new Error(
        "WB Analytics groups: HTTP " + responseCode + ": " +
        responseText.substring(0, 300)
      );
    }

    let payload;
    try {
      payload = JSON.parse(responseText);
    } catch (error) {
      throw new Error("WB Analytics groups: ответ не является JSON: " + error.message);
    }

    const items = payload && payload.data && Array.isArray(payload.data.items)
      ? payload.data.items
      : null;
    if (!items) throw new Error("WB Analytics groups: в data.items ожидался массив");

    allItems.push.apply(allItems, items);
    if (items.length < OBOR_WB_ANALYTICS_PAGE_LIMIT) break;

    offset += items.length;
    Utilities.sleep(OBOR_WB_ANALYTICS_REQUEST_INTERVAL_MS);
  }

  const aggregated = aggregateOborWbWarehouseStockRows_(allItems, warehouseName);
  Logger.log(
    "WB Analytics groups: склад=" + warehouseName +
    "; товаров=" + allItems.length +
    "; валидных артикулов=" + aggregated.validRows +
    "; агрегированных артикулов=" + Object.keys(aggregated.values).length
  );
  return aggregated.values;
}

function getOborWbAnalyticsDateRange_() {
  const dateTo = new Date();
  dateTo.setDate(dateTo.getDate() - 1);
  const dateFrom = new Date(dateTo);
  dateFrom.setDate(dateFrom.getDate() - 30);
  const timeZone = Session.getScriptTimeZone() || "Europe/Moscow";

  return {
    dateFrom: Utilities.formatDate(dateFrom, timeZone, "yyyy-MM-dd"),
    dateTo: Utilities.formatDate(dateTo, timeZone, "yyyy-MM-dd")
  };
}

/** Чистая агрегация WB-строк, вынесенная для локальной проверки без API. */
function aggregateOborWbStockRows_(rows) {
  const values = {};
  let validRows = 0;

  (Array.isArray(rows) ? rows : []).forEach(item => {
    const article = normalizeOborArticle_(
      item && (item.vendorCode || item.supplierArticle)
    );
    if (!article) return;

    const parsed = parseOborArticle_(article);
    const quantity = item && item.metrics &&
      Object.prototype.hasOwnProperty.call(item.metrics, "stockCount")
      ? item.metrics.stockCount
      : item && item.quantity;
    const stock = Math.max(0, parseOborNumber_(quantity));
    values[parsed.base] = (values[parsed.base] || 0) + stock * parsed.multiplier;
    validRows++;
  });

  return { values: values, validRows: validRows };
}

function aggregateOborWbWarehouseStockRows_(rows, warehouseName) {
  const values = {};
  let validRows = 0;

  (Array.isArray(rows) ? rows : []).forEach(item => {
    const article = normalizeOborArticle_(
      item && (item.vendorCode || item.supplierArticle)
    );
    if (!article) return;

    const parsed = parseOborArticle_(article);
    const directWarehouses = item && Array.isArray(item.warehouses)
      ? item.warehouses
      : [];
    const groupedWarehouses = item && Array.isArray(item.groups)
      ? item.groups.reduce((all, group) => all.concat(
        Array.isArray(group && group.warehouses) ? group.warehouses : []
      ), [])
      : [];
    const warehouses = directWarehouses.length > 0
      ? directWarehouses
      : groupedWarehouses;
    const stock = warehouses.reduce((sum, warehouse) => {
      if (!warehouse || warehouse.warehouseName !== warehouseName) return sum;
      return sum + Math.max(0, parseOborNumber_(warehouse.quantity));
    }, 0);

    values[parsed.base] = (values[parsed.base] || 0) + stock * parsed.multiplier;
    validRows++;
  });

  return { values: values, validRows: validRows };
}

/**
 * Собрать остаток КГТ СДЭК из Ozon FBS API и агрегировать по базовому артикулу.
 * В API используется поле present, без reserved.
 */
function fetchOborCdekStockByArticle_(spreadsheet) {
  const sourceSheet = spreadsheet.getSheetByName(OBOR_VALUES_SOURCE_SHEET);
  if (!sourceSheet) throw new Error("Не найден лист: " + OBOR_VALUES_SOURCE_SHEET);

  const lastRow = sourceSheet.getLastRow();
  if (lastRow < 2) return {};

  // A:V: артикул в A, SKU Ozon в V.
  const rows = sourceSheet.getRange(2, 1, lastRow - 1, 22).getValues();
  const skuEntries = [];
  const seenSkus = {};

  rows.forEach(row => {
    const article = normalizeOborArticle_(row[0]);
    const sku = normalizeOborSku_(row[21]);
    if (!article || !sku || seenSkus[sku]) return;

    const parsed = parseOborArticle_(article);
    skuEntries.push({
      sku: sku,
      baseArticle: parsed.base,
      multiplier: parsed.multiplier
    });
    seenSkus[sku] = true;
  });

  const stockBySku = {};
  let requestCount = 0;
  let lastRequestAt = 0;

  for (let offset = 0; offset < skuEntries.length; offset += OBOR_CDEK_BATCH_SIZE) {
    const batch = skuEntries.slice(offset, offset + OBOR_CDEK_BATCH_SIZE);
    let cursor = "";
    let hasNext = true;

    while (hasNext) {
      const payload = { sku: batch.map(item => item.sku), limit: 1000 };
      if (cursor) payload.cursor = cursor;

      const now = Date.now();
      if (lastRequestAt && now - lastRequestAt < OBOR_CDEK_REQUEST_INTERVAL_MS) {
        Utilities.sleep(OBOR_CDEK_REQUEST_INTERVAL_MS - (now - lastRequestAt));
      }

      const response = retryFetch(OBOR_CDEK_STOCKS_URL, {
        method: "post",
        contentType: "application/json",
        headers: ozonHeaders(),
        payload: JSON.stringify(payload),
        muteHttpExceptions: true
      }, 3);
      lastRequestAt = Date.now();
      requestCount++;

      if (!response) throw new Error("Ozon CDEK FBS: пустой ответ API");
      const code = response.getResponseCode();
      if (code < 200 || code >= 300) {
        throw new Error(
          "Ozon CDEK FBS: HTTP " + code + ": " +
          response.getContentText().substring(0, 500)
        );
      }

      const data = JSON.parse(response.getContentText() || "{}");
      (data.products || []).forEach(product => {
        if (String(product.warehouse_id) !== String(OBOR_CDEK_WAREHOUSE_ID)) return;
        const sku = normalizeOborSku_(product.sku);
        if (!sku) return;
        stockBySku[sku] = (stockBySku[sku] || 0) + (Number(product.present) || 0);
      });

      cursor = data.cursor || "";
      hasNext = data.has_next === true && !!cursor;
    }
  }

  const result = {};
  skuEntries.forEach(entry => {
    const stock = stockBySku[entry.sku] || 0;
    result[entry.baseArticle] =
      (result[entry.baseArticle] || 0) + stock * entry.multiplier;
  });

  Logger.log(
    "СДЭК API: warehouse_id=" + OBOR_CDEK_WAREHOUSE_ID +
    "; запросов=" + requestCount +
    "; SKU с остатком=" + Object.keys(stockBySku).length
  );
  return result;
}

function validateOborTargetHeaders_(targetHeaderMap) {
  const missing = OBOR_VALUE_CONFIG
    .filter(item => !targetHeaderMap[normalizeOborHeader_(item.targetHeader)])
    .map(item => item.targetHeader);
  if (missing.length) throw new Error("В ОБОР не найдены заголовки: " + missing.join(", "));
}

function validateOborSources_(spreadsheet) {
  OBOR_VALUE_CONFIG.forEach(item => {
    if (!item.sourceSheet) return;
    const sheet = spreadsheet.getSheetByName(item.sourceSheet);
    if (!sheet) throw new Error("Не найден лист источника: " + item.sourceSheet);
    const required = [item.sourceArticleColumn]
      .concat(item.sourceValueColumns)
      .concat(item.subtractValueColumns || []);
    required.forEach(column => {
      if (columnToNumberObor_(column) > sheet.getLastColumn()) {
        throw new Error(
          "В " + item.sourceSheet + " нет колонки " + column +
          " для " + item.targetHeader
        );
      }
    });
  });
}

function getOborHeaderMap_(sheet) {
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getDisplayValues()[0];
  const map = {};
  headers.forEach((header, index) => {
    const key = normalizeOborHeader_(header);
    if (key && !map[key]) map[key] = index + 1;
  });
  return map;
}

function normalizeOborHeader_(value) {
  return String(value == null ? "" : value).replace(/\s+/g, " ").trim().toLowerCase();
}

function normalizeOborArticle_(value) {
  return String(value == null ? "" : value)
    .replace(/[\s\u00a0]/g, "")
    .trim();
}

function normalizeOborSku_(value) {
  return String(value == null ? "" : value)
    .replace(/[\s\u00a0]/g, "")
    .replace(/\.0$/, "")
    .trim();
}

function parseOborArticle_(article) {
  const match = String(article).match(/^(.*)-([0-9]+)$/);
  if (!match) return { base: article, multiplier: 1 };
  return { base: match[1], multiplier: Number(match[2]) || 1 };
}

function parseOborNumber_(value) {
  if (value === null || value === undefined || value === "") return 0;
  if (typeof value === "number") return isFinite(value) ? value : 0;
  const normalized = String(value)
    .replace(/[\s\u00a0]/g, "")
    .replace(/%/g, "")
    .replace(/,/g, ".");
  const parsed = Number(normalized);
  return isFinite(parsed) ? parsed : 0;
}

function roundOborValue_(value) {
  return Math.round((Number(value) || 0) * 100) / 100;
}

function columnToNumberObor_(column) {
  return String(column).toUpperCase().split("").reduce((number, letter) => {
    return number * 26 + letter.charCodeAt(0) - 64;
  }, 0);
}
