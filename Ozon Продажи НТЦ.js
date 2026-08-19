/**
 * Ежедневные продажи FBS со склада «НТЦ СКЛАД».
 *
 * Функция updateOzonNTCSalesYesterday() рассчитана на ежедневный триггер.
 * Она берёт FBS-отправления за вчера (кроме отменённых), суммирует
 * products[].quantity по offer_id и записывает результат в колонку BM листа «ТЕСТ».
 */

const OZON_NTC_SALES_URL = 'https://api-seller.ozon.ru';
const OZON_NTC_WAREHOUSE_NAME = 'НТЦ СКЛАД';
const OZON_NTC_SALES_COLUMN = 65; // BM
const OZON_NTC_SALES_HEADER = 'Продажи НТЦ';
const OZON_NTC_WAREHOUSE_PAGE_SIZE = 200;
const OZON_NTC_POSTING_PAGE_SIZE = 1000;

function updateOzonNTCSalesYesterday() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  sheet.getRange(1, OZON_NTC_SALES_COLUMN).setValue(OZON_NTC_SALES_HEADER);
  if (lastRow < 2) {
    Logger.log('Лист «ТЕСТ» не содержит артикулов.');
    return;
  }

  const articleValues = sheet.getRange(2, 1, lastRow - 1, 1).getValues();
  const articles = articleValues.map(row => String(row[0] ?? '').trim());
  const [since, to] = ozonNTCYesterdayBounds();
  const warehouseId = ozonNTCFindWarehouseId();
  const salesByArticle = ozonNTCFetchSales(warehouseId, since, to);

  const output = articles.map(article => [article ? (salesByArticle[article] || 0) : '']);
  sheet.getRange(2, OZON_NTC_SALES_COLUMN, output.length, 1).setValues(output);

  const total = output.reduce((sum, row) => sum + (Number(row[0]) || 0), 0);
  Logger.log(`Продажи НТЦ записаны за ${since} — ${to}: ${total} шт., склад ID ${warehouseId}.`);
}

function ozonNTCYesterdayBounds() {
  const timezone = Session.getScriptTimeZone() || 'Etc/UTC';
  const today = new Date();
  const todayText = Utilities.formatDate(today, timezone, 'yyyy-MM-dd');
  const todayAtMidnight = new Date(`${todayText}T00:00:00`);
  const yesterday = new Date(todayAtMidnight.getTime() - 24 * 60 * 60 * 1000);
  const yesterdayText = Utilities.formatDate(yesterday, timezone, 'yyyy-MM-dd');

  return [
    new Date(`${yesterdayText}T00:00:00`).toISOString(),
    new Date(`${todayText}T00:00:00`).toISOString()
  ];
}

function ozonNTCFindWarehouseId() {
  let offset = 0;

  while (true) {
    const response = ozonNTCPost('/v2/warehouse/list', {
      limit: OZON_NTC_WAREHOUSE_PAGE_SIZE,
      offset: offset
    });
    const warehouses = response.warehouses || response.result || [];
    if (!Array.isArray(warehouses)) {
      throw new Error('Ozon вернул неожиданный формат списка складов.');
    }

    const target = warehouses.find(warehouse => {
      const name = warehouse.name || warehouse.warehouse_name || '';
      return String(name).trim().toLocaleLowerCase() === OZON_NTC_WAREHOUSE_NAME.toLocaleLowerCase();
    });
    if (target && target.warehouse_id !== undefined && target.warehouse_id !== null) {
      return Number(target.warehouse_id);
    }

    const hasNext = response.has_next === true || response.result?.has_next === true;
    if (!hasNext && warehouses.length < OZON_NTC_WAREHOUSE_PAGE_SIZE) break;
    offset += warehouses.length || OZON_NTC_WAREHOUSE_PAGE_SIZE;
  }

  throw new Error(`Склад «${OZON_NTC_WAREHOUSE_NAME}» не найден через /v2/warehouse/list.`);
}

function ozonNTCFetchSales(warehouseId, since, to) {
  const salesByArticle = {};

  // «Продажа» может оставаться в FBS в разных статусах в течение дня.
  // Запрашиваем все неотменённые статусы, иначе заказы, ещё не доставленные
  // покупателю, ошибочно дают нули. Один posting имеет только один статус,
  // поэтому суммирование по статусам не создаёт дублей.
  const saleStatuses = [
    'acceptance_in_progress',
    'awaiting_approve',
    'awaiting_packaging',
    'awaiting_deliver',
    'awaiting_registration',
    'delivering',
    'driver_pickup',
    'delivered'
  ];

  saleStatuses.forEach(status => {
    let offset = 0;
    let statusPostings = 0;
    let statusUnits = 0;
    while (true) {
      const response = ozonNTCPost('/v3/posting/fbs/list', {
        dir: 'ASC',
        filter: {
          since: since,
          to: to,
          warehouse_id: [warehouseId],
          status: status
        },
        limit: OZON_NTC_POSTING_PAGE_SIZE,
        offset: offset,
        with: {
          analytics_data: false,
          financial_data: false,
          translit: false
        }
      });
      const result = response.result || {};
      const postings = Array.isArray(result.postings) ? result.postings : [];
      statusPostings += postings.length;

      postings.forEach(posting => {
        (posting.products || []).forEach(product => {
          const article = String(product.offer_id ?? '').trim();
          const quantity = Number(product.quantity) || 0;
          statusUnits += quantity > 0 ? quantity : 0;
          if (article && quantity > 0) {
            salesByArticle[article] = (salesByArticle[article] || 0) + quantity;
          }
        });
      });

      const hasNext = result.has_next === true;
      if (!hasNext && postings.length < OZON_NTC_POSTING_PAGE_SIZE) break;
      if (postings.length === 0) break;
      offset += postings.length;
    }
    Logger.log(`НТЦ статус ${status}: ${statusPostings} отправлений, ${statusUnits} шт.`);
  });

  return salesByArticle;
}

function ozonNTCPost(path, body) {
  const options = {
    method: 'post',
    contentType: 'application/json',
    headers: ozonHeaders(),
    payload: JSON.stringify(body),
    muteHttpExceptions: true
  };
  let lastError;

  for (let attempt = 0; attempt < 4; attempt++) {
    const response = UrlFetchApp.fetch(OZON_NTC_SALES_URL + path, options);
    const status = response.getResponseCode();
    const text = response.getContentText();
    if (status >= 200 && status < 300) {
      try {
        return JSON.parse(text);
      } catch (error) {
        throw new Error(`Ozon вернул некорректный JSON (${path}): ${error.message}`);
      }
    }

    lastError = new Error(`Ozon ${path}: HTTP ${status}: ${text.substring(0, 500)}`);
    if (status !== 429 && status < 500) throw lastError;
    Utilities.sleep(1000 * Math.pow(2, attempt));
  }

  throw lastError;
}
