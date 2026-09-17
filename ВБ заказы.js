/**
 * WB ЗАКАЗЫ - Воронка продаж (Sales Funnel API v3)
 *
 * Заполняет колонку N (14): Сумма заказов Мес ВБ
 * Заполняет колонку AP (42): Сумма заказов Год ВБ
 *
 * ИСПРАВЛЕНО: Использует правильный Sales Funnel API v3:
 * POST https://seller-analytics-api.wildberries.ru/api/analytics/v3/sales-funnel/products
 *
 * Структура ответа API v3:
 * {
 *   cards: [
 *     { nmID, vendorCode, ordersSum, ordersCount, buyoutSum, buyoutCount, ... }
 *   ],
 *   totals: {
 *     ordersSum, ordersCount, buyoutSum, buyoutCount
 *   },
 *   cursor: { hasNextPage, nextCursor }
 * }
 */

/**
 * Выполняет запрос к WB Sales Funnel API v3 с пагинацией
 * @param {Date} dateFrom - Начальная дата
 * @param {Date} dateTo - Конечная дата
 * @returns {Object} - Объект с данными по товарам: { nmId: { orderSum, orderCount } }
 */
function fetchWBSalesFunnel(dateFrom, dateTo) {
  const formatDate = date => Utilities.formatDate(date, "GMT+3", "yyyy-MM-dd");

  const stats = {};
  let hasNextPage = true;
  let pageCount = 0;

  Logger.log(`🔄 WB Sales Funnel запрос: ${formatDate(dateFrom)} → ${formatDate(dateTo)}`);

  try {
    while (hasNextPage) {
      pageCount++;

      const body = {
        selectedPeriod: {
          start: formatDate(dateFrom),
          end: formatDate(dateTo)
        },
        limit: 1000
      };

      const options = {
        method: "post",
        contentType: "application/json",
        headers: wbHeaders(),
        payload: JSON.stringify(body),
        muteHttpExceptions: true
      };

      const response = retryFetch(wbSalesFunnelProductsURL(), options);

      if (!response) {
        Logger.log(`❌ Не удалось получить данные WB Sales Funnel (страница ${pageCount})`);
        break;
      }

      const responseText = response.getContentText();
      const data = JSON.parse(responseText);

      if (pageCount === 1) {
        Logger.log(`📊 Структура ответа API (первые 300 символов):`);
        Logger.log(`   ${JSON.stringify(data).substring(0, 300)}`);
      }

      if (!data || !data.data || !data.data.products) {
        Logger.log(`❌ Ошибка ответа API: не найдена структура data.products`);
        Logger.log(`   Поля: ${Object.keys(data || {}).join(', ')}`);
        if (data.data) {
          Logger.log(`   data поля: ${Object.keys(data.data).join(', ')}`);
        }
        break;
      }

      const products = data.data.products;
      Logger.log(`📦 Страница ${pageCount}: ${products.length} товаров`);

      // Агрегируем данные по nmId
      products.forEach(item => {
        const nmId = item.product ? (item.product.nmId || item.product.nmID) : null;
        const orderSum = item.statistic && item.statistic.selected
          ? (item.statistic.selected.orderSum || 0)
          : 0;
        const orderCount = item.statistic && item.statistic.selected
          ? (item.statistic.selected.orderCount || 0)
          : 0;

        if (nmId) {
          if (!stats[nmId]) {
            stats[nmId] = {
              orderSum: 0,
              orderCount: 0
            };
          }
          stats[nmId].orderSum += orderSum;
          stats[nmId].orderCount += orderCount;
        }
      });

      // Проверяем пагинацию
      if (data.data && data.data.cursor && data.data.cursor.hasNextPage === false) {
        hasNextPage = false;
      } else if (!data.data || !data.data.cursor) {
        // Если нет поля cursor, значит это последняя страница
        hasNextPage = false;
      } else if (products.length === 0) {
        // Если нет товаров, завершаем
        hasNextPage = false;
      }

      // Небольшая пауза между запросами
      if (hasNextPage) {
        Utilities.sleep(500);
      }
    }

    const totalNmIds = Object.keys(stats).length;
    Logger.log(`✅ Всего получено уникальных nmId: ${totalNmIds} (${pageCount} страниц)`);

    return stats;
  } catch (e) {
    Logger.log(`❌ Ошибка при получении данных: ${e.message}`);
    return null;
  }
}

