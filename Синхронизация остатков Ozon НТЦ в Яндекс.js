/**
 * Ozon НТЦ → UNIT YNX → Яндекс Маркет.
 *
 * Основная функция для ручного запуска и часового триггера:
 *   syncOzonNtcStocksToYandex()
 *
 * Источники/назначения:
 * - Ozon Seller API: FBS-остаток по складу с названием «НТЦ».
 * - Google Sheets, лист «UNIT YNX»: A = offerId/ShopSku Яндекс,
 *   Y = «НТЦ STOCK».
 * - Яндекс Market Partner API: кампания «ВольтМир НТЦ».
 *
 * Безопасность:
 * - Yandex API-Key не хранится в исходнике. Однократно выполните
 *   setupYandexMarketApiKey() вручную и вставьте ключ в диалог.
 * - Триггер запускает только syncOzonNtcStocksToYandex().
 *
 * Официальная документация:
 * - Ozon: POST /v1/warehouse/list и
 *   POST /v1/product/info/stocks-by-warehouse/fbs
 * - Yandex: PUT /v2/campaigns/{campaignId}/offers/stocks
 */

const OZON_NTC_YNX_SPREADSHEET_ID = '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
const OZON_NTC_YNX_UNIT_SHEET_NAME = 'UNIT YNX';
const OZON_NTC_YNX_OZON_SHEET_NAME = 'ТЕСТ';
const OZON_NTC_YNX_UNIT_ART_COLUMN = 1; // A: art / ShopSku Яндекс
const OZON_NTC_YNX_UNIT_STOCK_COLUMN = 25; // Y: НТЦ STOCK
const OZON_NTC_YNX_OZON_ART_COLUMN = 1; // A: Артикул
const OZON_NTC_YNX_OZON_SKU_COLUMN = 22; // V: SKU Ozon
const OZON_NTC_YNX_OZON_WAREHOUSE_NAME = 'НТЦ';
const OZON_NTC_YNX_OZON_WAREHOUSE_LIST_URL = 'https://api-seller.ozon.ru/v1/warehouse/list';
const OZON_NTC_YNX_OZON_STOCKS_URL = 'https://api-seller.ozon.ru/v1/product/info/stocks-by-warehouse/fbs';
const OZON_NTC_YNX_OZON_BATCH_SIZE = 500;
const OZON_NTC_YNX_YANDEX_CAMPAIGN_ID = 149209348;
const OZON_NTC_YNX_YANDEX_STOCKS_URL = 'https://api.partner.market.yandex.ru/v2/campaigns/' + OZON_NTC_YNX_YANDEX_CAMPAIGN_ID + '/offers/stocks';
const OZON_NTC_YNX_YANDEX_CAMPAIGNS_URL = 'https://api.partner.market.yandex.ru/v2/campaigns';
const OZON_NTC_YNX_YANDEX_PROPERTY = 'YANDEX_MARKET_API_KEY';
const OZON_NTC_YNX_YANDEX_BATCH_SIZE = 2000;

/**
 * Главная функция. Не создаёт и не меняет триггеры.
 */
