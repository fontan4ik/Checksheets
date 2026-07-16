/**
 * Формулы сводного листа «ОБОР».
 *
 * Источник: лист «ТЕСТ».
 * Для артикула 55222 источники 55222-10 и 55222-5 превращаются
 * в 10 × остаток и 5 × остаток соответственно, затем суммируются.
 *
 * ВАЖНО:
 * - Скрипт только устанавливает формулы в «ОБОР»; API и маркетплейсы не меняет.
 * - Перед запуском installOborArrayFormulas() очистка выполняется только
 *   в строках 2+ целевых колонок.
 * - В «ТЕСТ» нет отдельного источника «СДЭК Остаток». Конфигурация
 *   специально оставлена незаполненной и остановит установку формул,
 *   пока не будет указан правильный лист/колонка.
 * - Отдельной колонки «Факт выкупа» в «ТЕСТ» нет; используются месячные
 *   продажи FBO + FBS как ближайший доступный показатель.
 */

const OBOR_FORMULA_SOURCE_SHEET = "ТЕСТ";
const OBOR_FORMULA_TARGET_SHEET = "ОБОР";

/**
 * Карту источников легко изменить после появления отдельной колонки СДЭК
 * или API-колонки фактического выкупа.
 */
const OBOR_FORMULA_CONFIG = [
  { targetHeader: "Озон ост", sourceColumns: ["F"], note: "Остаток ФБО ОЗОН" },
  {
    targetHeader: "СДЭК Остаток",
    sourceColumns: [],
    note: "Нужно указать реальный источник: лист и колонку"
  },
  { targetHeader: "Уход месяц", sourceColumns: ["I"], note: "Уход Мес ОЗОН" },
  {
    targetHeader: "Факт выкупа месяц",
    sourceColumns: ["AQ", "AR"],
    note: "Прокси: Продажи штуки месяц FBO + FBS ОЗОН"
  },
  {
    targetHeader: "ВБ ост",
    sourceColumns: ["O", "P"],
    note: "Остаток ФБО ВБ + Остаток ФБС ВБ"
  },
  { targetHeader: "ВБ Ух", sourceColumns: ["R"], note: "Уход Мес ВБ" },
  {
    targetHeader: "ВБ факт выкуп месяц",
    sourceColumns: ["AV", "AW"],
    note: "Прокси: Продажи штуки месяц FBO + FBS ВБ"
  }
];

/**
 * Установить все семь сводных формул.
 * Запускать вручную после проверки карты источников.
 */
function installOborArrayFormulas() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const targetSheet = spreadsheet.getSheetByName(OBOR_FORMULA_TARGET_SHEET);
  const sourceSheet = spreadsheet.getSheetByName(OBOR_FORMULA_SOURCE_SHEET);

  if (!targetSheet) throw new Error("Не найден лист: " + OBOR_FORMULA_TARGET_SHEET);
  if (!sourceSheet) throw new Error("Не найден лист: " + OBOR_FORMULA_SOURCE_SHEET);

  const targetHeaderMap = getOborFormulaHeaderMap_(targetSheet);
  const sourceLastColumn = sourceSheet.getLastColumn();
  const missingTargets = OBOR_FORMULA_CONFIG
    .filter(item => !targetHeaderMap[normalizeOborFormulaHeader_(item.targetHeader)])
    .map(item => item.targetHeader);

  if (missingTargets.length) {
    throw new Error("В ОБОР не найдены заголовки: " + missingTargets.join(", "));
  }

  OBOR_FORMULA_CONFIG.forEach(item => {
    if (!item.sourceColumns || !item.sourceColumns.length) {
      throw new Error(
        "Не задан источник для «" + item.targetHeader +
        ". Укажите лист и колонку перед установкой формул."
      );
    }
    item.sourceColumns.forEach(column => {
      const columnNumber = columnToNumberOborFormula_(column);
      if (columnNumber > sourceLastColumn) {
        throw new Error(
          "В ТЕСТ нет колонки " + column + " для «" + item.targetHeader + "»"
        );
      }
    });
  });

  const targetColumns = OBOR_FORMULA_CONFIG.map(item =>
    targetHeaderMap[normalizeOborFormulaHeader_(item.targetHeader)]
  );
  const bodyLastRow = targetSheet.getLastRow();
  if (bodyLastRow >= 2) {
    targetColumns.forEach(column => {
      targetSheet.getRange(2, column, bodyLastRow - 1, 1).clearContent();
    });
  }

  OBOR_FORMULA_CONFIG.forEach(item => {
    const targetColumn = targetHeaderMap[normalizeOborFormulaHeader_(item.targetHeader)];
    const formula = buildOborArrayFormula_(item.targetHeader, item.sourceColumns);
    targetSheet.getRange(1, targetColumn).setFormula(formula);
    Logger.log(
      "Установлено: " + item.targetHeader + " → ТЕСТ!" + item.sourceColumns.join("+") +
      "; " + item.note
    );
  });

  SpreadsheetApp.flush();
  Logger.log("Готово: установлено формул — " + OBOR_FORMULA_CONFIG.length);
}

