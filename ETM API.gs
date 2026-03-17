// ============================================
// ETM API - Получение остатков со склада Стройкерамика
// Заполняет колонку AL (38)
//
// МЕТОД:
// 1. Используем артикул с параметром type=mnf (артикулы производителя)
// 2. Убираем суффикс -1 из артикулов (ETM не использует его)
// 3. Получаем остаток ТОЛЬКО со склада "Стройкерамика" с StoreType="rc"
//
// ВАЖНО:
// - ETM возвращает ДУБЛИрующие записи (rc и op с одинаковым остатком)
// - Берём только StoreType="rc" (распределительный центр) чтобы избежать задвоения
// - StoreType="op" (операционный склад) игнорируем
//
// ТИПЫ КОДОВ: cli (коды клиента), etm (коды ETM), mnf (артикулы производителя)
// ============================================

/**
 * Получить session-id для ETM API
 *
 * @returns {string|null} Session ID или null при ошибке
 */
function getETMSessionId() {
  const login = etmLogin();
  const password = etmPassword();
  const url = `https://ipro.etm.ru/api/v1/user/login?log=${encodeURIComponent(login)}&pwd=${encodeURIComponent(password)}`;

  const options = {
    method: "post",
    headers: {
      "Accept": "application/json"
    },
    muteHttpExceptions: true
  };

  try {
    const response = UrlFetchApp.fetch(url, options);
    const responseCode = response.getResponseCode();
    const responseText = response.getContentText();

    if (responseCode !== 200) {
      Logger.log(`❌ Ошибка авторизации ETM (${responseCode}): ${responseText}`);
      return null;
    }

    const data = JSON.parse(responseText);

    if (!data.data || !data.data.session) {
      Logger.log(`❌ Неверный формат ответа ETM авторизации`);
      return null;
    }

    const sessionId = data.data.session;
    Logger.log(`✅ Получен session-id ETM: ${sessionId}`);
    return sessionId;

  } catch (e) {
    Logger.log(`❌ Ошибка при авторизации ETM: ${e.message}`);
    return null;
  }
}

/**
 * Получить остаток конкретного артикула по складу Стройкерамика
 *
 * @param {string} article - Артикул товара (используется как артикул производителя)
 * @param {string} sessionId - Session ID от ETM API
 * @returns {number} Остаток на складе Стройкерамика (0 если не найден)
 */
function fetchETMStockForArticle(article, sessionId) {
  // Убираем суффикс -1 если он есть (ETM использует артикулы без -1)
  const etmArticle = article.endsWith('-1') ? article.slice(0, -2) : article;

  // Используем type=mnf для поиска по артикулам производителя
  const url = `https://ipro.etm.ru/api/v1/goods/${encodeURIComponent(etmArticle)}/remains?type=mnf&session-id=${sessionId}`;

  const options = {
    method: "get",
    headers: {
      "Accept": "application/json"
    },
    muteHttpExceptions: true
  };

  try {
    const response = UrlFetchApp.fetch(url, options);
    const responseCode = response.getResponseCode();

    if (responseCode !== 200) {
      // Товар не найден
      return 0;
    }

    const responseText = response.getContentText();
    const data = JSON.parse(responseText);

    if (!data.data || !data.data.InfoStores) {
      return 0;
    }

    // ИЩЕМ только склад "Стройкерамика" с типом "rc" (распределительный центр)
    // StoreType "op" дублирует остатки, поэтому берём только "rc"
    let stock = 0;
    data.data.InfoStores.forEach(store => {
      const storeName = store.StoreName || "";
      const storeType = store.StoreType || "";
      // Проверяем, что это Стройкерамика И тип "rc" (распределительный центр)
      if (storeName.toLowerCase().includes('стройкерамика') && storeType === 'rc') {
        stock += (store.StoreQuantRem || store.StockRem || 0);
      }
    });

    return stock;

  } catch (e) {
    // Ошибка сети или парсинга - возвращаем 0
    return 0;
  }
}

/**
 * Обновить остатки со склада ETM Стройкерамика
 *
 * Заполняет:
 * - AL (38): ЭТМ Стройкерамика
 *
 * АЛГОРИТМ:
 * 1. Получает session-id
 * 2. Для каждого артикула из колонки A делает запрос с type=mnf
 * 3. Берёт остаток только со склада "Стройкерамика"
 * 4. Записывает результат в колонку AL батчами
 * 5. Контролирует время выполнения, чтобы не превысить лимит Google (6 мин)
 *
 * МОЖНО ПЕРЕЗАПУСКАТЬ: продолжит с первой пустой ячейки в AL
 *
 * @param {number} startRow - Стартовая строка (по умолчанию 2)
 * @param {number} batchSize - Размер батча (по умолчанию 50, для частого сохранения)
 * @param {number} maxArticles - Макс. артикулов за запуск (по умолчанию 1000)
 * @param {boolean} forceStart - Принудительно начать с startRow (для циклического обновления)
 * @returns {number} Количество фактически обработанных артикулов
 */
