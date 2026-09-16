/**
 * НТЦ: FBS-резерв и ручное списание. Ни одна функция здесь не пишет остатки в MP.
 * F — внешний остаток модели; H — кратность артикула;
 * K — накопленное ручное списание в упаковках; J — chrlid.
 * L — готовое количество упаковок артикула для будущей выгрузки на MP.
 * M — FBS-резерв в физических штуках модели, N — доступно по модели.
 * G и I остаются справочными; MP API здесь не вызывается.
 */
const NTC_WRITE_OFF_SHEET = 'НТЦ списания';
const NTC_WRITE_OFF_LEDGER = '_НТЦ FBS резерв';
const NTC_WRITE_OFF_START_KEY = 'NTC_FBS_RESERVE_START_UTC';
const NTC_WRITE_OFF_CURSOR_KEY = 'NTC_FBS_RESERVE_CURSOR_UTC';
const NTC_WRITE_OFF_PAGE_SIZE = 1000;
const NTC_WRITE_OFF_PENDING = [
  'acceptance_in_progress', 'awaiting_approve', 'awaiting_packaging',
  'awaiting_deliver', 'awaiting_registration'
];

/** Один раз после проверки тестов: формулы L/N и начальная FBS-сверка. */
function installNtcWriteOffs() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(NTC_WRITE_OFF_SHEET);
  if (!sheet) throw new Error('Не найден лист «' + NTC_WRITE_OFF_SHEET + '».');
  ntcAssertHeaders_(sheet);
  const lock = LockService.getDocumentLock();
  if (!lock.tryLock(30000)) throw new Error('НТЦ: другое списание ещё выполняется.');
  try {
    const props = PropertiesService.getDocumentProperties();
    if (!props.getProperty(NTC_WRITE_OFF_START_KEY)) {
      props.setProperty(NTC_WRITE_OFF_START_KEY, new Date().toISOString());
    }
    ntcLedgerSheet_(ss);
    sheet.getRange('L1:N1').setValues([[
      'Остаток для маркетплейсов, упаковок', 'Резерв FBS по модели, шт.', 'Доступно по модели, шт.'
    ]]);
    const count = Math.max(0, sheet.getLastRow() - 1);
    if (count) {
      const available = [], outbound = [];
      const end = Math.max(1000, count + 1);
      for (let row = 2; row < count + 2; row++) {
        available.push([ntcAvailableFormula_(row, end)]);
        outbound.push([ntcOutboundFormula_(row, end)]);
      }
      sheet.getRange(2, 14, count, 1).setFormulas(available);
      sheet.getRange(2, 12, count, 1).setFormulas(outbound);
    }
    const validation = SpreadsheetApp.newDataValidation()
      .requireFormulaSatisfied('=OR(K2="";AND(ISNUMBER(K2);K2>=0;MOD(K2;1)=0))')
      .setAllowInvalid(false).build();
    sheet.getRange(2, 11, Math.max(count, 1), 1).setDataValidation(validation);
  } finally {
    lock.releaseLock();
  }
  syncNtcFbsWriteOffs();
}

