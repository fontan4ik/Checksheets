/**
 * Ozon НТЦ → UNIT YNX → Яндекс Маркет (остатки и цены).
 *
 * Основные функции для ручного запуска:
 *   syncOzonNtcStocksToUnitYnx()
 *   syncUnitYnxNtcStocksToYandex()
 *   syncUnitYnxPricesToYandex()
 *
 * Источники/назначения:
 * - Ozon Seller API: FBS-остаток по точному имени склада «НТЦ СКЛАД» и
 *   offer_id из UNIT YNX!A.
 * - Google Sheets, лист «UNIT YNX»: A = offer_id Ozon / ShopSku Яндекс,
 *   T = «Целевая цена», Y = «НТЦ STOCK».
 * - Яндекс Market Partner API: кампания «ВольтМир НТЦ».
 *
 * Безопасность:
 * - Yandex API-Key читается функцией YANDEX_MARKET_API_KEY() из settings.js.
 * - Триггеры не создаются и не меняются.
 *
 * Официальная документация:
 * - Ozon: POST /v2/warehouse/list и
 *   POST /v4/product/info/stocks (filter.offer_id).
 * - Яндекс: PUT /v2/campaigns/{campaignId}/offers/stocks и
 *   POST /v2/campaigns/{campaignId}/offer-prices/updates
 */

const OZON_NTC_YNX_SPREADSHEET_ID = '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
const OZON_NTC_YNX_UNIT_SHEET_NAME = 'UNIT YNX';
const OZON_NTC_YNX_UNIT_ART_COLUMN = 1; // A: offer_id Ozon / ShopSku Яндекс
const OZON_NTC_YNX_UNIT_PRICE_COLUMN = 20; // T: Целевая цена
const OZON_NTC_YNX_UNIT_STOCK_COLUMN = 25; // Y: НТЦ STOCK
const OZON_NTC_YNX_OZON_WAREHOUSE_NAME = 'НТЦ СКЛАД';
const OZON_NTC_YNX_OZON_WAREHOUSE_LIST_URL = 'https://api-seller.ozon.ru/v2/warehouse/list';
const OZON_NTC_YNX_OZON_STOCKS_URL = 'https://api-seller.ozon.ru/v4/product/info/stocks';
const OZON_NTC_YNX_OZON_BATCH_SIZE = 1000;
const OZON_NTC_YNX_YANDEX_CAMPAIGN_ID = 149209348;
const OZON_NTC_YNX_YANDEX_STOCKS_URL = 'https://api.partner.market.yandex.ru/v2/campaigns/' + OZON_NTC_YNX_YANDEX_CAMPAIGN_ID + '/offers/stocks';
const OZON_NTC_YNX_YANDEX_PRICES_URL = 'https://api.partner.market.yandex.ru/v2/campaigns/' + OZON_NTC_YNX_YANDEX_CAMPAIGN_ID + '/offer-prices/updates';
const OZON_NTC_YNX_YANDEX_CAMPAIGNS_URL = 'https://api.partner.market.yandex.ru/v2/campaigns';
const OZON_NTC_YNX_YANDEX_BATCH_SIZE = 2000;
const OZON_NTC_YNX_YANDEX_PRICE_PER_MINUTE_LIMIT = 10000;
const OZON_NTC_YNX_YANDEX_PRICE_LIMIT_COOLDOWN_MS = 61000;

/**
 * Шаг 1. Ozon НТЦ СКЛАД → UNIT YNX!Y («НТЦ STOCK»).
 * Работает по артикулам: UNIT YNX!A ↔ ТЕСТ!A, SKU Ozon берётся из ТЕСТ!V.
 * В Яндекс ничего не отправляет.
 */