function syncOzonNtcStocksToYandex() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(5000)) {
    throw new Error('Синхронизация уже выполняется: получен lock не был.');
  }

  try {
    const yandexApiKey = getOzonNtcYnxYandexApiKey_();
    const spreadsheet = SpreadsheetApp.openById(OZON_NTC_YNX_SPREADSHEET_ID);
    const unitSheet = getOzonNtcYnxSheet_(spreadsheet, OZON_NTC_YNX_UNIT_SHEET_NAME);
    const ozonSheet = getOzonNtcYnxSheet_(spreadsheet, OZON_NTC_YNX_OZON_SHEET_NAME);

    const unitData = readOzonNtcYnxUnitRows_(unitSheet);
    if (!unitData.rows.length) {
      Logger.log('UNIT YNX: нет строк с art для обновления.');
      return;
    }

    const ozonSkuByArt = readOzonNtcYnxOzonSkuMap_(ozonSheet);
    const apiRows = unitData.rows.filter(function(row) {
      return row.offerId && ozonSkuByArt[row.offerId];
    });

    if (!apiRows.length) {
      throw new Error('Не найдено ни одного соответствия UNIT YNX!A ↔ ТЕСТ!A с SKU Ozon в V.');
    }

    const warehouse = findOzonNtcWarehouse_();
    Logger.log('Ozon: выбран склад «' + warehouse.name + '», ID ' + warehouse.id + '.');

    const stockBySku = fetchOzonNtcStocks_(apiRows, ozonSkuByArt, warehouse.id);
    const freshByOfferId = {};
    apiRows.forEach(function(row) {
      const sku = ozonSkuByArt[row.offerId];
      const skuKey = String(sku);
      freshByOfferId[row.offerId] = Object.prototype.hasOwnProperty.call(stockBySku, skuKey)
        ? stockBySku[skuKey]
        : 0;
    });

    writeOzonNtcYnxStocks_(unitSheet, unitData, freshByOfferId);
    const yandexEntries = apiRows.map(function(row) {
      return {
        sku: row.offerId,
        count: freshByOfferId[row.offerId]
      };
    });

    uploadOzonNtcYnxStocksToYandex_(yandexEntries, yandexApiKey);

    Logger.log('✅ Ozon НТЦ → UNIT YNX → Яндекс завершено.');
    Logger.log('Строк UNIT YNX: ' + unitData.rows.length + '; получено из Ozon: ' + apiRows.length + '.');
    Logger.log('Ненулевых остатков: ' + yandexEntries.filter(function(item) { return item.count > 0; }).length + '.');
    Logger.log('Отправлено в Яндекс: ' + yandexEntries.length + ' SKU.');
  } finally {
    lock.releaseLock();
  }
}

/**
 * Однократная ручная настройка ключа Яндекс.
 * Ключ вводится пользователем в диалог и сохраняется в Script Properties.
 */
function setupYandexMarketApiKey() {
  const ui = SpreadsheetApp.getUi();
  const result = ui.prompt(
    'Настройка Яндекс Market API',
    'Вставьте API-Key Яндекс Маркета. Значение не записывается в исходник.',
    ui.ButtonSet.OK_CANCEL
  );

  if (result.getSelectedButton() !== ui.Button.OK) {
    Logger.log('Настройка отменена.');
    return;
  }

  const apiKey = String(result.getResponseText() || '').trim();
  if (!apiKey) {
    throw new Error('Пустой API-Key Яндекс Маркета.');
  }

  PropertiesService.getScriptProperties().setProperty(OZON_NTC_YNX_YANDEX_PROPERTY, apiKey);
  Logger.log('✅ API-Key Яндекс Маркета сохранён в Script Properties.');
}

/**
 * Read-only проверка ключа и кампании. Запись остатков не выполняется.
 */
function verifyYandexNtcConfiguration() {
  const apiKey = getOzonNtcYnxYandexApiKey_();
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

function getOzonNtcYnxYandexApiKey_() {
  const value = PropertiesService.getScriptProperties().getProperty(OZON_NTC_YNX_YANDEX_PROPERTY);
  if (!value || !String(value).trim()) {
    throw new Error('Не задан Script Property ' + OZON_NTC_YNX_YANDEX_PROPERTY + '. Сначала выполните setupYandexMarketApiKey().');
  }
  return String(value).trim();
}

function getOzonNtcYnxSheet_(spreadsheet, name) {
  const sheet = spreadsheet.getSheetByName(name);
  if (!sheet) throw new Error('Не найден лист «' + name + '».');
  return sheet;
}

function readOzonNtcYnxUnitRows_(sheet) {
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return { rows: [], stockValues: [] };

  const values = sheet.getRange(1, 1, lastRow, OZON_NTC_YNX_UNIT_STOCK_COLUMN).getDisplayValues();
  const headers = values[0];
  const stockHeader = String(headers[OZON_NTC_YNX_UNIT_STOCK_COLUMN - 1] || '').trim().toLowerCase();
  if (stockHeader.indexOf('нтц') === -1 || stockHeader.indexOf('stock') === -1) {
    throw new Error('UNIT YNX!Y: ожидался заголовок с «НТЦ» и «STOCK», получено «' + headers[OZON_NTC_YNX_UNIT_STOCK_COLUMN - 1] + '».');
  }

  const rows = [];
  const stockValues = [];
  values.slice(1).forEach(function(row, index) {
    const offerId = String(row[OZON_NTC_YNX_UNIT_ART_COLUMN - 1] || '').trim();
    stockValues.push([row[OZON_NTC_YNX_UNIT_STOCK_COLUMN - 1] || '']);
    if (offerId) rows.push({ rowNumber: index + 2, offerId: offerId });
  });

  return { rows: rows, stockValues: stockValues };
}

function readOzonNtcYnxOzonSkuMap_(sheet) {
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) throw new Error('Лист «' + OZON_NTC_YNX_OZON_SHEET_NAME + '» пуст.');

  const values = sheet.getRange(1, 1, lastRow, OZON_NTC_YNX_OZON_SKU_COLUMN).getDisplayValues();
  const map = {};
  values.slice(1).forEach(function(row) {
    const offerId = String(row[OZON_NTC_YNX_OZON_ART_COLUMN - 1] || '').trim();
    const sku = String(row[OZON_NTC_YNX_OZON_SKU_COLUMN - 1] || '').trim();
    if (!offerId || !sku || !/^\d+$/.test(sku)) return;
    if (!Object.prototype.hasOwnProperty.call(map, offerId)) map[offerId] = sku;
  });

  return map;
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
  const warehouses = Array.isArray(data.result) ? data.result : [];
  const targetName = OZON_NTC_YNX_OZON_WAREHOUSE_NAME.toLowerCase();
  const exact = warehouses.filter(function(item) {
    return String(item.name || '').trim().toLowerCase() === targetName;
  });
  const partial = warehouses.filter(function(item) {
    return String(item.name || '').toLowerCase().indexOf(targetName) !== -1;
  });
  const matches = exact.length ? exact : partial;

  if (matches.length !== 1) {
    throw new Error('Ozon: найдено складов с «' + OZON_NTC_YNX_OZON_WAREHOUSE_NAME + '»: ' + matches.length + '. Нельзя безопасно выбрать склад.');
  }

  return { id: String(matches[0].warehouse_id), name: String(matches[0].name || '') };
}

