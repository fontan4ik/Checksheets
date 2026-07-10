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

      // ДИАГНОСТИКА: Проверяем наличие поля nmId в ответе API
      if (orders.length > 0) {
        const firstOrder = orders[0];
        const hasNmId = firstOrder.hasOwnProperty('nmId');
        const hasSupplierArticle = firstOrder.hasOwnProperty('supplierArticle');

        Logger.log(`🔍 Поля в первом заказе:`);
        Logger.log(`   nmId: ${hasNmId ? '✅ ЕСТЬ' : '❌ НЕТ'}`);
        Logger.log(`   supplierArticle: ${hasSupplierArticle ? '✅ ЕСТЬ' : '❌ НЕТ'}`);

        if (hasNmId) {
          Logger.log(`   Значение nmId: ${firstOrder.nmId}`);
        }
        if (hasSupplierArticle) {
          Logger.log(`   Значение supplierArticle: ${firstOrder.supplierArticle}`);
        }

        // Показываем все поля первого заказа
        const allKeys = Object.keys(firstOrder);
        Logger.log(`   Все поля: ${allKeys.join(', ')}`);
      }

      // ИСПРАВЛЕНО: Возвращаем ВСЕ заказы (как в воронке продаж)
      // Воронка продаж считает все заказы, включая отмененные
      return orders;
    } catch (e) {
      Logger.log(`❌ Ошибка при получении заказов: ${e.message}`);
      return [];
    }
  }

  // Получаем заказы за месяц и квартал
  const ordersMonth = fetchOrders(dateFromMonth, "месяц");
  // Пауза не нужна - API вызовы разнесены по времени
  const ordersQuarter = fetchOrders(dateFromQuarter, "квартал");

  // ИСПРАВЛЕНО: агрегируем по nmId (артикул WB), а не по supplierArticle
  const monthStats = {};
  const quarterStats = {};

  // ДИАГНОСТИКА: Считаем заказы с/без nmId
  let monthWithNmId = 0;
  let monthWithoutNmId = 0;

  ordersMonth.forEach(order => {
    const nmId = order.nmId;
    if (!nmId) {
      monthWithoutNmId++;
      return;
    }

    monthWithNmId++;

    if (!monthStats[nmId]) {
      monthStats[nmId] = 0;
    }
    monthStats[nmId]++;
  });

  ordersQuarter.forEach(order => {
    const nmId = order.nmId;
    if (!nmId) return;

    if (!quarterStats[nmId]) {
      quarterStats[nmId] = 0;
    }
    quarterStats[nmId]++;
  });

  Logger.log(``);
  Logger.log(`📊 Статистика nmId за месяц:`);
  Logger.log(`   С nmId: ${monthWithNmId}`);
  Logger.log(`   Без nmId: ${monthWithoutNmId}`);

  // ДИАГНОСТИКА для артикула 23350
  Logger.log(``);
  Logger.log(`=== ДИАГНОСТИКА АРТИКУЛА 23350 (месяц) ===`);

  // Считаем заказы по supplierArticle для 23350-*
  const article23350Stats = {};
  ordersMonth.forEach(order => {
    // ИСПРАВЛЕНО: Считаем ВСЕ заказы (как в воронке продаж)
    const art = order.supplierArticle;
    if (art && art.toString().startsWith('23350')) {
      article23350Stats[art] = (article23350Stats[art] || 0) + 1;
    }
  });

  Object.keys(article23350Stats).sort().forEach(art => {
    const hasNmId = ordersMonth.find(o => o.supplierArticle === art && o.nmId)?.nmId || 'НЕ ЗАПОЛНЕН';
    Logger.log(`   ${art} (nmId: ${hasNmId}): ${article23350Stats[art]} заказов`);
  });

  const total23350 = Object.values(article23350Stats).reduce((a, b) => a + b, 0);
  Logger.log(`   ИТОГО по всем 23350-*: ${total23350} заказов`);

  // Читаем nmId из колонки T (20) - Артикул WB
  const nmIds = sheet.getRange(2, 20, lastRow - 1).getValues().flat();

  // Подготавливаем данные для записи
  const monthValues = [];
  const quarterValues = [];

  let monthWithOrders = 0;
  let quarterWithOrders = 0;

  nmIds.forEach(nmId => {
    if (nmId && nmId > 0) {
      // ИСПРАВЛЕНО: ищем по nmId (артикул WB)
      const monthCount = monthStats[nmId] || 0;
      const quarterCount = quarterStats[nmId] || 0;

      monthValues.push([monthCount]);
      quarterValues.push([quarterCount]);

      if (monthCount > 0) monthWithOrders++;
      if (quarterCount > 0) quarterWithOrders++;
    } else {
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
  Logger.log(`📝 Строк обновлено: ${nmIds.length}`);
  Logger.log(`📊 Статистика:`);
  Logger.log(`   С заказами за месяц: ${monthWithOrders}`);
  Logger.log(`   С заказами за квартал: ${quarterWithOrders}`);

  // ДИАГНОСТИКА для тестового nmId
  const testNmId = 320893058; // nmId для артикула 23350-1
  Logger.log("");
  Logger.log(`=== ДИАГНОСТИКА nmId ${testNmId} (23350-1) ===`);
  Logger.log(`Уход Мес ВБ: ${monthStats[testNmId] || 0} заказов`);
  Logger.log(`Уход КВ ВБ: ${quarterStats[testNmId] || 0} заказов`);
}