function syncOzonNtcStocksToUnitYnx() {
  withOzonNtcYnxUserLock_('загрузка остатков Ozon НТЦ в UNIT YNX', function() {
    const spreadsheet = SpreadsheetApp.openById(OZON_NTC_YNX_SPREADSHEET_ID);
    const unitSheet = getOzonNtcYnxSheet_(spreadsheet, OZON_NTC_YNX_UNIT_SHEET_NAME);
    const unitData = readOzonNtcYnxUnitStockRows_(unitSheet);
    if (!unitData.rows.length) {
      Logger.log('UNIT YNX: нет строк с offer_id в колонке A для обновления.');
      return;
    }

    const warehouse = findOzonNtcWarehouse_();
    Logger.log('Ozon: выбран склад «' + warehouse.name + '», ID ' + warehouse.id + '.');
    const freshByOfferId = fetchOzonNtcStocks_(unitData.rows, warehouse.id);

    writeOzonNtcYnxStocks_(unitSheet, unitData, freshByOfferId);
    Logger.log('✅ Ozon НТЦ СКЛАД → UNIT YNX!Y завершено.');
    Logger.log('Строк UNIT YNX с offer_id в A: ' + unitData.rows.length + '; запрошено в Ozon: ' + Object.keys(freshByOfferId).length + '.');
    Logger.log('Ненулевых остатков: ' + unitData.rows.filter(function(row) {
      return freshByOfferId[row.offerId] > 0;
    }).length + '.');
  });
}

/**
 * Шаг 2. UNIT YNX!Y («НТЦ STOCK») → Яндекс Маркет.
 * Ozon и Google Sheets не обновляет: в Яндекс уходят только уже загруженные значения Y.
 */
function syncUnitYnxNtcStocksToYandex() {
  withOzonNtcYnxUserLock_('отправка остатков UNIT YNX в Яндекс', function() {
    const spreadsheet = SpreadsheetApp.openById(OZON_NTC_YNX_SPREADSHEET_ID);
    const unitSheet = getOzonNtcYnxSheet_(spreadsheet, OZON_NTC_YNX_UNIT_SHEET_NAME);
    const entries = readOzonNtcYnxYandexStockEntries_(unitSheet);
    const apiKey = YANDEX_MARKET_API_KEY();
    uploadOzonNtcYnxStocksToYandex_(entries, apiKey);
    Logger.log('✅ UNIT YNX!Y → Яндекс: остатки отправлены для ' + entries.length + ' SKU.');
  });
}

/**
 * Шаг 3. UNIT YNX!T («Целевая цена») → Яндекс Маркет.
 * Остатки и Ozon не обновляет.
 */
function syncUnitYnxPricesToYandex() {
  withOzonNtcYnxUserLock_('отправка цен UNIT YNX в Яндекс', function() {
    const spreadsheet = SpreadsheetApp.openById(OZON_NTC_YNX_SPREADSHEET_ID);
    const unitSheet = getOzonNtcYnxSheet_(spreadsheet, OZON_NTC_YNX_UNIT_SHEET_NAME);
    const entries = readOzonNtcYnxYandexPriceEntries_(unitSheet);
    const apiKey = YANDEX_MARKET_API_KEY();
    uploadOzonNtcYnxPricesToYandex_(entries, apiKey);
    Logger.log('✅ UNIT YNX!T → Яндекс: цены отправлены для ' + entries.length + ' SKU.');
  });
}

function withOzonNtcYnxUserLock_(operationName, callback) {
  // Не блокируемся глобальными ScriptLock из других Ozon/WB задач проекта.
  const lock = LockService.getUserLock();
  if (!lock.tryLock(5000)) {
    throw new Error('НТЦ: уже выполняется «' + operationName + '».');
  }
  try {
    return callback();
  } finally {
    lock.releaseLock();
  }
}

/**
 * Read-only проверка ключа и кампании. Запись остатков не выполняется.
 */
