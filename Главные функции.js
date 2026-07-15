// ============================================
// ГЛАВНЫЕ ФУНКЦИИ ДЛЯ ТРИГГЕРОВ
// Этот файл содержит функции которые вызывают старые триггеры
// ============================================

/**
 * OzonMain - Основная функция для выгрузки данных Ozon
 * Вызывается триггерами в 03:07 и 08:54
 *
 * ✅ АВТОНОМНАЯ ФУНКЦИЯ - updateProductsV2() сама заполняет V (22) SKU
 * ⚠️ Независимо от порядка триггеров OzonSKUAndAnalytic всегда получит свежие SKU
 *
 * Заполняет:
 * - U (21): Product_id Ozon
 * - C (3), D (4), E (5), X (24), Y (25): Данные товаров
 * - V (22): SKU Ozon ✅ ЧИТАЕТСЯ OzonSKUAndAnalytic
 * - F (6): Остаток FBO
 * - G (7): Остаток FBS
 * - H (8): FBS склад Москва
 * - K (11): ЦЕНА ОЗОН
 * - AB-AH (28-34): FBS склады (7 складов) ✅ НОВОЕ
 */
function OzonMain(){
  // updateProductsV2() сама последовательно обновляет A/U и данные карточек.
  // Это также сохраняет совместимость с отдельным существующим триггером.
  updateProductsV2();
  updateStockFBO();             // Остатки FBO (F, 6) - ИСПРАВЛЕНО: суммирует все FBO
  updateAllFBSStocks();         // Остатки FBS (G, 7) - ИСПРАВЛЕНО: сумма всех FBS
  getOzonPricesOptimized();    // Цены
  // updateSkuByProductId();      // ❌ УБРАНО: updateProductsV2() уже заполняет V (22) SKU!
  getStocksByWarehouseFBS();   // FBS склад Москва (H, 8)
  fetchAndUpdateAll();         // ✅ НОВОЕ: FBS склады (AB-AH, 28-34) - 7 складов
}

/**
 * Ручной полный запуск после установки исправления.
 * Убирает существующие разрывы в A, синхронизирует A/U и обновляет карточки.
 * Триггер для этой функции создавать не нужно.
 */
function refreshOzonProductsNow() {
  return runWithOzonProductSyncLock_("refreshOzonProductsNow", function() {
    removeEmptyProductRowGaps();
    syncOfferIdWithProductIdCore_();
    updateProductsV2Core_();
  });
}

/**
 * WbMain - Основная функция для выгрузки данных Wildberries
 * Вызывается триггерами в 03:20 и 08:50
 *
 * ИСПРАВЛЕНО (2026-02-05):
 * - Убрана importStocksWithImages() - она перезаписывала L (12) "Сумма заказов Мес ОЗОН"
 * - L (12) используется только Ozon заказами.gs
 */
function WbMain() {
  SpreadsheetApp.getActiveSpreadsheet().toast("Запуск обновления WB (Шаг 1 из 8)", "WB Аналитика", 5);
  PropertiesService.getScriptProperties().deleteProperty("wb_main_step");

  clearWbTriggers();
  processWbStep(1);
}
function clearWbTriggers() {
  const triggers = ScriptApp.getProjectTriggers();
  for (let i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === "resumeWbMain") {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }
}
function resumeWbMain(e) {
  if (e && e.triggerUid) {
    const triggers = ScriptApp.getProjectTriggers();
    for (let i = 0; i < triggers.length; i++) {
      if (triggers[i].getUniqueId() === e.triggerUid) {
        ScriptApp.deleteTrigger(triggers[i]);
        break;
      }
    }
  }

  const step = parseInt(PropertiesService.getScriptProperties().getProperty("wb_main_step"), 10);
  if (step) {
    processWbStep(step);
  }
}
function processWbStep(step) {
  Logger.log(`=== WB MAIN ШАГ ${step} ===`);
  switch(step) {
    case 1:
      updateWBStocksFromStatisticsAPI();
      scheduleNextWbStep(2, "Остатки загружены. Шаг 2: Сумма заказов...");
      break;
    case 2:
      updateOrdersSummaryV2();
      scheduleNextWbStep(3, "Шаг 3: Цены и картинки...");
      break;
    case 3:
      updatePricesAndImages();
      scheduleNextWbStep(4, "Шаг 4: Основная функция ВБ...");
      break;
    case 4:
      main();
      scheduleNextWbStep(5, "Шаг 5: Аналитика уходимость...");
      break;
    case 5:
      // updateWBArticles(); - Убрано по вашей старой конфигурации
      updateWBAnalytics();
      scheduleNextWbStep(6, "Шаг 6: Склады WB...");
      break;
    case 6:
      updateWBWarehousesByName();
      PropertiesService.getScriptProperties().deleteProperty("wb_main_step");
      SpreadsheetApp.getActiveSpreadsheet().toast("Обновление Wildberries полностью завершено!", "Готово", 5);
      break;
  }
}
function scheduleNextWbStep(nextStep, toastMessage) {
  PropertiesService.getScriptProperties().setProperty("wb_main_step", nextStep.toString());
  ScriptApp.newTrigger("resumeWbMain").timeBased().after(1000).create();
  SpreadsheetApp.getActiveSpreadsheet().toast(toastMessage, "WB Аналитика", 5);
}

