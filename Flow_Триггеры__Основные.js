// ============================================
// ГЛАВНЫЕ ФУНКЦИИ ДЛЯ ТРИГГЕРОВ
// Этот файл содержит функции которые вызывают старые триггеры
// ============================================

/**
 * Старое имя чужого триггера: добавление отсутствующих товаров Ozon в A/U.
 * Использует тот же lock и сохранённый курсор, что syncOfferIdWithProductId.
 */
function OzonMainCore_(){
  return syncOfferIdWithProductIdAlertCore_();
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
function WbMainCore_() {
  // Старый постоянный триггер также подхватывает незавершённый проход.
  const props = PropertiesService.getScriptProperties();
  if (Date.now() < Number(props.getProperty("wb_main_not_before"))) return;
  const step = Number(props.getProperty("wb_main_step")) || 1;
  clearWbTriggers();
  processWbStep(step);
}
function clearWbTriggers() {
  const triggers = ScriptApp.getProjectTriggers();
  for (let i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === "resumeWbMain") {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }
}
function resumeWbMainCore_(e) {
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
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) {
    Logger.log("WB Main: другой запуск занят; сохранённый шаг подхватит следующий триггер.");
    return;
  }
  const props = PropertiesService.getScriptProperties();
  try {
    if (Date.now() < Number(props.getProperty("wb_main_not_before"))) {
      Logger.log("WB Main: ожидаем разрешённое время продолжения.");
      return;
    }
    const savedStep = Number(props.getProperty("wb_main_step"));
    if (savedStep && savedStep !== step) step = savedStep;
    props.setProperty("wb_main_step", String(step));
    wbMainContext_ = { deadline: Date.now() + 180000, state: loadWbMainState_(step), step: step };
    Logger.log(`=== WB MAIN ШАГ ${step}/6 ===`);
    const handlers = [updateWBStocksFromStatisticsAPI, updateOrdersSummaryV2,
      updatePricesAndImages, main, updateWBAnalytics, updateWBWarehousesByName];
    if (!handlers[step - 1]) throw new Error("Некорректный шаг WB Main: " + step);
    handlers[step - 1]();
    clearWbMainState_();
    wbMainContext_.state = {};
    wbMainContext_.beforeRequest = null;
    if (step < handlers.length) {
      scheduleNextWbStep(step + 1, "WB: следующий шаг " + (step + 1) + "/6");
    } else {
      props.deleteProperty("wb_main_step");
      props.deleteProperty("wb_main_not_before");
      SpreadsheetApp.getActiveSpreadsheet().toast("Обновление Wildberries завершено", "Готово", 5);
    }
  } catch (err) {
    if (wbMainContext_ && Object.keys(wbMainContext_.state).length) {
      const safeState = !(err && err.wbMainYield) && wbMainContext_.beforeRequest
        ? JSON.parse(wbMainContext_.beforeRequest) : wbMainContext_.state;
      saveWbMainState_(safeState);
    }
    if (err && err.wbMainYield) {
      scheduleNextWbStep(step, "WB: продолжение шага " + step + "/6", err.delayMs);
      Logger.log("WB Main: прогресс сохранён; " + err.message);
      return;
    }
    Logger.log(`Ошибка WB Main на шаге ${step}: ${err}`);
    throw err;
  } finally {
    wbMainContext_ = null;
    lock.releaseLock();
  }
}
function scheduleNextWbStep(nextStep, toastMessage, delayMs) {
  const props = PropertiesService.getScriptProperties();
  props.setProperty("wb_main_step", String(nextStep));
  const delay = Math.max(60000, Number(delayMs) || 60000);
  props.setProperty("wb_main_not_before", String(Date.now() + delay));
  try {
    clearWbTriggers();
    ScriptApp.newTrigger("resumeWbMain").timeBased().after(delay).create();
  } catch (err) {
    // При лимите триггеров сохранённый шаг подхватит постоянный WbMain.
    if (!/too many triggers|слишком много триггер|maximum number of triggers/i.test(String(err))) throw err;
    Logger.log("WB: достигнут лимит триггеров; продолжение при следующем WbMain.");
  }
  SpreadsheetApp.getActiveSpreadsheet().toast(toastMessage, "WB Аналитика", 5);
}

/**
 * OzonSKUAndAnalytic - Аналитика Ozon
 * Вызывается триггерами в 03:23 и 08:14 (текущее расписание)
 *
 * ✅ АВТОНОМНАЯ ФУНКЦИЯ - работает независимо от порядка выполнения
 * Читает SKU из V (22), который обновляет maintainArticleColumn/updateProductsV2.
 *
 * ЧИТАЕТ ИЗ:
 * - V (22): SKU Ozon (maintainArticleColumn → updateProductsV2Core_)
 *
 * ЗАПОЛНЯЕТ:
 * - I (9): Уход Мес ОЗОН
 * - J (10): Уход КВ
 * - L (12): Сумма заказов Мес ОЗОН
 */
function OzonSKUAndAnalyticCore_(){
  try {
    return startFetchAndWriteAnalytics_();
  } catch (err) {
    Logger.log("❌ Ошибка в OzonSKUAndAnalytic: " + err);
    throw err;
  }
}


/**
 * Старое имя триггера: обогащение карточек Ozon по уже имеющимся артикулам.
 * Общий lock и курсор updateProductsV2 ограничивают проход 2.5 минутами.
 */
function maintainArticleColumnCore_() {
  return updateProductsV2AlertCore_();
}

/** Прежняя проверка колонки A доступна для отдельного ручного запуска. */
function auditArticleColumn() {
  return runWithTelegramAlertGAS_('auditArticleColumn', auditArticleColumnCore_);
}

function auditArticleColumnCore_() {
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

function OzonMain() {
  var args = arguments;
  return runWithTelegramAlertGAS_('OzonMain', function() {
    return OzonMainCore_.apply(null, args);
  });
}

function WbMain() {
  var args = arguments;
  return runWithTelegramAlertGAS_('WbMain', function() {
    return WbMainCore_.apply(null, args);
  });
}

function resumeWbMain() {
  var args = arguments;
  return runWithTelegramAlertGAS_('resumeWbMain', function() {
    return resumeWbMainCore_.apply(null, args);
  });
}

function OzonSKUAndAnalytic() {
  var args = arguments;
  return runWithTelegramAlertGAS_('OzonSKUAndAnalytic', function() {
    return OzonSKUAndAnalyticCore_.apply(null, args);
  });
}

function maintainArticleColumn() {
  var args = arguments;
  return runWithTelegramAlertGAS_('maintainArticleColumn', function() {
    return maintainArticleColumnCore_.apply(null, args);
  });
}
