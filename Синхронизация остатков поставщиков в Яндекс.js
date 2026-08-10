/**
 * Самарские остатки поставщиков → UNIT YNX → Яндекс Маркет «ВольтМир FBS».
 *
 * Источники:
 * - FERON TR: art + SMR;
 * - ETM TR: art + SMR;
 * - РуСВ TR: Артикул + Округлённое (остаток после охлаждения/округления).
 *
 * Результат:
 * - UNIT YNX: новый контрольный столбец «TR YA FBS»;
 * - Яндекс: кампания «ВольтМир FBS».
 *
 * Основные функции:
 * - verifyYandexSamaraSupplierConfiguration() — только чтение API Яндекса;
 * - aggregateSamaraSupplierStocksToUnitYnx() — только Google Sheets;
 * - syncSamaraSupplierStocksToYandexFbs() — отправка UNIT YNX → Яндекс.
 *
 * Существующий столбец «TR YA» не используется и не изменяется: он относится
 * к отдельному контуру НТЦ.
 */

const SAMARA_SUPPLIER_YNX_SPREADSHEET_ID = '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
const SAMARA_SUPPLIER_YNX_TARGET_SHEET = 'UNIT YNX';
const SAMARA_SUPPLIER_YNX_TARGET_KEY_HEADER = 'art';
const SAMARA_SUPPLIER_YNX_TARGET_STOCK_HEADER = 'TR YA FBS';
const SAMARA_SUPPLIER_YNX_YANDEX_CAMPAIGN_ID = 58480133;
const SAMARA_SUPPLIER_YNX_YANDEX_CAMPAIGN_NAME = 'ВольтМир FBS';
const SAMARA_SUPPLIER_YNX_YANDEX_CAMPAIGNS_URL = 'https://api.partner.market.yandex.ru/v2/campaigns';
const SAMARA_SUPPLIER_YNX_YANDEX_BATCH_SIZE = 2000;

const SAMARA_SUPPLIER_YNX_SOURCES = [
  { sheetName: 'FERON TR', keyHeader: 'art', stockHeader: 'SMR' },
  { sheetName: 'ETM TR', keyHeader: 'art', stockHeader: 'SMR' },
  { sheetName: 'РуСВ TR', keyHeader: 'Артикул', stockHeader: 'Округлённое' }
];

function verifyYandexSamaraSupplierConfiguration() {
  const apiKey = YANDEX_MARKET_API_KEY();
  const response = retryFetch(SAMARA_SUPPLIER_YNX_YANDEX_CAMPAIGNS_URL, {
    method: 'get',
    headers: {
      'Api-Key': apiKey,
      'Content-Type': 'application/json'
    },
    muteHttpExceptions: true
  }, 3);

  if (!response) throw new Error('Яндекс: не получен список кампаний.');
  const code = response.getResponseCode();
  if (code < 200 || code >= 300) {
    throw new Error('Яндекс: список кампаний завершился HTTP ' + code + '.');
  }

  const data = JSON.parse(response.getContentText());
  const campaigns = Array.isArray(data.campaigns) ? data.campaigns : [];
  const matches = campaigns.filter(function(item) {
    return String(item.id) === String(SAMARA_SUPPLIER_YNX_YANDEX_CAMPAIGN_ID);
  });

  if (matches.length !== 1) {
    throw new Error('Яндекс: кампания «' + SAMARA_SUPPLIER_YNX_YANDEX_CAMPAIGN_NAME +
      '» с ID ' + SAMARA_SUPPLIER_YNX_YANDEX_CAMPAIGN_ID +
      ' не найдена ровно один раз. Совпадений: ' + matches.length + '.');
  }

  const campaign = matches[0];
  if (String(campaign.domain || '').trim() !== SAMARA_SUPPLIER_YNX_YANDEX_CAMPAIGN_NAME ||
      String(campaign.placementType || '').toUpperCase() !== 'FBS') {
    throw new Error('Яндекс: найденная кампания не соответствует «' +
      SAMARA_SUPPLIER_YNX_YANDEX_CAMPAIGN_NAME + '» / FBS.');
  }

  Logger.log('✅ Проверена кампания Яндекс: «' + campaign.domain +
    '», ID ' + campaign.id + ', модель ' + campaign.placementType + '.');
  return {
    campaignId: campaign.id,
    domain: campaign.domain,
    placementType: campaign.placementType,
    apiAvailability: campaign.apiAvailability || ''
  };
}

