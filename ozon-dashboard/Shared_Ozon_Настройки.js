/** Ozon credentials copied from the existing Checksheets configuration. */
function ozonDashboardHeaders_() {
  return {
    'Content-Type': 'application/json',
    'Client-Id': '142355',
    'Api-Key': 'fe539630-170b-4b48-b222-8ba092907a63'
  };
}

const TELEGRAM_CONFIG = {
  BOT_TOKEN: '8657497257:AAFH9Sb6hNrKFL3WpDTuQd01FQbNB_I1-_o',
  CHAT_ID: '-1004398203333'
}

const OZON_DASHBOARD_API_ = {
  prices: 'https://api-seller.ozon.ru/v5/product/info/prices',
  analyticsStocks: 'https://api-seller.ozon.ru/v1/analytics/stocks',
  warehouses: 'https://api-seller.ozon.ru/v2/warehouse/list',
  fbsStocks: 'https://api-seller.ozon.ru/v2/product/info/stocks-by-warehouse/fbs',
  fboClusters: 'https://api-seller.ozon.ru/v2/cluster/list',
  fboPostings: 'https://api-seller.ozon.ru/v3/posting/fbo/list'
};

const OZON_DASHBOARD_TARGET_HEADERS_ = {
  price: 'Цена продажи',
  offerId: 'Артикул',
  fboSku: 'FBO OZON SKU ID',
  fbsSku: 'FBS OZON SKU ID',
  fbsWarehouses: {
    'ФБС СМ': 'ФЕРОН САМАРА',
    'ФБС МО': 'МОСКВА',
    'СДЭК ОСТ': 'КГТ СДЭК'
  },
  fboClusters: [
    'МО ОСТ', 'СПБ ОСТ', 'ЯР ОСТ', 'ВОР ОСТ', 'ЮГ ОСТ', 'Рост ост',
    'КАВ ОСТ', 'САР ОСТ', 'КАЗ ост', 'СМ ОСТ', 'УФА ОСТ', 'ЕКБ ОСТ',
    'НСБ ОСТ', 'ДВ ОСТ', 'Бел ост', 'Казах Ост'
  ]
};

/** Monthly FBO order targets paired with the stock-region headers above. */
const OZON_DASHBOARD_OUTFLOW_HEADERS_ = {
  'МО ОСТ': 'МО УХ',
  'СПБ ОСТ': 'СПБ УХ',
  'ЯР ОСТ': 'ЯР УХ',
  'ВОР ОСТ': 'ВОР УХ',
  'ЮГ ОСТ': 'ЮГ УХ',
  'Рост ост': 'Рост ух',
  'КАВ ОСТ': 'КАВ УХ',
  'САР ОСТ': 'САР УХ',
  'КАЗ ост': 'КАЗ ух',
  'СМ ОСТ': 'СМ УХ',
  'УФА ОСТ': 'УФА УХ',
  'ЕКБ ОСТ': 'ЕКБ УХ',
  'НСБ ОСТ': 'НСБ УХ',
  'ДВ ОСТ': 'ДВ УХ',
  'Бел ост': 'Бел ух',
  'Казах Ост': 'Казах Ух'
};

/** Region-to-cluster aliases based on the provided warehouse workbook. */
const OZON_DASHBOARD_REGION_HEADERS_ = {
  'беларусь': 'Бел ост',
  'москва, мо и дальние регионы': 'МО ОСТ',
  'тверь': 'МО ОСТ',
  'калининград': 'СПБ ОСТ',
  'санкт-петербург и сзо': 'СПБ ОСТ',
  'казань': 'КАЗ ост',
  'казахстан': 'Казах Ост',
  'астана': 'Казах Ост',
  'алматы': 'Казах Ост',
  'самара': 'СМ ОСТ',
  'уфа': 'УФА ОСТ',
  'оренбург': 'УФА ОСТ',
  'воронеж': 'ВОР ОСТ',
  'волгоград': 'САР ОСТ',
  'саратов': 'САР ОСТ',
  'ростов': 'Рост ост',
  'юг': 'ЮГ ОСТ',
  'краснодар': 'ЮГ ОСТ',
  'армения': 'КАВ ОСТ',
  'кавказ': 'КАВ ОСТ',
  'невинномысск': 'КАВ ОСТ',
  'махачкала': 'КАВ ОСТ',
  'тюмень': 'ЕКБ ОСТ',
  'урал': 'ЕКБ ОСТ',
  'екатеринбург': 'ЕКБ ОСТ',
  'пермь': 'ЕКБ ОСТ',
  'сибирь': 'НСБ ОСТ',
  'новосибирск': 'НСБ ОСТ',
  'красноярск': 'НСБ ОСТ',
  'омск': 'НСБ ОСТ',
  'дальний восток': 'ДВ ОСТ',
  'ярославль': 'ЯР ОСТ',
  'азербайджан': 'МО ОСТ',
  'кыргызстан': 'МО ОСТ',
  'грузия': 'МО ОСТ',
  'узбекистан': 'МО ОСТ'
};

function ozonDashboardNormalize_(value) {
  return String(value === null || value === undefined ? '' : value)
    .replace(/\s+/g, ' ').trim().toLocaleLowerCase('ru-RU').replace(/ё/g, 'е');
}

/** Strictly resolve a sheet column by its visible row-1 header. */
function ozonDashboardColumnByHeader_(sheet, header) {
  const wanted = ozonDashboardNormalize_(header);
  const lastColumn = sheet.getLastColumn();
  if (!wanted || lastColumn < 1) throw new Error('Пустая таблица или заголовок для листа ' + sheet.getName());
  const headers = sheet.getRange(1, 1, 1, lastColumn).getDisplayValues()[0];
  const matches = [];
  headers.forEach(function(value, index) {
    if (ozonDashboardNormalize_(value) === wanted) matches.push(index + 1);
  });
  if (matches.length !== 1) {
    throw new Error('Лист «' + sheet.getName() + '»: заголовок «' + header +
      '» найден ' + matches.length + ' раз; колонки: ' + matches.join(', '));
  }
  return matches[0];
}

function ozonDashboardValidSku_(value) {
  if (value === null || value === undefined || String(value).trim() === '') return '';
  const numeric = Number(String(value).trim());
  if (!Number.isSafeInteger(numeric) || numeric <= 0) return '';
  return String(numeric);
}

function ozonDashboardValidOfferId_(value) {
  return String(value === null || value === undefined ? '' : value).trim();
}

/** Write only selected cells and preserve any formulas in the destination. */
function ozonDashboardWriteColumn_(sheet, column, startRow, values, selected) {
  if (!values.length) return 0;
  const formulas = sheet.getRange(startRow, column, values.length, 1).getFormulas();
  let written = 0;
  let runStart = -1;
  const flush = function(endIndex) {
    if (runStart < 0) return;
    const count = endIndex - runStart;
    sheet.getRange(startRow + runStart, column, count, 1)
      .setValues(values.slice(runStart, endIndex).map(function(value) { return [value]; }));
    written += count;
    runStart = -1;
  };
  for (let index = 0; index < values.length; index++) {
    const canWrite = Boolean(selected[index]) && !formulas[index][0];
    if (canWrite && runStart < 0) runStart = index;
    if (!canWrite) flush(index);
  }
  flush(values.length);
  return written;
}
