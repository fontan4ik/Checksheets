/**
 * HUCKSTER REPRAISER: чтение цен и запись цен из листа ARL TR
 *
 * Заполняет лист "ТЕСТ":
 * - BN (66): текущая выставленная цена (upload_price)
 * - BO (67): рекомендуемая цена / РЦ для удержания (market_card_price)
 * - колонка с заголовком "Цена на витрине с картой Х": цена по карте (market_card_price)
 * - колонка с заголовком "Мин. цена продажи" (также поддерживается
 *   исторический вариант "Мин цена продажи Х"): минимальная цена (min_price)
 *
 * Источник: POST /markets/integrations/repricer/items/list
 * База API: https://wbs.e-teleport.ru
 *
 * ВАЖНО:
 * - updateHucksterPrices() — read-only выгрузка цен Huckster в лист "ТЕСТ".
 * - syncHucksterPricesFromArlTr() — запись только минимальной цены из U
 *   листа "ARL TR" в `min_price` Huckster.
 * - Логин/пароль хранятся только в Script Properties Apps Script.
 * - Для сопоставления используется V (22) — SKU Ozon; A (1) — fallback для
 *   случаев, когда Huckster вернул артикул в формате offer_id.
 * - Если в Huckster несколько кабинетов Ozon и HUCKSTER_SHOP_ID не задан,
 *   функция остановится без записи и попросит выбрать кабинет.
 * - Две новые целевые колонки ищутся по заголовкам в строке 1.
 */

var HUCKSTER_API_BASE_URL = 'https://wbs.e-teleport.ru';
var HUCKSTER_TARGET_SHEET_NAME = 'ТЕСТ';
var HUCKSTER_MARKETPLACE = 'ozon';
// Секреты и shop_id задаются только через Script Properties Apps Script.
var HUCKSTER_USER_NAME = '';
var HUCKSTER_PASSWORD = '';
var HUCKSTER_SHOP_ID = '';
var HUCKSTER_SKU_COLUMN = 22; // V: SKU Ozon
var HUCKSTER_OFFER_ID_COLUMN = 1; // A: offer_id
var HUCKSTER_CURRENT_PRICE_COLUMN = 66; // BN
var HUCKSTER_RECOMMENDED_PRICE_COLUMN = 67; // BO
var HUCKSTER_MARKET_CARD_PRICE_HEADER = 'Цена на витрине с картой Х';
var HUCKSTER_MIN_PRICE_HEADERS = [
  'Мин цена продажи Х',
  'Мин. цена продажи',
  'Мин цена продажи'
];
var HUCKSTER_PAGE_SIZE = 1000;
var HUCKSTER_WRITE_BATCH_SIZE = 100;
var HUCKSTER_ARL_SHEET_NAME = 'ARL TR';
var HUCKSTER_ARL_VENDOR_CODE_COLUMN = 1; // A: Артикул продавца / offer_id
var HUCKSTER_ARL_MIN_PRICE_COLUMN = 21; // U: МИНИМАЛЬНАЯ ХАКСТЕР

/**
 * Основной read/write запуск: получает данные Huckster и записывает четыре
 * согласованные колонки на листе "ТЕСТ".
 */