/**
 * Собирает сумму трёх источников в UNIT YNX!«TR YA FBS».
 * Отсутствующий артикул в источнике считается остатком 0.
 * Дубли в одном источнике складываются, чтобы не терять остаток.
 */
function aggregateSamaraSupplierStocksToUnitYnx() {
  withSamaraSupplierYnxLock_('агрегация самарских остатков', function() {
    const spreadsheet = SpreadsheetApp.openById(SAMARA_SUPPLIER_YNX_SPREADSHEET_ID);
    const targetSheet = getSamaraSupplierYnxSheet_(spreadsheet, SAMARA_SUPPLIER_YNX_TARGET_SHEET);
    const target = readSamaraSupplierYnxRows_(targetSheet, SAMARA_SUPPLIER_YNX_TARGET_KEY_HEADER);
    if (!target.rows.length) throw new Error('UNIT YNX: нет SKU в колонке «' + SAMARA_SUPPLIER_YNX_TARGET_KEY_HEADER + '».');

    const sourceMaps = {};
    SAMARA_SUPPLIER_YNX_SOURCES.forEach(function(source) {
      const sourceSheet = getSamaraSupplierYnxSheet_(spreadsheet, source.sheetName);
      sourceMaps[source.sheetName] = readSamaraSupplierYnxSourceMap_(sourceSheet, source.keyHeader, source.stockHeader);
    });

    const values = aggregateSamaraSupplierMaps_(
      target.rows.map(function(row) { return row.key; }),
      sourceMaps['FERON TR'],
      sourceMaps['ETM TR'],
      sourceMaps['РуСВ TR']
    );

    const targetStockColumn = ensureSamaraSupplierYnxHeader_(
      targetSheet,
      SAMARA_SUPPLIER_YNX_TARGET_STOCK_HEADER
    );
    targetSheet.getRange(2, targetStockColumn, values.length, 1).setValues(values);

    const positive = values.filter(function(row) { return Number(row[0]) > 0; }).length;
    const total = values.reduce(function(sum, row) { return sum + Number(row[0] || 0); }, 0);
    Logger.log('✅ Самарские остатки собраны в UNIT YNX!«' + SAMARA_SUPPLIER_YNX_TARGET_STOCK_HEADER + '».');
    Logger.log('SKU: ' + values.length + '; с остатком > 0: ' + positive + '; сумма: ' + total + '.');
  });
}

/**
 * Отправляет заранее рассчитанный UNIT YNX!«TR YA FBS» в Яндекс.
 * Перед этим не обновляет поставщиков и не изменяет Google Sheets.
 */
function syncSamaraSupplierStocksToYandexFbs() {
  withSamaraSupplierYnxLock_('отправка самарских остатков в Яндекс FBS', function() {
    const spreadsheet = SpreadsheetApp.openById(SAMARA_SUPPLIER_YNX_SPREADSHEET_ID);
    const targetSheet = getSamaraSupplierYnxSheet_(spreadsheet, SAMARA_SUPPLIER_YNX_TARGET_SHEET);
    const entries = readSamaraSupplierYnxStockEntries_(targetSheet);
    const apiKey = YANDEX_MARKET_API_KEY();
    uploadSamaraSupplierYnxStocksToYandex_(entries, apiKey);
    Logger.log('✅ UNIT YNX!«' + SAMARA_SUPPLIER_YNX_TARGET_STOCK_HEADER +
      '» → Яндекс «' + SAMARA_SUPPLIER_YNX_YANDEX_CAMPAIGN_NAME +
      '»: отправлено SKU ' + entries.length + '.');
  });
}