/**
 * OzonSKUAndAnalytic - Аналитика Ozon
 * Вызывается триггерами в 03:23 и 08:14 (текущее расписание)
 *
 * ✅ АВТОНОМНАЯ ФУНКЦИЯ - работает независимо от порядка выполнения
 * ✅ Читает SKU из V (22) который заполняет OzonMain
 *
 * ЧИТАЕТ ИЗ:
 * - V (22): SKU Ozon (заполняется в OzonMain → updateProductsV2)
 *
 * ЗАПОЛНЯЕТ:
 * - I (9): Уход Мес ОЗОН
 * - J (10): Уход КВ
 * - L (12): Сумма заказов Мес ОЗОН
 */
function OzonSKUAndAnalytic(){
  fetchAndWriteAnalytics();      // Получение и запись аналитики
}

/**
 * maintainArticleColumn - Проверка артикулов
 * Вызывается триггером в 02:22
 * Работает без ошибок (0%)
 */
function maintainArticleColumn() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return;

  const column = 1; // Column A

  // Set format as text
  sheet.getRange(2, 1, lastRow - 1).setNumberFormat('@');

  let duplicates = {};
  let emptyRows = [];

  const range = sheet.getRange(2, column, lastRow - 1);
  const values = range.getValues().flat();

  values.forEach((val, i) => {
    const rowNumber = i + 2;

    // Track duplicates
    if (val) {
      const cleanVal = val.toString().trim();
      if (!duplicates[cleanVal]) {
        duplicates[cleanVal] = [];
      }
      duplicates[cleanVal].push(rowNumber);
    }

    // Check for empty
    if (!val || !val.toString().trim()) {
      emptyRows.push(rowNumber);
    }
  });

  // Log report
  const dupReport = Object.entries(duplicates)
    .filter(([_, rows]) => rows.length > 1)
    .map(([val, rows]) => `Артикул "${val}" повторяется ${rows.length} раз: строки ${rows.join(", ")}`)
    .join("\n");

  let report = [];
  if (dupReport) report.push("Дубликаты:\n" + dupReport);
  if (emptyRows.length) report.push("Пустые значения в строках: " + emptyRows.join(", "));

  if (report.length > 0) {
    Logger.log(report.join("\n\n"));
  } else {
    Logger.log("✅ Проверка завершена: дубликатов нет");
  }
}

// ============================================
// ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
// ============================================

/**
 * all() - Запустить все функции последовательно
 * Для ручного запуска всех операций
 */
function all(){
  maintainArticleColumn();
  OzonMain();
  WbMain();
  OzonSKUAndAnalytic();
  updateExternalAPIStocks(); // ✅ НОВОЕ: Feron и ETM API
}

/**
 * testAll() - Тестовый запуск всех функций
 */
function testAll(){
  Logger.log("🧪 Запуск тестирования всех функций...");
  all();
}

/**
 * runOzonOnly() - Запустить только Ozon функции
 */
function runOzonOnly(){
  Logger.log("🚀 Запуск Ozon функций...");
  maintainArticleColumn();
  OzonMain();
  OzonSKUAndAnalytic();
}

/**
 * runWbOnly() - Запустить только Wildberries функции
 */
function runWbOnly(){
  Logger.log("🚀 Запуск Wildberries функций...");
  WbMain();
}

/**
 * updateExternalAPIStocks() - Запустить только внешние API (Feron, ETM)
 * Заполняет колонки AI (35), AJ (36), AK (37), AL (38)
 */
function updateExternalAPIStocks(){
  Logger.log("🚀 Запуск внешних API (Feron, ETM)...");
  updateFeronStocks();       // AI, AJ, AK: Ферон склады
  updateETMStocksTrigger();   // AL: ЭТМ Самара (с автоперезапуском через триггеры)
}
