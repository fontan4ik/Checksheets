/**
 * WILDBERRIES FBO/FBS ПРОДАЖИ (Analytics API)
 *
 * Заполняет колонки:
 * - AV (48): Продажи штуки месяц FBO ВБ
 * - AW (49): Продажи штуки месяц FBS ВБ
 * - AX (50): Продажи штуки квартал FBO ВБ
 * - AY (51): Продажи штуки квартал FBS ВБ
 *
 * ИСПОЛЬЗУЕТСЯ API: POST /api/v2/stocks-report/products/products
 * Базовый URL: https://seller-analytics-api.wildberries.ru
 *
 * ПАРАМЕТРЫ:
 * - stockType: "wb" → FBO (склады WB), "mp" → FBS (склады продавца)
 * - Поле ordersCount: количество заказов
 *
 * ЛИМИТЫ:
 * - 3 запроса / 20 секунд
 * - До 1000 товаров за запрос (limit)
 * - До 1000 nmIDs за запрос
 * - Пагинация через offset
 *
 * ПЕРИОДЫ:
 * - МЕСЯЦ: скользящий месяц - 30 дней назад по сегодня
 * - КВАРТАЛ: скользящий квартал - 90 дней назад по сегодня
 */

/**
 * Разбивает массив на чанки
 */
function chunkArray(arr, size) {
  const chunks = [];
  for (let i = 0; i < arr.length; i += size) {
    chunks.push(arr.slice(i, i + size));
  }
  return chunks;
}

/**
 * Извлечь ordersCount из элемента (поддержка разных структур)
 */
function getOrdersCount(item) {
  if (!item) return 0;

  // Пробуем разные варианты вложенности
  if (typeof item.ordersCount === 'number') {
    return item.ordersCount;
  }
  if (typeof item.statistics?.ordersCount === 'number') {
    return item.statistics.ordersCount;
  }
  if (typeof item.metrics?.ordersCount === 'number') {
    return item.metrics.ordersCount;
  }
  if (typeof item.data?.ordersCount === 'number') {
    return item.data.ordersCount;
  }

  return 0;
}

/**
 * Базовая функция запроса к Analytics API
 * @param {Array} nmIDs - Массив nmId (пустой = все товары)
 * @param {string} dateFrom - Начало периода "YYYY-MM-DD"
 * @param {string} dateTo - Конец периода "YYYY-MM-DD"
 * @param {string} stockType - "wb" (FBO), "mp" (FBS), "" (все)
 * @param {number} offset - Смещение для пагинации
 * @returns {Array} - Массив товаров
 */
