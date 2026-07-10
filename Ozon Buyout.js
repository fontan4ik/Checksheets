/**
 * OZON BUYOUT → UNIT API
 *
 * Заполняет колонку "УПД" листа "UNIT API".
 *
 * Если в таблице остался legacy-заголовок "ЗАКАЗЫ BUYOUT",
 * скрипт переводит запись на колонку УПД, чтобы её могла читать
 * основная логика Ozon UNIT API из O.js.
 *
 * Источник: официальный Ozon Seller API
 * POST https://api-seller.ozon.ru/v1/finance/products/buyout
 * Документация: Finance API → Purchased product report.
 *
 * Даты берутся по той же логике, что и Ozon UNIT API:
 * getOzonReport65DefaultDateRange_() = месяц назад → вчера.
 */

const OZON_BUYOUT_UNIT_API_SHEET_NAME = 'UNIT API';
const OZON_BUYOUT_UNIT_API_HEADER = 'УПД';
const OZON_BUYOUT_UNIT_API_LEGACY_HEADERS = ['ЗАКАЗЫ BUYOUT'];
const OZON_BUYOUT_UNIT_API_FIXED_COLUMN = 11;
const OZON_BUYOUT_UNIT_API_TRIGGER_HANDLER = 'updateOzonBuyoutOrdersUnitApi';
const OZON_BUYOUT_UNIT_API_TRIGGER_HOUR = 6;
const OZON_BUYOUT_UNIT_API_TRIGGER_NEAR_MINUTE = 40;

function updateOzonBuyoutOrdersUnitApi() {
  const range = getOzonBuyoutOrdersDateRange_();
  updateOzonBuyoutOrdersUnitApiForDates(range.from, range.to);
}

function updateOzonBuyoutOrdersUnitApiForDates(dateFrom, dateTo) {
  return withOzonBuyoutOrdersLock_('updateOzonBuyoutOrdersUnitApiForDates', function() {
    const sheet = getOzonBuyoutOrdersUnitApiSheet_();
    const lastRow = sheet.getLastRow();
    if (lastRow < 2) {
      Logger.log('UNIT API: нет строк для обновления');
      return;
    }

    const headerMap = getOzonBuyoutOrdersHeaderMap_(sheet);
    const skuCol = headerMap[normalizeOzonBuyoutOrdersHeader_('СКУ OZ')];
    if (!skuCol) throw new Error('UNIT API: не найден заголовок "СКУ OZ"');

    const targetCol = ensureOzonBuyoutOrdersColumn_(sheet);
    const buyoutMap = fetchOzonBuyoutOrdersMap_(dateFrom, dateTo);

    const rowCount = lastRow - 1;
    const skuValues = sheet.getRange(2, skuCol, rowCount, 1).getDisplayValues();
    const values = skuValues.map(function(row) {
      const sku = normalizeOzonBuyoutOrdersSku_(row[0]);
      return [sku && buyoutMap[sku] ? roundOzonBuyoutOrdersMoney_(buyoutMap[sku].amount) : 0];
    });

    sheet.getRange(2, targetCol, values.length, 1).setValues(values);
    sheet.getRange(2, targetCol, values.length, 1).setNumberFormat('#,##0.00');

    const total = values.reduce(function(sum, row) { return sum + (Number(row[0]) || 0); }, 0);
    const nonZero = values.filter(function(row) { return Number(row[0]) !== 0; }).length;

    Logger.log('OZON BUYOUT → UNIT API завершено');
    Logger.log('Период: ' + dateFrom + ' → ' + dateTo);
    Logger.log('SKU в отчёте: ' + Object.keys(buyoutMap).length);
    Logger.log('Ненулевых строк записано: ' + nonZero);
    Logger.log('Сумма записана: ' + roundOzonBuyoutOrdersMoney_(total));
  });
}

function verifyOzonBuyoutOrdersUnitApiFirst3() {
  const range = getOzonBuyoutOrdersDateRange_();
  return verifyOzonBuyoutOrdersUnitApiFirst3ForDates(range.from, range.to);
}

