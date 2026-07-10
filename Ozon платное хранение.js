/**
 * OZON ПЛАТНОЕ ХРАНЕНИЕ
 *
 * Заполняет:
 * - BJ (62): Хранение
 *
 * Источник данных:
 * - POST /v1/report/placement/by-products/create
 * - POST /v1/report/info
 *
 * Это тот же раздел, что на скрине:
 * FBO -> Стоимость размещения -> Скачать отчёт -> По товарам.
 */

const OZON_STORAGE_COLUMN = 62; // BJ
const OZON_STORAGE_HANDLER = "updateOzonStorageCost";
const OZON_STORAGE_REPORT_MAX_WAIT_MS = 5 * 60 * 1000;
const OZON_STORAGE_REPORT_POLL_MS = 10000;
const OZON_STORAGE_TEMP_SHEET_NAME = "defolt";

function updateOzonStorageCost() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет строк для обработки хранения");
    return;
  }

  ensureOzonStorageHeader_(sheet);

  const articlesRaw = sheet.getRange(2, 1, lastRow - 1, 1).getValues().flat();
  const skusRaw = sheet.getRange(2, 22, lastRow - 1, 1).getValues().flat();
  const rowItems = articlesRaw.map((articleValue, index) => ({
    article: normalizeOzonStorageKey_(articleValue),
    sku: normalizeOzonStorageKey_(skusRaw[index])
  }));

  const dateRange = getOzonStorageRollingDateRange_();
  Logger.log("=== ОЗОН ПЛАТНОЕ ХРАНЕНИЕ: ОТЧЁТ ПО ТОВАРАМ ===");
  Logger.log(`Период: ${dateRange.from} -> ${dateRange.to}`);

  const reportCode = createOzonPlacementByProductsReport_(dateRange.from, dateRange.to);
  if (!reportCode) return;

  const fileUrl = waitOzonReportFileUrl_(reportCode);
  if (!fileUrl) return;

  const rows = downloadAndParseOzonStorageReport_(fileUrl);
  if (!rows.length) {
    Logger.log("❌ Отчёт скачан, но строки не распознаны");
    return;
  }

  const storageMap = buildOzonStorageMapFromReport_(rows);
  const valuesToWrite = rowItems.map(item => {
    if (!item.sku && !item.article) return [""];

    const value = storageMap[item.sku] !== undefined
      ? storageMap[item.sku]
      : storageMap[item.article] || 0;

    return [roundOzonStorageMoney_(value)];
  });

  sheet.getRange(2, OZON_STORAGE_COLUMN, valuesToWrite.length, 1).setValues(valuesToWrite);

  const filledCount = valuesToWrite.filter(row => row[0] !== "" && Number(row[0]) > 0).length;
  const totalAmount = Object.values(storageMap).reduce((sum, value) => sum + (Number(value) || 0), 0);

  Logger.log(`✅ Строк в отчёте: ${rows.length}`);
  Logger.log(`✅ Позиций с хранением в отчёте: ${Object.keys(storageMap).length}`);
  Logger.log(`✅ Хранение записано в BJ: ${filledCount} строк`);
  Logger.log(`✅ Сумма по отчёту: ${roundOzonStorageMoney_(totalAmount)}`);
}

function installOzonStorageDailyTrigger() {
  deleteOzonStorageTriggers_();

  ScriptApp.newTrigger(OZON_STORAGE_HANDLER)
    .timeBased()
    .everyDays(1)
    .atHour(9)
    .nearMinute(10)
    .inTimezone(Session.getScriptTimeZone())
    .create();

  Logger.log("✅ Дневной триггер Ozon платного хранения установлен");
}

function deleteOzonStorageTriggers_() {
  const triggers = ScriptApp.getProjectTriggers();
  triggers.forEach(trigger => {
    if (trigger.getHandlerFunction() === OZON_STORAGE_HANDLER) {
      ScriptApp.deleteTrigger(trigger);
    }
  });
}