function updateETMStocks(startRow = 2, batchSize = 50, maxArticles = 1000, forceStart = false) {
  const START_TIME = Date.now();
  const MAX_EXECUTION_TIME = 4.5 * 60 * 1000; // 4.5 минуты предел для безопасности (Google API limit = 6 min)

  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет артикулов для обработки");
    return 0;
  }

  Logger.log("=== ОБНОВЛЕНИЕ ОСТАТКОВ ETM СТРОЙКЕРАМИКА ===");
  Logger.log("📋 Используем артикулы производителя (type=mnf)");
  Logger.log("📊 Получаем остатки только со склада Стройкерамика");
  Logger.log(`⏱️  Макс. артикулов за запуск: ${maxArticles} (batch: ${batchSize}, ~2.5 артикула/сек)`);

  // Шаг 1: Найти первую пустую ячейку в AL (38)
  // Если forceStart=true, пропускаем поиск пустых ячеек (для циклического обновления)
  if (startRow === 2 && !forceStart) {
    const existingData = sheet.getRange(2, 38, lastRow - 1, 1).getValues().flat();
    const firstEmptyIndex = existingData.findIndex(cell => cell === "" || cell === null || cell === undefined);

    if (firstEmptyIndex !== -1) {
      startRow = 2 + firstEmptyIndex;
      Logger.log(`🔄 Найден прогресс: продолжаем со строки ${startRow}`);
    } else {
      Logger.log("✅ Все ячейки AL уже заполнены!");
      return 0;
    }
  } else if (forceStart) {
    Logger.log(`🔄 Принудительное обновление с строки ${startRow} (циклическое обновление)`);
  }

  // Шаг 2: Ограничиваем количество артикулов для этого запуска
  const endRow = Math.min(startRow + maxArticles - 1, lastRow);

  // Шаг 3: Авторизация
  const sessionId = getETMSessionId();
  if (!sessionId) {
    Logger.log("❌ Не удалось авторизоваться в ETM API");
    return 0;
  }

  // Шаг 4: Получить список артикулов (ограниченный)
  const articlesRange = sheet.getRange(startRow, 1, endRow - startRow + 1, 1);
  const articles = articlesRange.getValues().flat();

  Logger.log(`📋 Артикулов для обработки: ${articles.length} (строки ${startRow}-${endRow})`);
  Logger.log(`📋 Всего осталось: ${lastRow - startRow + 1} (строки ${startRow}-${lastRow})`);

  // Шаг 5: Обрабатывать батчами с СРАЗУ ЖЕ записью в таблицу
  const totalBatches = Math.ceil(articles.length / batchSize);
  let totalSuccessCount = 0;
  let totalFoundCount = 0;
  let totalProcessedArticles = 0;

  let timeLimitReached = false;

  for (let batch = 0; batch < totalBatches; batch++) {
    if (timeLimitReached) break;

    const startIdx = batch * batchSize;
    const endIdx = Math.min(startIdx + batchSize, articles.length);
    const batchArticles = articles.slice(startIdx, endIdx);
    const targetRow = startRow + startIdx;

    Logger.log(`\n[${batch + 1}/${totalBatches}] Строки ${targetRow}-${targetRow + batchArticles.length - 1}...`);

    // Получаем остатки для батча (без задержек)
    const batchStocks = [];
    let batchSuccessCount = 0;
    let batchFoundCount = 0;

    for (let i = 0; i < batchArticles.length; i++) {
      // Проверка таймаута ПЕРЕД каждым запросом, чтобы успеть записать батч
      if (Date.now() - START_TIME > MAX_EXECUTION_TIME) {
        Logger.log(`⚠️ Превышен лимит времени (4.5 мин). Остановка на строке ${targetRow + i}.`);
        timeLimitReached = true;
        break; // Прерываем обработку артикулов внутри батча
      }

      const article = String(batchArticles[i]).trim();

      if (!article) {
        batchStocks.push([""]);
        totalProcessedArticles++;
        continue;
      }

      // БЕЗ ЗАДЕРЖЕК - максимальная скорость
      const stock = fetchETMStockForArticle(article, sessionId);
      batchStocks.push([stock]);

      if (stock > 0) {
        batchSuccessCount++;
        totalSuccessCount++;
      }

      // Считаем найденные (включая с остатком 0)
      if (stock >= 0) {
        batchFoundCount++;
        totalFoundCount++;
      }

      totalProcessedArticles++;

      // Логируем прогресс каждые 25 артикулов
      if ((i + 1) % 25 === 0) {
        Logger.log(`   Обработано ${i + 1}/${batchArticles.length} в батче...`);
      }
    }

    // Если сформировали хоть что-то - записываем в таблицу
    if (batchStocks.length > 0) {
      sheet.getRange(targetRow, 38, batchStocks.length, 1).setValues(batchStocks);
      Logger.log(`   ✅ Батч записан (${batchStocks.length} шт). Найдено в ETM: ${batchFoundCount}.`);
    }
  }

  // Финальная статистика
  Logger.log("\n=== ЗАВЕРШЕНО ЗАПУСК ===");
  Logger.log(`✅ Обработано артикулов: ${totalProcessedArticles}`);
  Logger.log(`✅ Найдено в ETM: ${totalFoundCount}`);
  Logger.log(`✅ Найдено товаров с остатком: ${totalSuccessCount}`);
  Logger.log(`📊 Процент найденных: ${totalProcessedArticles > 0 ? ((totalFoundCount / totalProcessedArticles) * 100).toFixed(2) : 0}%`);

  const executionSeconds = ((Date.now() - START_TIME) / 1000).toFixed(1);
  Logger.log(`⏱️ Время выполнения: ${executionSeconds} сек`);
  // Изменил сообщение, чтобы не предлагать создавать бесконечную цепочку триггеров
  Logger.log(`💡 Для повторного запуска используйте функцию: updateETMStocksOnce()`);

  return totalProcessedArticles;
}