function verifyYandexNtcConfiguration() {
  const apiKey = YANDEX_MARKET_API_KEY();
  const response = retryFetch(OZON_NTC_YNX_YANDEX_CAMPAIGNS_URL, {
    method: 'get',
    headers: {
      'Api-Key': apiKey,
      'Content-Type': 'application/json'
    },
    muteHttpExceptions: true
  }, 3);

  if (!response) throw new Error('Яндекс: не получен ответ от /v2/campaigns.');
  const code = response.getResponseCode();
  if (code < 200 || code >= 300) {
    throw new Error('Яндекс: проверка кампаний завершилась HTTP ' + code + '.');
  }

  const data = JSON.parse(response.getContentText());
  const campaigns = data.campaigns || [];
  const target = campaigns.filter(function(item) {
    return String(item.id) === String(OZON_NTC_YNX_YANDEX_CAMPAIGN_ID);
  })[0];

  if (!target) {
    throw new Error('Яндекс: кампания ' + OZON_NTC_YNX_YANDEX_CAMPAIGN_ID + ' не найдена у текущего API-Key.');
  }

  Logger.log('✅ Яндекс API доступен. Кампания: «' + (target.domain || '') + '», ID ' + target.id + ', модель ' + (target.placementType || '') + '.');
  return {
    campaignId: target.id,
    domain: target.domain || '',
    placementType: target.placementType || '',
    apiAvailability: target.apiAvailability || ''
  };
}

function getOzonNtcYnxSheet_(spreadsheet, name) {
  const sheet = spreadsheet.getSheetByName(name);
  if (!sheet) throw new Error('Не найден лист «' + name + '».');
  return sheet;
}

function readOzonNtcYnxUnitStockRows_(sheet) {
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return { rows: [], stockValues: [] };

  const values = sheet.getRange(1, 1, lastRow, OZON_NTC_YNX_UNIT_STOCK_COLUMN).getDisplayValues();
  const headers = values[0];
  validateOzonNtcYnxStockHeader_(headers);

  const rows = [];
  const stockValues = [];
  values.slice(1).forEach(function(row, index) {
    const offerId = String(row[OZON_NTC_YNX_UNIT_ART_COLUMN - 1] || '').trim();
    stockValues.push([row[OZON_NTC_YNX_UNIT_STOCK_COLUMN - 1] || '']);
    if (offerId) rows.push({
      rowNumber: index + 2,
      offerId: offerId
    });
  });

  return { rows: rows, stockValues: stockValues };
}

function readOzonNtcYnxYandexStockEntries_(sheet) {
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) throw new Error('UNIT YNX: нет строк для передачи остатков в Яндекс.');

  const values = sheet.getRange(1, 1, lastRow, OZON_NTC_YNX_UNIT_STOCK_COLUMN).getDisplayValues();
  validateOzonNtcYnxStockHeader_(values[0]);
  const entries = [];
  const invalidOfferIds = [];

  values.slice(1).forEach(function(row) {
    const offerId = String(row[OZON_NTC_YNX_UNIT_ART_COLUMN - 1] || '').trim();
    if (!offerId) return;
    const count = parseOzonNtcYnxStock_(row[OZON_NTC_YNX_UNIT_STOCK_COLUMN - 1]);
    if (count === null) {
      invalidOfferIds.push(offerId);
      return;
    }
    entries.push({ sku: offerId, count: count });
  });

  if (invalidOfferIds.length) {
    throw new Error('UNIT YNX!Y («НТЦ STOCK»): пустой или некорректный остаток у ' + invalidOfferIds.length + ' SKU; в Яндекс ничего не отправлено.');
  }
  if (!entries.length) throw new Error('UNIT YNX: нет SKU с остатками для передачи в Яндекс.');
  return entries;
}

