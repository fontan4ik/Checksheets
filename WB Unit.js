/**
 * WB UNIT API: финансовый отчет по артикулам.
 *
 * Заполняет лист "UNIT WB" в таблице 15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI:
 * В текущей структуре файла это AJ:AQ:
 * ВЫКУПЫ API, ВЫКУП ШТ API, ВОЗВРАТЫ API, ЛОГИСТИКА API,
 * ШТРАФЫ API, КОМИССИЯ ВБ API, ЭКВАЙРИНГ API, НАЧИСЛЕНО API.
 *
 * Источник: POST https://finance-api.wildberries.ru/api/finance/v1/sales-reports/detailed
 */

const WB_UNIT_SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI";
const WB_UNIT_SHEET_NAME = "UNIT WB";
const WB_UNIT_API_URL = "https://finance-api.wildberries.ru/api/finance/v1/sales-reports/detailed";
const WB_UNIT_LEGACY_API_URL = "https://statistics-api.wildberries.ru/api/v5/supplier/reportDetailByPeriod";
const WB_UNIT_FINANCE_REPORT_PERIOD = "daily";
const WB_UNIT_PAGE_LIMIT = 100000;
const WB_UNIT_HEADER_SCAN_ROWS = 20;
const WB_UNIT_MAX_DAYS_PER_REQUEST = 31;
const WB_UNIT_REQUEST_INTERVAL_MS = 65000;
const WB_UNIT_RATE_LIMIT_ATTEMPTS = 4;
const WB_UNIT_MAX_RATE_LIMIT_WAIT_MS = 5 * 60 * 1000;

const WB_UNIT_REQUIRED_HEADERS = [
  "Артикул",
  "ориг. артикул",
  "ВЫКУПЫ API",
  "ВЫКУП ШТ API",
  "ВОЗВРАТЫ API",
  "ЛОГИСТИКА API",
  "ШТРАФЫ API",
  "КОМИССИЯ ВБ API",
  "ЭКВАЙРИНГ API",
  "НАЧИСЛЕНО API"
];

function updateWbUnitApi() {
  const range = getWbUnitDefaultDateRange_();
  updateWbUnitApiForDates(range.from, range.to);
}

function updateWbUnitApiForDates(dateFrom, dateTo) {
  return withWbUnitScriptLock_("updateWbUnitApiForDates", function() {
    const sheet = getWbUnitSheet_();
    const lastRow = sheet.getLastRow();
    if (lastRow < 2) {
      Logger.log("UNIT WB: нет строк для обработки");
      return;
    }

    const headerMap = getWbUnitHeaderMap_(sheet);
    validateWbUnitHeaders_(headerMap);

    if (lastRow <= headerMap.__headerRow) {
      Logger.log("UNIT WB: нет строк ниже строки заголовков " + headerMap.__headerRow);
      return;
    }

    Logger.log("=== WB UNIT API: финансовый отчет ===");
    Logger.log("Период: " + dateFrom + " -> " + dateTo);

    const rowItems = readWbUnitRows_(sheet, lastRow, headerMap);
    const financeMap = fetchWbUnitFinanceMap_(dateFrom, dateTo);

    writeWbUnitColumns_(sheet, headerMap, rowItems, financeMap);
  });
}

function getWbUnitSheet_() {
  const spreadsheet = SpreadsheetApp.openById(WB_UNIT_SPREADSHEET_ID);
  const sheet = spreadsheet.getSheetByName(WB_UNIT_SHEET_NAME);
  if (!sheet) throw new Error("Не найден лист: " + WB_UNIT_SHEET_NAME);
  return sheet;
}

