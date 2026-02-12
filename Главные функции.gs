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
  syncOfferIdWithProductId();  // Синхронизация ID
  updateProductsV2();          // ВАЖНО: Используем V2 версию с Бренд и Модель
  updateStockFBO();             // Остатки FBO (F, 6) - ИСПРАВЛЕНО: суммирует все FBO
  updateAllFBSStocks();         // Остатки FBS (G, 7) - ИСПРАВЛЕНО: сумма всех FBS
  getOzonPricesOptimized();    // Цены
  // updateSkuByProductId();      // ❌ УБРАНО: updateProductsV2() уже заполняет V (22) SKU!
  getStocksByWarehouseFBS();   // FBS склад Москва (H, 8)
  fetchAndUpdateAll();         // ✅ НОВОЕ: FBS склады (AB-AH, 28-34) - 7 складов
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
  updateWBStocksFromStatisticsAPI(); // Остаток ФБО ВБ (O, 15) - ИСПРАВЛЕНО
  // importStocksWithImages();        // ❌ УБРАНО: перезаписывала L (12) "Сумма заказов Мес ОЗОН"
  updateOrdersSummaryV2();           // Сумма заказов Мес ВБ (N, 14)
  updatePricesAndImages();           // Цены ВБ (M, 13) и картинки
  main();                            // Основная функция ВБ: O (15), P (16), Q (17)
  updateWBArticles();                // Артикулы WB (T, 20)
  updateWBAnalytics();               // Аналитика WB: Уход Мес/КВ (R, 18) (S, 19)
  updateWBWarehousesByName();        // Склады по warehouseName: Z (26), AA (27) - НОВОЕ
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