function readOzonNtcYnxYandexPriceEntries_(sheet) {
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) throw new Error('UNIT YNX: нет строк для передачи цен в Яндекс.');

  const values = sheet.getRange(1, 1, lastRow, OZON_NTC_YNX_UNIT_PRICE_COLUMN).getDisplayValues();
  const headers = values[0];
  validateOzonNtcYnxPriceHeader_(headers);
  const entries = [];
  const invalidOfferIds = [];

  values.slice(1).forEach(function(row) {
    const offerId = String(row[OZON_NTC_YNX_UNIT_ART_COLUMN - 1] || '').trim();
    if (!offerId) return;
    const price = parseOzonNtcYnxPrice_(row[OZON_NTC_YNX_UNIT_PRICE_COLUMN - 1]);
    if (price === null) {
      invalidOfferIds.push(offerId);
      return;
    }
    entries.push({ offerId: offerId, price: price });
  });

  if (invalidOfferIds.length) {
    throw new Error('UNIT YNX!T («Целевая цена»): пустая или некорректная цена у ' + invalidOfferIds.length + ' SKU; в Яндекс ничего не отправлено.');
  }
  if (!entries.length) throw new Error('UNIT YNX: нет SKU с ценами для передачи в Яндекс.');
  return entries;
}

function validateOzonNtcYnxStockHeader_(headers) {
  const stockHeader = String(headers[OZON_NTC_YNX_UNIT_STOCK_COLUMN - 1] || '').trim().toLowerCase();
  if (stockHeader.indexOf('нтц') === -1 || stockHeader.indexOf('stock') === -1) {
    throw new Error('UNIT YNX!Y: ожидался заголовок с «НТЦ» и «STOCK», получено «' + headers[OZON_NTC_YNX_UNIT_STOCK_COLUMN - 1] + '».');
  }
}

function validateOzonNtcYnxPriceHeader_(headers) {
  const priceHeader = String(headers[OZON_NTC_YNX_UNIT_PRICE_COLUMN - 1] || '').trim().toLowerCase();
  if (priceHeader !== 'целевая цена') {
    throw new Error('UNIT YNX!T: ожидался заголовок «Целевая цена», получено «' + headers[OZON_NTC_YNX_UNIT_PRICE_COLUMN - 1] + '».');
  }
}

function parseOzonNtcYnxPrice_(rawValue) {
  const normalized = String(rawValue === undefined || rawValue === null ? '' : rawValue)
    .replace(/\s|\u00A0/g, '')
    .replace(',', '.');
  if (!normalized || !/^\d+(\.\d+)?$/.test(normalized)) return null;
  const value = Number(normalized);
  if (!isFinite(value) || value <= 0) return null;
  return Math.round(value * 100) / 100;
}

function parseOzonNtcYnxStock_(rawValue) {
  const normalized = String(rawValue === undefined || rawValue === null ? '' : rawValue)
    .replace(/\s|\u00A0/g, '')
    .replace(',', '.');
  if (!normalized || !/^\d+(\.0+)?$/.test(normalized)) return null;
  const value = Number(normalized);
  if (!isFinite(value) || value < 0) return null;
  return Math.trunc(value);
}

function findOzonNtcWarehouse_() {
  const response = retryFetch(OZON_NTC_YNX_OZON_WAREHOUSE_LIST_URL, {
    method: 'post',
    contentType: 'application/json',
    headers: ozonHeaders(),
    payload: JSON.stringify({ limit: 200, offset: 0 }),
    muteHttpExceptions: true
  }, 3);

  if (!response) throw new Error('Ozon: не получен список складов.');
  const code = response.getResponseCode();
  if (code < 200 || code >= 300) throw new Error('Ozon: список складов завершился HTTP ' + code + '.');

  const data = JSON.parse(response.getContentText());
  const warehouses = Array.isArray(data.warehouses) ? data.warehouses : [];
  const targetName = OZON_NTC_YNX_OZON_WAREHOUSE_NAME.toLowerCase();
  const matches = warehouses.filter(function(item) {
    return String(item.name || '').trim().toLowerCase() === targetName;
  });

  if (matches.length !== 1) {
    throw new Error('Ozon: не найден ровно один склад «' + OZON_NTC_YNX_OZON_WAREHOUSE_NAME + '». Совпадений: ' + matches.length + '.');
  }

  return { id: String(matches[0].warehouse_id), name: String(matches[0].name || '') };
}

