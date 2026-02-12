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
 *
 * МОЖНО ПЕРЕЗАПУСКАТЬ: продолжит с первой пустой ячейки в AL
 *
 * @param {number} startRow - Стартовая строка (по умолчанию 2)
 * @param {number} batchSize - Размер батча (по умолчанию 50, для частого сохранения)
 * @param {number} maxArticles - Макс. артикулов за запуск (по умолчанию 150, ~2.5 артикула/сек)
 * @param {boolean} forceStart - Принудительно начать с startRow (для циклического обновления)
 */
function updateETMStocks(startRow = 2, batchSize = 50, maxArticles = 150, forceStart = false) {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет артикулов для обработки");
    return;
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
      return;
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
    return;
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

  for (let batch = 0; batch < totalBatches; batch++) {
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
      const article = String(batchArticles[i]).trim();

      if (!article) {
        batchStocks.push([""]);
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

      // Логируем прогресс каждые 25 артикулов (для батча 50 будет 2 лога)
      if ((i + 1) % 25 === 0) {
        Logger.log(`   Обработано ${i + 1}/${batchArticles.length} в батче...`);
      }
    }

    // СРАЗУ ЖЕ записываем батч в таблицу (прогресс сохраняется!)
    sheet.getRange(targetRow, 38, batchStocks.length, 1).setValues(batchStocks);

    Logger.log(`   ✅ Батч записан. Найдено в ETM: ${batchFoundCount}, с остатком: ${batchSuccessCount}`);
  }

  // Финальная статистика
  Logger.log("\n=== ЗАВЕРШЕНО ===");
  Logger.log(`✅ Обработано артикулов: ${articles.length}`);
  Logger.log(`✅ Найдено в ETM: ${totalFoundCount}`);
  Logger.log(`✅ Найдено товаров с остатком: ${totalSuccessCount}`);
  Logger.log(`📊 Процент найденных: ${totalFoundCount > 0 ? ((totalFoundCount / articles.length) * 100).toFixed(2) : 0}%`);

  const remainingArticles = lastRow - endRow;
  if (remainingArticles > 0) {
    Logger.log(`\n💡 Осталось обработать: ${remainingArticles} артикулов`);
    Logger.log(`💡 Следующая строка: ${endRow + 1}`);
    Logger.log(`💡 Запустите updateETMStocks(${endRow + 1}) снова для продолжения`);
  } else {
    Logger.log(`\n🎉 ВСЕ АРТИКУЛЫ ОБРАБОТАНЫ!`);
  }
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
 * Автоматическое обновление ETM с продолжением (циклическое)
 * Запускает updateETMStocks несколько раз до завершения
 *
 * После завершения обработки всех строк начинает заново с первой строки.
 *
 * @param {number} maxRuns - Максимальное количество запусков (по умолчанию 3)
 */
function updateETMStocksAuto(maxRuns = 3) {
  let startRow = 2;
  let runCount = 0;
  let forceStart = false;  // Флаг принудительного обновления с начала

  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   АВТОМАТИЧЕСКОЕ ОБНОВЛЕНИЕ ETM (с продолжением)                     ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");

  while (runCount < maxRuns) {
    runCount++;
    Logger.log(`\n🔄 ЗАПУСК #${runCount} (строка ${startRow})`);

    const sheet = mainSheet();
    const lastRow = sheet.getLastRow();

    if (startRow > lastRow) {
      Logger.log("✅ Все артикулы обработаны!");
      break;
    }

    // Сохраняем начальную строку для этого запуска
    const runStartRow = startRow;

    // Запускаем обновление (с forceStart если это циклическое обновление)
    if (forceStart) {
      Logger.log(`🔄 Принудительное обновление (циклическое)`);
    }
    updateETMStocks(startRow, 50, 150, forceStart);
    forceStart = false;  // Сбрасываем флаг после первого запуска

    // Находим новую начальную строку (первая пустая после последнего запуска)
    const newData = sheet.getRange(runStartRow, 38, lastRow - runStartRow + 1, 1).getValues().flat();
    const firstEmptyInNewData = newData.findIndex(cell => cell === "" || cell === null || cell === undefined);

    if (firstEmptyInNewData === -1) {
      // Все ячейки заполнены - начинаем заново с первой строки (циклическое обновление)
      Logger.log(`\n🔄 Запуск #${runCount} завершил обработку всех артикулов!`);
      Logger.log(`🔄 Сбрасываем на начало таблицы для следующего запуска...`);
      startRow = 2;
      forceStart = true;  // Следующий запуск будет принудительным
    } else {
      startRow = runStartRow + firstEmptyInNewData;
    }

    // Проверяем, достигли ли мы конца
    if (startRow > lastRow) {
      Logger.log(`\n🔄 Запуск #${runCount} достиг конца таблицы!`);
      Logger.log(`🔄 Сбрасываем на начало для следующего запуска...`);
      startRow = 2;
      forceStart = true;  // Следующий запуск будет принудительным
    }
  }

  if (runCount >= maxRuns) {
    const sheet = mainSheet();
    const lastRow = sheet.getLastRow();
    Logger.log(`\n⚠️  Выполнено ${maxRuns} запусков (максимум).`);
    if (startRow === 2) {
      Logger.log(`💡 Таблица обновляется циклически. Следующий запуск продолжит с начала.`);
    } else {
      Logger.log(`💡 Для продолжения запустите: updateETMStocks(${startRow})`);
      Logger.log(`💡 Или запустите снова: updateETMStocksAuto()`);
    }
  }

  Logger.log("\n════════════════════════════════════════════════════════════════════════\n");
}

/**
 * Автоматическое обновление ETM с триггерами (циклическое)
 * Обрабатывает порцию артикулов и создаёт триггер для продолжения
 *
 * После завершения обработки всех строк начинает заново с первой строки.
 * Таким образом обеспечивается постоянное циклическое обновление данных.
 *
 * Использование: запустите один раз, функция будет перезапускать себя через триггеры
 *
 * @param {number} startRow - Стартовая строка (для внутреннего использования)
 */
function updateETMStocksTrigger(startRow = 2) {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет артикулов для обработки");
    return;
  }

  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ОБНОВЛЕНИЕ ETM С АВТОПЕРЕЗАПУСКОМ (триггеры)                       ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");

  // Удаляем старые триггеры этой функции
  deleteETMTriggers();

  // Проверяем, есть ли ещё необработанные артикулы
  const newData = sheet.getRange(2, 38, lastRow - 1, 1).getValues().flat();
  const firstEmptyIndex = newData.findIndex(cell => cell === "" || cell === null || cell === undefined);

  let forceStart = false;
  if (firstEmptyIndex === -1) {
    // Все ячейки заполнены - это циклическое обновление
    forceStart = true;
    Logger.log(`🔄 Циклическое обновление: начинаем заново с строки 2`);
  }

  // Запускаем обновление с ограничением 150 артикулов за раз (укладываемся в 5 минут)
  updateETMStocks(startRow, 50, 150, forceStart);

  // Проверяем, есть ли ещё необработанные артикулы (после обновления)
  const updatedData = sheet.getRange(2, 38, lastRow - 1, 1).getValues().flat();
  const newFirstEmptyIndex = updatedData.findIndex(cell => cell === "" || cell === null || cell === undefined);

  if (newFirstEmptyIndex !== -1) {
    // Есть ещё необработанные артикулы - создаём триггер
    const nextRow = 2 + newFirstEmptyIndex;
    Logger.log(`\n⏰ Создаю триггер для продолжения со строки ${nextRow}...`);

    ScriptApp.newTrigger("updateETMStocksTrigger")
      .timeBased()
      .after(1000 * 60) // Через 1 минуту
      .create();

    Logger.log(`✅ Триггер создан. Следующий запуск через 1 минуту.`);
  } else {
    // Все ячейки заполнены - продолжаем циклическое обновление
    Logger.log(`\n🔄 Все артикулы обработаны. Следующий запуск обновит данные заново...`);

    ScriptApp.newTrigger("updateETMStocksTrigger")
      .timeBased()
      .after(1000 * 60) // Через 1 минуту
      .create();

    Logger.log(`✅ Триггер создан. Следующий запуск начнётся с строки 2.`);
  }

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

  Logger.log("════════════════════════════════════════════════════════════════════════\n");
}