function updateHucksterPrices() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) {
    throw new Error('Другой запуск updateHucksterPrices уже выполняется.');
  }

  try {
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(HUCKSTER_TARGET_SHEET_NAME);
    if (!sheet) {
      throw new Error('Не найден лист "' + HUCKSTER_TARGET_SHEET_NAME + '".');
    }

    var lastRow = sheet.getLastRow();
    if (lastRow < 2) {
      Logger.log('Huckster: в листе нет строк товаров.');
      return { rows: 0, matchedItems: 0, updatedRows: 0 };
    }

    var targetColumns = hucksterResolveTargetColumns_(sheet);
    var session = hucksterCreateSession_();
    var shopId = hucksterResolveShopId_(session);
    var items = hucksterLoadRepricerItems_(session, shopId);

    var skuValues = sheet.getRange(2, HUCKSTER_SKU_COLUMN, lastRow - 1, 1).getDisplayValues();
    var offerIdValues = sheet.getRange(2, HUCKSTER_OFFER_ID_COLUMN, lastRow - 1, 1).getDisplayValues();
    var currentValues = sheet.getRange(2, HUCKSTER_CURRENT_PRICE_COLUMN, lastRow - 1, 1).getValues();
    var recommendedValues = sheet.getRange(2, HUCKSTER_RECOMMENDED_PRICE_COLUMN, lastRow - 1, 1).getValues();
    var marketCardPriceValues = sheet.getRange(2, targetColumns.marketCardPrice, lastRow - 1, 1).getValues();
    var minPriceValues = sheet.getRange(2, targetColumns.minPrice, lastRow - 1, 1).getValues();

    var skuRowIndex = {};
    var offerIdRowIndex = {};
    skuValues.forEach(function(row, index) {
      hucksterAddRowKey_(row[0], index, skuRowIndex);
    });
    offerIdValues.forEach(function(row, index) {
      hucksterAddRowKey_(row[0], index, offerIdRowIndex);
    });

    var matchedItems = 0;
    var updatedRows = 0;
    var unmatchedItems = 0;

    items.forEach(function(item) {
      var key = hucksterNormalizeKey_(item.sku);
      // Основной ключ — V/SKU Ozon. A/offer_id используется только как fallback.
      var rows = key && skuRowIndex[key] ? skuRowIndex[key] : [];
      if (!rows.length && key && offerIdRowIndex[key]) {
        rows = offerIdRowIndex[key];
      }

      if (!rows.length) {
        unmatchedItems++;
        return;
      }

      matchedItems++;
      var mappedPrices = hucksterMapPrices_(item);
      var displayedPrice = mappedPrices.displayedPrice;
      var recommendedPrice = mappedPrices.recommendedPrice;
      var marketCardPrice = mappedPrices.marketCardPrice;
      var minPrice = mappedPrices.minPrice;

      rows.forEach(function(index) {
        var changed = false;
        // Не затираем старое значение, если Huckster не вернул цену.
        if (displayedPrice !== '') {
          if (currentValues[index][0] !== displayedPrice) changed = true;
          currentValues[index][0] = displayedPrice;
        }
        if (recommendedPrice !== '') {
          if (recommendedValues[index][0] !== recommendedPrice) changed = true;
          recommendedValues[index][0] = recommendedPrice;
        }
        if (marketCardPrice !== '') {
          if (marketCardPriceValues[index][0] !== marketCardPrice) changed = true;
          marketCardPriceValues[index][0] = marketCardPrice;
        }
        if (minPrice !== '') {
          if (minPriceValues[index][0] !== minPrice) changed = true;
          minPriceValues[index][0] = minPrice;
        }
        if (changed) updatedRows++;
      });
    });

    // Записываем только четыре согласованные целевые колонки.
    sheet.getRange(2, HUCKSTER_CURRENT_PRICE_COLUMN, lastRow - 1, 1).setValues(currentValues);
    sheet.getRange(2, HUCKSTER_RECOMMENDED_PRICE_COLUMN, lastRow - 1, 1).setValues(recommendedValues);
    sheet.getRange(2, targetColumns.marketCardPrice, lastRow - 1, 1).setValues(marketCardPriceValues);
    sheet.getRange(2, targetColumns.minPrice, lastRow - 1, 1).setValues(minPriceValues);

    var report = {
      rows: lastRow - 1,
      shopId: shopId,
      hucksterItems: items.length,
      matchedItems: matchedItems,
      unmatchedItems: unmatchedItems,
      updatedRows: updatedRows,
      columns: 'BN:BO,' + targetColumns.marketCardPriceLetter + ',' + targetColumns.minPriceLetter
    };
    Logger.log('Huckster цены обновлены: ' + JSON.stringify(report));
    return report;
  } finally {
    lock.releaseLock();
  }
}

/**
 * Записывает минимальную цену продажи из колонки U листа "ARL TR"
 * в поле `min_price` Huckster через `/markets/integrations/repricer/items/set`.
 *
 * Колонки W / ВЫСТАВЛЯЕМАЯ ХАКСТЕР и X / РЦ ХАКСТЕР намеренно не
 * обрабатываются: они не должны менять выставляемую цену или РЦ Huckster.
 *
 * Функция отдельная от read-only updateHucksterPrices() и не вызывается
 * автоматически: запись минимальной цены выполняется только ручным запуском.
 */
