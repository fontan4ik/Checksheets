/**
 * Сводные показатели для листа «ОБОР».
 *
 * Формулы агрегируют строки по базовому артикулу. Если в источнике есть
 * 55222-10 и 55222-5, значения умножаются на 10 и 5 соответственно.
 *
 * Источники формул:
 * - J  «Озон ост»              ← ТЕСТ!F, Остаток ФБО ОЗОН
 * - N  «Уход месяц»            ← ТЕСТ!I, Уход Мес ОЗОН
 * - O  «Факт выкупа месяц»     ← ТЕСТ!AQ+AR, продажи Ozon FBO+FBS
 * - W  «ВБ ост»                ← ТЕСТ!O+P, остатки WB FBO+FBS
 * - Y  «ВБ Ух»                 ← ТЕСТ!R, Уход Мес ВБ
 * - Z  «ВБ факт выкуп месяц»   ← UNIT WB!AP, ВЫКУП ШТ API
 *
 * Источник API:
 * - K  «СДЭК Остаток»          ← Ozon FBS warehouse «КГТ СДЭК»
 *                                  warehouse_id = 1020002321437000
 *
 * Скрипт не создаёт триггеры и не выполняет API-запись при загрузке файла.
 * Запускать функции вручную после проверки/одобрения.
 */

const OBOR_FORMULA_TARGET_SHEET = "ОБОР";
const OBOR_CDEK_SOURCE_SHEET = "ТЕСТ";
const OBOR_CDEK_WAREHOUSE_NAME = "КГТ СДЭК";
const OBOR_CDEK_WAREHOUSE_ID = 1020002321437000;
const OBOR_CDEK_STOCKS_URL = "https://api-seller.ozon.ru/v2/product/info/stocks-by-warehouse/fbs";
const OBOR_CDEK_BATCH_SIZE = 100;
const OBOR_CDEK_REQUEST_INTERVAL_MS = 1000;

/** Формульные колонки. Колонка K обновляется отдельной API-функцией. */
const OBOR_FORMULA_CONFIG = [
  {
    targetHeader: "Озон ост",
    sourceSheet: "ТЕСТ",
    sourceArticleColumn: "A",
    sourceColumns: ["F"],
    note: "Остаток ФБО ОЗОН"
  },
  {
    targetHeader: "Уход месяц",
    sourceSheet: "ТЕСТ",
    sourceArticleColumn: "A",
    sourceColumns: ["I"],
    note: "Уход Мес ОЗОН"
  },
  {
    targetHeader: "Факт выкупа месяц",
    sourceSheet: "ТЕСТ",
    sourceArticleColumn: "A",
    sourceColumns: ["AQ", "AR"],
    note: "Продажи штуки месяц FBO + FBS ОЗОН; выбран по сравнению со старым ОБОР"
  },
  {
    targetHeader: "ВБ ост",
    sourceSheet: "ТЕСТ",
    sourceArticleColumn: "A",
    sourceColumns: ["O", "P"],
    note: "Остаток ФБО ВБ + Остаток ФБС ВБ"
  },
  {
    targetHeader: "ВБ Ух",
    sourceSheet: "ТЕСТ",
    sourceArticleColumn: "A",
    sourceColumns: ["R"],
    note: "Уход Мес ВБ"
  },
  {
    targetHeader: "ВБ факт выкуп месяц",
    sourceSheet: "UNIT WB",
    sourceArticleColumn: "A",
    sourceColumns: ["AP"],
    note: "ВЫКУП ШТ API; выбран по сравнению со старым ОБОР"
  }
];

/**
 * Установить шесть формул в строку 1 листа «ОБОР».
 * Перед установкой очищаются только строки 2+ этих шести колонок.
 */
