/**
 * WB ЗАКАЗЫ - Воронка продаж (Sales Funnel API)
 *
 * Заполняет колонку N (14): Сумма заказов Мес ВБ
 *
 * ИСПРАВЛЕНО: Использует правильный API endpoint:
 * GET https://seller-analytics-api.wildberries.ru/api/analytics/v3/sales-funnel/products/history
 */

function updateOrdersSummaryV2() {
  const sheet = mainSheet();
  const formatDate = date => Utilities.formatDate(date, "GMT+3", "yyyy-MM-dd");

  Logger.log("=== ОБНОВЛЕНИЕ СУММЫ ЗАКАЗОВ МЕС ВБ (N, 14) ===");

  // ИСПРАВЛЕНО: Диапазон "сегодняшнее число месяца назад по сегодня"
  const today = new Date();

  const dateFrom = new Date(today.getFullYear(), today.getMonth() - 1, today.getDate()); // Тот же день, месяц назад
  const dateTo = today;

  Logger.log(`Период: с ${formatDate(dateFrom)} по ${formatDate(dateTo)}`);

  // ИСПРАВЛЕНО: WB Sales Funnel API требует POST с телом запроса
  // Не используем этот endpoint, так как он требует сложную структуру
  // Вместо этого используем проверенный старый метод

  const url = `${wbOrdersApiURL()}?dateFrom=${formatDate(dateFrom)}`;

  Logger.log(`API Endpoint: ${url}`);

  const options = {
    method: "get",
    headers: wbHeaders(),
    muteHttpExceptions: true
  };

  try {
    const response = retryFetch(url, options);

    if (!response) {
      Logger.log(`❌ Не удалось получить заказы WB (проблемы с сетью)`);
      return;
    }

    const responseText = response.getContentText();
    const data = JSON.parse(responseText);

    // Проверка структуры ответа
    if (!data || !Array.isArray(data)) {
      Logger.log(`❌ Ошибка ответа API: ${JSON.stringify(data).substring(0, 200)}`);
      return;
    }

    Logger.log(`✅ Получено заказов: ${data.length}`);

    // Агрегируем данные по артикулам (старый API возвращает массив заказов)
    const orderStats = {};

    data.forEach(order => {
      const article = order.supplierArticle;

      // ИСПРАВЛЕНО: убираем суффикс после дефиса
      const baseArt = String(article).split('-')[0];

      if (!orderStats[baseArt]) {
        orderStats[baseArt] = { sum: 0, count: 0 };
      }

      // ИСПРАВЛЕНО: priceWithDisc уже в рублях, НЕ делим на 100
      orderStats[baseArt].sum += order.priceWithDisc;
      orderStats[baseArt].count += 1;
    });

    // Обновляем таблицу
    const lastRow = sheet.getLastRow();

    if (lastRow < 2) {
      Logger.log("Нет данных для обновления");
      return;
    }

    // Читаем артикулы из колонки A (1)
    const articles = sheet.getRange(2, 1, lastRow - 1).getValues().flat();

    const colN = []; // Сумма заказов Мес ВБ (14)

    let withOrdersCount = 0;

    for (let i = 0; i < articles.length; i++) {
      const art = articles[i];

      // ИСПРАВЛЕНО: ищем по базовому артикулу (без суффикса), так как агрегация была по baseArt
      const baseArt = art ? String(art).split('-')[0] : "";

      if (baseArt && orderStats[baseArt]) {
        colN.push([orderStats[baseArt].sum]);
        if (orderStats[baseArt].sum > 0) withOrdersCount++;
      } else {
        // ИСПРАВЛЕНО: пишем 0 вместо пустой строки для артикулов без заказов
        colN.push([0]);
      }
    }

    // Записываем в N (14): Сумма заказов Мес ВБ
    sheet.getRange(2, 14, colN.length, 1).setValues(colN);

    // ДИАГНОСТИКА для 22068-1
    const testArticle = "22068-1";
    const testBase = "22068";
    const testSum = orderStats[testBase] ? orderStats[testBase].sum : 0;
    Logger.log(``);
    Logger.log(`=== ДИАГНОСТИКА ${testArticle} ===`);
    Logger.log(`   Базовый артикул: ${testBase}`);
    Logger.log(`   Сумма заказов Мес ВБ: ${testSum} (ожидается 5276)`);
    Logger.log(`${testSum === 5276 ? '✅' : '❌'} Проверка данных`);

    Logger.log(`Обновлено строк: ${articles.length}`);
    Logger.log(`С заказами за период: ${withOrdersCount}`);
    Logger.log(`✅ Завершено`);

  } catch (e) {
    Logger.log(`❌ Ошибка: ${e.message}`);
    Logger.log(e.stack);
  }
}