/** Полная сверка известного периода; повторный запуск не удваивает списания. */
function syncNtcFbsWriteOffs() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(NTC_WRITE_OFF_SHEET);
  if (!sheet) throw new Error('Не найден лист «' + NTC_WRITE_OFF_SHEET + '».');
  ntcAssertHeaders_(sheet);
  const lock = LockService.getDocumentLock();
  if (!lock.tryLock(30000)) throw new Error('НТЦ: другое списание ещё выполняется.');
  try {
    const props = PropertiesService.getDocumentProperties();
    const start = props.getProperty(NTC_WRITE_OFF_START_KEY);
    if (!start) throw new Error('Сначала выполните installNtcWriteOffs().');
    const ledger = ntcLedgerSheet_(ss);
    const old = ntcReadLedger_(ledger);
    const rowCount = Math.max(0, sheet.getLastRow() - 1);
    const rows = rowCount ? sheet.getRange(2, 1, rowCount, 8).getValues() : [];
    const article = {};
    rows.forEach((r, index) => {
      const offer = String(r[0] || '').trim();
      if (!offer) return;
      const size = Number(r[7]);
      if (!Number.isInteger(size) || size <= 0) throw new Error('НТЦ: неверный размер упаковки H' + (index + 2));
      article[offer] = {model: String(r[1] || '').trim(), size: size};
    });
    const warehouseId = ozonNTCFindWarehouseId();
    const since = new Date(Date.parse(start) - 90 * 86400000).toISOString();
    const now = new Date().toISOString();
    const cursor = props.getProperty(NTC_WRITE_OFF_CURSOR_KEY);
    const postings = [];
    // Повторно читаем сборку: частичная отмена может изменить products без смены статуса.
    // Также это включает заказы, созданные до установки, но ещё не переданные в доставку.
    NTC_WRITE_OFF_PENDING.forEach(status => {
      postings.push(...ntcFetchPostings_(warehouseId, since, now, status));
    });
    const changedFrom = new Date(Date.parse(cursor || start) - 5 * 60000).toISOString();
    postings.push(...ntcFetchPostings_(warehouseId, since, now, '', changedFrom));
    const next = Object.assign({}, old);
    postings.forEach(posting => {
      const number = String(posting.posting_number || '').trim();
      if (!number) throw new Error('Ozon вернул отправление без posting_number.');
      const status = String(posting.status || '').trim();
      const created = Date.parse(posting.in_process_at || posting.created_at || '');
      const wasTracked = Object.prototype.hasOwnProperty.call(old, number);
      if (!wasTracked && !(created >= Date.parse(start) || NTC_WRITE_OFF_PENDING.includes(status))) return;
      if (!Array.isArray(posting.products)) throw new Error('Ozon не вернул products для ' + number);
      const items = posting.products.map(p => ({offer_id: String(p.offer_id || '').trim(), quantity: Number(p.quantity)}));
      if (items.some(p => !p.offer_id || !Number.isInteger(p.quantity) || p.quantity < 0)) {
        throw new Error('Некорректные товары отправления ' + number);
      }
      const relevant = items.filter(item => article[item.offer_id]);
      if (!relevant.length && !wasTracked) return;
      const shipped = wasTracked && old[number].shipped ||
        ['driver_pickup', 'delivering', 'delivered', 'last_mile'].includes(status);
      next[number] = {status: status, items: relevant, shipped: Boolean(shipped)};
    });
    const reserved = {};
    Object.keys(next).forEach(number => {
      const record = next[number];
      if ((record.status === 'cancelled' || record.status === 'not_accepted') && !record.shipped) return;
      record.items.forEach(item => {
        if (!item.quantity) return;
        const found = article[item.offer_id];
        if (!found) return;
        if (!found.model) throw new Error('НТЦ: у артикула ' + item.offer_id + ' нет модели.');
        reserved[found.model] = (reserved[found.model] || 0) + item.quantity * found.size;
      });
    });
    // Запись выполняется только после успешной полной загрузки и валидации.
    ntcWriteLedger_(ledger, next);
    if (rows.length) sheet.getRange(2, 13, rows.length, 1).setValues(rows.map(r => [reserved[String(r[1] || '').trim()] || 0]));
    props.setProperty(NTC_WRITE_OFF_CURSOR_KEY, now);
    Logger.log('НТЦ FBS: ' + Object.keys(next).length + ' отправлений по листу; резерв ' + JSON.stringify(reserved));
  } finally {
    lock.releaseLock();
  }
}

/** Распределяет общий запас модели между её кратностями, не обещая одни физические штуки дважды. */
function ntcAvailableFormula_(row, end) {
  return `=IF($A${row}="";"";N($F${row})-N($M${row})-SUMPRODUCT(($B$2:$B$${end}=$B${row})*IFERROR($K$2:$K$${end}*1;0)*IFERROR($H$2:$H$${end}*1;0)))`;
}