function createOzonPlacementByProductsReport_(dateFrom, dateTo) {
  const body = {
    date_from: dateFrom,
    date_to: dateTo
  };

  const options = {
    method: "post",
    contentType: "application/json",
    headers: ozonHeaders(),
    payload: JSON.stringify(body),
    muteHttpExceptions: true
  };

  const response = retryFetch(ozonPlacementByProductsReportURL(), options, 3);
  if (!response) {
    Logger.log("❌ Не удалось создать отчёт стоимости размещения");
    return null;
  }

  const code = response.getResponseCode();
  const text = response.getContentText();

  if (code !== 200) {
    Logger.log(`❌ Создание отчёта: HTTP ${code}`);
    Logger.log(text);
    return null;
  }

  const json = JSON.parse(text);
  const reportCode = json.code || json.result?.code;

  if (!reportCode) {
    Logger.log("❌ Ozon не вернул code отчёта");
    Logger.log(text);
    return null;
  }

  Logger.log(`✅ Отчёт создан, code: ${reportCode}`);
  return reportCode;
}

function waitOzonReportFileUrl_(reportCode) {
  const startedAt = Date.now();
  let attempt = 1;

  while (Date.now() - startedAt < OZON_STORAGE_REPORT_MAX_WAIT_MS) {
    const info = getOzonReportInfo_(reportCode);
    if (!info) return null;

    const status = String(info.status || info.state || "").toLowerCase();
    const fileUrl = info.file || info.file_url || info.download_url || info.url;

    Logger.log(`Отчёт ${reportCode}: попытка ${attempt}, статус ${status || "без статуса"}`);

    if (fileUrl) {
      Logger.log("✅ Ссылка на файл отчёта получена");
      return fileUrl;
    }

    if (status === "error" || status === "failed") {
      Logger.log(`❌ Ozon вернул ошибку формирования отчёта: ${JSON.stringify(info)}`);
      return null;
    }

    Utilities.sleep(OZON_STORAGE_REPORT_POLL_MS);
    attempt++;
  }

  Logger.log("❌ Истекло время ожидания готовности отчёта");
  return null;
}

function getOzonReportInfo_(reportCode) {
  const options = {
    method: "post",
    contentType: "application/json",
    headers: ozonHeaders(),
    payload: JSON.stringify({ code: reportCode }),
    muteHttpExceptions: true
  };

  const response = retryFetch(ozonReportInfoURL(), options, 3);
  if (!response) return null;

  const code = response.getResponseCode();
  const text = response.getContentText();

  if (code !== 200) {
    Logger.log(`❌ Получение report/info: HTTP ${code}`);
    Logger.log(text);
    return null;
  }

  const json = JSON.parse(text);
  return json.result || json;
}

function downloadAndParseOzonStorageReport_(fileUrl) {
  const response = UrlFetchApp.fetch(fileUrl, { muteHttpExceptions: true });
  const code = response.getResponseCode();

  if (code !== 200) {
    Logger.log(`❌ Скачивание отчёта: HTTP ${code}`);
    Logger.log(response.getContentText());
    return [];
  }

  const blob = response.getBlob();
  const bytes = blob.getBytes();
  const textStart = bytes.slice(0, 8).map(b => String.fromCharCode(b)).join("");

  if (textStart.substring(0, 2) === "PK") {
    Logger.log("Формат отчёта: XLSX");
    return parseXlsxRows_(blob);
  }

  Logger.log("Формат отчёта: CSV/TSV");
  return parseDelimitedRows_(response.getContentText("UTF-8"));
}