/**
 * Тестовая функция: проверить конкретный артикул в ETM
 *
 * @param {string} article - Артикул для проверки
 */
function testETMArticle(article) {
  Logger.log(`=== ПРОВЕРКА АРТИКУЛА ${article} В ETM ===`);

  const sessionId = getETMSessionId();
  if (!sessionId) {
    Logger.log("❌ Не удалось авторизоваться");
    return;
  }

  const stock = fetchETMStockForArticle(article, sessionId);

  if (stock > 0) {
    Logger.log(`✅ Остаток на Стройкерамике: ${stock}`);
  } else {
    Logger.log(`❌ Артикул ${article} не найден или остаток = 0`);
  }
}

/**
 * Тестовая функция: проверить несколько артикулов
 */
function testETMArticles() {
  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ТЕСТ ETM API (Стройкерамика)                                        ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");
  Logger.log("");

  // Тестовые артикулы из списка (БЕЗ суффикса -1, код сам уберёт его)
  testETMArticle("41580-1");           // Ожидается ~190
  testETMArticle("MKP42-N-02-30-20-1"); // Ожидается ~1362
  testETMArticle("MAD22-5-016-C-30-1");  // Ожидается ~6027
  testETMArticle("UZA-11-D01-D10-1");    // Ожидается ~8980
  testETMArticle("RBD-80-1");           // Ожидается ~703
  testETMArticle("YND10-4-15-125-1");   // Ожидается ~444

  Logger.log("");
  Logger.log("💡 Примечание: суффикс -1 автоматически убирается перед запросом к ETM API");
  Logger.log("════════════════════════════════════════════════════════════════════════");
}

/**
 * Автоматическое обновление ETM с продолжением (циклическое в одном скрипте)
 * Запускает updateETMStocks несколько раз до завершения без триггеров.
 * Сохраняет прогресс в PropertiesService.
 *
 * @param {number} maxRuns - Максимальное количество запусков (по умолчанию 3)
 */
function updateETMStocksAuto(maxRuns = 3) {
  let runCount = 0;

  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   АВТОМАТИЧЕСКОЕ ОБНОВЛЕНИЕ ETM (с продолжением)                     ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");

  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();
  const props = PropertiesService.getScriptProperties();

  while (runCount < maxRuns) {
    let startRow = parseInt(props.getProperty('ETM_START_ROW'), 10);
    if (isNaN(startRow) || startRow < 2) {
      startRow = 2;
    }

    if (startRow > lastRow) {
      Logger.log(`✅ Достигнут конец таблицы. Начинаем новый цикл со строки 2.`);
      startRow = 2;
    }

    runCount++;
    Logger.log(`\n🔄 ЗАПУСК #${runCount} (строка ${startRow})`);

    const maxArticles = 1000;

    // Запускаем обновление с forceStart=true
    const processedCount = updateETMStocks(startRow, 50, maxArticles, true);

    if (processedCount === 0) {
      Logger.log("⚠️ Не было обработано ни одного артикула. Прерывание цикла.");
      break;
    }

    const nextRow = startRow + processedCount;
    props.setProperty('ETM_START_ROW', nextRow.toString());

    if (nextRow > lastRow) {
      Logger.log(`\n🔄 Запуск #${runCount} достиг конца таблицы!`);
    }
  }

  if (runCount >= maxRuns) {
    Logger.log(`\n⚠️  Выполнено ${maxRuns} запусков (максимум).`);
    Logger.log(`💡 Для продолжения запустите: updateETMStocksAuto()`);
  }

  Logger.log("\n════════════════════════════════════════════════════════════════════════\n");
}