function verifyOzonBuyoutOrdersUnitApiFirst3ForDates(dateFrom, dateTo) {
  const sheet = getOzonBuyoutOrdersUnitApiSheet_();
  const headerMap = getOzonBuyoutOrdersHeaderMap_(sheet);
  const skuCol = headerMap[normalizeOzonBuyoutOrdersHeader_('СКУ OZ')];
  const articleCol = headerMap[normalizeOzonBuyoutOrdersHeader_('Артикул')];
  const buyoutCol = getOzonBuyoutOrdersColumn_(sheet);

  if (!skuCol) throw new Error('UNIT API: не найден заголовок "СКУ OZ"');
  if (!buyoutCol) throw new Error('UNIT API: не найден заголовок "' + OZON_BUYOUT_UNIT_API_HEADER + '"');

  const lastRow = sheet.getLastRow();
  const width = Math.max(skuCol, articleCol || 1, buyoutCol);
  const rows = sheet.getRange(2, 1, Math.max(0, lastRow - 1), width).getDisplayValues();
  const buyoutMap = fetchOzonBuyoutOrdersMap_(dateFrom, dateTo);

  const checks = [];
  rows.forEach(function(row, index) {
    if (checks.length >= 3) return;
    const sheetValue = parseOzonBuyoutOrdersNumber_(row[buyoutCol - 1]);
    if (!sheetValue) return;

    const sku = normalizeOzonBuyoutOrdersSku_(row[skuCol - 1]);
    const reportValue = buyoutMap[sku] ? roundOzonBuyoutOrdersMoney_(buyoutMap[sku].amount) : 0;
    checks.push({
      row: index + 2,
      article: articleCol ? row[articleCol - 1] : '',
      sku: sku,
      sheetValue: roundOzonBuyoutOrdersMoney_(sheetValue),
      reportValue: reportValue,
      ok: Math.abs(roundOzonBuyoutOrdersMoney_(sheetValue) - reportValue) < 0.01
    });
  });

  checks.forEach(function(item) {
    Logger.log(JSON.stringify(item));
  });

  const failed = checks.filter(function(item) { return !item.ok; });
  if (checks.length < 3) throw new Error('Проверено меньше 3 ненулевых строк: ' + checks.length);
  if (failed.length) throw new Error('Есть расхождения в проверке: ' + JSON.stringify(failed));

  Logger.log('Проверка первых 3 ненулевых строк пройдена: OK');
  return checks;
}

function setupOzonBuyoutOrdersUnitApiDailyTrigger() {
  const triggers = ScriptApp.getProjectTriggers();
  triggers.forEach(function(trigger) {
    if (trigger.getHandlerFunction && trigger.getHandlerFunction() === OZON_BUYOUT_UNIT_API_TRIGGER_HANDLER) {
      ScriptApp.deleteTrigger(trigger);
    }
  });

  ScriptApp.newTrigger(OZON_BUYOUT_UNIT_API_TRIGGER_HANDLER)
    .timeBased()
    .everyDays(1)
    .atHour(OZON_BUYOUT_UNIT_API_TRIGGER_HOUR)
    .nearMinute(OZON_BUYOUT_UNIT_API_TRIGGER_NEAR_MINUTE)
    .create();

  Logger.log('Создан ежедневный триггер ' + OZON_BUYOUT_UNIT_API_TRIGGER_HANDLER +
    ' около ' + OZON_BUYOUT_UNIT_API_TRIGGER_HOUR + ':' + OZON_BUYOUT_UNIT_API_TRIGGER_NEAR_MINUTE);
}

function fetchOzonBuyoutOrdersMap_(dateFrom, dateTo) {
  const periods = splitOzonBuyoutOrdersPeriods_(dateFrom, dateTo, 31);
  const result = {};

  periods.forEach(function(period) {
    const response = retryFetch('https://api-seller.ozon.ru/v1/finance/products/buyout', {
      method: 'post',
      contentType: 'application/json',
      headers: ozonHeaders(),
      payload: JSON.stringify({ date_from: period.from, date_to: period.to }),
      muteHttpExceptions: true
    });

    if (!response) throw new Error('Ozon Buyout API: пустой ответ за период ' + period.from + ' → ' + period.to);

    const code = response.getResponseCode();
    const text = response.getContentText();
    if (code !== 200) {
      throw new Error('Ozon Buyout API вернул ' + code + ' за период ' + period.from + ' → ' + period.to + ': ' + text.substring(0, 500));
    }

    const data = JSON.parse(text || '{}');
    const products = Array.isArray(data.products) ? data.products : [];
    products.forEach(function(product) {
      const sku = normalizeOzonBuyoutOrdersSku_(product.sku);
      if (!sku) return;

      const amount = Number(product.amount) || 0;
      const quantity = Number(product.quantity) || 0;
      if (!result[sku]) {
        result[sku] = { amount: 0, quantity: 0, rows: 0 };
      }
      result[sku].amount += amount;
      result[sku].quantity += quantity;
      result[sku].rows += 1;
    });
  });

  return result;
}

function ensureOzonBuyoutOrdersColumn_(sheet) {
  const targetCol = getOzonBuyoutOrdersColumn_(sheet, { createIfMissing: true, normalizeHeader: true });
  sheet.getRange(1, targetCol).setValue(OZON_BUYOUT_UNIT_API_HEADER);
  sheet.getRange(2, targetCol, Math.max(1, sheet.getMaxRows() - 1), 1).setNumberFormat('#,##0.00');
  return targetCol;
}