function getWbUnitHeaderMap_(sheet) {
  const rowsToScan = Math.min(WB_UNIT_HEADER_SCAN_ROWS, sheet.getLastRow());
  const colsToScan = Math.max(sheet.getLastColumn(), 43);
  const values = sheet.getRange(1, 1, rowsToScan, colsToScan).getValues();
  const best = { row: 1, count: 0, map: {} };
  const required = WB_UNIT_REQUIRED_HEADERS.map(normalizeWbUnitHeader_);

  for (let r = 0; r < values.length; r++) {
    const map = {};
    let count = 0;

    for (let c = 0; c < values[r].length; c++) {
      const key = normalizeWbUnitHeader_(values[r][c]);
      if (!key) continue;
      if (!map[key]) map[key] = c + 1;
      if (required.indexOf(key) !== -1) count++;
    }

    if (count > best.count) {
      best.row = r + 1;
      best.count = count;
      best.map = map;
    }
  }

  best.map.__headerRow = best.row;
  Logger.log("UNIT WB: строка заголовков " + best.row);
  return best.map;
}

function validateWbUnitHeaders_(headerMap) {
  const missing = WB_UNIT_REQUIRED_HEADERS.filter(header => !getWbUnitColumn_(headerMap, header));
  if (missing.length) throw new Error("UNIT WB: не найдены заголовки: " + missing.join(", "));
}

function getWbUnitColumn_(headerMap, header) {
  return headerMap[normalizeWbUnitHeader_(header)] || 0;
}

function readWbUnitRows_(sheet, lastRow, headerMap) {
  const startRow = headerMap.__headerRow + 1;
  const rowCount = lastRow - headerMap.__headerRow;
  const width = Math.max(sheet.getLastColumn(), 43);
  const values = sheet.getRange(startRow, 1, rowCount, width).getValues();
  const articleCol = getWbUnitColumn_(headerMap, "Артикул") - 1;
  const originalArticleCol = getWbUnitColumn_(headerMap, "ориг. артикул") - 1;
  const originalCounts = {};

  values.forEach(row => {
    const originalArticle = normalizeWbUnitArticle_(row[originalArticleCol]);
    if (!originalArticle) return;
    originalCounts[originalArticle] = (originalCounts[originalArticle] || 0) + 1;
  });

  return values.map((row, index) => {
    const article = normalizeWbUnitArticle_(row[articleCol]);
    const originalArticle = normalizeWbUnitArticle_(row[originalArticleCol]);
    const useOriginalArticle = originalArticle && originalCounts[originalArticle] === 1;
    return {
      rowNumber: startRow + index,
      article: article,
      originalArticle: originalArticle,
      keys: buildWbUnitLookupKeys_(article, useOriginalArticle ? originalArticle : "")
    };
  });
}

function fetchWbUnitFinanceMap_(dateFrom, dateTo) {
  const periods = splitWbUnitDateRange_(dateFrom, dateTo);
  const totals = {};
  const allRows = [];
  let totalRows = 0;
  let lastRequestTime = 0;

  periods.forEach(period => {
    let next = 0;
    let page = 1;

    while (true) {
      const payload = {
        dateFrom: period.from,
        dateTo: period.to,
        limit: WB_UNIT_PAGE_LIMIT,
        rrdId: next,
        period: WB_UNIT_FINANCE_REPORT_PERIOD
      };

      if (lastRequestTime) {
        const elapsed = Date.now() - lastRequestTime;
        if (elapsed < WB_UNIT_REQUEST_INTERVAL_MS) {
          Utilities.sleep(WB_UNIT_REQUEST_INTERVAL_MS - elapsed);
        }
      }

      const response = fetchWbUnitFinancePage_(payload, "период " + period.from + " -> " + period.to + ", страница " + page);
      lastRequestTime = Date.now();
      const rows = extractWbUnitRowsFromResponse_(response);
      if (!rows.length) break;

      rows.forEach(row => allRows.push(row));
      totalRows += rows.length;

      Logger.log("WB finance: " + period.from + " -> " + period.to + ", страница " + page + ", строк " + rows.length);

      const nextCursor = getWbUnitNextRrdId_(rows);
      if (!nextCursor || rows.length < WB_UNIT_PAGE_LIMIT) break;

      next = nextCursor;
      page++;
    }
  });

  const correctionReturnKeys = buildWbUnitCorrectionReturnKeys_(allRows, dateFrom, dateTo);
  allRows.forEach(row => addWbUnitFinanceRow_(totals, row, dateFrom, dateTo, correctionReturnKeys));

  Logger.log("WB finance: всего строк отчета " + totalRows + ", уникальных артикулов " + Object.keys(totals).length);
  return totals;
}