function installOborArrayFormulas() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const targetSheet = spreadsheet.getSheetByName(OBOR_FORMULA_TARGET_SHEET);
  if (!targetSheet) throw new Error("Не найден лист: " + OBOR_FORMULA_TARGET_SHEET);

  const targetHeaderMap = getOborHeaderMap_(targetSheet);
  const missingTargets = OBOR_FORMULA_CONFIG
    .filter(item => !targetHeaderMap[normalizeOborHeader_(item.targetHeader)])
    .map(item => item.targetHeader);
  if (missingTargets.length) {
    throw new Error("В ОБОР не найдены заголовки: " + missingTargets.join(", "));
  }

  OBOR_FORMULA_CONFIG.forEach(item => validateOborFormulaSource_(spreadsheet, item));

  const targetColumns = OBOR_FORMULA_CONFIG.map(item =>
    targetHeaderMap[normalizeOborHeader_(item.targetHeader)]
  );
  const lastRow = targetSheet.getLastRow();
  if (lastRow >= 2) {
    targetColumns.forEach(column => {
      targetSheet.getRange(2, column, lastRow - 1, 1).clearContent();
    });
  }

  OBOR_FORMULA_CONFIG.forEach(item => {
    const targetColumn = targetHeaderMap[normalizeOborHeader_(item.targetHeader)];
    const formula = buildOborArrayFormula_(item);
    targetSheet.getRange(1, targetColumn).setFormula(formula);
    Logger.log(
      "Установлено: " + item.targetHeader +
      " ← " + item.sourceSheet + "!" + item.sourceColumns.join("+") +
      "; " + item.note
    );
  });

  SpreadsheetApp.flush();
  Logger.log("Готово: установлено формул — " + OBOR_FORMULA_CONFIG.length);
}

/**
 * Получить остаток из Ozon FBS по складу «КГТ СДЭК» и записать в ОБОР!K.
 * Используется только present, как в существующей функции FBS-остатков.
 */