function buildOzonStorageMapFromReport_(rows) {
  if (!rows.length) return {};

  const headerIndex = findOzonStorageHeaderRowIndex_(rows);
  if (headerIndex < 0) {
    Logger.log("❌ Не нашёл строку заголовков в отчёте");
    Logger.log(JSON.stringify(rows.slice(0, 5)));
    return {};
  }

  const headers = rows[headerIndex].map(normalizeOzonStorageHeader_);
  const skuIndex = findHeaderIndex_(headers, ["sku"]);
  const offerIndex = findHeaderIndex_(headers, ["артикул", "offer"]);
  const amountIndex = findHeaderIndex_(headers, ["стоимость размещения", "хран", "размещ", "начислено", "сумма", "итого", "storage"]);

  Logger.log(`Колонки отчёта: sku=${skuIndex}, артикул=${offerIndex}, сумма=${amountIndex}`);

  if (amountIndex < 0 || (skuIndex < 0 && offerIndex < 0)) {
    Logger.log("❌ Не распознаны нужные колонки отчёта");
    Logger.log(JSON.stringify(rows[headerIndex]));
    return {};
  }

  const map = {};

  for (let i = headerIndex + 1; i < rows.length; i++) {
    const row = rows[i];
    const sku = skuIndex >= 0 ? normalizeOzonStorageKey_(row[skuIndex]) : "";
    const offerId = offerIndex >= 0 ? normalizeOzonStorageKey_(row[offerIndex]) : "";
    const amount = Math.abs(parseOzonStorageMoney_(row[amountIndex]));

    if (!amount) continue;

    if (sku) map[sku] = (map[sku] || 0) + amount;
    if (offerId) map[offerId] = (map[offerId] || 0) + amount;
  }

  return map;
}

function findOzonStorageHeaderRowIndex_(rows) {
  for (let i = 0; i < Math.min(rows.length, 50); i++) {
    const joined = rows[i].map(normalizeOzonStorageHeader_).join(" | ");
    if ((joined.indexOf("sku") !== -1 || joined.indexOf("артикул") !== -1) &&
        (joined.indexOf("хран") !== -1 || joined.indexOf("размещ") !== -1 || joined.indexOf("начис") !== -1 || joined.indexOf("сумм") !== -1)) {
      return i;
    }
  }
  return -1;
}

function findHeaderIndex_(headers, markers) {
  for (let i = 0; i < headers.length; i++) {
    if (markers.some(marker => headers[i].indexOf(marker) !== -1)) return i;
  }
  return -1;
}

function parseDelimitedRows_(text) {
  const cleaned = text.replace(/^\uFEFF/, "");
  const firstLine = cleaned.split(/\r?\n/)[0] || "";
  const delimiter = firstLine.indexOf(";") !== -1 ? ";" : firstLine.indexOf("\t") !== -1 ? "\t" : ",";

  return Utilities.parseCsv(cleaned, delimiter)
    .filter(row => row.some(cell => String(cell || "").trim() !== ""));
}

function parseXlsxRows_(blob) {
  try {
    return parseXlsxRowsViaGoogleSheets_(blob);
  } catch (error) {
    Logger.log(`⚠️ Не удалось разобрать XLSX через Google Sheets: ${error}`);

    if (isDriveApiDisabledError_(error)) {
      Logger.log("❌ Google Drive API выключен для проекта Apps Script. Включите Drive API по ссылке из ошибки, иначе большой XLSX нельзя конвертировать в лист defolt.");
      return [];
    }

    Logger.log("Пробую резервный парсер XLSX через ZIP");
  }

  const files = Utilities.unzip(blob);
  const fileMap = {};
  files.forEach(file => {
    fileMap[file.getName()] = file.getDataAsString("UTF-8");
  });

  const sharedStrings = parseXlsxSharedStrings_(fileMap["xl/sharedStrings.xml"]);
  const sheetName = Object.keys(fileMap).filter(name => /^xl\/worksheets\/sheet\d+\.xml$/.test(name)).sort()[0];
  if (!sheetName) return [];

  const document = XmlService.parse(fileMap[sheetName]);
  const root = document.getRootElement();
  const namespace = root.getNamespace();
  const sheetData = root.getChild("sheetData", namespace);
  if (!sheetData) return [];

  return sheetData.getChildren("row", namespace).map(rowNode => {
    const row = [];
    rowNode.getChildren("c", namespace).forEach(cell => {
      const ref = cell.getAttribute("r")?.getValue() || "";
      const columnIndex = xlsxColumnRefToIndex_(ref.replace(/[0-9]/g, ""));
      row[columnIndex] = readXlsxCellValue_(cell, namespace, sharedStrings);
    });
    return row.map(value => value === undefined ? "" : value);
  }).filter(row => row.some(cell => String(cell || "").trim() !== ""));
}

