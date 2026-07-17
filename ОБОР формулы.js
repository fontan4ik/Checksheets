/**
 * Расчёт показателей листа «ОБОР» без формул.
 *
 * Скрипт читает источники, агрегирует значения по базовому артикулу,
 * учитывает числовой суффикс после последнего дефиса и записывает готовые
 * значения в ОБОР!J/K/N/O/W/Y/Z.
 *
 * Пример: 55222-10 и 55222-5 превращаются в 10 × значение и 5 × значение.
 *
 * Источники:
 * - J «Озон ост»            ← ТЕСТ!F, Остаток ФБО ОЗОН
 * - K «СДЭК Остаток»        ← Ozon FBS API, склад «КГТ СДЭК»
 * - N «Уход месяц»          ← ТЕСТ!AQ+AR−BH, продажи Ozon FBO+FBS без отмен
 * - O «Факт выкупа месяц»   ← UNIT API!M, UNIT ШТ
 * - W «ВБ ост»              ← ТЕСТ!O+P, остатки WB FBO+FBS с множителем упаковки
 * - Y «ВБ Ух»               ← ТЕСТ!AV+AW, продажи WB FBO+FBS
 * - Z «ВБ факт выкуп месяц» ← UNIT WB!AP, ВЫКУП ШТ API
 *
 * Основной ручной запуск: calculateOborValues().
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
  {
    key: "cdekStock",
    targetHeader: "СДЭК Остаток",
    sourceSheet: null,
    sourceArticleColumn: null,
    sourceValueColumns: [],
    note: "Ozon FBS API / КГТ СДЭК"
  },
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
    targetHeader: "ВБ ост",
    sourceSheet: "ТЕСТ",
    sourceArticleColumn: "A",
    sourceValueColumns: ["O", "P"],
    subtractValueColumns: [],
    note: "Остаток ФБО ВБ + Остаток ФБС ВБ; с множителем упаковки"
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
 * Полностью пересчитать и записать семь целевых показателей.
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
  OBOR_VALUE_CONFIG.forEach(item => {
    if (!item.sourceSheet) return;
    sourceMaps[item.key] = buildOborValueMap_(spreadsheet, item);
  });

  // API читается до первой записи, чтобы ошибка API не оставила полурасчёт.
  sourceMaps.cdekStock = fetchOborCdekStockByArticle_(spreadsheet);

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
      const value = article ? roundOborValue_(valueMap[article] || 0) : "";
      if (Number(value) !== 0) nonZero[item.key] = (nonZero[item.key] || 0) + 1;
      return [value];
    });

    const targetColumn = targetHeaderMap[normalizeOborHeader_(item.targetHeader)];
    // Перезаписываем заголовок обычным текстом — это удаляет старую формулу из J1.
    targetSheet.getRange(1, targetColumn).setValue(item.targetHeader);
    targetSheet.getRange(2, targetColumn, values.length, 1).setValues(values);

    Logger.log(
      "Записано: " + item.targetHeader +
      "; источник: " + (item.sourceSheet || "Ozon FBS API") +
      "; ненулевых строк: " + (nonZero[item.key] || 0) +
      "; " + item.note
    );
  });

  SpreadsheetApp.flush();
  Logger.log(
    "ОБОР: расчёт завершён; строк=" + (targetLastRow - 1) +
    "; склад СДЭК=" + OBOR_CDEK_WAREHOUSE_NAME +
    " (" + OBOR_CDEK_WAREHOUSE_ID + ")"
  );
  return { rows: targetLastRow - 1, nonZero: nonZero };
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
    Logger.log(
      item.targetHeader +
      ": " + (item.sourceSheet || "Ozon FBS API") +
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