/**
 * Проверка конфигурации без изменения таблицы.
 */
function previewOborArrayFormulas() {
  OBOR_FORMULA_CONFIG.forEach(item => {
    const formula = buildOborArrayFormula_(item.targetHeader, item.sourceColumns);
    Logger.log(
      item.targetHeader +
      ": источники ТЕСТ!" + item.sourceColumns.join("+") +
      "; длина формулы=" + formula.length +
      "; " + item.note
    );
  });
}

/**
 * Создаёт формулу с одним агрегированным справочником:
 * 1) отрезает последний суффикс -число;
 * 2) умножает значение источника на этот суффикс;
 * 3) QUERY суммирует по базовому артикулу;
 * 4) VLOOKUP заполняет строки ОБОР.
 */
function buildOborArrayFormula_(targetHeader, sourceColumns) {
  if (!sourceColumns || !sourceColumns.length) {
    throw new Error(
      "Не задан источник для «" + targetHeader +
      ". Укажите лист и колонку перед построением формулы."
    );
  }
  const sourceArticleRange = "'" + OBOR_FORMULA_SOURCE_SHEET + "'!$A$2:$A";
  const nonEmptySourceArticle = sourceArticleRange + "<>\"\"";
  const sourceValueExpressions = sourceColumns.map(column => {
    const range = "'" + OBOR_FORMULA_SOURCE_SHEET + "'!$" + column + "$2:$" + column;
    return "IFERROR(VALUE(SUBSTITUTE(SUBSTITUTE(TO_TEXT(" + range + ");CHAR(160);\"\");\" \";\"\"));0)";
  });

  const sourceValue = sourceValueExpressions.length === 1
    ? sourceValueExpressions[0]
    : "(" + sourceValueExpressions.join("+") + ")";

  const quotedHeader = String(targetHeader).replace(/"/g, "\"\"");
  return "={\"" + quotedHeader + "\";ARRAYFORMULA(LET(" +
    "srcArt;FILTER(ARRAYFORMULA(TRIM(SUBSTITUTE(TO_TEXT(" + sourceArticleRange + ");CHAR(160);\"\")));" +
      nonEmptySourceArticle + ");" +
    "srcVal;FILTER(ARRAYFORMULA(" + sourceValue + ");" + nonEmptySourceArticle + ");" +
    "baseArt;ARRAYFORMULA(REGEXREPLACE(srcArt;\"-[0-9]+$\";\"\"));" +
    "multiplier;ARRAYFORMULA(IFERROR(VALUE(REGEXEXTRACT(srcArt;\"-([0-9]+)$\"));1));" +
    "agg;QUERY({baseArt\\srcVal*multiplier};\"select Col1, sum(Col2) where Col1 is not null group by Col1 label sum(Col2) ''\";0);" +
    "targetArt;ARRAYFORMULA(TRIM(SUBSTITUTE(TO_TEXT($A$2:$A);CHAR(160);\"\")));" +
    "IF(targetArt=\"\";\"\";IFNA(VLOOKUP(targetArt;agg;2;FALSE);0))" +
  "))}";
}

function getOborFormulaHeaderMap_(sheet) {
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getDisplayValues()[0];
  const map = {};
  headers.forEach((header, index) => {
    const normalized = normalizeOborFormulaHeader_(header);
    if (normalized && !map[normalized]) map[normalized] = index + 1;
  });
  return map;
}

function normalizeOborFormulaHeader_(value) {
  return String(value == null ? "" : value)
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function columnToNumberOborFormula_(column) {
  return String(column).toUpperCase().split("").reduce((number, letter) => {
    return number * 26 + letter.charCodeAt(0) - 64;
  }, 0);
}