function fetchOzonNtcStocks_(unitRows, warehouseId) {
  const stockByOfferId = {};
  const uniqueOfferIds = [];
  const seen = {};
  const warehouseKey = String(warehouseId);

  unitRows.forEach(function(row) {
    const offerId = String(row.offerId || '').trim();
    if (offerId && !seen[offerId]) {
      seen[offerId] = true;
      uniqueOfferIds.push(offerId);
    }
  });

  for (let start = 0; start < uniqueOfferIds.length; start += OZON_NTC_YNX_OZON_BATCH_SIZE) {
    const chunk = uniqueOfferIds.slice(start, start + OZON_NTC_YNX_OZON_BATCH_SIZE);
    let cursor = '';
    let page = 0;
    do {
      page += 1;
      const response = retryFetch(OZON_NTC_YNX_OZON_STOCKS_URL, {
        method: 'post',
        contentType: 'application/json',
        headers: ozonHeaders(),
        payload: JSON.stringify({
          cursor: cursor,
          filter: {
            offer_id: chunk,
            visibility: 'ALL'
          },
          limit: chunk.length
        }),
        muteHttpExceptions: true
      }, 3);

      const batchNumber = Math.floor(start / OZON_NTC_YNX_OZON_BATCH_SIZE) + 1;
      if (!response) throw new Error('Ozon: не получены остатки для батча offer_id ' + batchNumber + '.');
      const code = response.getResponseCode();
      if (code < 200 || code >= 300) throw new Error('Ozon: остатки завершились HTTP ' + code + ' на батче offer_id ' + batchNumber + '.');

      const data = JSON.parse(response.getContentText());
      const result = Array.isArray(data.items) ? data.items : [];
      result.forEach(function(item) {
        const offerId = String(item.offer_id || '').trim();
        if (!offerId) return;
        const stock = (Array.isArray(item.stocks) ? item.stocks : []).reduce(function(total, stockItem) {
          const warehouseIds = Array.isArray(stockItem.warehouse_ids) ? stockItem.warehouse_ids : [];
          const belongsToNtc = warehouseIds.some(function(id) {
            return String(id) === warehouseKey;
          });
          if (!belongsToNtc) return total;
          const present = Math.max(0, Number(stockItem.present) || 0);
          const reserved = Math.max(0, Number(stockItem.reserved) || 0);
          return total + present + reserved;
        }, 0);
        stockByOfferId[offerId] = Math.trunc(stock);
      });

      cursor = String(data.cursor || '').trim();
      Logger.log('Ozon: offer_id батч ' + batchNumber + '/' + Math.ceil(uniqueOfferIds.length / OZON_NTC_YNX_OZON_BATCH_SIZE) + ', страница ' + page + ', offer_id: ' + chunk.length + '.');
    } while (cursor);
  }

  uniqueOfferIds.forEach(function(offerId) {
    if (!Object.prototype.hasOwnProperty.call(stockByOfferId, offerId)) stockByOfferId[offerId] = 0;
  });
  return stockByOfferId;
}

function writeOzonNtcYnxStocks_(sheet, unitData, freshByOfferId) {
  const offerIdByRowNumber = {};
  unitData.rows.forEach(function(item) {
    offerIdByRowNumber[item.rowNumber] = item.offerId;
  });

  const values = unitData.stockValues.map(function(row, index) {
    const offerId = offerIdByRowNumber[index + 2];
    if (!offerId) return row;
    return Object.prototype.hasOwnProperty.call(freshByOfferId, offerId)
      ? [freshByOfferId[offerId]]
      : row;
  });

  if (values.length) {
    sheet.getRange(2, OZON_NTC_YNX_UNIT_STOCK_COLUMN, values.length, 1).setValues(values);
  }
}