function fetchWbUnitFinancePage_(payload, label) {
  const useLegacy = getWbUnitUseLegacyApi_();
  if (useLegacy) return fetchWbUnitLegacyFinancePage_(payload, label);

  const options = {
    method: "post",
    contentType: "application/json",
    headers: wbUnitHeaders_(),
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  const response = fetchWbUnitFinanceApiWithRateLimit_(WB_UNIT_API_URL, options, label);
  if (!response) throw new Error("WB finance: пустой ответ API (" + label + ")");

  const code = response.getResponseCode();
  const body = response.getContentText();

  if (code === 204) return [];

  if (code === 401 && body.indexOf("token scope not allowed") !== -1) {
    Logger.log(
      "WB finance-api недоступен для текущего токена, переключаюсь на legacy statistics-api/reportDetailByPeriod. " +
      "Важно: legacy-источник может расходиться с ежедневным отчетом Доходы и расходы."
    );
    return fetchWbUnitLegacyFinancePage_(payload, label);
  }

  if (code === 401) {
    throw new Error(
      "WB finance: токен не имеет доступа к финансовым отчетам. " +
      "Создайте в кабинете WB новый API-токен с категорией Финансы и обновите wbHeaders()/WB_API_TOKEN(). " +
      "Ответ WB: " + body.substring(0, 500)
    );
  }

  if (code < 200 || code >= 300) {
    throw new Error("WB finance: HTTP " + code + " (" + label + "): " + body.substring(0, 500));
  }

  try {
    return JSON.parse(body);
  } catch (e) {
    throw new Error("WB finance: не удалось распарсить JSON (" + label + "): " + e.message);
  }
}

function fetchWbUnitFinanceApiWithRateLimit_(url, options, label) {
  for (let attempt = 1; attempt <= WB_UNIT_RATE_LIMIT_ATTEMPTS; attempt++) {
    const response = UrlFetchApp.fetch(url, options);
    const code = response.getResponseCode();

    if (code !== 429 && code < 500) return response;

    if (attempt >= WB_UNIT_RATE_LIMIT_ATTEMPTS) return response;

    const waitMs = getWbUnitRateLimitWaitMs_(response);
    if (waitMs > WB_UNIT_MAX_RATE_LIMIT_WAIT_MS) {
      throw new Error(
        "WB finance: глобальный лимит WB (" + label + "). " +
        "API просит ждать около " + Math.round(waitMs / 1000) + " сек; повторите запуск позже."
      );
    }

    Logger.log(
      "WB finance: HTTP " + code + " (" + label + "), лимит/временная ошибка. " +
      "Жду " + Math.round(waitMs / 1000) + " сек, попытка " + attempt + "/" + WB_UNIT_RATE_LIMIT_ATTEMPTS
    );
    Utilities.sleep(waitMs);
  }

  return null;
}

function getWbUnitRateLimitWaitMs_(response) {
  const retry = parseWbUnitHeaderNumber_(response, "X-Ratelimit-Retry");
  const reset = parseWbUnitHeaderNumber_(response, "X-Ratelimit-Reset");
  const retryAfter = parseWbUnitHeaderNumber_(response, "Retry-After");
  const seconds = Math.max(retry, reset, retryAfter, WB_UNIT_REQUEST_INTERVAL_MS / 1000);
  return (seconds + 5) * 1000;
}

function parseWbUnitHeaderNumber_(response, headerName) {
  const headers = response.getAllHeaders ? response.getAllHeaders() : response.getHeaders();
  const target = headerName.toLowerCase();
  for (const key in headers) {
    if (String(key).toLowerCase() === target) {
      const value = Number(Array.isArray(headers[key]) ? headers[key][0] : headers[key]);
      return isNaN(value) ? 0 : value;
    }
  }
  return 0;
}

function fetchWbUnitLegacyFinancePage_(payload, label) {
  const url = WB_UNIT_LEGACY_API_URL
    + "?dateFrom=" + encodeURIComponent(payload.dateFrom)
    + "&dateTo=" + encodeURIComponent(payload.dateTo)
    + "&limit=" + encodeURIComponent(payload.limit)
    + "&rrdid=" + encodeURIComponent(payload.rrdId || 0);

  const options = {
    method: "get",
    headers: wbHeaders(),
    muteHttpExceptions: true
  };

  const response = retryFetch(url, options, 3);
  if (!response) throw new Error("WB legacy finance: пустой ответ API (" + label + ")");

  const code = response.getResponseCode();
  const body = response.getContentText();

  if (code === 204) return [];

  if (code < 200 || code >= 300) {
    if (code === 401) {
      throw new Error(
        "WB legacy finance: текущий токен не подходит для старого финансового отчета reportDetailByPeriod. " +
        "Нужен WB API-токен с доступом к финансовым отчетам. Ответ WB: " + body.substring(0, 500)
      );
    }
    throw new Error("WB legacy finance: HTTP " + code + " (" + label + "): " + body.substring(0, 500));
  }

  try {
    return JSON.parse(body);
  } catch (e) {
    throw new Error("WB legacy finance: не удалось распарсить JSON (" + label + "): " + e.message);
  }
}

function getWbUnitUseLegacyApi_() {
  return PropertiesService.getScriptProperties().getProperty("WB_UNIT_USE_LEGACY_API") === "1";
}

function resetWbUnitFinanceApiMode() {
  PropertiesService.getScriptProperties().deleteProperty("WB_UNIT_USE_LEGACY_API");
  Logger.log("UNIT WB: режим API сброшен, следующий запуск снова попробует finance-api");
}

function extractWbUnitRowsFromResponse_(response) {
  if (!response) return [];
  if (Array.isArray(response)) return response;
  if (Array.isArray(response.data)) return response.data;
  if (response.data && Array.isArray(response.data.report)) return response.data.report;
  if (Array.isArray(response.report)) return response.report;
  if (Array.isArray(response.rows)) return response.rows;
  return [];
}

function getWbUnitNextRrdId_(rows) {
  let maxRrdId = 0;
  rows.forEach(row => {
    const rrdId = Number(pickWbUnitField_(row, ["rrdId", "rrd_id"]));
    if (rrdId > maxRrdId) maxRrdId = rrdId;
  });
  return maxRrdId;
}

function addWbUnitFinanceRow_(totals, row, dateFrom, dateTo, correctionReturnKeys) {
  if (!isWbUnitRowInDateRange_(row, dateFrom, dateTo)) return;

  const vendorCode = normalizeWbUnitArticle_(pickWbUnitField_(row, ["vendorCode", "supplierArticle", "sa_name"]));
  if (!vendorCode) return;

  if (!totals[vendorCode]) totals[vendorCode] = createWbUnitEmptyStats_();
  const stats = totals[vendorCode];

  const docType = normalizeWbUnitText_(pickWbUnitField_(row, ["docTypeName", "doc_type_name"]));
  const operationName = normalizeWbUnitText_(pickWbUnitField_(row, ["sellerOperName", "supplierOperName", "supplier_oper_name"]));
  const isReturn = docType.indexOf("возврат") !== -1;
  const isVoluntaryReturnComp = operationName.indexOf("добровольная компенсация при возврате") !== -1;
  const quantity = Math.abs(parseWbUnitNumber_(pickWbUnitField_(row, ["quantity", "quantityFull", "quantity_full"])));
  const retailAmount = getWbUnitRetailAmount_(row);
  const ppvzForPay = parseWbUnitNumber_(pickWbUnitField_(row, ["forPay", "ppvzForPay", "ppvz_for_pay"]));
  const acquiring = Math.abs(parseWbUnitNumber_(pickWbUnitField_(row, ["acquiringFee", "acquiring_fee"])));
  const hasReturnCorrectionPair = operationName.indexOf("коррекция продаж") !== -1
    && correctionReturnKeys[getWbUnitCorrectionKey_(row, ppvzForPay)];
  const commission = retailAmount > 0
    ? Math.abs(roundWbUnitMoney_(retailAmount - ppvzForPay - acquiring))
    : operationName.indexOf("коррекция продаж") !== -1 && ppvzForPay && !hasReturnCorrectionPair
      ? -ppvzForPay
      : parseWbUnitNumber_(pickWbUnitField_(row, ["ppvzSalesCommission", "ppvz_sales_commission"]));

  if (isVoluntaryReturnComp) {
    const compensation = Math.abs(ppvzForPay || retailAmount);
    stats.buyouts -= compensation;
    stats.commission += compensation;
  } else if (isReturn) {
    stats.returns -= retailAmount;
    stats.commission += commission;
    stats.acquiring += acquiring;
  } else {
    if (retailAmount > 0) {
      stats.buyouts += retailAmount;
      stats.buyoutQty += quantity || 1;
    } else if (operationName.indexOf("коррекция продаж") !== -1 && quantity > 0) {
      stats.buyoutQty += quantity;
    }
    stats.commission -= commission;
    stats.acquiring -= acquiring;
  }

  stats.logistics -= Math.abs(parseWbUnitNumber_(pickWbUnitField_(row, ["deliveryService", "delivery_rub"])));
  stats.penalties -= parseWbUnitNumber_(pickWbUnitField_(row, ["penalty"]));
  const accruedPpvz = isReturn ? -ppvzForPay : ppvzForPay;
  stats.accrued += accruedPpvz
    - Math.abs(parseWbUnitNumber_(pickWbUnitField_(row, ["deliveryService", "delivery_rub"])))
    - parseWbUnitNumber_(pickWbUnitField_(row, ["penalty"]))
    + parseWbUnitOtherCharges_(row);
}

function writeWbUnitColumns_(sheet, headerMap, rowItems, financeMap) {
  const columns = [
    "ВЫКУПЫ API",
    "ВЫКУП ШТ API",
    "ВОЗВРАТЫ API",
    "ЛОГИСТИКА API",
    "ШТРАФЫ API",
    "КОМИССИЯ ВБ API",
    "ЭКВАЙРИНГ API",
    "НАЧИСЛЕНО API"
  ];

  const values = rowItems.map(item => {
    const stats = findWbUnitStats_(financeMap, item.keys) || createWbUnitEmptyStats_();
    return [
      roundWbUnitMoney_(stats.buyouts),
      stats.buyoutQty || 0,
      roundWbUnitMoney_(stats.returns),
      roundWbUnitMoney_(stats.logistics),
      roundWbUnitMoney_(stats.penalties),
      roundWbUnitMoney_(stats.commission),
      roundWbUnitMoney_(stats.acquiring),
      roundWbUnitMoney_(getWbUnitAccrued_(stats))
    ];
  });

  columns.forEach((header, offset) => {
    const col = getWbUnitColumn_(headerMap, header);
    const columnValues = values.map(row => [row[offset]]);
    sheet.getRange(headerMap.__headerRow + 1, col, columnValues.length, 1).setValues(columnValues);
  });

  const totals = values.reduce((acc, row) => {
    row.forEach((value, index) => acc[index] += Number(value) || 0);
    return acc;
  }, [0, 0, 0, 0, 0, 0, 0, 0]);

  Logger.log("UNIT WB: записано строк " + rowItems.length);
  Logger.log("Итого ВЫКУПЫ API: " + roundWbUnitMoney_(totals[0]));
  Logger.log("Итого ВЫКУП ШТ API: " + totals[1]);
  Logger.log("Итого ВОЗВРАТЫ API: " + roundWbUnitMoney_(totals[2]));
  Logger.log("Итого НАЧИСЛЕНО API: " + roundWbUnitMoney_(totals[7]));
}

function findWbUnitStats_(financeMap, keys) {
  for (let i = 0; i < keys.length; i++) {
    if (financeMap[keys[i]]) return financeMap[keys[i]];
  }
  return null;
}

function createWbUnitEmptyStats_() {
  return {
    buyouts: 0,
    buyoutQty: 0,
    returns: 0,
    logistics: 0,
    penalties: 0,
    commission: 0,
    acquiring: 0,
    accrued: 0
  };
}

function getWbUnitRetailAmount_(row) {
  const retailPrice = Math.abs(parseWbUnitNumber_(pickWbUnitField_(row, ["retailPrice", "retail_price"])));
  const quantity = Math.abs(parseWbUnitNumber_(pickWbUnitField_(row, ["quantity", "quantityFull", "quantity_full"]))) || 1;
  if (retailPrice > 0) return retailPrice * quantity;

  return Math.abs(parseWbUnitNumber_(pickWbUnitField_(row, [
    "retailAmount",
    "retail_amount",
    "retailPriceWithDiscRub",
    "retail_price_withdisc_rub"
  ])));
}

function getWbUnitCommission_(row, retailAmount) {
  const commissionPercent = Math.abs(parseWbUnitNumber_(pickWbUnitField_(row, [
    "commissionPercent",
    "commission_percent"
  ])));

  if (commissionPercent > 0 && retailAmount > 0) {
    return roundWbUnitMoney_(retailAmount * commissionPercent / 100);
  }

  return Math.abs(parseWbUnitNumber_(pickWbUnitField_(row, [
    "ppvzSalesCommission",
    "ppvz_sales_commission"
  ])));
}

function getWbUnitAccrued_(stats) {
  return stats.accrued;
}

function splitWbUnitDateRange_(dateFrom, dateTo) {
  let current = parseWbUnitDate_(dateFrom);
  const end = parseWbUnitDate_(dateTo);
  if (current.getTime() > end.getTime()) throw new Error("dateFrom больше dateTo: " + dateFrom + " > " + dateTo);

  const periods = [];
  while (current.getTime() <= end.getTime()) {
    const chunkEnd = new Date(current.getFullYear(), current.getMonth(), current.getDate() + WB_UNIT_MAX_DAYS_PER_REQUEST - 1);
    const actualEnd = chunkEnd.getTime() < end.getTime() ? chunkEnd : end;
    periods.push({
      from: formatWbUnitDate_(current),
      to: formatWbUnitDate_(actualEnd)
    });
    current = new Date(actualEnd.getFullYear(), actualEnd.getMonth(), actualEnd.getDate() + 1);
  }
  return periods;
}

function getWbUnitDefaultDateRange_() {
  const today = new Date();
  const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
  const fromDate = new Date(today.getFullYear(), today.getMonth() - 1, today.getDate());

  return {
    from: formatWbUnitDate_(fromDate),
    to: formatWbUnitDate_(yesterday)
  };
}

function parseWbUnitDate_(value) {
  const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) throw new Error("Дата должна быть в формате YYYY-MM-DD: " + value);
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

function formatWbUnitDate_(date) {
  return Utilities.formatDate(date, Session.getScriptTimeZone(), "yyyy-MM-dd");
}

function pickWbUnitField_(row, names) {
  for (let i = 0; i < names.length; i++) {
    if (row[names[i]] !== undefined && row[names[i]] !== null) return row[names[i]];
  }
  return "";
}

function parseWbUnitOtherCharges_(row) {
  const paidAcceptance = Math.abs(parseWbUnitNumber_(pickWbUnitField_(row, [
    "paidAcceptance",
    "paid_acceptance",
    "acceptance",
    "acceptanceDeduction"
  ])));
  const storage = Math.abs(parseWbUnitNumber_(pickWbUnitField_(row, [
    "paidStorage",
    "storageFee",
    "storage_fee"
  ])));
  const deduction = Math.abs(parseWbUnitNumber_(pickWbUnitField_(row, [
    "deduction"
  ])));
  const additionalPayment = parseWbUnitNumber_(pickWbUnitField_(row, [
    "additionalPayment",
    "additional_payment"
  ]));

  return additionalPayment - paidAcceptance - storage - deduction;
}

function buildWbUnitCorrectionReturnKeys_(rows, dateFrom, dateTo) {
  const keys = {};
  rows.forEach(row => {
    if (!isWbUnitRowInDateRange_(row, dateFrom, dateTo)) return;
    const operationName = normalizeWbUnitText_(pickWbUnitField_(row, ["sellerOperName", "supplierOperName", "supplier_oper_name"]));
    const docType = normalizeWbUnitText_(pickWbUnitField_(row, ["docTypeName", "doc_type_name"]));
    if (operationName.indexOf("коррекция возвратов") === -1 || docType.indexOf("возврат") === -1) return;
    const ppvzForPay = parseWbUnitNumber_(pickWbUnitField_(row, ["forPay", "ppvzForPay", "ppvz_for_pay"]));
    if (ppvzForPay) keys[getWbUnitCorrectionKey_(row, ppvzForPay)] = true;
  });
  return keys;
}

function getWbUnitCorrectionKey_(row, ppvzForPay) {
  return [
    normalizeWbUnitArticle_(pickWbUnitField_(row, ["vendorCode", "supplierArticle", "sa_name"])),
    roundWbUnitMoney_(ppvzForPay)
  ].join("|");
}

function isWbUnitRowInDateRange_(row, dateFrom, dateTo) {
  const operationDate = getWbUnitDateOnly_(pickWbUnitField_(row, ["rrDate", "sale_dt", "saleDt", "rr_dt", "rrDt"]));
  return !operationDate || (operationDate >= dateFrom && operationDate <= dateTo);
}

function getWbUnitDateOnly_(value) {
  const text = String(value || "");
  if (/^\d{4}-\d{2}-\d{2}T.*Z$/.test(text)) {
    const date = new Date(text);
    date.setUTCHours(date.getUTCHours() + 3);
    return Utilities.formatDate(date, "GMT", "yyyy-MM-dd");
  }
  const match = text.match(/^(\d{4}-\d{2}-\d{2})/);
  return match ? match[1] : "";
}

function wbUnitHeaders_() {
  return {
    "Authorization": WB_API_TOKEN(),
    "Content-Type": "application/json"
  };
}

function parseWbUnitNumber_(value) {
  if (value === null || value === undefined || value === "") return 0;
  if (typeof value === "number") return value;
  const normalized = String(value).replace(/\s/g, "").replace(",", ".");
  const number = Number(normalized);
  return isNaN(number) ? 0 : number;
}

function roundWbUnitMoney_(value) {
  return Math.round((Number(value) || 0) * 100) / 100;
}

function buildWbUnitLookupKeys_(article, originalArticle) {
  const result = [];
  [article, originalArticle].forEach(value => {
    if (!value) return;
    addWbUnitLookupKey_(result, value);
  });
  return result;
}

function addWbUnitLookupKey_(result, value) {
  const key = normalizeWbUnitArticle_(value);
  if (key && result.indexOf(key) === -1) result.push(key);
}

function normalizeWbUnitArticle_(value) {
  if (value === null || value === undefined) return "";
  return String(value).trim().toLowerCase().replace(/\s+/g, " ");
}

function normalizeWbUnitText_(value) {
  return normalizeWbUnitArticle_(value).toLowerCase().replace(/ё/g, "е").replace(/\s+/g, " ");
}

function normalizeWbUnitHeader_(value) {
  return normalizeWbUnitText_(value);
}

function withWbUnitScriptLock_(label, callback) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) throw new Error("Не удалось получить lock для " + label);
  try {
    return callback();
  } finally {
    lock.releaseLock();
  }
}