function updateOrdersSummaryV2() {
  const sheet = mainSheet();
  const formatDate = date => Utilities.formatDate(date, "GMT+3", "yyyy-MM-dd");

  Logger.log("=== ОБНОВЛЕНИЕ СУММЫ ЗАКАЗОВ (WB Sales Funnel API) ===");
  Logger.log("Колонка N (14): Сумма заказов Мес ВБ");
  Logger.log("Колонка AP (42): Сумма заказов Год ВБ");

  const today = new Date();

  // Месяц: с 24 числа предыдущего месяца по 24 число текущего месяца (например, 2026-01-24 по 2026-02-24)
  const dateFromMonth = new Date(today.getFullYear(), today.getMonth() - 1, today.getDate());
  const dateTo = today;

  Logger.log(`Период (месяц): с ${formatDate(dateFromMonth)} по ${formatDate(dateTo)}`);

  // Получаем данные за месяц
  const monthStats = fetchWBSalesFunnel(dateFromMonth, dateTo);

  if (!monthStats) {
    Logger.log(`❌ Не удалось получить данные за месяц`);
    return;
  }

  // Год: ограничение API - 365 дней максимум
  const dateFromYearStart = new Date(today.getFullYear() - 1, 0, 1); // 1 января прошлого года
  const year365DaysAgo = new Date(today);
  year365DaysAgo.setDate(today.getDate() - 365);

  // Определяем начальную дату для годового запроса (берем более позднюю дату)
  // Используем getTime() для корректного сравнения дат
  const dateFromYear = year365DaysAgo.getTime() > dateFromYearStart.getTime()
    ? year365DaysAgo
    : dateFromYearStart;

  Logger.log(`Период (год, ограничение 365 дней): с ${formatDate(dateFromYear)} по ${formatDate(dateTo)}`);

  // Получаем данные за год
  const yearStats = fetchWBSalesFunnel(dateFromYear, dateTo);

  if (!yearStats) {
    Logger.log(`❌ Не удалось получить данные за год`);
    return;
  }

  // Обновляем таблицу
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет данных для обновления");
    return;
  }

  // Читаем nmId из колонки T (20) - Артикул WB
  const nmIds = sheet.getRange(2, 20, lastRow - 1).getValues().flat();

  // ДИАГНОСТИКА: Показываем примеры nmId
  const apiNmIds = Object.keys(monthStats);
  Logger.log(``);
  Logger.log(`📊 ДИАГНОСТИКА nmId:`);
  Logger.log(`   API вернул nmId (первые 10): ${apiNmIds.slice(0, 10).join(', ')}`);
  Logger.log(`   В таблице nmId (первые 10): ${nmIds.slice(0, 10).map(id => id || 'EMPTY').filter(id => id !== 'EMPTY').join(', ') || 'ВСЕ ПУСТЫЕ'}`);

  // Проверяем совпадения
  let tableHasNmId = 0;
  let nmIdMatches = 0;
  nmIds.forEach(nmId => {
    if (nmId && nmId > 0) {
      tableHasNmId++;
      if (monthStats[nmId]) {
        nmIdMatches++;
      }
    }
  });

  Logger.log(`   В таблице заполнено nmId: ${tableHasNmId} из ${nmIds.length}`);
  Logger.log(`   Совпадений nmId с API: ${nmIdMatches}`);

  if (nmIdMatches === 0 && tableHasNmId > 0) {
    Logger.log(`   ⚠️ nmId в таблице не совпадают с nmId из API!`);
    Logger.log(`   Проверьте колонку T (20) - Артикул WB`);
  }

  const colN = []; // Сумма заказов Мес ВБ (14)
  const colAP = []; // Сумма заказов Год ВБ (42)

  let withOrdersMonthCount = 0;
  let withOrdersYearCount = 0;

  for (let i = 0; i < nmIds.length; i++) {
    const nmId = nmIds[i];

    if (nmId && nmId > 0) {
      // Ищем по nmId (артикул WB)
      const monthData = monthStats[nmId] || { orderSum: 0 };
      const yearData = yearStats[nmId] || { orderSum: 0 };

      colN.push([monthData.orderSum]);
      colAP.push([yearData.orderSum]);

      if (monthData.orderSum > 0) withOrdersMonthCount++;
      if (yearData.orderSum > 0) withOrdersYearCount++;
    } else {
      colN.push([0]);
      colAP.push([0]);
    }
  }

  // Записываем в N (14): Сумма заказов Мес ВБ
  sheet.getRange(2, 14, colN.length, 1).setValues(colN);

  // Записываем в AP (42): Сумма заказов Год ВБ
  sheet.getRange(2, 42, colAP.length, 1).setValues(colAP);

  // ДИАГНОСТИКА
  Logger.log(``);
  Logger.log(`📊 СТАТИСТИКА:`);
  Logger.log(`   Обновлено строк: ${nmIds.length}`);
  Logger.log(`   С заказами за месяц: ${withOrdersMonthCount}`);
  Logger.log(`   С заказами за год: ${withOrdersYearCount}`);
  Logger.log(`✅ Завершено`);
}
