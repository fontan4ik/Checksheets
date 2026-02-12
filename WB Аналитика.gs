/**
 * АНАЛИТИКА WILDBERRIES
 *
 * Заполняет колонки:
 * - R (18): Уход Мес ВБ - количество заказов за месяц
 * - S (19): Уход КВ ВБ - количество заказов за квартал
 */

function updateWBAnalytics() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет данных для обработки");
    return;
  }

  const today = new Date();
  const dateFromMonth = new Date(today.getFullYear(), today.getMonth() - 1, today.getDate()); // Тот же день, месяц назад
  const dateFromQuarter = new Date(today);
  dateFromQuarter.setDate(today.getDate() - 91); // Примерно 91 день назад (квартал)

  const formatDate = date => Utilities.formatDate(date, "GMT+3", "yyyy-MM-dd");

  Logger.log(`📊 Период анализа:`);
  Logger.log(`   Месяц: с ${formatDate(dateFromMonth)}`);
  Logger.log(`   Квартал: с ${formatDate(dateFromQuarter)}`);

  // Функция для получения заказов
  function fetchOrders(dateFrom, label) {
    const url = `https://statistics-api.wildberries.ru/api/v1/supplier/orders?dateFrom=${formatDate(dateFrom)}`;
    const options = {
      method: "get",
      headers: wbHeaders(),
      muteHttpExceptions: true
    };

    Logger.log(`🔄 Загрузка: ${label}...`);

    try {
      const response = retryFetch(url, options);

      if (!response) {
        Logger.log(`❌ Не удалось получить заказы WB (${label})`);
        return [];
      }

      const orders = JSON.parse(response.getContentText());

      if (!Array.isArray(orders)) {
        Logger.log(`❌ Ошибка ответа: ${JSON.stringify(orders).substring(0, 200)}`);
        return [];
      }

      Logger.log(`✅ Получено заказов: ${orders.length}`);

      // Фильтруем только завершённые (не отменённые)
      return orders.filter(o => !o.isCancel);
    } catch (e) {
      Logger.log(`❌ Ошибка при получении заказов: ${e.message}`);
      return [];
    }
  }

  // Получаем заказы за месяц и квартал
  const ordersMonth = fetchOrders(dateFromMonth, "месяц");
  // Пауза не нужна - API вызовы разнесены по времени
  const ordersQuarter = fetchOrders(dateFromQuarter, "квартал");

  // ИСПРАВЛЕНО: агрегируем по базовым артикулам (без суффиксов)
  const monthStats = {};
  const quarterStats = {};

  ordersMonth.forEach(order => {
    const art = order.supplierArticle;
    if (!art) return;

    // Убираем суффикс после дефиса для статистики
    const baseArt = String(art).split('-')[0];

    if (!monthStats[baseArt]) {
      monthStats[baseArt] = 0;
    }
    monthStats[baseArt]++;
  });

  ordersQuarter.forEach(order => {
    const art = order.supplierArticle;
    if (!art) return;

    // Убираем суффикс после дефиса для статистики
    const baseArt = String(art).split('-')[0];

    if (!quarterStats[baseArt]) {
      quarterStats[baseArt] = 0;
    }
    quarterStats[baseArt]++;
  });

  // Читаем артикулы из колонки A
  const articles = sheet.getRange(2, 1, lastRow - 1).getValues().flat();

  // Подготавливаем данные для записи
  const monthValues = [];
  const quarterValues = [];

  let monthWithOrders = 0;
  let quarterWithOrders = 0;

  articles.forEach(art => {
    const artStr = art?.toString().trim() || "";

    if (artStr) {
      // ИСПРАВЛЕНО: ищем по базовому артикулу (без суффикса)
      const baseArt = artStr.split('-')[0];
      const monthCount = monthStats[baseArt] || 0;
      const quarterCount = quarterStats[baseArt] || 0;

      monthValues.push([monthCount]);
      quarterValues.push([quarterCount]);

      if (monthCount > 0) monthWithOrders++;
      if (quarterCount > 0) quarterWithOrders++;
    } else {
      // ИСПРАВЛЕНО: пишем 0 вместо пустой строки
      monthValues.push([0]);
      quarterValues.push([0]);
    }
  });

  // Записываем в колонки
  // R (18): Уход Мес ВБ
  sheet.getRange(2, 18, monthValues.length, 1).setValues(monthValues);

  // S (19): Уход КВ ВБ
  sheet.getRange(2, 19, quarterValues.length, 1).setValues(quarterValues);

  Logger.log(`✅ Обновление завершено!`);
  Logger.log(`📝 Строк обновлено: ${articles.length}`);
  Logger.log(`📊 Статистика:`);
  Logger.log(`   С заказами за месяц: ${monthWithOrders}`);
  Logger.log(`   С заказами за квартал: ${quarterWithOrders}`);

  // ДИАГНОСТИКА для 22068-1
  const testArticle = "22068-1";
  const testBase = "22068";
  Logger.log("");
  Logger.log(`=== ДИАГНОСТИКА 22068-1 ===`);
  Logger.log(`Артикул: ${testArticle}`);
  Logger.log(`Базовый: ${testBase}`);
  Logger.log(`Уход Мес ВБ: ${monthStats[testBase] || 0} (ожидается 4)`);
  Logger.log(`Уход КВ ВБ: ${quarterStats[testBase] || 0} (ожидается 19)`);
  const monthOk = (monthStats[testBase] || 0) >= 3 && (monthStats[testBase] || 0) <= 5;
  Logger.log(`${monthOk ? '✅' : '⚠️'} Проверка данных`);
}