function fetchStocksReport({ nmIDs = [], dateFrom, dateTo, stockType, offset = 0 }) {
  const url = `${WB_ANALYTICS_BASE_URL()}/api/v2/stocks-report/products/products`;

  const payload = {
    nmIDs: nmIDs,
    currentPeriod: {
      start: dateFrom,
      end: dateTo
    },
    stockType: stockType,
    skipDeletedNm: false,
    availabilityFilters: [],
    orderBy: {
      field: 'ordersCount',
      mode: 'desc'
    },
    limit: 1000,
    offset: offset
  };

  const options = {
    method: "post",
    headers: wbAnalyticsHeaders(),
    contentType: "application/json",
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  Logger.log(`🔄 Analytics запрос: stockType=${stockType}, offset=${offset}, nmIDs=${nmIDs.length}`);
  Logger.log(`   Период: ${dateFrom} - ${dateTo}`);

  const response = retryFetch(url, options);

  if (!response) {
    Logger.log(`❌ Не удалось получить данные Analytics`);
    return [];
  }

  const responseCode = response.getResponseCode();
  const responseText = response.getContentText();

  if (responseCode !== 200) {
    Logger.log(`❌ Ошибка API: HTTP ${responseCode}`);
    Logger.log(`   ${responseText.substring(0, 200)}`);
    return [];
  }

  const json = JSON.parse(responseText);
  const items = json.data?.items ?? [];

  // 🔍 ДЕБАГ: показываем структуру первого элемента (только один раз)
  if (items.length > 0 && offset === 0) {
    Logger.log('🔍 СТРУКТУРА ПЕРВОГО ЭЛЕМЕНТА:');
    const firstItem = items[0];
    const keys = Object.keys(firstItem).slice(0, 20); // Первые 20 ключей
    Logger.log(`   Ключи: ${keys.join(', ')}`);
    Logger.log(`   nmID: ${firstItem.nmID}`);
    Logger.log(`   ordersCount: ${firstItem.ordersCount}`);
    if (firstItem.statistics) {
      Logger.log(`   statistics: ${JSON.stringify(Object.keys(firstItem.statistics))}`);
    }
    if (firstItem.metrics) {
      Logger.log(`   metrics: ${JSON.stringify(Object.keys(firstItem.metrics))}`);
    }
  }

  Logger.log(`   Получено товаров: ${items.length}`);

  return items;
}

/**
 * Пагинация для одного батча nmIDs
 */
function fetchAllPages({ nmIDs, dateFrom, dateTo, stockType }) {
  const allItems = [];
  let offset = 0;
  let pageCount = 0;

  while (true) {
    const items = fetchStocksReport({ nmIDs, dateFrom, dateTo, stockType, offset });

    if (items.length === 0) {
      break;
    }

    allItems.push(...items);
    pageCount++;

    if (items.length < 1000) {
      break; // Последняя страница
    }

    offset += 1000;

    // Лимит: 3 запроса / 20 сек → ждём 12 сек (с запасом)
    Logger.log(`⏳ Пауза 12 сек (лимит API)...`);
    Utilities.sleep(12000);
  }

  Logger.log(`   Страниц: ${pageCount}, всего товаров: ${allItems.length}`);

  return allItems;
}

/**
 * Собрать все товары с батчингом по nmIDs
 * @param {Array} nmIDs - Массив nmId
 * @param {string} dateFrom - Начало периода
 * @param {string} dateTo - Конец периода
 * @param {string} stockType - "wb" или "mp"
 * @returns {Array} - Все товары
 */
function fetchAllProductsBatched({ nmIDs, dateFrom, dateTo, stockType }) {
  const BATCH_SIZE = 500; // Безопасный лимит (до 1000 по документации)
  const allItems = [];

  // Если пустой массив или нет фильтрации — один запрос без nmIDs
  if (!nmIDs || nmIDs.length === 0) {
    Logger.log(`   Запрос без фильтра по nmID`);
    return fetchAllPages({ nmIDs: [], dateFrom, dateTo, stockType });
  }

  const batches = chunkArray(nmIDs, BATCH_SIZE);
  Logger.log(`   Батчей: ${batches.length} по ~${BATCH_SIZE} nmID`);

  batches.forEach((batch, i) => {
    Logger.log(`   Батч ${i + 1}/${batches.length}: ${batch.length} nmID`);

    const items = fetchAllPages({ nmIDs: batch, dateFrom, dateTo, stockType });
    allItems.push(...items);

    // Пауза между батчами
    if (i < batches.length - 1) {
      Logger.log(`⏳ Пауза 10 сек между батчами...`);
      Utilities.sleep(10000);
    }
  });

  Logger.log(`   Итого товаров: ${allItems.length}`);

  return allItems;
}

/**
 * Получить диапазон дат для месяца (скользящий месяц: 30 дней назад по вчера)
 * ВАЖНО: WB API не принимает сегодняшнюю дату в currentPeriod.end — используем вчера
 * @returns {Array} - [dateFrom, dateTo] в формате "YYYY-MM-DD"
 */
function getWBSalesMonthDateRange() {
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);

  const dateFrom = new Date(yesterday);
  dateFrom.setMonth(dateFrom.getMonth() - 1);

  return [
    Utilities.formatDate(dateFrom, "GMT+3", "yyyy-MM-dd"),
    Utilities.formatDate(yesterday, "GMT+3", "yyyy-MM-dd")
  ];
}