function withSamaraSupplierYnxLock_(operationName, callback) {
  const lock = LockService.getUserLock();
  if (!lock.tryLock(5000)) throw new Error('Самарские остатки: уже выполняется «' + operationName + '».');
  try {
    return callback();
  } finally {
    lock.releaseLock();
  }
}

function getSamaraSupplierYnxSheet_(spreadsheet, sheetName) {
  const sheet = spreadsheet.getSheetByName(sheetName);
  if (!sheet) throw new Error('Не найден лист «' + sheetName + '».');
  return sheet;
}

function normalizeSamaraSupplierYnxHeader_(value) {
  return String(value === undefined || value === null ? '' : value).trim().toLowerCase().replace(/ё/g, 'е');
}

function findSamaraSupplierYnxHeader_(headers, requiredHeader) {
  const wanted = normalizeSamaraSupplierYnxHeader_(requiredHeader);
  const matches = [];
  headers.forEach(function(value, index) {
    if (normalizeSamaraSupplierYnxHeader_(value) === wanted) matches.push(index + 1);
  });
  if (matches.length !== 1) {
    throw new Error('Лист: заголовок «' + requiredHeader + '» найден не ровно один раз: ' + matches.length + '.');
  }
  return matches[0];
}

function ensureSamaraSupplierYnxHeader_(sheet, header) {
  const headers = sheet.getRange(1, 1, 1, Math.max(1, sheet.getLastColumn())).getDisplayValues()[0];
  const wanted = normalizeSamaraSupplierYnxHeader_(header);
  const matches = [];
  headers.forEach(function(value, index) {
    if (normalizeSamaraSupplierYnxHeader_(value) === wanted) matches.push(index + 1);
  });
  if (matches.length > 1) throw new Error('UNIT YNX: заголовок «' + header + '» дублируется.');
  if (matches.length === 1) return matches[0];

  const column = Math.max(1, sheet.getLastColumn()) + 1;
  sheet.getRange(1, column).setValue(header);
  Logger.log('UNIT YNX: добавлен новый контрольный заголовок «' + header + '» в колонку ' + column + '.');
  return column;
}

function readSamaraSupplierYnxRows_(sheet, keyHeader) {
  const lastRow = sheet.getLastRow();
  const lastColumn = Math.max(1, sheet.getLastColumn());
  if (lastRow < 2) return { rows: [], keyColumn: 0, dataRowCount: 0 };
  const values = sheet.getRange(1, 1, lastRow, lastColumn).getDisplayValues();
  const keyColumn = findSamaraSupplierYnxHeader_(values[0], keyHeader);
  const rows = values.slice(1).map(function(row) {
    return { key: String(row[keyColumn - 1] || '').trim() };
  });
  return { rows: rows, keyColumn: keyColumn, dataRowCount: rows.length };
}

function parseSamaraSupplierYnxStock_(rawValue, sheetName, key) {
  const raw = String(rawValue === undefined || rawValue === null ? '' : rawValue)
    .replace(/\s|\u00a0/g, '')
    .replace(',', '.')
    .trim();
  if (!raw) return 0;
  if (!/^\d+(?:\.0+)?$/.test(raw)) {
    throw new Error('Лист «' + sheetName + '»: некорректный остаток для «' + key + '»: ' + rawValue);
  }
  const value = Number(raw);
  if (!isFinite(value) || value < 0) {
    throw new Error('Лист «' + sheetName + '»: отрицательный остаток для «' + key + '».');
  }
  return Math.trunc(value);
}

function readSamaraSupplierYnxSourceMap_(sheet, keyHeader, stockHeader) {
  const lastRow = sheet.getLastRow();
  const lastColumn = Math.max(1, sheet.getLastColumn());
  if (lastRow < 2) return {};
  const values = sheet.getRange(1, 1, lastRow, lastColumn).getDisplayValues();
  const keyColumn = findSamaraSupplierYnxHeader_(values[0], keyHeader);
  const stockColumn = findSamaraSupplierYnxHeader_(values[0], stockHeader);
  const result = {};
  values.slice(1).forEach(function(row) {
    const key = String(row[keyColumn - 1] || '').trim();
    if (!key) return;
    result[key] = (result[key] || 0) + parseSamaraSupplierYnxStock_(row[stockColumn - 1], sheet.getName(), key);
  });
  return result;
}

