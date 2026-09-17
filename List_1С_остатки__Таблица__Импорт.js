// ⚠️ Замените SPREADSHEET_ID на реальный ID вашей Google Таблицы.
// ID находится в URL таблицы между /d/ и /edit:
// https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit
var SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI";

function doPost(e) {
  try {
    // Получаем JSON из тела запроса
    var jsonString = e.postData.getDataAsString();      // application/json
    var data = JSON.parse(jsonString);                  // { values: [ [...], [...], ... ] }

    // Открываем таблицу по ID — getActiveSpreadsheet() не работает в веб-приложении!
    var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    var sheet = ss.getSheetByName('1С остатки');           // имя листа

    if (!sheet) {
      return ContentService
        .createTextOutput(JSON.stringify({ error: "Лист '1С остатки' не найден" }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    // Полностью очищаем лист перед новой загрузкой
    sheet.clearContents();

    var values = data.values;
    if (values && values.length > 0) {
      sheet.getRange(1, 1, values.length, values[0].length).setValues(values);
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
