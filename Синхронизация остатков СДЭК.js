/**
 * Синхронизация остатков CDEK Fulfillment → лист «СДЕК TR».
 *
 * Источник: CDEK Fulfillment API, GET /products/offer с фильтром article.
 * Цель: колонка с заголовком `stocks` (по имени, не по номеру).
 *
 * ВАЖНО: в «СДЕК TR» поле art всегда имеет вариантный суффикс
 * (`model + -<номер>`), поэтому для поиска в CDEK используется `model`.
 * Повторяющиеся model намеренно запрашиваются один раз и получают один остаток.
 *
 * Перед запуском задайте Script Properties (Project Settings → Script properties):
 * - CDEK_FULFILLMENT_LOGIN
 * - CDEK_FULFILLMENT_API_KEY
 *
 * Секреты не должны попадать в исходный код, Logger или Google Sheet.
 */

const CDEK_STOCK_SPREADSHEET_ID = '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
const CDEK_STOCK_SHEET_NAME = 'СДЕК TR';
const CDEK_STOCK_API_BASE_URL = 'https://cdek.orderadmin.ru/api';
const CDEK_STOCK_REQUEST_DELAY_MS = 120;
const CDEK_STOCK_MAX_RETRIES = 3;
const CDEK_STOCK_INCLUDED_ITEM_STATES = ['normal'];

/** Ручная точка входа: безопасно заменяет только колонку `stocks`. */
function syncCdekStocks() {
  const config = cdekStockConfig_();
  const spreadsheet = SpreadsheetApp.openById(CDEK_STOCK_SPREADSHEET_ID);
  const sheet = spreadsheet.getSheetByName(CDEK_STOCK_SHEET_NAME);
  if (!sheet) throw new Error(`Лист «${CDEK_STOCK_SHEET_NAME}» не найден`);

  const lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    Logger.log(`Лист «${CDEK_STOCK_SHEET_NAME}» пуст — синхронизация не требуется`);
    return { rows: 0, models: 0, updated: 0 };
  }

  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const columns = cdekStockHeaderMap_(headers);
  const rows = sheet.getRange(2, 1, lastRow - 1, sheet.getLastColumn()).getValues();
  const models = cdekStockUniqueModels_(rows, columns.model);

  // Все внешние чтения завершаются до первой записи в Sheet.
  const stockByModel = cdekStockFetchByModel_(models, config);
  const output = rows.map((row) => {
    const model = cdekStockText_(row[columns.model - 1]);
    if (!model) return [''];
    if (!Object.prototype.hasOwnProperty.call(stockByModel, model)) {
      throw new Error(`CDEK не вернул остаток для model «${model}»; запись отменена`);
    }
    return [stockByModel[model]];
  });

  sheet.getRange(2, columns.stocks, output.length, 1).setValues(output);
  const nonZero = output.filter((value) => Number(value[0]) > 0).length;
  Logger.log(`CDEK: обновлено строк=${output.length}, уникальных model=${models.length}, ненулевых=${nonZero}`);
  return { rows: output.length, models: models.length, updated: output.length, nonZero: nonZero };
}

function cdekStockConfig_() {
  const properties = PropertiesService.getScriptProperties();
  const login = cdekStockText_(properties.getProperty('CDEK_FULFILLMENT_LOGIN'));
  const apiKey = cdekStockText_(properties.getProperty('CDEK_FULFILLMENT_API_KEY'));
  if (!login || !apiKey) {
    throw new Error('Не заданы Script Properties CDEK_FULFILLMENT_LOGIN и/или CDEK_FULFILLMENT_API_KEY');
  }
  return {
    headers: {
      Accept: 'application/json',
      Authorization: `Basic ${Utilities.base64Encode(`${login}:${apiKey}`)}`
    }
  };
}

function cdekStockHeaderMap_(headers) {
  const normalized = {};
  headers.forEach((header, index) => {
    const name = cdekStockHeader_(header);
    if (!name) return;
    if (!normalized[name]) normalized[name] = [];
    normalized[name].push(index + 1);
  });

  const required = { art: 'art', model: 'model', stocks: 'stocks' };
  const resolved = {};
  Object.keys(required).forEach((key) => {
    const locations = normalized[required[key]] || [];
    if (locations.length !== 1) {
      throw new Error(`В «${CDEK_STOCK_SHEET_NAME}» заголовок «${required[key]}» должен быть ровно один; найдено: ${locations.length}`);
    }
    resolved[key] = locations[0];
  });
  return resolved;
}