/**
 * Полная синхронизация цен из ARL TR в Huckster.
 */
function syncHucksterPricesFromArlTr() {
  return hucksterSyncPricesFromArlTr_('');
}

/**
 * Тестовая синхронизация только для артикула 032431-1.
 * ВАЖНО: функция выполняет реальную запись в Huckster, но только по одной
 * строке ARL TR с точным артикулом 032431-1.
 */
function testSyncHucksterPricesFromArlTr_032431_1() {
  return hucksterSyncPricesFromArlTr_('032431-1');
}

function hucksterSyncPricesFromArlTr_(articleFilter) {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) {
    throw new Error('Другой запуск Huckster уже выполняется.');
  }

  try {
    var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = spreadsheet.getSheetByName(HUCKSTER_ARL_SHEET_NAME);
    if (!sheet) {
      throw new Error('Не найден лист "' + HUCKSTER_ARL_SHEET_NAME + '".');
    }

    var sourceRows = hucksterReadArlPriceRows_(sheet, articleFilter);
    if (!sourceRows.length) {
      var filterLabel = hucksterNormalizeKey_(articleFilter);
      Logger.log(
        filterLabel
          ? 'Huckster: в ARL TR нет строк с ценами для артикула ' + filterLabel + '.'
          : 'Huckster: в ARL TR нет строк с ценами для записи.'
      );
      return {
        sourceRows: 0,
        matchedItems: 0,
        unmatchedRows: 0,
        written: 0,
        articleFilter: filterLabel || null
      };
    }

    var session = hucksterCreateSession_();
    var shopId = hucksterResolveShopId_(session);
    var repricerItems = hucksterLoadRepricerItems_(session, shopId);
    var itemIndex = hucksterIndexItemsByKey_(repricerItems);
    var matched = [];
    var unmatchedRows = 0;

    sourceRows.forEach(function(source) {
      var candidates = itemIndex[source.key] || [];
      if (candidates.length !== 1) {
        unmatchedRows++;
        return;
      }
      matched.push({ source: source, item: candidates[0] });
    });

    if (!matched.length) {
      throw new Error('Ни одна строка ARL TR не сопоставлена с товаром Huckster.');
    }

    var minUpdates = [];
    matched.forEach(function(pair) {
      var source = pair.source;
      var item = pair.item;
      if (source.minPrice !== '') {
        minUpdates.push(hucksterBuildRepricerUpdate_(item, source.minPrice));
      }
    });

    var written = hucksterWriteBatches_(session, '/markets/integrations/repricer/items/set', function(batch) {
      return { marketplace: HUCKSTER_MARKETPLACE, shop_id: shopId, item_list: batch };
    }, minUpdates);

    var report = {
      sourceRows: sourceRows.length,
      articleFilter: hucksterNormalizeKey_(articleFilter) || null,
      matchedItems: matched.length,
      unmatchedRows: unmatchedRows,
      minPriceItems: minUpdates.length,
      written: written
    };
    Logger.log('Huckster цены из ARL TR записаны: ' + JSON.stringify(report));
    return report;
  } finally {
    lock.releaseLock();
  }
}

function hucksterReadArlPriceRows_(sheet, articleFilter) {
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return [];
  var normalizedArticleFilter = hucksterNormalizeKey_(articleFilter);
  var lastColumn = Math.max(
    HUCKSTER_ARL_VENDOR_CODE_COLUMN,
    HUCKSTER_ARL_MIN_PRICE_COLUMN
  );
  var values = sheet.getRange(2, 1, lastRow - 1, lastColumn).getValues();
  return values.map(function(row, index) {
    return {
      rowNumber: index + 2,
      key: hucksterNormalizeKey_(row[HUCKSTER_ARL_VENDOR_CODE_COLUMN - 1]),
      minPrice: hucksterToPrice_(row[HUCKSTER_ARL_MIN_PRICE_COLUMN - 1])
    };
  }).filter(function(source) {
    return source.key &&
      (!normalizedArticleFilter || source.key === normalizedArticleFilter) &&
      source.minPrice !== '';
  });
}

