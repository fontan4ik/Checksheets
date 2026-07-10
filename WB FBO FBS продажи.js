/**
 * WB FBO/FBS ПРОДАЖИ (штуки)
 *
 * Заполняет колонки:
 * - AV (48): Продажи штуки месяц FBO ВБ
 * - AW (49): Продажи штуки месяц FBS ВБ
 * - AX (50): Продажи штуки квартал FBO ВБ
 * - AY (51): Продажи штуки квартал FBS ВБ
 *
 * API: /api/v1/supplier/orders
 * Разделение по warehouseType:
 *   - "Склад продавца" = FBS
 *   - Все остальные = FBO
 */

function updateWBFBOFBSSales() {
  const startTime = new Date();
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет данных для обработки");
    return;
  }

  const today = new Date();
  const dateFromMonth = new Date(today.getFullYear(), today.getMonth() - 1, today.getDate());
  const dateFromQuarter = new Date(today.getFullYear(), today.getMonth() - 3, today.getDate());

  const formatDate = date => Utilities.formatDate(date, "GMT+3", "yyyy-MM-dd");

  Logger.log(`📊 Период анализа:`);
  Logger.log(`   Месяц: с ${formatDate(dateFromMonth)}`);
  Logger.log(`   Квартал: с ${formatDate(dateFromQuarter)}`);

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

      return orders;
    } catch (e) {
      Logger.log(`❌ Ошибка при получении заказов: ${e.message}`);
      return [];
    }
  }

  const ordersMonth = fetchOrders(dateFromMonth, "месяц");
  const ordersQuarter = fetchOrders(dateFromQuarter, "квартал");

  const monthFBOStats = {};
  const monthFBSStats = {};
  const quarterFBOStats = {};
  const quarterFBSStats = {};

  const warehouseTypes = new Set();

  ordersMonth.forEach(order => {
    const nmId = order.nmId;
    if (!nmId) return;

    const wType = order.warehouseType || "";
    warehouseTypes.add(wType);

    const isFBS = wType === "Склад продавца";

    if (isFBS) {
      monthFBSStats[nmId] = (monthFBSStats[nmId] || 0) + 1;
    } else {
      monthFBOStats[nmId] = (monthFBOStats[nmId] || 0) + 1;
    }
  });

  ordersQuarter.forEach(order => {
    const nmId = order.nmId;
    if (!nmId) return;

    const wType = order.warehouseType || "";
    warehouseTypes.add(wType);

    const isFBS = wType === "Склад продавца";

    if (isFBS) {
      quarterFBSStats[nmId] = (quarterFBSStats[nmId] || 0) + 1;
    } else {
      quarterFBOStats[nmId] = (quarterFBOStats[nmId] || 0) + 1;
    }
  });

  Logger.log(`📦 Уникальные warehouseType в ответе API:`);
  warehouseTypes.forEach(wt => Logger.log(`   - "${wt}"`));

  const nmIds = sheet.getRange(2, 20, lastRow - 1).getValues().flat();

  const fboMonthValues = [];
  const fbsMonthValues = [];
  const fboQuarterValues = [];
  const fbsQuarterValues = [];

  let monthWithOrders = 0;
  let quarterWithOrders = 0;

  nmIds.forEach(nmId => {
    if (nmId && nmId > 0) {
      const fboMonth = monthFBOStats[nmId] || 0;
      const fbsMonth = monthFBSStats[nmId] || 0;
      const fboQuarter = quarterFBOStats[nmId] || 0;
      const fbsQuarter = quarterFBSStats[nmId] || 0;

      fboMonthValues.push([fboMonth]);
      fbsMonthValues.push([fbsMonth]);
      fboQuarterValues.push([fboQuarter]);
      fbsQuarterValues.push([fbsQuarter]);

      if (fboMonth > 0 || fbsMonth > 0) monthWithOrders++;
      if (fboQuarter > 0 || fbsQuarter > 0) quarterWithOrders++;
    } else {
      fboMonthValues.push([0]);
      fbsMonthValues.push([0]);
      fboQuarterValues.push([0]);
      fbsQuarterValues.push([0]);
    }
  });

  sheet.getRange(2, 48, fboMonthValues.length, 1).setValues(fboMonthValues);
  sheet.getRange(2, 49, fbsMonthValues.length, 1).setValues(fbsMonthValues);
  sheet.getRange(2, 50, fboQuarterValues.length, 1).setValues(fboQuarterValues);
  sheet.getRange(2, 51, fbsQuarterValues.length, 1).setValues(fbsQuarterValues);

  let totalFboMonth = 0, totalFbsMonth = 0, totalFboQuarter = 0, totalFbsQuarter = 0;
  nmIds.forEach((nmId, idx) => {
    if (nmId && nmId > 0) {
      totalFboMonth += fboMonthValues[idx][0] || 0;
      totalFbsMonth += fbsMonthValues[idx][0] || 0;
      totalFboQuarter += fboQuarterValues[idx][0] || 0;
      totalFbsQuarter += fbsQuarterValues[idx][0] || 0;
    }
  });

  Logger.log(`✅ Обновление завершено!`);
  Logger.log(`📝 Строк обновлено: ${nmIds.length}`);
  Logger.log(`📊 Статистика:`);
  Logger.log(`   FBO месяц: ${totalFboMonth} шт`);
  Logger.log(`   FBS месяц: ${totalFbsMonth} шт`);
  Logger.log(`   FBO квартал: ${totalFboQuarter} шт`);
  Logger.log(`   FBS квартал: ${totalFbsQuarter} шт`);
  Logger.log(`   С заказами за месяц: ${monthWithOrders}`);
  Logger.log(`   С заказами за квартал: ${quarterWithOrders}`);

  const endTime = new Date();
  const seconds = Math.round((endTime - startTime) / 1000);
  Logger.log(`⏱️ Время выполнения: ${seconds} сек.`);
}