function parseXlsxRowsViaGoogleSheets_(blob) {
  const tempName = `ozon_storage_${Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyyMMdd_HHmmss")}`;
  const xlsxBlob = blob.copyBlob()
    .setName(`${tempName}.xlsx`)
    .setContentType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  let tempFileId = "";

  try {
    tempFileId = uploadXlsxAsGoogleSheet_(xlsxBlob, tempName);
    Logger.log(`Временная Google-таблица отчёта: ${tempFileId}`);

    const tempSpreadsheet = SpreadsheetApp.openById(tempFileId);
    const sourceSheet = tempSpreadsheet.getSheets()[0];
    const rows = sourceSheet.getDataRange().getDisplayValues()
      .filter(row => row.some(cell => String(cell || "").trim() !== ""));

    const defoltSheet = prepareOzonStorageDefoltSheet_(rows);
    const defoltRows = defoltSheet.getDataRange().getDisplayValues()
      .filter(row => row.some(cell => String(cell || "").trim() !== ""));

    Logger.log(`Строк записано в лист ${OZON_STORAGE_TEMP_SHEET_NAME}: ${defoltRows.length}`);
    return defoltRows;
  } finally {
    if (tempFileId) {
      try {
        DriveApp.getFileById(tempFileId).setTrashed(true);
        Logger.log("Временная Google-таблица отчёта удалена в корзину");
      } catch (cleanupError) {
        Logger.log(`⚠️ Не удалось удалить временную Google-таблицу: ${cleanupError}`);
      }
    }
  }
}

function uploadXlsxAsGoogleSheet_(blob, name) {
  const boundary = `ozon_storage_${Date.now()}`;
  const delimiter = `\r\n--${boundary}\r\n`;
  const closeDelimiter = `\r\n--${boundary}--`;
  const metadata = {
    name,
    mimeType: MimeType.GOOGLE_SHEETS
  };
  const payloadBytes = []
    .concat(Utilities.newBlob(`${delimiter}Content-Type: application/json; charset=UTF-8\r\n\r\n${JSON.stringify(metadata)}`).getBytes())
    .concat(Utilities.newBlob(`${delimiter}Content-Type: ${blob.getContentType()}\r\n\r\n`).getBytes())
    .concat(blob.getBytes())
    .concat(Utilities.newBlob(closeDelimiter).getBytes());
  const response = UrlFetchApp.fetch("https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id", {
    method: "post",
    contentType: `multipart/related; boundary=${boundary}`,
    headers: {
      Authorization: `Bearer ${ScriptApp.getOAuthToken()}`
    },
    payload: payloadBytes,
    muteHttpExceptions: true
  });
  const code = response.getResponseCode();
  const text = response.getContentText();

  if (code < 200 || code >= 300) {
    throw new Error(`Drive upload HTTP ${code}: ${text}`);
  }

  const json = JSON.parse(text);
  if (!json.id) {
    throw new Error(`Drive upload не вернул id: ${text}`);
  }

  return json.id;
}

