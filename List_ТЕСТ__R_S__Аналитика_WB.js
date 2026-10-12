/** Обновляет количество всех заказов WB за месяц и 91 день в R/S. */
function updateWBAnalytics() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return;
  const state = wbMainState_("analytics", { today: new Date().toISOString(), stats: {} });
  const today = new Date(state.today);
  const monthFrom = new Date(today.getFullYear(), today.getMonth() - 1, today.getDate());
  const quarterFrom = new Date(today);
  quarterFrom.setDate(today.getDate() - 91);
  const periods = [{ key: 'month', start: monthFrom, header: 'Уход Мес ВБ' },
    { key: 'quarter', start: quarterFrom, header: 'Уход КВ ВБ' }];
  const nmIds = sheet.getRange(2, 20, lastRow - 1).getValues().flat();
  periods.forEach(period => {
    const column = columnByHeader_(sheet, period.header);
    if (!state.stats[period.key]) {
      wbMainCheckBudget_();
      const date = Utilities.formatDate(period.start, 'GMT+3', 'yyyy-MM-dd');
      const response = wbMainFetch_('https://statistics-api.wildberries.ru/api/v1/supplier/orders?dateFrom=' + date,
        { method: 'get', headers: wbHeaders(), muteHttpExceptions: true });
      if (!response || response.getResponseCode() !== 200) throw new Error('WB заказы не получены: ' + period.key);
      const orders = JSON.parse(response.getContentText());
      if (!Array.isArray(orders)) throw new Error('WB вернул неполную структуру заказов');
      const counts = {};
      // Как ранее, включаем отменённые заказы. Checkpoint содержит только счётчики.
      orders.forEach(order => {
        if (order.nmId) counts[order.nmId] = (counts[order.nmId] || 0) + 1;
      });
      state.stats[period.key] = counts;
    }
  });
  // Записываем обе колонки после полного получения двух периодов.
  periods.forEach(period => {
    const column = columnByHeader_(sheet, period.header);
    const counts = state.stats[period.key];
    sheet.getRange(2, column, nmIds.length, 1).setValues(nmIds.map(id => [id && id > 0 ? counts[id] || 0 : 0]));
  });
  Logger.log('WB аналитика: обновлено строк ' + nmIds.length);
}