/**
 * Получить диапазон дат для квартала (скользящий квартал: 90 дней назад по вчера)
 * ВАЖНО: WB API не принимает сегодняшнюю дату в currentPeriod.end — используем вчера
 * @returns {Array} - [dateFrom, dateTo] в формате "YYYY-MM-DD"
 */
function getWBSalesQuarterDateRange() {
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);

  const dateFrom = new Date(yesterday);
  dateFrom.setDate(dateFrom.getDate() - 90);

  return [
    Utilities.formatDate(dateFrom, "GMT+3", "yyyy-MM-dd"),
    Utilities.formatDate(yesterday, "GMT+3", "yyyy-MM-dd")
  ];
}

/**
 * Создать индекс для O(1) поиска
 */
function createIndex(data) {
  const index = {};
  data.forEach(item => {
    if (item.nmID) {
      index[item.nmID] = item;
    }
  });
  return index;
}

/**
 * Обновить продажи WB FBO/FBS (месяц и квартал)
 */
function updateWBSalesFBOFBS() {
  const sheet = mainSheet();

  Logger.log("=== ОБНОВЛЕНИЕ ПРОДАЖ WB FBO/FBS (Analytics API) ===");
  Logger.log("AV (48): Продажи штуки месяц FBO");
  Logger.log("AW (49): Продажи штуки месяц FBS");
  Logger.log("AX (50): Продажи штуки квартал FBO");
  Logger.log("AY (51): Продажи штуки квартал FBS");

  const [monthFrom, monthTo] = getWBSalesMonthDateRange();
  const [quarterFrom, quarterTo] = getWBSalesQuarterDateRange();

  Logger.log(`📅 Месяц:   ${monthFrom} → ${monthTo}`);
  Logger.log(`📅 Квартал: ${quarterFrom} → ${quarterTo}`);

  // Получаем все nmId из таблицы для фильтрации
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    Logger.log("❌ Нет данных для обновления");
    return;
  }

  const articles = sheet.getRange(2, 20, lastRow - 1).getValues().flat();
  const nmIDs = articles.filter(a => a && a > 0).map(a => Number(a));

  Logger.log(`📦 Товаров в таблице: ${nmIDs.length}`);

  Logger.log('');
  Logger.log('--- ЗАПРОС 1/4: FBO месяц ---');

  const fboMonth = fetchAllProductsBatched({
    nmIDs: nmIDs,
    dateFrom: monthFrom,
    dateTo: monthTo,
    stockType: 'wb'
  });

  Logger.log('');
  Logger.log('⏳ Пауза 10 сек (лимит API)...');
  Utilities.sleep(10000);

  Logger.log('');
  Logger.log('--- ЗАПРОС 2/4: FBS месяц ---');

  const fbsMonth = fetchAllProductsBatched({
    nmIDs: nmIDs,
    dateFrom: monthFrom,
    dateTo: monthTo,
    stockType: 'mp'
  });

  Logger.log('');
  Logger.log('⏳ Пауза 10 сек (лимит API)...');
  Utilities.sleep(10000);

  Logger.log('');
  Logger.log('--- ЗАПРОС 3/4: FBO квартал ---');

  const fboQuarter = fetchAllProductsBatched({
    nmIDs: nmIDs,
    dateFrom: quarterFrom,
    dateTo: quarterTo,
    stockType: 'wb'
  });

  Logger.log('');
  Logger.log('⏳ Пауза 10 сек (лимит API)...');
  Utilities.sleep(10000);

  Logger.log('');
  Logger.log('--- ЗАПРОС 4/4: FBS квартал ---');

  const fbsQuarter = fetchAllProductsBatched({
    nmIDs: nmIDs,
    dateFrom: quarterFrom,
    dateTo: quarterTo,
    stockType: 'mp'
  });

  Logger.log('');
  Logger.log('--- ОБРАБОТКА ДАННЫХ ---');

  // Создаём индексы для быстрого поиска
  const iFboM = createIndex(fboMonth);
  const iFbsM = createIndex(fbsMonth);
  const iFboQ = createIndex(fboQuarter);
  const iFbsQ = createIndex(fbsQuarter);

  const colAV = []; // Продажи месяц FBO (48)
  const colAW = []; // Продажи месяц FBS (49)
  const colAX = []; // Продажи квартал FBO (50)
  const colAY = []; // Продажи квартал FBS (51)

  let fboMonthCount = 0;
  let fbsMonthCount = 0;
  let fboQuarterCount = 0;
  let fbsQuarterCount = 0;

  for (let i = 0; i < articles.length; i++) {
    const nmId = articles[i];

    if (nmId) {
      const nmIdNum = Number(nmId);

      // Используем getOrdersCount для поддержки разных структур
      const fboMonthQty = getOrdersCount(iFboM[nmIdNum]);
      const fbsMonthQty = getOrdersCount(iFbsM[nmIdNum]);
      const fboQuarterQty = getOrdersCount(iFboQ[nmIdNum]);
      const fbsQuarterQty = getOrdersCount(iFbsQ[nmIdNum]);

      colAV.push([fboMonthQty]);
      colAW.push([fbsMonthQty]);
      colAX.push([fboQuarterQty]);
      colAY.push([fbsQuarterQty]);

      if (fboMonthQty > 0) fboMonthCount++;
      if (fbsMonthQty > 0) fbsMonthCount++;
      if (fboQuarterQty > 0) fboQuarterCount++;
      if (fbsQuarterQty > 0) fbsQuarterCount++;
    } else {
      colAV.push([0]);
      colAW.push([0]);
      colAX.push([0]);
      colAY.push([0]);
    }
  }

  sheet.getRange(2, 48, colAV.length, 1).setValues(colAV);  // AV (48)
  sheet.getRange(2, 49, colAW.length, 1).setValues(colAW);  // AW (49)
  sheet.getRange(2, 50, colAX.length, 1).setValues(colAX);  // AX (50)
  sheet.getRange(2, 51, colAY.length, 1).setValues(colAY);  // AY (51)

  Logger.log('');
  Logger.log('📊 СТАТИСТИКА:');
  Logger.log(`   Обработано строк: ${articles.length}`);
  Logger.log(`   FBO месяц: ${fboMonthCount} артикулов с продажами`);
  Logger.log(`   FBS месяц: ${fbsMonthCount} артикулов с продажами`);
  Logger.log(`   FBO квартал: ${fboQuarterCount} артикулов с продажами`);
  Logger.log(`   FBS квартал: ${fbsQuarterCount} артикулов с продажами`);
  Logger.log('✅ Завершено');
}

/**
 * Тестовая функция для проверки с малым количеством nmID
 */
function testWBSalesSmall() {
  const sheet = mainSheet();

  Logger.log("=== ТЕСТ: 5 первых nmID ===");

  const articles = sheet.getRange(2, 20, 5).getValues().flat();
  const nmIDs = articles.filter(a => a && a > 0).map(a => Number(a));

  Logger.log(`nmID для теста: ${nmIDs.join(', ')}`);

  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);

  const dateFrom = new Date(yesterday);
  dateFrom.setDate(dateFrom.getDate() - 7); // Неделя

  const dateFromStr = Utilities.formatDate(dateFrom, "GMT+3", "yyyy-MM-dd");
  const dateToStr = Utilities.formatDate(yesterday, "GMT+3", "yyyy-MM-dd");

  Logger.log(`Период: ${dateFromStr} - ${dateToStr}`);

  const result = fetchStocksReport({
    nmIDs: nmIDs,
    dateFrom: dateFromStr,
    dateTo: dateToStr,
    stockType: 'wb'
  });

  Logger.log(`Получено товаров: ${result.length}`);
}