function fetchOzonNtcStocks_(unitRows, skuByArt, warehouseId) {
  const stockBySku = {};
  const uniqueSkus = [];
  const seen = {};

  unitRows.forEach(function(row) {
    const sku = String(skuByArt[row.offerId] || '').trim();
    if (sku && !seen[sku]) {
      seen[sku] = true;
      uniqueSkus.push(sku);
    }
  });

  for (let start = 0; start < uniqueSkus.length; start += OZON_NTC_YNX_OZON_BATCH_SIZE) {
    const chunk = uniqueSkus.slice(start, start + OZON_NTC_YNX_OZON_BATCH_SIZE).map(Number);
    const response = retryFetch(OZON_NTC_YNX_OZON_STOCKS_URL, {
      method: 'post',
      contentType: 'application/json',
      headers: ozonHeaders(),
      payload: JSON.stringify({
        sku: chunk,
        warehouse_id: Number(warehouseId),
        limit: OZON_NTC_YNX_OZON_BATCH_SIZE
      }),
      muteHttpExceptions: true
    }, 3);

    if (!response) throw new Error('Ozon: не получены остатки для батча ' + (Math.floor(start / OZON_NTC_YNX_OZON_BATCH_SIZE) + 1) + '.');
    const code = response.getResponseCode();
    if (code < 200 || code >= 300) throw new Error('Ozon: остатки завершились HTTP ' + code + ' на батче ' + (Math.floor(start / OZON_NTC_YNX_OZON_BATCH_SIZE) + 1) + '.');

    const data = JSON.parse(response.getContentText());
    const result = Array.isArray(data.result) ? data.result : [];
    result.forEach(function(item) {
      if (String(item.warehouse_id) !== String(warehouseId)) return;
      const sku = String(item.sku || '').trim();
      if (!sku) return;
      const present = Math.max(0, Number(item.present) || 0);
      const reserved = Math.max(0, Number(item.reserved) || 0);
      stockBySku[sku] = Math.trunc(present + reserved);
    });

    Logger.log('Ozon: батч ' + (Math.floor(start / OZON_NTC_YNX_OZON_BATCH_SIZE) + 1) + '/' + Math.ceil(uniqueSkus.length / OZON_NTC_YNX_OZON_BATCH_SIZE) + ', SKU: ' + chunk.length + '.');
  }

  return stockBySku;
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

    Logger.log('Яндекс: батч ' + (Math.floor(start / OZON_NTC_YNX_YANDEX_BATCH_SIZE) + 1) + '/' + Math.ceil(entries.length / OZON_NTC_YNX_YANDEX_BATCH_SIZE) + ', SKU: ' + batch.length + '.');
  }
}