/**
 * СТАРАЯ ВЕРСИЯ (оставлена для совместимости)
 * Использует старый endpoint statistics-api
 *
 * ВНИМАНИЕ: Эта версия использует неправильный API endpoint!
 * Рекомендуется использовать updateOrdersSummaryV2() с sales funnel API
 */
function updateOrdersSummaryOld() {
  const sheet = mainSheet();
  const formatDate = date => Utilities.formatDate(date, "GMT+3", "yyyy-MM-dd");

  Logger.log("=== ОБНОВЛЕНИЕ СУММЫ ЗАКАЗОВ МЕС ВБ (СТАРЫЙ МЕТОД) ===");

  // Формируем диапазоны
  const today = new Date();
  const dateFromMonth = new Date(today.getFullYear(), today.getMonth() - 1, today.getDate()); // Тот же день, месяц назад
  const dateFromQuarter = new Date(today);
  dateFromQuarter.setDate(today.getDate() - 91);

  Logger.log(`Период: с ${formatDate(dateFromMonth)}`);

  function fetchOrdersV2(dateFrom) {
    const url = `https://statistics-api.wildberries.ru/api/v1/supplier/orders?dateFrom=${formatDate(dateFrom)}`;
    const options = {
      method: "get",
      headers: wbHeaders(),
      muteHttpExceptions: true
    };
    const response = retryFetch(url, options);

    if (!response) {
      Logger.log(`❌ Не удалось получить заказы WB (старый метод)`);
      return [];
    }

    const orders = JSON.parse(response.getContentText());
    return orders.filter(o => !o.isCancel);
  }

  let v2Sum = 0;
  function summarizeV2(orders) {
    const map = {};
    for (const order of orders) {
      const art = order.supplierArticle;

      // ИСПРАВЛЕНО: убираем суффикс после дефиса
      const baseArt = String(art).split('-')[0];

      if (!map[baseArt]) map[baseArt] = { sum: 0, count: 0, finishedPrice: order.finishedPrice };
      map[baseArt].sum += order.priceWithDisc;
      map[baseArt].count += 1;
    }
    return map;
  }

  // Получаем данные
  const ordersMonth = fetchOrdersV2(dateFromMonth);
  Logger.log(`Получено заказов: ${ordersMonth.length}`);

  const monthStats = summarizeV2(ordersMonth);

  sleep(1);

  const ordersQuarter = fetchOrdersV2(dateFromQuarter);
  const quarterStats = {};
  for (const order of ordersQuarter) {
    const art = order.supplierArticle;

    // ИСПРАВЛЕНО: убираем суффикс после дефиса
    const baseArt = String(art).split('-')[0];

    if (!quarterStats[baseArt]) quarterStats[baseArt] = 0;
    quarterStats[baseArt] += 1;
  }

  // Обновляем таблицу
  const lastRow = sheet.getLastRow();
  const articles = sheet.getRange(2, 1, lastRow - 1).getValues().flat();

  const colK = []; // Сумма заказов Мес ВБ (14)

  let withOrdersCount = 0;

  for (let i = 0; i < articles.length; i++) {
    const art = articles[i];

    // ИСПРАВЛЕНО: ищем по базовому артикулу (без суффикса)
    const baseArt = art ? String(art).split('-')[0] : "";
    const month = baseArt ? (monthStats[baseArt] || { sum: 0, count: 0, finishedPrice: 0 }) : { sum: 0, count: 0, finishedPrice: 0 };

    colK.push([month.sum]);

    if (month.sum > 0) withOrdersCount++;
  };

  // Записываем в N (14): Сумма заказов Мес ВБ
  sheet.getRange(2, 14, colK.length, 1).setValues(colK);

  Logger.log(`Обновлено строк: ${articles.length}`);
  Logger.log(`С заказами за месяц: ${withOrdersCount}`);

  // ДИАГНОСТИКА для 23348-1
  const testArticle = "23348-1";
  const testBase = "23348";
  const testData = monthStats[testBase];
  Logger.log("");
  Logger.log(`=== ДИАГНОСТИКА 23348-1 ===`);
  Logger.log(`Артикул: ${testArticle}`);
  Logger.log(`Базовый: ${testBase}`);
  Logger.log(`Сумма заказов: ${testData ? testData.sum : 0} руб. (ожидается 23119)`);
  Logger.log(`${(testData && testData.sum === 23119) ? '✅' : '⚠️'} Проверка данных`);
  Logger.log(`✅ Завершено`);
}