function aggregateSamaraSupplierMaps_(targetKeys, feronMap, etmMap, rsMap) {
  return targetKeys.map(function(key) {
    return [
      (Number(feronMap[key]) || 0) +
      (Number(etmMap[key]) || 0) +
      (Number(rsMap[key]) || 0)
    ];
  });
}

function readSamaraSupplierYnxStockEntries_(sheet) {
  const lastRow = sheet.getLastRow();
  const lastColumn = Math.max(1, sheet.getLastColumn());
  if (lastRow < 2) throw new Error('UNIT YNX: нет строк для Яндекса.');
  const values = sheet.getRange(1, 1, lastRow, lastColumn).getDisplayValues();
  const keyColumn = findSamaraSupplierYnxHeader_(values[0], SAMARA_SUPPLIER_YNX_TARGET_KEY_HEADER);
  const stockColumn = findSamaraSupplierYnxHeader_(values[0], SAMARA_SUPPLIER_YNX_TARGET_STOCK_HEADER);
  const entries = [];
  const invalid = [];
  values.slice(1).forEach(function(row) {
    const sku = String(row[keyColumn - 1] || '').trim();
    if (!sku) return;
    const raw = String(row[stockColumn - 1] || '').trim();
    if (!/^\d+$/.test(raw)) {
      invalid.push(sku);
      return;
    }
    entries.push({ sku: sku, count: Math.trunc(Number(raw)) });
  });
  if (invalid.length) {
    throw new Error('UNIT YNX!«' + SAMARA_SUPPLIER_YNX_TARGET_STOCK_HEADER +
      '»: пустые/некорректные значения у ' + invalid.length + ' SKU; в Яндекс ничего не отправлено.');
  }
  if (!entries.length) throw new Error('UNIT YNX: нет SKU для передачи в Яндекс.');
  return entries;
}

function uploadSamaraSupplierYnxStocksToYandex_(entries, apiKey) {
  for (let start = 0; start < entries.length; start += SAMARA_SUPPLIER_YNX_YANDEX_BATCH_SIZE) {
    const batch = entries.slice(start, start + SAMARA_SUPPLIER_YNX_YANDEX_BATCH_SIZE);
    const batchNumber = Math.floor(start / SAMARA_SUPPLIER_YNX_YANDEX_BATCH_SIZE) + 1;
    const response = retryFetch(
      'https://api.partner.market.yandex.ru/v2/campaigns/' +
        SAMARA_SUPPLIER_YNX_YANDEX_CAMPAIGN_ID + '/offers/stocks',
      {
        method: 'put',
        contentType: 'application/json',
        headers: {
          'Api-Key': apiKey,
          'Content-Type': 'application/json'
        },
        payload: JSON.stringify({
          skus: batch.map(function(item) {
            return { sku: item.sku, items: [{ count: item.count }] };
          })
        }),
        muteHttpExceptions: true
      },
      3
    );
    if (!response) throw new Error('Яндекс: нет ответа на батч ' + batchNumber + '.');
    const code = response.getResponseCode();
    if (code < 200 || code >= 300) {
      throw new Error('Яндекс: обновление остатков завершилось HTTP ' + code + ' на батче ' + batchNumber + '.');
    }
    Logger.log('Яндекс «' + SAMARA_SUPPLIER_YNX_YANDEX_CAMPAIGN_NAME + '»: батч ' +
      batchNumber + '/' + Math.ceil(entries.length / SAMARA_SUPPLIER_YNX_YANDEX_BATCH_SIZE) +
      ', SKU: ' + batch.length + '.');
  }
}
