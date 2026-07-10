/**
 * ГОДОВЫЕ ПРОДАЖИ
 *
 * Заполняет колонки:
 * - BD (56): Количество продаж Год ОЗОН
 * - BE (57): Количество продаж Год ВБ
 *
 * Период: с (текущая дата - 1 год) по текущую дату
 */

function updateYearlySales() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет данных для обработки");
    return;
  }

  const range = getYearRange();
  const dateFrom = range.dateFrom;
  const dateTo = range.dateTo;

  Logger.log("=== ОБНОВЛЕНИЕ ГОДОВЫХ ПРОДАЖ ===");
  Logger.log(`Период: с ${dateFrom} по ${dateTo}`);

  const startTime = Date.now();

  const ozonSales = fetchOzonYearlySales(dateFrom, dateTo);
  const wbSales = fetchWBYearlySales(dateFrom);

  const offerIds = sheet.getRange(2, 1, lastRow - 1).getValues().flat();
  const skus = sheet.getRange(2, 22, lastRow - 1).getValues().flat();
  const nmIds = sheet.getRange(2, 20, lastRow - 1).getValues().flat();

  Logger.log(`🔍 Диагностика Ozon: проверяем ключи...`);
  const sampleKeys = Object.keys(ozonSales).slice(0, 5);
  const sampleSkus = skus.slice(0, 5).map(String);
  Logger.log(`   Ключи из API: ${sampleKeys.join(", ")}`);
  Logger.log(`   SKU из таблицы: ${sampleSkus.join(", ")}`);

  const ozonValues = [];
  const wbValues = [];
  let ozonFilled = 0;
  let wbFilled = 0;

  for (let i = 0; i < offerIds.length; i++) {
    const skuStr = String(skus[i] || "").trim();
    const nmId = nmIds[i];

    let ozonCount = 0;
    if (skuStr) {
      ozonCount = ozonSales[skuStr] || 0;
      if (ozonCount === 0 && ozonSales[Number(skuStr)]) {
        ozonCount = ozonSales[Number(skuStr)];
      }
    }

    const wbCount = nmId && nmId > 0 ? (wbSales[nmId] || 0) : 0;

    ozonValues.push([ozonCount]);
    wbValues.push([wbCount]);

    if (ozonCount > 0) ozonFilled++;
    if (wbCount > 0) wbFilled++;
  }

  sheet.getRange(2, 56, ozonValues.length, 1).setValues(ozonValues);
  sheet.getRange(2, 57, wbValues.length, 1).setValues(wbValues);

  const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
  Logger.log(`✅ Годовые продажи обновлены за ${elapsed} сек`);
  Logger.log(`   Ozon: ${ozonFilled} товаров с продажами`);
  Logger.log(`   WB: ${wbFilled} товаров с продажами`);
}

function getYearRange() {
  const today = new Date();
  const dateTo = Utilities.formatDate(today, "GMT+3", "yyyy-MM-dd");

  const dateFromObj = new Date(today);
  dateFromObj.setFullYear(dateFromObj.getFullYear() - 1);
  const dateFrom = Utilities.formatDate(dateFromObj, "GMT+3", "yyyy-MM-dd");

  return { dateFrom, dateTo };
}

function fetchOzonYearlySales(dateFrom, dateTo) {
  const url = ozonAnalyticsData();
  const headers = ozonHeaders();
  const batchSize = 1000;
  const sales = {};

  Logger.log("🔄 Загрузка данных Ozon Analytics с пагинацией...");

  try {
    let offset = 0;
    let totalFetched = 0;

    while (true) {
      const payload = {
        date_from: dateFrom,
        date_to: dateTo,
        dimension: ["sku"],
        metrics: ["ordered_units"],
        limit: batchSize,
        offset: offset
      };

      const options = {
        method: "post",
        contentType: "application/json",
        headers: headers,
        payload: JSON.stringify(payload),
        muteHttpExceptions: true
      };

      const response = retryFetch(url, options);
      if (!response) break;

      const data = JSON.parse(response.getContentText());

      if (!data.result || !data.result.data || data.result.data.length === 0) {
        break;
      }

      data.result.data.forEach(entry => {
        const offerId = entry.dimensions[0]?.id;
        const orders = entry.metrics?.[0] || 0;

        if (offerId) {
          sales[offerId] = orders;
        }
      });

      totalFetched += data.result.data.length;
      Logger.log(`  Пакет: получено ${data.result.data.length}, всего ${totalFetched}`);

      if (data.result.data.length < batchSize) break;
      offset += batchSize;
    }

    Logger.log(`✅ Ozon: получено ${totalFetched} товаров`);

    const nonZero = Object.values(sales).filter(v => v > 0).length;
    Logger.log(`   С продажами: ${nonZero} товаров`);

    return sales;
  } catch (e) {
    Logger.log(`❌ Ошибка Ozon Analytics: ${e.message}`);
    return {};
  }
}

function fetchWBYearlySales(dateFrom) {
  const url = `https://statistics-api.wildberries.ru/api/v1/supplier/orders?dateFrom=${dateFrom}`;
  const options = {
    method: "get",
    headers: wbHeaders(),
    muteHttpExceptions: true
  };

  Logger.log(`🔄 Загрузка заказов WB с ${dateFrom}...`);

  try {
    const response = retryFetch(url, options);
    if (!response) {
      Logger.log("❌ Ошибка получения заказов WB");
      return {};
    }

    const orders = JSON.parse(response.getContentText());

    if (!Array.isArray(orders)) {
      Logger.log("⚠️ Ответ WB не массив: " + JSON.stringify(orders).substring(0, 500));
      return {};
    }

    const sales = {};

    orders.forEach(order => {
      const nmId = order.nmId;
      if (!nmId) return;

      sales[nmId] = (sales[nmId] || 0) + 1;
    });

    Logger.log(`✅ WB: получено ${orders.length} заказов, ${Object.keys(sales).length} товаров`);

    return sales;
  } catch (e) {
    Logger.log(`❌ Ошибка WB Orders: ${e.message}`);
    return {};
  }
}