function updateOborCdekStock() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sourceSheet = spreadsheet.getSheetByName(OBOR_CDEK_SOURCE_SHEET);
  const targetSheet = spreadsheet.getSheetByName(OBOR_FORMULA_TARGET_SHEET);
  if (!sourceSheet) throw new Error("Не найден лист: " + OBOR_CDEK_SOURCE_SHEET);
  if (!targetSheet) throw new Error("Не найден лист: " + OBOR_FORMULA_TARGET_SHEET);

  const targetHeaderMap = getOborHeaderMap_(targetSheet);
  const targetColumn = targetHeaderMap[normalizeOborHeader_("СДЭК Остаток")];
  if (!targetColumn) throw new Error("В ОБОР не найден заголовок: СДЭК Остаток");

  const sourceLastRow = sourceSheet.getLastRow();
  const targetLastRow = targetSheet.getLastRow();
  if (sourceLastRow < 2 || targetLastRow < 2) {
    Logger.log("Нет строк для обновления СДЭК-остатка");
    return;
  }

  // A:V: артикул в A, SKU Ozon в V.
  const sourceRows = sourceSheet.getRange(2, 1, sourceLastRow - 1, 22).getValues();
  const skuEntries = [];
  const seenSkus = {};
  sourceRows.forEach(row => {
    const article = normalizeOborArticle_(row[0]);
    const sku = normalizeOborSku_(row[21]);
    if (!article || !sku || seenSkus[sku]) return;

    const parsed = parseOborArticle_(article);
    skuEntries.push({ sku: sku, baseArticle: parsed.base, multiplier: parsed.multiplier });
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
        throw new Error("Ozon CDEK FBS: HTTP " + code + ": " + response.getContentText().substring(0, 500));
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

  const stockByArticle = {};
  skuEntries.forEach(entry => {
    const stock = stockBySku[entry.sku] || 0;
    stockByArticle[entry.baseArticle] =
      (stockByArticle[entry.baseArticle] || 0) + stock * entry.multiplier;
  });

  const targetArticles = targetSheet.getRange(2, 1, targetLastRow - 1, 1).getValues();
  const output = targetArticles.map(row => {
    const article = normalizeOborArticle_(row[0]);
    return [article ? (stockByArticle[article] || 0) : ""];
  });

  // Записываем только после полного успешного чтения всех API-батчей.
  targetSheet.getRange(2, targetColumn, output.length, 1).setValues(output);
  SpreadsheetApp.flush();

  const nonZero = output.filter(row => Number(row[0]) > 0).length;
  const total = output.reduce((sum, row) => sum + (Number(row[0]) || 0), 0);
  Logger.log(
    "КГТ СДЭК: warehouse_id=" + OBOR_CDEK_WAREHOUSE_ID +
    ", API-запросов=" + requestCount +
    ", ненулевых строк=" + nonZero +
    ", сумма=" + total
  );
}

/** Обновить формулы и API-остаток. Триггер не создаётся. */
function updateOborSummary() {
  installOborArrayFormulas();
  updateOborCdekStock();
}

/** Проверка без записи: источники и длины формул. */
function previewOborArrayFormulas() {
  OBOR_FORMULA_CONFIG.forEach(item => {
    const formula = buildOborArrayFormula_(item);
    Logger.log(
      item.targetHeader +
      ": " + item.sourceSheet + "!" + item.sourceColumns.join("+") +
      "; длина формулы=" + formula.length +
      "; " + item.note
    );
  });
  Logger.log("API-источник СДЭК: " + OBOR_CDEK_WAREHOUSE_NAME + " / " + OBOR_CDEK_WAREHOUSE_ID);
}

/**
 * Формула строит агрегированный справочник через QUERY:
 * базовый артикул, взвешенное значение, затем VLOOKUP в ОБОР.
 */
function buildOborArrayFormula_(item) {
  const sourceSheet = quoteOborSheet_(item.sourceSheet);
  const articleRange = sourceSheet + "!$" + item.sourceArticleColumn + "$2:$" + item.sourceArticleColumn;
  const nonEmptyArticle = articleRange + "<>\"\"";
  const valueExpressions = item.sourceColumns.map(column => {
    const range = sourceSheet + "!$" + column + "$2:$" + column;
    return "IFERROR(VALUE(SUBSTITUTE(SUBSTITUTE(TO_TEXT(" + range + ");CHAR(160);\"\");\" \";\"\"));0)";
  });
  const sourceValue = valueExpressions.length === 1
    ? valueExpressions[0]
    : "(" + valueExpressions.join("+") + ")";
  const header = String(item.targetHeader).replace(/"/g, "\"\"");

  return "={\"" + header + "\";ARRAYFORMULA(LET(" +
    "srcArt;FILTER(ARRAYFORMULA(TRIM(SUBSTITUTE(TO_TEXT(" + articleRange + ");CHAR(160);\"\")));" + nonEmptyArticle + ");" +
    "srcVal;FILTER(ARRAYFORMULA(" + sourceValue + ");" + nonEmptyArticle + ");" +
    "baseArt;ARRAYFORMULA(REGEXREPLACE(srcArt;\"-[0-9]+$\";\"\"));" +
    "multiplier;ARRAYFORMULA(IFERROR(VALUE(REGEXEXTRACT(srcArt;\"-([0-9]+)$\"));1));" +
    "agg;QUERY({baseArt\\srcVal*multiplier};\"select Col1, sum(Col2) where Col1 is not null group by Col1 label sum(Col2) ''\";0);" +
    "targetArt;ARRAYFORMULA(TRIM(SUBSTITUTE(TO_TEXT($A$2:$A);CHAR(160);\"\")));" +
    "IF(targetArt=\"\";\"\";IFNA(VLOOKUP(targetArt;agg;2;FALSE);0))" +
  "))}";
}

function validateOborFormulaSource_(spreadsheet, item) {
  const sourceSheet = spreadsheet.getSheetByName(item.sourceSheet);
  if (!sourceSheet) throw new Error("Не найден лист: " + item.sourceSheet);
  const lastColumn = sourceSheet.getLastColumn();
  const requiredColumns = [item.sourceArticleColumn].concat(item.sourceColumns);
  requiredColumns.forEach(column => {
    if (columnToNumberObor_(column) > lastColumn) {
      throw new Error("В " + item.sourceSheet + " нет колонки " + column + " для " + item.targetHeader);
    }
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

function quoteOborSheet_(sheetName) {
  return "'" + String(sheetName).replace(/'/g, "''") + "'";
}

function columnToNumberObor_(column) {
  return String(column).toUpperCase().split("").reduce((number, letter) => {
    return number * 26 + letter.charCodeAt(0) - 64;
  }, 0);
}