function hucksterIndexItemsByKey_(items) {
  var index = {};
  (items || []).forEach(function(item) {
    [item && item.sku, item && item.uid].forEach(function(value) {
      var key = hucksterNormalizeKey_(value);
      if (!key) return;
      if (!index[key]) index[key] = [];
      if (index[key].indexOf(item) === -1) index[key].push(item);
    });
  });
  return index;
}

function hucksterBuildRepricerUpdate_(item, minPrice) {
  var update = {
    uid: String(item.uid),
    enabled: item.enabled === undefined ? null : item.enabled,
    card_control: item.card_control === undefined ? null : item.card_control,
    max_discount: hucksterToPrice_(item.max_discount),
    min_price: minPrice
  };
  if (item.sku !== undefined && item.sku !== null && String(item.sku).trim()) {
    update.sku = String(item.sku);
  }
  return update;
}

function hucksterWriteBatches_(session, path, payloadFactory, items) {
  var written = 0;
  for (var offset = 0; offset < items.length; offset += HUCKSTER_WRITE_BATCH_SIZE) {
    var batch = items.slice(offset, offset + HUCKSTER_WRITE_BATCH_SIZE);
    var response = hucksterAuthorizedResponse_(session, path, payloadFactory(batch));
    hucksterAssertWriteResponse_(response, path);
    written += batch.length;
  }
  return written;
}

/**
 * Создаёт короткоживущую сессию Huckster.
 * SessionId не сохраняется в Properties и не выводится в лог.
 */
function hucksterCreateSession_() {
  var props = PropertiesService.getScriptProperties();
  // Незаполненные поля используют более безопасный резервный вариант — Script Properties.
  var userName = HUCKSTER_USER_NAME || props.getProperty('HUCKSTER_USER_NAME');
  var password = HUCKSTER_PASSWORD || props.getProperty('HUCKSTER_PASSWORD');

  if (!userName || !password) {
    throw new Error('Не заданы HUCKSTER_USER_NAME/HUCKSTER_PASSWORD в Script Properties.');
  }

  var hashResponse = hucksterFetchRaw_('/md5', { input: password }, null);
  var hashCode = hashResponse.getResponseCode();
  if (hashCode < 200 || hashCode >= 300) {
    throw new Error('Huckster /md5 вернул HTTP ' + hashCode + '.');
  }
  var passwordHash = hucksterParseMd5Response_(hashResponse.getContentText());
  if (!passwordHash) {
    throw new Error('Huckster /md5 не вернул хэш пароля.');
  }

  var authResponse = hucksterFetchRaw_('/auth/credentials', {
    userName: userName,
    password: passwordHash
  }, null);
  var authPayload = hucksterParseJson_(authResponse.getContentText(), 'auth');
  var sessionId = authPayload && authPayload.SessionId;
  if (!sessionId) {
    throw new Error('Huckster авторизация не вернула SessionId.');
  }

  return { id: String(sessionId) };
}

/**
 * Выполнить авторизованный запрос. При HTTP 401 повторно получает сессию один раз.
 */
function hucksterAuthorizedResponse_(session, path, payload) {
  var response = hucksterFetchRaw_(path, payload, session.id);
  if (response.getResponseCode() === 401) {
    var freshSession = hucksterCreateSession_();
    session.id = freshSession.id;
    response = hucksterFetchRaw_(path, payload, session.id);
  }

  var code = response.getResponseCode();
  if (code < 200 || code >= 300) {
    throw new Error('Huckster API ' + path + ' вернул HTTP ' + code + '.');
  }
  return response;
}

function hucksterAuthorizedJson_(session, path, payload) {
  var response = hucksterAuthorizedResponse_(session, path, payload);
  return hucksterParseJson_(response.getContentText(), path);
}

function hucksterAssertWriteResponse_(response, path) {
  var text = String(response.getContentText() || '').replace(/^\uFEFF/, '').trim();
  if (!text) return;
  var payload = hucksterParseJson_(text, path);
  var results = Array.isArray(payload && payload.result) ? payload.result : [payload];
  var errors = results.filter(function(result) {
    return hucksterNormalizeKey_(result && result.result) === 'error';
  });
  if (errors.length) {
    throw new Error('Huckster API ' + path + ' сообщил об ошибке для ' + errors.length + ' товара(ов).');
  }
}

