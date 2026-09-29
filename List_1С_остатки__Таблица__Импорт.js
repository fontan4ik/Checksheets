// ⚠️ Замените SPREADSHEET_ID на реальный ID вашей Google Таблицы.
// ID находится в URL таблицы между /d/ и /edit:
// https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit
var SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI";

function doPost(e) {
  try {
    // Получаем JSON из тела запроса
    var jsonString = e.postData.getDataAsString();      // application/json
    var data = JSON.parse(jsonString);                  // { values: [ [...], [...], ... ] }
    var values = data && data.values;
    if (!Array.isArray(values) || values.length < 2 || !Array.isArray(values[0]) || !values[0].length) {
      throw new Error("Неполный импорт остатков 1С: ожидаются заголовок и хотя бы одна строка товара");
    }
    var width = values[0].length;
    if (values.some(function(row) {
      return !Array.isArray(row) || row.length !== width || row.some(function(value) {
        return typeof value === "number" && !isFinite(value);
      });
    })) {
      throw new Error("Неполный импорт остатков 1С: строки имеют разную ширину или некорректные числа");
    }

    // Открываем таблицу по ID — getActiveSpreadsheet() не работает в веб-приложении!
    var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    var sheet = ss.getSheetByName('1С остатки');           // имя листа

    if (!sheet) {
      return ContentService
        .createTextOutput(JSON.stringify({ error: "Лист '1С остатки' не найден" }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    // Сначала записываем полностью проверенный снимок. Хвост старых данных
    // очищаем только после успешной записи нового прямоугольного массива.
    var previousRows = sheet.getLastRow();
    var previousColumns = sheet.getLastColumn();
    sheet.getRange(1, 1, values.length, width).setValues(values);
    if (previousRows > values.length) {
      sheet.getRange(values.length + 1, 1, previousRows - values.length, Math.max(previousColumns, width)).clearContent();
    }
    if (previousColumns > width) {
      sheet.getRange(1, width + 1, Math.max(previousRows, values.length), previousColumns - width).clearContent();
    }

    return ContentService
      .createTextOutput(JSON.stringify({ status: "OK", rows: values ? values.length : 0 }))
      .setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ error: err.message }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}