function cdekStockUniqueModels_(rows, modelColumn) {
  const seen = {};
  const models = [];
  rows.forEach((row) => {
    const model = cdekStockText_(row[modelColumn - 1]);
    if (model && !seen[model]) {
      seen[model] = true;
      models.push(model);
    }
  });
  if (!models.length) throw new Error('В колонке model нет значений для запроса CDEK');
  return models;
}

function cdekStockFetchByModel_(models, config) {
  const result = {};
  let lastRequestAt = 0;
  models.forEach((model) => {
    const elapsed = Date.now() - lastRequestAt;
    if (lastRequestAt && elapsed < CDEK_STOCK_REQUEST_DELAY_MS) {
      Utilities.sleep(CDEK_STOCK_REQUEST_DELAY_MS - elapsed);
    }
    result[model] = cdekStockFetchOneModel_(model, config.headers);
    lastRequestAt = Date.now();
  });
  return result;
}

function cdekStockFetchOneModel_(model, headers) {
  let url = `${CDEK_STOCK_API_BASE_URL}/products/offer?filter%5B0%5D%5Btype%5D=eq&filter%5B0%5D%5Bfield%5D=article&filter%5B0%5D%5Bvalue%5D=${encodeURIComponent(model)}`;
  let total = 0;
  let matched = 0;
  let pages = 0;

  while (url) {
    const response = cdekStockFetchJson_(url, headers);
    pages += 1;
    const offers = response && response._embedded && Array.isArray(response._embedded.product_offer)
      ? response._embedded.product_offer
      : null;
    if (!offers) throw new Error(`CDEK вернул неожиданную структуру списка для model «${model}»`);

    offers.forEach((offer) => {
      if (cdekStockText_(offer.article) !== model) return;
      matched += 1;
      total += cdekStockAvailableCount_(offer.items);
    });

    const nextHref = response && response._links && response._links.next && response._links.next.href;
    url = cdekStockSafeNextUrl_(nextHref);
    if (pages > 100) throw new Error(`CDEK pagination превысила 100 страниц для model «${model}»`);
  }

  if (!matched) throw new Error(`CDEK не нашёл товар с article «${model}»`);
  return total;
}

function cdekStockFetchJson_(url, headers) {
  let lastCode = null;
  for (let attempt = 1; attempt <= CDEK_STOCK_MAX_RETRIES; attempt += 1) {
    const response = UrlFetchApp.fetch(url, {
      method: 'get',
      headers: headers,
      muteHttpExceptions: true
    });
    const code = response.getResponseCode();
    lastCode = code;
    if (code >= 200 && code < 300) {
      try {
        return JSON.parse(response.getContentText());
      } catch (error) {
        throw new Error(`CDEK вернул некорректный JSON (HTTP ${code})`);
      }
    }
    if (code !== 429 && code < 500) throw new Error(`CDEK API вернул HTTP ${code}`);
    if (attempt < CDEK_STOCK_MAX_RETRIES) Utilities.sleep(1000 * attempt);
  }
  throw new Error(`CDEK API недоступен после ${CDEK_STOCK_MAX_RETRIES} попыток (последний HTTP ${lastCode})`);
}

function cdekStockAvailableCount_(items) {
  if (!Array.isArray(items)) throw new Error('В карточке CDEK отсутствует массив items');
  return items.reduce((sum, item) => {
    const state = cdekStockHeader_(item && item.state);
    if (CDEK_STOCK_INCLUDED_ITEM_STATES.indexOf(state) === -1) return sum;
    const count = Number(item.count);
    if (!Number.isFinite(count) || count < 0) throw new Error('CDEK вернул некорректный count в items');
    return sum + Math.trunc(count);
  }, 0);
}

function cdekStockSafeNextUrl_(nextHref) {
  if (!nextHref) return null;
  const prefix = `${CDEK_STOCK_API_BASE_URL}/products/offer`;
  if (String(nextHref).indexOf(prefix) !== 0) throw new Error('CDEK вернул небезопасную ссылку пагинации');
  return String(nextHref);
}

function cdekStockHeader_(value) {
  return cdekStockText_(value).toLowerCase().replace(/ё/g, 'е');
}

function cdekStockText_(value) {
  return String(value === undefined || value === null ? '' : value).trim();
}