function hucksterResolveShopId_(session) {
  var configuredShopId = HUCKSTER_SHOP_ID || PropertiesService.getScriptProperties().getProperty('HUCKSTER_SHOP_ID');
  if (configuredShopId && String(configuredShopId).trim()) {
    return String(configuredShopId).trim();
  }

  var accounts = hucksterAuthorizedJson_(session, '/markets/integrations/accounts/list', {});
  var ozonAccounts = (Array.isArray(accounts.result) ? accounts.result : []).filter(function(account) {
    return hucksterNormalizeKey_(account.marketplace) === HUCKSTER_MARKETPLACE;
  });

  var unique = {};
  ozonAccounts.forEach(function(account) {
    var id = account.shop_id === null || account.shop_id === undefined ? '' : String(account.shop_id).trim();
    if (id) unique[id] = account;
  });
  var shopIds = Object.keys(unique);

  if (shopIds.length === 1) return shopIds[0];
  if (!shopIds.length) {
    throw new Error('В Huckster не найден кабинет Ozon.');
  }

  throw new Error(
    'В Huckster найдено несколько кабинетов Ozon. Задайте Script Property HUCKSTER_SHOP_ID. Доступные shop_id: ' +
    shopIds.join(', ')
  );
}

/**
 * Находит две новые целевые колонки по заголовкам строки 1.
 * Это защищает от сдвигов колонок при добавлении полей в таблицу.
 */
function hucksterResolveTargetColumns_(sheet) {
  var headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getDisplayValues()[0];
  var marketCardPrice = hucksterFindHeaderColumn_(headers, HUCKSTER_MARKET_CARD_PRICE_HEADER, 'Цена на витрине с картой Х');
  var minPrice = hucksterFindHeaderColumn_(headers, HUCKSTER_MIN_PRICE_HEADERS, 'Мин цена продажи Х');

  if (marketCardPrice === minPrice) {
    throw new Error('Колонки цены на витрине с картой Х и Мин цена продажи Х не должны совпадать.');
  }

  return {
    marketCardPrice: marketCardPrice,
    marketCardPriceLetter: hucksterColumnToLetter_(marketCardPrice),
    minPrice: minPrice,
    minPriceLetter: hucksterColumnToLetter_(minPrice)
  };
}

function hucksterFindHeaderColumn_(headers, aliases, label) {
  var aliasList = Array.isArray(aliases) ? aliases : [aliases];
  var normalizedAliases = aliasList.map(hucksterNormalizeHeader_);
  var matches = [];

  headers.forEach(function(header, index) {
    if (normalizedAliases.indexOf(hucksterNormalizeHeader_(header)) !== -1) {
      matches.push(index + 1);
    }
  });

  if (matches.length !== 1) {
    throw new Error('Нужна ровно одна колонка с заголовком "' + label + '", найдено: ' + matches.length + '.');
  }
  return matches[0];
}

function hucksterNormalizeHeader_(value) {
  return hucksterNormalizeKey_(value).replace(/\s+/g, ' ');
}