function uploadOzonNtcYnxStocksToYandex_(entries, apiKey) {
  for (let start = 0; start < entries.length; start += OZON_NTC_YNX_YANDEX_BATCH_SIZE) {
    const batch = entries.slice(start, start + OZON_NTC_YNX_YANDEX_BATCH_SIZE);
    const response = retryFetch(OZON_NTC_YNX_YANDEX_STOCKS_URL, {
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
    }, 3);

    if (!response) throw new Error('Яндекс: не получен ответ на батч ' + (Math.floor(start / OZON_NTC_YNX_YANDEX_BATCH_SIZE) + 1) + '.');
    const code = response.getResponseCode();
    if (code < 200 || code >= 300) {
      throw new Error('Яндекс: передача остатков завершилась HTTP ' + code + ' на батче ' + (Math.floor(start / OZON_NTC_YNX_YANDEX_BATCH_SIZE) + 1) + '.');
    }

    Logger.log('Яндекс: остатки, батч ' + (Math.floor(start / OZON_NTC_YNX_YANDEX_BATCH_SIZE) + 1) + '/' + Math.ceil(entries.length / OZON_NTC_YNX_YANDEX_BATCH_SIZE) + ', SKU: ' + batch.length + '.');
  }
}

function uploadOzonNtcYnxPricesToYandex_(entries, apiKey) {
  let pricesSentInCurrentWindow = 0;

  for (let start = 0; start < entries.length; start += OZON_NTC_YNX_YANDEX_BATCH_SIZE) {
    const batch = entries.slice(start, start + OZON_NTC_YNX_YANDEX_BATCH_SIZE);
    const batchNumber = Math.floor(start / OZON_NTC_YNX_YANDEX_BATCH_SIZE) + 1;

    if (pricesSentInCurrentWindow + batch.length > OZON_NTC_YNX_YANDEX_PRICE_PER_MINUTE_LIMIT) {
      Logger.log('Яндекс: достигнут лимит цен ' + OZON_NTC_YNX_YANDEX_PRICE_PER_MINUTE_LIMIT + ' SKU/мин; ожидание ' + (OZON_NTC_YNX_YANDEX_PRICE_LIMIT_COOLDOWN_MS / 1000) + ' сек.');
      Utilities.sleep(OZON_NTC_YNX_YANDEX_PRICE_LIMIT_COOLDOWN_MS);
      pricesSentInCurrentWindow = 0;
    }

    let response = null;
    for (let attempt = 1; attempt <= 2; attempt++) {
      response = retryFetch(OZON_NTC_YNX_YANDEX_PRICES_URL, {
        method: 'post',
        contentType: 'application/json',
        headers: {
          'Api-Key': apiKey,
          'Content-Type': 'application/json'
        },
        payload: JSON.stringify({
          offers: batch.map(function(item) {
            return {
              offerId: item.offerId,
              price: {
                value: item.price,
                currencyId: 'RUR'
              }
            };
          })
        }),
        muteHttpExceptions: true
      }, 3);

      if (!response) break;
      const code = response.getResponseCode();
      if (code >= 200 && code < 300) break;
      if (code === 420 && attempt === 1) {
        Logger.log('Яндекс: HTTP 420 для цен, ожидание ' + (OZON_NTC_YNX_YANDEX_PRICE_LIMIT_COOLDOWN_MS / 1000) + ' сек. перед одной повторной попыткой.');
        Utilities.sleep(OZON_NTC_YNX_YANDEX_PRICE_LIMIT_COOLDOWN_MS);
        pricesSentInCurrentWindow = 0;
        continue;
      }
      throw new Error('Яндекс: передача цен завершилась HTTP ' + code + ' на батче ' + batchNumber + '.');
    }

    if (!response) throw new Error('Яндекс: не получен ответ на батч цен ' + batchNumber + '.');
    const finalCode = response.getResponseCode();
    if (finalCode < 200 || finalCode >= 300) {
      throw new Error('Яндекс: передача цен завершилась HTTP ' + finalCode + ' на батче ' + batchNumber + '.');
    }

    pricesSentInCurrentWindow += batch.length;
    Logger.log('Яндекс: цены, батч ' + batchNumber + '/' + Math.ceil(entries.length / OZON_NTC_YNX_YANDEX_BATCH_SIZE) + ', SKU: ' + batch.length + '.');
  }
}