function getOzonBuyoutOrdersColumn_(sheet, options) {
  options = options || {};
  const headerMap = getOzonBuyoutOrdersHeaderMap_(sheet);
  const preferredKey = normalizeOzonBuyoutOrdersHeader_(OZON_BUYOUT_UNIT_API_HEADER);
  const preferredCol = headerMap[preferredKey];
  if (preferredCol) {
    return preferredCol;
  }

  const fixedCol = OZON_BUYOUT_UNIT_API_FIXED_COLUMN;
  const fixedHeader = sheet.getRange(1, fixedCol).getDisplayValue();
  const normalizedFixedHeader = normalizeOzonBuyoutOrdersHeader_(fixedHeader);
  const normalizedLegacyHeaders = OZON_BUYOUT_UNIT_API_LEGACY_HEADERS.map(normalizeOzonBuyoutOrdersHeader_);
  const legacyCol = normalizedLegacyHeaders
    .map(function(key) { return headerMap[key] || 0; })
    .filter(Boolean)[0] || 0;

  if (!normalizedFixedHeader || normalizedFixedHeader === preferredKey || normalizedLegacyHeaders.indexOf(normalizedFixedHeader) !== -1) {
    if (sheet.getMaxColumns() < fixedCol) {
      sheet.insertColumnsAfter(sheet.getMaxColumns(), fixedCol - sheet.getMaxColumns());
    }
    if (options.normalizeHeader) {
      sheet.getRange(1, fixedCol).setValue(OZON_BUYOUT_UNIT_API_HEADER);
    }
    return fixedCol;
  }

  if (legacyCol) {
    throw new Error(
      'UNIT API: колонка ' + fixedCol + ' занята заголовком "' + fixedHeader +
      '", а legacy-колонка выкупа найдена в колонке ' + legacyCol +
      '. Освободите/синхронизируйте колонку УПД вручную.'
    );
  }

  if (!options.createIfMissing) {
    return 0;
  }

  if (sheet.getMaxColumns() < fixedCol) {
    sheet.insertColumnsAfter(sheet.getMaxColumns(), fixedCol - sheet.getMaxColumns());
  }
  if (options.normalizeHeader) {
    sheet.getRange(1, fixedCol).setValue(OZON_BUYOUT_UNIT_API_HEADER);
  }
  return fixedCol;
}

function getOzonBuyoutOrdersDateRange_() {
  if (typeof getOzonReport65DefaultDateRange_ === 'function') {
    return getOzonReport65DefaultDateRange_();
  }

  const today = new Date();
  const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
  const fromDate = new Date(today.getFullYear(), today.getMonth() - 1, today.getDate());
  const tz = Session.getScriptTimeZone();
  return {
    from: Utilities.formatDate(fromDate, tz, 'yyyy-MM-dd'),
    to: Utilities.formatDate(yesterday, tz, 'yyyy-MM-dd')
  };
}

function getOzonBuyoutOrdersUnitApiSheet_() {
  const spreadsheetId = (typeof OZON_REPORT65_SPREADSHEET_ID !== 'undefined')
    ? OZON_REPORT65_SPREADSHEET_ID
    : '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
  const spreadsheet = SpreadsheetApp.openById(spreadsheetId);
  const sheet = spreadsheet.getSheetByName(OZON_BUYOUT_UNIT_API_SHEET_NAME);
  if (!sheet) throw new Error('Не найден лист ' + OZON_BUYOUT_UNIT_API_SHEET_NAME);
  return sheet;
}

function getOzonBuyoutOrdersHeaderMap_(sheet) {
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getDisplayValues()[0];
  const map = {};
  headers.forEach(function(header, index) {
    const key = normalizeOzonBuyoutOrdersHeader_(header);
    if (key && !map[key]) map[key] = index + 1;
  });
  return map;
}

function splitOzonBuyoutOrdersPeriods_(dateFrom, dateTo, maxDays) {
  const periods = [];
  let current = parseOzonBuyoutOrdersDate_(dateFrom);
  const end = parseOzonBuyoutOrdersDate_(dateTo);
  const tz = Session.getScriptTimeZone();

  while (current <= end) {
    const chunkEnd = new Date(current);
    chunkEnd.setDate(chunkEnd.getDate() + maxDays - 1);
    if (chunkEnd > end) chunkEnd.setTime(end.getTime());

    periods.push({
      from: Utilities.formatDate(current, tz, 'yyyy-MM-dd'),
      to: Utilities.formatDate(chunkEnd, tz, 'yyyy-MM-dd')
    });

    current = new Date(chunkEnd);
    current.setDate(current.getDate() + 1);
  }

  return periods;
}

function parseOzonBuyoutOrdersDate_(value) {
  const parts = String(value).split('-').map(Number);
  return new Date(parts[0], parts[1] - 1, parts[2]);
}

function normalizeOzonBuyoutOrdersHeader_(value) {
  return String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
}

function normalizeOzonBuyoutOrdersSku_(value) {
  return String(value || '').replace(/[\s\u00A0]/g, '').replace(/\.0$/, '').trim();
}

function parseOzonBuyoutOrdersNumber_(value) {
  if (value === null || value === undefined || value === '') return 0;
  if (typeof value === 'number') return value;
  const normalized = String(value)
    .replace(/\s/g, '')
    .replace(/\u00A0/g, '')
    .replace('%', '')
    .replace(',', '.');
  const parsed = Number(normalized);
  return isNaN(parsed) ? 0 : parsed;
}

function roundOzonBuyoutOrdersMoney_(value) {
  return Math.round((Number(value) || 0) * 100) / 100;
}

function withOzonBuyoutOrdersLock_(label, callback) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) {
    throw new Error(label + ': не удалось получить lock');
  }
  try {
    return callback();
  } finally {
    lock.releaseLock();
  }
}