/**
 * Обновление ETM однократно от первой пустой ячейки до последней строки
 * Не создает триггеры, обрабатывает только один раз
 */
function updateETMStocksOnce() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет артикулов для обработки");
    return 0;
  }

  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ОДНОКРАТНОЕ ОБНОВЛЕНИЕ ETM (без триггеров)                          ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");

  // Находим первую пустую ячейку в колонке AL (38)
  const existingData = sheet.getRange(2, 38, lastRow - 1, 1).getValues().flat();
  const firstEmptyIndex = existingData.findIndex(cell => cell === "" || cell === null || cell === undefined);

  let startRow;
  if (firstEmptyIndex !== -1) {
    startRow = 2 + firstEmptyIndex;
    Logger.log(`🔄 Найден прогресс: продолжаем со строки ${startRow}`);
  } else {
    Logger.log("✅ Все ячейки AL уже заполнены!");
    return 0;
  }

  // Запускаем обновление до конца таблицы (или до лимита времени)
  const maxArticles = lastRow - startRow + 1; // Обрабатываем до конца таблицы
  const processedCount = updateETMStocks(startRow, 50, maxArticles, false);

  Logger.log(`\n🏁 Обработка завершена. Обработано: ${processedCount} артикулов`);
  Logger.log("💡 Для повторного запуска вызовите функцию updateETMStocksOnce()");
  Logger.log("════════════════════════════════════════════════════════════════════════\n");

  return processedCount;
}

/**
 * Автоматическое обновление ETM (однократное выполнение без триггеров)
 * Обрабатывает все незаполненные ячейки до конца таблицы
 */
function updateETMStocksTrigger() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет артикулов для обработки");
    return;
  }

  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ОДНОКРАТНОЕ ОБНОВЛЕНИЕ ETM (без создания новых триггеров)           ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");

  // Находим первую пустую ячейку в колонке AL (38)
  const existingData = sheet.getRange(2, 38, lastRow - 1, 1).getValues().flat();
  const firstEmptyIndex = existingData.findIndex(cell => cell === "" || cell === null || cell === undefined);

  let startRow;
  if (firstEmptyIndex !== -1) {
    startRow = 2 + firstEmptyIndex;
    Logger.log(`🔄 Найден прогресс: продолжаем со строки ${startRow}`);
  } else {
    Logger.log("✅ Все ячейки AL уже заполнены!");
    return;
  }

  // Запускаем обновление до конца таблицы
  const maxArticles = lastRow - startRow + 1; // Обрабатываем до конца таблицы
  const processedCount = updateETMStocks(startRow, 50, maxArticles, false);

  Logger.log(`\n🏁 Обработка завершена. Обработано: ${processedCount} артикулов`);
  Logger.log("💡 Функция выполнена однократно без создания новых триггеров");
  Logger.log("════════════════════════════════════════════════════════════════════════\n");
}

/**
 * Удалить все триггеры функции updateETMStocksTrigger
 */
function deleteETMTriggers() {
  const triggers = ScriptApp.getProjectTriggers();
  let deletedCount = 0;

  triggers.forEach(trigger => {
    if (trigger.getHandlerFunction() === "updateETMStocksTrigger") {
      ScriptApp.deleteTrigger(trigger);
      deletedCount++;
    }
  });

  if (deletedCount > 0) {
    Logger.log(`🗑️  Удалено старых триггеров: ${deletedCount}`);
  }
}

/**
 * Отменить все триггеры ETM (для остановки автоматического обновления)
 */
function stopETMAutoUpdate() {
  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ОСТАНОВКА АВТООБНОВЛЕНИЯ ETM                                         ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");

  const triggers = ScriptApp.getProjectTriggers();
  let deletedCount = 0;

  triggers.forEach(trigger => {
    if (trigger.getHandlerFunction() === "updateETMStocksTrigger") {
      ScriptApp.deleteTrigger(trigger);
      deletedCount++;
    }
  });

  if (deletedCount > 0) {
    Logger.log(`✅ Удалено триггеров: ${deletedCount}`);
    Logger.log("✅ Автообновление ETM остановлено");
  } else {
    Logger.log("ℹ️  Активных триггеров ETM не найдено");
  }

  // Очищаем прогресс
  const props = PropertiesService.getScriptProperties();
  props.deleteProperty('ETM_START_ROW');
  Logger.log("✅ Прогресс обновления ETM сброшен (начнётся со строки 2)");

  Logger.log("════════════════════════════════════════════════════════════════════════\n");
}