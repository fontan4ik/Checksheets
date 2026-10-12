// Контекст существует только внутри WbMain/resumeWbMain. Ручные функции
// используют прежний режим; checkpoint сжат и хранится в общем скрытом служебном листе.
var wbMainContext_ = null;

/**
 * _WB_TRIGGER_STATE — скрытый служебный лист с фиксированной структурой:
 * A1 = номер шага, A2 = число частей, A3:A = gzip/base64 по 32000 символов.
 * Это документированное исключение для служебного layout: пользовательских
 * заголовков и данных здесь нет. Доступ одинаков для обоих владельцев триггеров.
 */
function loadWbMainState_(step) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('_WB_TRIGGER_STATE');
  if (!sheet || sheet.getLastRow() < 2) return {};
  const metadata = sheet.getRange(1, 1, 2, 1).getValues();
  if (Number(metadata[0][0]) !== step) throw new Error('WB checkpoint принадлежит другому шагу');
  const count = Number(metadata[1][0]);
  if (!Number.isSafeInteger(count) || count < 1) throw new Error('WB checkpoint имеет неверное число частей');
  const chunks = sheet.getRange(3, 1, count, 1).getValues().map(row => row[0]);
  if (chunks.some(chunk => typeof chunk !== 'string' || !chunk)) throw new Error('WB checkpoint неполон');
  return JSON.parse(Utilities.ungzip(Utilities.newBlob(Utilities.base64Decode(chunks.join('')))).getDataAsString());
}

function saveWbMainState_(state) {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = spreadsheet.getSheetByName('_WB_TRIGGER_STATE');
  if (!sheet) {
    sheet = spreadsheet.insertSheet('_WB_TRIGGER_STATE');
    sheet.hideSheet();
  }
  const encoded = Utilities.base64Encode(Utilities.gzip(Utilities.newBlob(JSON.stringify(state))).getBytes());
  const size = 32000; // Меньше лимита 50000 символов в ячейке.
  const count = Math.ceil(encoded.length / size);
  const values = [[wbMainContext_.step], [count]];
  for (let i = 0; i < count; i++) values.push([encoded.slice(i * size, (i + 1) * size)]);
  if (sheet.getMaxRows() < values.length) sheet.insertRowsAfter(sheet.getMaxRows(), values.length - sheet.getMaxRows());
  // Метаданные и части записываются вместе; остаток старых частей игнорируется.
  sheet.getRange(1, 1, values.length, 1).setValues(values);
}

function clearWbMainState_() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('_WB_TRIGGER_STATE');
  if (sheet) sheet.clearContents();
}

function wbMainState_(key, initial) {
  if (!wbMainContext_) return initial;
  if (!wbMainContext_.state[key]) wbMainContext_.state[key] = initial;
  return wbMainContext_.state[key];
}

function wbMainPause_(message, delayMs) {
  const error = new Error(message);
  error.wbMainYield = true;
  error.delayMs = delayMs || 60000;
  throw error;
}

function wbMainCheckBudget_() {
  // Резерв на последний HTTP запрос, запись таблицы и сохранение checkpoint.
  if (wbMainContext_ && Date.now() > wbMainContext_.deadline - 60000) {
    wbMainPause_('Закончился бюджет текущего запуска');
  }
}

function wbMainFetch_(url, options) {
  if (!wbMainContext_) return retryFetch(url, options);
  wbMainCheckBudget_();
  wbMainContext_.beforeRequest = JSON.stringify(wbMainContext_.state);
  let response;
  try {
    response = UrlFetchApp.fetch(url, Object.assign({}, options, { muteHttpExceptions: true }));
  } catch (error) {
    wbMainPause_("Временная ошибка сети: " + error.message);
  }
  const code = response.getResponseCode();
  if (code === 429 || code >= 500) {
    wbMainPause_('Временный HTTP ' + code, Math.max(60000, retryAfterDelayMs_(response) || 60000));
  }
  if (code < 200 || code >= 300) throw new Error('WB HTTP ' + code + ': ' + response.getContentText().substring(0, 200));
  return response;
}

/** Bulk write avoids thousands of individual range calls on sparse WB matches. */
function wbMainWriteMasked_(sheet, column, values, mask) {
  if (!wbMainContext_) return writeMaskedColumnValues_(sheet, column, values, mask);
  if (values.length !== mask.length) throw new Error('WB masked write: размеры не совпадают');
  if (!values.length) return 0;
  const range = sheet.getRange(2, column, values.length, 1);
  const current = range.getValues();
  const formulas = range.getFormulas();
  let count = 0;
  const merged = current.map((value, index) => {
    if (mask[index]) { count++; return values[index]; }
    return formulas[index][0] ? [formulas[index][0]] : value;
  });
  if (count) range.setValues(merged);
  return count;
}