function hucksterColumnToLetter_(column) {
  var result = '';
  var number = Number(column);
  while (number > 0) {
    var remainder = (number - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    number = Math.floor((number - 1) / 26);
  }
  return result;
}

function hucksterLoadRepricerItems_(session, shopId) {
  var items = [];
  var offset = 0;
  var total = null;
  var maxPages = 100;

  for (var page = 0; page < maxPages; page++) {
    var payload = {
      marketplace: HUCKSTER_MARKETPLACE,
      shop_id: shopId,
      limit: HUCKSTER_PAGE_SIZE,
      offset: offset
    };
    var response = hucksterAuthorizedJson_(session, '/markets/integrations/repricer/items/list', payload);
    var pageItems = Array.isArray(response.result) ? response.result : [];
    var cursor = response.cursor || {};

    if (total === null && cursor.total !== undefined && cursor.total !== null) {
      total = Number(cursor.total);
      if (!isFinite(total)) total = null;
    }

    items = items.concat(pageItems);
    if (!pageItems.length) break;
    if (total !== null && items.length >= total) break;
    if (pageItems.length < HUCKSTER_PAGE_SIZE) break;

    var nextOffset = offset + HUCKSTER_PAGE_SIZE;
    if (cursor.offset !== undefined && Number(cursor.offset) === offset) {
      nextOffset = offset + HUCKSTER_PAGE_SIZE;
    }
    if (nextOffset <= offset) {
      throw new Error('Huckster pagination не продвигается.');
    }
    offset = nextOffset;
  }

  if (items.length >= HUCKSTER_PAGE_SIZE * maxPages) {
    throw new Error('Huckster pagination превысила безопасный предел страниц.');
  }
  return items;
}

function hucksterFetchRaw_(path, payload, sessionId) {
  var url = HUCKSTER_API_BASE_URL + path;
  var options = {
    method: 'post',
    contentType: 'application/json',
    muteHttpExceptions: true,
    payload: JSON.stringify(payload || {}),
    headers: {
      Accept: 'application/json'
    }
  };
  if (sessionId) {
    // Фактический API принимает сессию в обычном request-заголовке Cookie.
    options.headers.Cookie = 'ss-id=' + String(sessionId);
  }

  var maxAttempts = 4;
  for (var attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      var response = UrlFetchApp.fetch(url, options);
      var code = response.getResponseCode();
      if (code !== 429 && code < 500) return response;
      if (attempt === maxAttempts) return response;
    } catch (error) {
      if (attempt === maxAttempts) {
        throw new Error('Не удалось выполнить запрос Huckster ' + path + '.');
      }
    }
    Utilities.sleep(Math.pow(2, attempt - 1) * 1000);
  }

  throw new Error('Не удалось выполнить запрос Huckster ' + path + '.');
}

function hucksterParseJson_(text, label) {
  try {
    return JSON.parse(String(text).replace(/^\uFEFF/, '').trim());
  } catch (error) {
    throw new Error('Huckster вернул некорректный JSON (' + label + ').');
  }
}

function hucksterParseMd5Response_(text) {
  var normalized = String(text === null || text === undefined ? '' : text)
    .replace(/^\uFEFF/, '')
    .trim();
  if (!normalized) return '';

  try {
    var payload = JSON.parse(normalized);
    var jsonHash = hucksterExtractPasswordHash_(payload);
    if (jsonHash) return jsonHash;
  } catch (error) {
    // Некоторые ответы /md5 приходят как plain text вместо JSON-строки.
  }

  if (/^[a-f0-9]{32}$/i.test(normalized)) return normalized;
  throw new Error('Huckster вернул некорректный JSON (md5).');
}

function hucksterExtractPasswordHash_(payload) {
  if (typeof payload === 'string') return payload.trim();
  if (!payload || typeof payload !== 'object') return '';
  var candidates = [payload.hash, payload.password, payload.result, payload.value];
  for (var i = 0; i < candidates.length; i++) {
    if (typeof candidates[i] === 'string' && candidates[i].trim()) return candidates[i].trim();
  }
  return '';
}

function hucksterNormalizeKey_(value) {
  if (value === null || value === undefined) return '';
  return String(value).trim().toLowerCase();
}

function hucksterAddRowKey_(value, index, rowIndex) {
  var key = hucksterNormalizeKey_(value);
  if (!key) return;
  if (!rowIndex[key]) rowIndex[key] = [];
  if (rowIndex[key].indexOf(index) === -1) rowIndex[key].push(index);
}

function hucksterToPrice_(value) {
  return hucksterToNonNegativeNumber_(value);
}

function hucksterToNonNegativeNumber_(value) {
  if (value === null || value === undefined || value === '') return '';
  var normalized = String(value).replace(',', '.').trim();
  var number = Number(normalized);
  return isFinite(number) && number >= 0 ? number : '';
}

function hucksterMapPrices_(item) {
  return {
    displayedPrice: hucksterToPrice_(item && item.upload_price),
    recommendedPrice: hucksterToPrice_(item && item.market_card_price),
    marketCardPrice: hucksterToPrice_(item && item.market_card_price),
    minPrice: hucksterToPrice_(item && item.min_price)
  };
}

function hucksterSafeText_(value) {
  if (value === null || value === undefined) return '';
  return String(value).replace(/[\r\n]/g, ' ').substring(0, 200);
}