function ntcOutboundFormula_(row, end) {
  return `=IF(OR($A${row}="";$H${row}="");"";IF(COUNTIFS($B$2:$B$${end};$B${row};$H$2:$H$${end};$H${row})>1;0;IFERROR(LET(` +
    `sizes;SORT(FILTER($H$2:$H$${end};$B$2:$B$${end}=$B${row});1;TRUE);` +
    `prefixes;SCAN(0;sizes;LAMBDA(a;x;a+x));` +
    `rev;SORT(prefixes;1;FALSE);` +
    `pool;MAX(0;N($N${row}));` +
    `remainders;VSTACK(pool;SCAN(pool;rev;LAMBDA(a;x;MOD(a;x))));` +
    `rounds;ARRAYFORMULA(QUOTIENT(FILTER(remainders;SEQUENCE(ROWS(remainders))<ROWS(remainders));rev));` +
    `INDEX(SCAN(0;rounds;LAMBDA(a;x;a+x));MATCH($H${row};SORT(sizes;1;FALSE);0))` +
    `);0)))`;
}

function ntcFetchPostings_(warehouseId, since, to, status, changedFrom) {
  const all = [];
  let offset = 0;
  while (true) {
    const filter = {since: since, to: to, warehouse_id: [warehouseId]};
    if (status) filter.status = status;
    if (changedFrom) filter.last_changed_status_date = {from: changedFrom, to: to};
    const response = ozonNTCPost('/v3/posting/fbs/list', {
      dir: 'ASC', filter: filter,
      limit: NTC_WRITE_OFF_PAGE_SIZE, offset: offset,
      with: {analytics_data: false, financial_data: false, translit: false}
    });
    const result = response.result || {};
    if (!Array.isArray(result.postings)) throw new Error('Ozon: неверный ответ списка FBS.');
    all.push(...result.postings);
    if (!result.has_next) break;
    if (!result.postings.length) throw new Error('Ozon: пустая страница при has_next.');
    offset += result.postings.length;
  }
  return all;
}

function ntcAssertHeaders_(sheet) {
  const headers = sheet.getRange(1, 1, 1, 11).getDisplayValues()[0];
  if (headers[0] !== 'Артикул продавца' || headers[5] !== 'Остаток склад по моделям' ||
      headers[10] !== 'Ручное списание штук') throw new Error('НТЦ: структура листа изменилась.');
}

function ntcLedgerSheet_(ss) {
  let sheet = ss.getSheetByName(NTC_WRITE_OFF_LEDGER);
  if (!sheet) {
    sheet = ss.insertSheet(NTC_WRITE_OFF_LEDGER);
    sheet.getRange('A1:C1').setValues([['posting_number', 'status', 'products_json']]);
    sheet.hideSheet();
  }
  return sheet;
}

function ntcReadLedger_(sheet) {
  const result = {};
  const count = sheet.getLastRow() - 1;
  if (count < 1) return result;
  sheet.getRange(2, 1, count, 3).getValues().forEach(r => {
    if (r[0]) {
      const data = JSON.parse(String(r[2]));
      result[String(r[0])] = {status: String(r[1]), items: data.items || data, shipped: Boolean(data.shipped)};
    }
  });
  return result;
}

function ntcWriteLedger_(sheet, ledger) {
  const rows = Object.keys(ledger).sort().map(number => [number, ledger[number].status,
    JSON.stringify({items: ledger[number].items, shipped: ledger[number].shipped})]);
  const oldCount = Math.max(0, sheet.getLastRow() - 1);
  if (rows.length) sheet.getRange(2, 1, rows.length, 3).setValues(rows);
  if (oldCount > rows.length) sheet.getRange(rows.length + 2, 1, oldCount - rows.length, 3).clearContent();
}