function prepareOzonStorageDefoltSheet_(rows) {
  const spreadsheet = mainSheet().getParent();
  let sheet = spreadsheet.getSheetByName(OZON_STORAGE_TEMP_SHEET_NAME);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(OZON_STORAGE_TEMP_SHEET_NAME);
  }

  sheet.clearContents();

  if (!rows.length) return sheet;

  const width = rows.reduce((max, row) => Math.max(max, row.length), 0);
  const normalizedRows = rows.map(row => {
    const result = row.slice();
    while (result.length < width) result.push("");
    return result;
  });

  sheet.getRange(1, 1, normalizedRows.length, width).setValues(normalizedRows);
  return sheet;
}

function isDriveApiDisabledError_(error) {
  const text = String(error || "");
  return text.indexOf("drive.googleapis.com") !== -1 ||
    text.indexOf("SERVICE_DISABLED") !== -1 ||
    text.indexOf("accessNotConfigured") !== -1 ||
    text.indexOf("Drive upload HTTP 403") !== -1;
}

function parseXlsxSharedStrings_(xmlText) {
  if (!xmlText) return [];

  const document = XmlService.parse(xmlText);
  const root = document.getRootElement();
  const namespace = root.getNamespace();

  return root.getChildren("si", namespace).map(si => {
    const textParts = [];
    const directText = si.getChild("t", namespace);
    if (directText) textParts.push(directText.getText());

    si.getChildren("r", namespace).forEach(run => {
      const text = run.getChild("t", namespace);
      if (text) textParts.push(text.getText());
    });

    return textParts.join("");
  });
}

function readXlsxCellValue_(cell, namespace, sharedStrings) {
  const type = cell.getAttribute("t")?.getValue() || "";
  const valueNode = cell.getChild("v", namespace);

  if (type === "inlineStr") {
    const inline = cell.getChild("is", namespace);
    return inline?.getChild("t", namespace)?.getText() || "";
  }

  const raw = valueNode ? valueNode.getText() : "";
  if (type === "s") return sharedStrings[Number(raw)] || "";
  return raw;
}

function xlsxColumnRefToIndex_(letters) {
  let index = 0;
  for (let i = 0; i < letters.length; i++) {
    index = index * 26 + letters.charCodeAt(i) - 64;
  }
  return Math.max(index - 1, 0);
}

function getOzonStorageRollingDateRange_() {
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0);
  const fromDate = addMonthsClamped_(todayStart, -1);
  const toDate = new Date(todayStart.getTime() - 24 * 60 * 60 * 1000);

  return {
    from: formatOzonStorageDate_(fromDate),
    to: formatOzonStorageDate_(toDate)
  };
}

function addMonthsClamped_(date, deltaMonths) {
  const base = new Date(date.getTime());
  const desiredDay = base.getDate();

  base.setDate(1);
  base.setMonth(base.getMonth() + deltaMonths);

  const maxDay = new Date(base.getFullYear(), base.getMonth() + 1, 0).getDate();
  base.setDate(Math.min(desiredDay, maxDay));

  return base;
}

function formatOzonStorageDate_(date) {
  return Utilities.formatDate(date, Session.getScriptTimeZone(), "yyyy-MM-dd");
}

function normalizeOzonStorageKey_(value) {
  if (value === null || value === undefined) return "";
  return String(value).trim();
}

function normalizeOzonStorageHeader_(value) {
  return normalizeOzonStorageKey_(value).toLowerCase().replace(/\s+/g, " ");
}

function ensureOzonStorageHeader_(sheet) {
  const headerCell = sheet.getRange(1, OZON_STORAGE_COLUMN);
  if (headerCell.getValue() !== "Хранение") {
    headerCell.setValue("Хранение");
  }
}

function roundOzonStorageMoney_(value) {
  const num = Number(value) || 0;
  return Math.round(num * 100) / 100;
}

function parseOzonStorageMoney_(value) {
  if (value === null || value === undefined || value === "") return 0;
  const normalized = String(value)
    .replace(/\u00A0/g, "")
    .replace(/\s+/g, "")
    .replace(/[₽рруб.]/gi, "")
    .replace(",", ".");
  const num = Number(normalized);
  return Number.isFinite(num) ? num : 0;
}
