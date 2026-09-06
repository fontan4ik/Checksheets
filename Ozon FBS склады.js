/**
 * OZON FBS СКЛАДЫ - Множественные FBS склады
 *
 * Заполняет колонки:
 * - AB (28): ФЕРОН ФБС
 * - AC (29): ЭТМ САМАРА
 * - AD (30): РЕЗЕРВ
 * - AE (31): НТЦ СКЛАД
 * - AF (32): ПОДОРОЖНИК ФБС
 * - AG (33): Арлайт Москва
 * - AH (34): GAUSS MSK
 *
 * Алгоритм:
 * 1. ШАГ 1 (один раз): fetchAndSaveWarehouses() - получить список складов через /v2/warehouse/list
 * 2. ШАГ 2 (основной): updateAllFBSWarehouses() - получить остатки по всем складам через /v2/product/info/stocks-by-warehouse/fbs
 *
 * Официальная документация Ozon Seller API:
 * - https://docs.ozon.ru/api/seller/#v2/warehouse/list
 * - https://docs.ozon.ru/api/seller/#v2/product/info/stocks-by-warehouse/fbs
 */

// ============================================
// КОНФИГУРАЦИЯ СКЛАДОВ
// ============================================

/**
 * Список целевых складов для поиска
 * Имена должны совпадать (полностью или частично) с названиями из API
 */
const TARGET_WAREHOUSES = [
  { name: "ФЕРОН ФБС", column: 28, letter: "AB" },
  { name: "ЭТМ САМАРА", column: 29, letter: "AC" },
  { name: "РЕЗЕРВ", column: 30, letter: "AD" },
  { name: "НТЦ СКЛАД", column: 31, letter: "AE" },
  { name: "ПОДОРОЖНИК ФБС", column: 32, letter: "AF" },
  { name: "Арлайт Москва", column: 33, letter: "AG" },
  { name: "GAUSS MSK", column: 34, letter: "AH" }
];

// ============================================
// ШАГ 1: ПОЛУЧЕНИЕ И СОХРАНЕНИЕ СПИСКА СКЛАДОВ
// ============================================

/**
 * ШАГ 1: Получить список всех складов и сохранить в PropertiesService
 *
 * Выполните ЭТУ ФУНКЦИЮ ПЕРВОЙ один раз!
 * Результат: список складов сохранится в PropertiesService под ключом "ozon_warehouses"
 *
 * Официальный endpoint: POST /v1/warehouse/list
 * Документация: https://docs.ozon.ru/api/seller/#v1/warehouse/list
 *
 * Формат запроса:
 * {
 *   "limit": 200,           // опционально, макс. количество результатов (МАКС: 200!)
 *   "offset": 0,            // опционально, смещение
 *   "status": "ACTIVE"      // опционально, статус склада
 * }
 *
 * Формат ответа:
 * {
 *   "result": [
 *     {
 *       "warehouse_id": 1234567890,  // ID склада (число)
 *       "name": "Название склада",    // название (строка)
 *       "type": "FBS",               // тип склада (строка)
 *       "status": "ACTIVE"           // статус (строка)
 *     }
 *   ]
 * }
 */
function fetchAndSaveWarehouses() {
  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ШАГ 1: ПОЛУЧЕНИЕ СПИСКА СКЛАДОВ OZON FBS                            ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");

  const url = "https://api-seller.ozon.ru/v2/warehouse/list";

  const limit = 200;
  const maxPages = 10;

  let allWarehouses = [];
  let cursor = "";
  let pageCount = 0;
  let lastRequestTime = Date.now() - 1000 / RPS();

  Logger.log("\n📤 Загрузка списка складов (Ozon v2 API)...");

  try {
    // Цикл пагинации
    while (pageCount < maxPages) {
      pageCount++;

      // Rate limiting
      lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

      const payload = {
        "limit": limit
      };
      if (cursor) {
        payload.cursor = cursor;
      }

      const options = {
        "method": "post",
        "contentType": "application/json",
        "headers": ozonHeaders(),
        "payload": JSON.stringify(payload),
        "muteHttpExceptions": true
      };

      if (pageCount === 1 || pageCount % 5 === 0) {
        Logger.log(`   📤 Страница ${pageCount}...`);
      }

      const response = retryFetch(url, options);

      if (!response) {
        Logger.log(`❌ Не удалось получить данные (страница ${pageCount})`);
        break;
      }

      const responseCode = response.getResponseCode();
      const responseText = response.getContentText();

      if (responseCode === 200) {
        const data = JSON.parse(responseText);
        const warehouses = data.warehouses || data.result || [];

        if (Array.isArray(warehouses) && warehouses.length > 0) {
          allWarehouses.push(...warehouses);

          if (data.has_next && data.cursor) {
            cursor = data.cursor;
          } else {
            Logger.log(`   ✅ Загружены все склады (${allWarehouses.length} складов)`);
            break;
          }
        } else {
          break;
        }
      } else {
        Logger.log(`   ❌ Ошибка API на странице ${pageCount}: код ${responseCode}`);
        Logger.log(`   Response: ${responseText.substring(0, 300)}`);
        break;
      }
    }

    if (allWarehouses.length === 0) {
      Logger.log("\n❌ Не удалось получить склады");
      return null;
    }

    Logger.log(`\n✅ Всего загружено складов: ${allWarehouses.length}`);

    // Сохраняем в PropertiesService
    const scriptProperties = PropertiesService.getScriptProperties();
    scriptProperties.setProperty("ozon_warehouses", JSON.stringify(allWarehouses));

    Logger.log(`✅ Список складов сохранён в PropertiesService (ключ: "ozon_warehouses")`);

    // Выводим первые 10 складов для проверки
    Logger.log("\n📋 Первые 10 складов:");
    allWarehouses.slice(0, 10).forEach((wh, i) => {
      Logger.log(`   ${i + 1}. ID: ${wh.warehouse_id}, "${wh.name}", тип: ${wh.type || "N/A"}`);
    });

    // Ищем целевые склады
    const found = findTargetWarehouses(allWarehouses);

    Logger.log(`\n🎯 Найдено целевых складов: ${found.length}/${TARGET_WAREHOUSES.length}`);

    if (found.length > 0) {
      Logger.log("\n✅ СОВПАДЕНИЯ:");
      found.forEach(item => {
        Logger.log(`   ✅ "${item.warehouseName}" (ID: ${item.warehouseId}) → ${item.letter} (${item.column})`);
      });
    }

    const missing = TARGET_WAREHOUSES.length - found.length;
    if (missing > 0) {
      Logger.log(`\n⚠️  НЕ НАЙДЕНО: ${missing} складов`);
      Logger.log("   Проверьте точность названий в TARGET_WAREHOUSES");
    }

    Logger.log("\n════════════════════════════════════════════════════════════════════════\n");

    return allWarehouses;
  } catch (e) {
    Logger.log(`❌ Исключение: ${e.message}`);
    Logger.log(e.stack);
    return null;
  }
}

/**
 * Вспомогательная функция: поиск целевых складов в массиве
 *
 * @param {Array} warehouses - массив складов из API
 * @returns {Array} - массив найденных складов с метаданными
 */
function findTargetWarehouses(warehouses) {
  // ИСПРАВЛЕНО: проверяем что warehouses существует и является массивом
  if (!warehouses || !Array.isArray(warehouses)) {
    Logger.log("❌ Ошибка: warehouses не передан или не является массивом");
    return [];
  }

  const found = [];
  const usedWarehouseIds = new Set(); // ИСПРАВЛЕНО: отслеживаем использованные ID
  const duplicates = []; // ИСПРАВЛЕНО: отслеживаем дубликаты

  TARGET_WAREHOUSES.forEach(target => {
    // Ищем склад (полное совпадение ИЛИ частичное без учета регистра)
    // ИСПРАВЛЕНО: проверяем что warehouse_id еще не использован
    const warehouse = warehouses.find(wh =>
      (wh.name === target.name ||
        (wh.name && wh.name.toLowerCase().includes(target.name.toLowerCase())))
    );

    if (warehouse) {
      // ИСПРАВЛЕНО: проверяем на дубликаты warehouse_id
      if (usedWarehouseIds.has(warehouse.warehouse_id)) {
        duplicates.push({
          targetName: target.name,
          warehouseId: warehouse.warehouse_id,
          warehouseName: warehouse.name,
          column: target.column,
          letter: target.letter
        });
      } else {
        usedWarehouseIds.add(warehouse.warehouse_id); // помечаем как использованный
        found.push({
          targetName: target.name,
          warehouseId: warehouse.warehouse_id,
          warehouseName: warehouse.name,
          column: target.column,
          letter: target.letter
        });
      }
    }
  });

  // ИСПРАВЛЕНО: выводим предупреждение о дубликатах
  if (duplicates.length > 0) {
    Logger.log("\n⚠️  ОБНАРУЖЕНЫ ДУБЛИКАТЫ warehouse_id:");
    duplicates.forEach(d => {
      Logger.log(`   ❌ "${d.targetName}" → ${d.letter} (${d.column}) использует warehouse_id ${d.warehouseId}`);
      Logger.log(`      Этот же ID уже использован для другого склада!`);
    });
    Logger.log("   💡 Возможные решения:");
    Logger.log("      1. Проверьте точность названий в TARGET_WAREHOUSES");
    Logger.log("      2. Используйте строгое совпадение (===) вместо includes()");
    Logger.log("");
  }

  return found;
}

/**
 * Проверить сохранённые склады (диагностика)
 */
function checkSavedWarehouses() {
  const scriptProperties = PropertiesService.getScriptProperties();
  const warehousesJson = scriptProperties.getProperty("ozon_warehouses");

  if (!warehousesJson) {
    Logger.log("❌ Список складов не найден в PropertiesService");
    Logger.log("   Сначала выполните: fetchAndSaveWarehouses()");
    return null;
  }

  let warehouses;
  try {
    warehouses = JSON.parse(warehousesJson);
  } catch (e) {
    Logger.log("❌ Ошибка парсинга списка складов: " + e.message);
    return null;
  }

  if (!Array.isArray(warehouses)) {
    Logger.log("❌ Неверный формат списка складов (не массив)");
    return null;
  }

  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ПРОВЕРКА СОХРАНЁННЫХ СКЛАДОВ                                        ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");

  Logger.log(`\n📦 Всего складов сохранено: ${warehouses.length}`);

  // Ищем целевые склады (с проверкой на дубликаты)
  const found = findTargetWarehouses(warehouses);

  Logger.log(`\n🎯 Найдено целевых складов: ${found.length}/${TARGET_WAREHOUSES.length}`);

  if (found.length > 0) {
    Logger.log("\n✅ СОВПАДЕНИЯ:");
    found.forEach(item => {
      Logger.log(`   ✅ "${item.warehouseName}" (ID: ${item.warehouseId}) → ${item.letter} (${item.column})`);
    });

    // ИСПРАВЛЕНО: проверяем на уникальные warehouse_id
    const uniqueIds = new Set(found.map(f => f.warehouseId));
    if (uniqueIds.size < found.length) {
      Logger.log("\n⚠️  ВНИМАНИЕ: Найдено дубликатов warehouse_id!");
      Logger.log(`   Уникальных ID: ${uniqueIds.size}, Всего сопоставлений: ${found.length}`);
      Logger.log("   Это означает что разные колонки используют один и тот же склад!");
    }
  }

  const missing = TARGET_WAREHOUSES.filter(t =>
    !found.some(f => f.targetName === t.name)
  );

  if (missing.length > 0) {
    Logger.log("\n⚠️  НЕ НАЙДЕНО:");
    missing.forEach(m => {
      Logger.log(`   ❌ "${m.name}" → ${m.letter} (${m.column})`);
    });
  }

  Logger.log("\n════════════════════════════════════════════════════════════════════════\n");

  return warehouses;
}

// ============================================
// ШАГ 2: ПОЛУЧЕНИЕ ОСТАТКОВ ПО FBS СКЛАДАМ
// ============================================

/**
 * ШАГ 2 (основной): Обновить остатки по всем целевым FBS складам
 *
 * Официальный endpoint: POST /v2/product/info/stocks-by-warehouse/fbs
 * Документация: https://docs.ozon.ru/api/seller/#v2/product/info/stocks-by-warehouse/fbs
 *
 * Формат запроса:
 * {
 *   "sku": [123, 456, 789],      // массив SKU (числа)
 *   "limit": 1000,               // макс. количество результатов (до 1000)
 *   "cursor": "..."              // курсор для пагинации (если has_next = true)
 * }
 *
 * Формат ответа:
 * {
 *   "products": [
 *     {
 *       "sku": 123,
 *       "warehouse_id": 1020005000689690,
 *       "warehouse_name": "ЭТМ САМАРА",
 *       "present": 10,
 *       "reserved": 2,
 *       "free_stock": 10
 *     }
 *   ],
 *   "has_next": false,
 *   "cursor": ""
 * }
 *
 * ВАЖНО:
 * 1. Мы записываем present + reserved (всего на складе), а не только present.
 * 2. API v2 возвращает остатки по ВСЕМ складам сразу для каждого SKU.
 *    Поэтому мы опрашиваем уникальные SKU один раз батчами по 200 и распределяем
 *    остатки по всем целевым колонкам (AB:AH) за один проход!
 * 3. Встроена защита: если все запросы завершились ошибкой, запись в таблицу
 *    ОТМЕНЯЕТСЯ во избежание зануления колонок.
 */
function updateAllFBSWarehouses() {
  const startTime = new Date();

  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ШАГ 2: ОБНОВЛЕНИЕ ОСТАТКОВ ПО FBS СКЛАДАМ (Ozon v2 API)               ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");

  // 1. Загружаем список складов из PropertiesService (или запрашиваем через API)
  const scriptProperties = PropertiesService.getScriptProperties();
  let warehousesJson = scriptProperties.getProperty("ozon_warehouses");
  let warehouses = null;

  if (warehousesJson) {
    try {
      warehouses = JSON.parse(warehousesJson);
    } catch (e) {
      Logger.log("⚠️ Ошибка парсинга ozon_warehouses: " + e.message);
    }
  }

  if (!warehouses || !Array.isArray(warehouses) || warehouses.length === 0) {
    Logger.log("⚠️ Список складов не найден или пуст. Получаем свежий список складов...");
    warehouses = fetchAndSaveWarehouses();
    if (!warehouses || !Array.isArray(warehouses) || warehouses.length === 0) {
      Logger.log("❌ Не удалось получить список складов. Завершение работы.");
      return;
    }
  }

  // 2. Ищем целевые склады
  const targetWarehouses = findTargetWarehouses(warehouses);

  if (targetWarehouses.length === 0) {
    Logger.log("❌ Целевые склады не найдены!");
    Logger.log("   Проверьте названия в TARGET_WAREHOUSES");
    return;
  }

  const targetWhMap = {};
  targetWarehouses.forEach(tw => {
    targetWhMap[String(tw.warehouseId)] = tw;
    Logger.log(`   ✅ "${tw.warehouseName}" (ID: ${tw.warehouseId}) → ${tw.letter} (${tw.column})`);
  });

  // 3. Читаем SKU из таблицы (колонка V = 22)
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("❌ Нет данных в таблице");
    return;
  }

  const numRows = lastRow - 1;
  const skuRange = sheet.getRange(2, 22, numRows); // V (22): SKU Ozon
  const skuValuesRaw = skuRange.getValues().flat();

  // Сопоставляем каждый валидный SKU со списком индексов строк (0-based)
  const skuToIndices = new Map();
  let validSkuCount = 0;

  for (let idx = 0; idx < skuValuesRaw.length; idx++) {
    const val = skuValuesRaw[idx];
    const sku = val ? Number(val) : null;
    if (sku && !isNaN(sku) && sku > 0) {
      validSkuCount++;
      let indices = skuToIndices.get(sku);
      if (!indices) {
        indices = [];
        skuToIndices.set(sku, indices);
      }
      indices.push(idx);
    }
  }

  const uniqueSkus = Array.from(skuToIndices.keys());
  Logger.log(`\n📦 Всего строк: ${numRows}, валидных SKU: ${validSkuCount}, уникальных SKU: ${uniqueSkus.length}`);

  if (uniqueSkus.length === 0) {
    Logger.log("❌ Нет валидных SKU в колонке V (22)");
    Logger.log("   Сначала заполните SKU: выполните OzonMain()");
    return;
  }

  // 4. Подготавливаем массивы для записи (инициализируем нулями)
  const columnsData = {};
  targetWarehouses.forEach(tw => {
    columnsData[tw.column] = new Array(numRows).fill(0);
  });

  // 5. Запрашиваем остатки по батчам через v2 API (один проход по всем складам сразу)
  const chunkSize = 200;
  const totalChunks = Math.ceil(uniqueSkus.length / chunkSize);
  const url = typeof ozonFBSStocks === "function" ? ozonFBSStocks() : "https://api-seller.ozon.ru/v2/product/info/stocks-by-warehouse/fbs";

  let lastRequestTime = Date.now() - 1000 / RPS();
  let successCount = 0;
  let failureCount = 0;
  let totalProductsReceived = 0;

  Logger.log(`\n📤 Запрос остатков по всем складам (Ozon v2 API)...`);
  Logger.log(`   Всего чанков: ${totalChunks} (по ${chunkSize} SKU)`);

  for (let i = 0; i < uniqueSkus.length; i += chunkSize) {
    const chunk = uniqueSkus.slice(i, i + chunkSize);
    const chunkNum = Math.floor(i / chunkSize) + 1;

    if (chunkNum === 1 || chunkNum % 10 === 0 || chunkNum === totalChunks) {
      Logger.log(`   📤 Чанк ${chunkNum}/${totalChunks} (${chunk.length} SKU)...`);
    }

    let cursor = "";
    let hasNext = true;
    let chunkSuccess = true;

    while (hasNext) {
      lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

      const payload = {
        "sku": chunk,
        "limit": 1000
      };
      if (cursor) {
        payload.cursor = cursor;
      }

      const options = {
        "method": "post",
        "contentType": "application/json",
        "headers": ozonHeaders(),
        "payload": JSON.stringify(payload),
        "muteHttpExceptions": true
      };

      try {
        const response = retryFetch(url, options);

        if (!response) {
          Logger.log(`   ❌ Ошибка сети при запросе остатков для чанка ${chunkNum}`);
          chunkSuccess = false;
          break;
        }

        const responseCode = response.getResponseCode();

        if (responseCode === 200) {
          const data = JSON.parse(response.getContentText());
          const products = data.products || data.result || [];

          if (Array.isArray(products) && products.length > 0) {
            totalProductsReceived += products.length;

            products.forEach(item => {
              const tw = targetWhMap[String(item.warehouse_id)];
              if (tw) {
                const sku = Number(item.sku);
                const present = Number(item.present) || 0;
                const reserved = Number(item.reserved) || 0;
                const totalStock = present + reserved;

                const indices = skuToIndices.get(sku);
                if (indices) {
                  for (let k = 0; k < indices.length; k++) {
                    columnsData[tw.column][indices[k]] = totalStock;
                  }
                }
              }
            });
          }

          if (data.has_next && data.cursor) {
            cursor = data.cursor;
          } else {
            hasNext = false;
          }
        } else {
          Logger.log(`   ❌ Ошибка API на чанке ${chunkNum}: код ${responseCode}`);
          chunkSuccess = false;
          break;
        }
      } catch (e) {
        Logger.log(`   ❌ Исключение на чанке ${chunkNum}: ${e.message}`);
        chunkSuccess = false;
        break;
      }
    }

    if (chunkSuccess) {
      successCount++;
    } else {
      failureCount++;
    }
  }

  Logger.log(`\n📊 Результат запросов: успешно ${successCount}/${totalChunks} чанков, ошибок: ${failureCount}`);
  Logger.log(`📦 Всего получено записей остатков: ${totalProductsReceived}`);

  // КРИТИЧЕСКАЯ ЗАЩИТА: не перезаписывать таблицу нулями, если API упал
  if (successCount === 0 && failureCount > 0) {
    Logger.log("\n❌ КРИТИЧЕСКАЯ ОШИБКА: Ни один запрос к API не завершился успешно!");
    Logger.log("⛔ Запись в таблицу ОТМЕНЕНА во избежание зануления остатков.");
    return;
  }

  if (failureCount > totalChunks * 0.3) {
    Logger.log(`\n⚠️ ВНИМАНИЕ: Слишком много ошибок запросов (${failureCount}/${totalChunks} > 30%)!`);
    Logger.log("⛔ Запись в таблицу ОТМЕНЕНА для защиты целостности данных.");
    return;
  }

  // 6. Записываем данные в таблицу (все колонки)
  Logger.log(`\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);
  Logger.log(`📥 ЗАПИСЬ В ТАБЛИЦУ...`);

  targetWarehouses.forEach(tw => {
    const values = columnsData[tw.column].map(v => [v]);
    sheet.getRange(2, tw.column, values.length, 1).setValues(values);

    const withStock = values.filter(v => v[0] > 0).length;
    Logger.log(`   ✅ ${tw.letter} (${tw.column}): "${tw.warehouseName}" - ${withStock} товаров с остатками`);
  });

  // 7. Итоги
  const endTime = new Date();
  const seconds = Math.round((endTime - startTime) / 1000);

  Logger.log("\n╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ИТОГИ                                                             ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");
  Logger.log(`📊 Обновлено складов: ${targetWarehouses.length}`);
  Logger.log(`📦 Всего уникальных SKU обработано: ${uniqueSkus.length}`);
  Logger.log(`⏱️  Время выполнения: ${seconds} сек.`);
  Logger.log("✅ Завершено успешно!");
  Logger.log("════════════════════════════════════════════════════════════════════════\n");
}

// ============================================
// КОМБИНИРОВАННАЯ ФУНКЦИЯ (всё в одном)
// ============================================

/**
 * Выполнить всё автоматически:
 * 1. Получить список складов (если нет в PropertiesService)
 * 2. Обновить остатки по всем целевым складам
 *
 * Удобно для ручного запуска или добавления в триггеры
 */
function fetchAndUpdateAll() {
  const scriptProperties = PropertiesService.getScriptProperties();
  const warehousesJson = scriptProperties.getProperty("ozon_warehouses");

  // Если список складов ещё не сохранён - получаем его
  if (!warehousesJson) {
    Logger.log("⚠️  Список складов не найден. Получаем...");
    const warehouses = fetchAndSaveWarehouses();

    if (!warehouses) {
      Logger.log("❌ Не удалось получить список складов");
      return;
    }
  }

  // Обновляем остатки
  updateAllFBSWarehouses();
}

// ============================================
// ДИАГНОСТИКА И ОТЛАДКА
// ============================================

/**
 * Диагностика: проверить остатки по конкретному SKU на всех складах
 *
 * Использование:
 * diagnoseSku(301916350)  // проверяет конкретный SKU
 */
function diagnoseSku(skuToCheck) {
  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log(`║   ДИАГНОСТИКА SKU: ${skuToCheck} (Ozon v2 API)                         ║`);
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");

  // Загружаем список складов
  const scriptProperties = PropertiesService.getScriptProperties();
  const warehousesJson = scriptProperties.getProperty("ozon_warehouses");

  let warehouses = null;
  if (warehousesJson) {
    try {
      warehouses = JSON.parse(warehousesJson);
    } catch (e) {
      Logger.log("❌ Ошибка парсинга списка складов: " + e.message);
    }
  }

  if (!warehouses || !Array.isArray(warehouses)) {
    Logger.log("⚠️ Список складов не найден. Получаем свежий список...");
    warehouses = fetchAndSaveWarehouses();
    if (!warehouses) {
      Logger.log("❌ Не удалось получить список складов");
      return;
    }
  }

  const targetWarehouses = findTargetWarehouses(warehouses);

  if (targetWarehouses.length === 0) {
    Logger.log("❌ Целевые склады не найдены");
    return;
  }

  Logger.log(`\n🔍 Запрос остатков по SKU ${skuToCheck} через Ozon v2 API...\n`);

  const url = typeof ozonFBSStocks === "function" ? ozonFBSStocks() : "https://api-seller.ozon.ru/v2/product/info/stocks-by-warehouse/fbs";
  const payload = {
    "sku": [Number(skuToCheck)],
    "limit": 100
  };

  const options = {
    "method": "post",
    "contentType": "application/json",
    "headers": ozonHeaders(),
    "payload": JSON.stringify(payload),
    "muteHttpExceptions": true
  };

  try {
    const response = retryFetch(url, options);
    if (!response) {
      Logger.log("❌ Не удалось получить ответ от API");
      return;
    }

    const responseCode = response.getResponseCode();

    if (responseCode === 200) {
      const data = JSON.parse(response.getContentText());
      const products = data.products || data.result || [];

      if (!Array.isArray(products) || products.length === 0) {
        Logger.log(`⚪ Товар SKU ${skuToCheck} не имеет остатков ни на одном FBS складе`);
      } else {
        Logger.log(`📦 Всего записей по складам: ${products.length}\n`);

        targetWarehouses.forEach(tw => {
          const item = products.find(p => String(p.warehouse_id) === String(tw.warehouseId));
          if (item) {
            const present = Number(item.present) || 0;
            const reserved = Number(item.reserved) || 0;
            const total = present + reserved;

            Logger.log(`✅ ${tw.letter} (${tw.column}): "${tw.warehouseName}" [ID: ${tw.warehouseId}]`);
            Logger.log(`   Present (доступно): ${present}`);
            Logger.log(`   Reserved (зарезервировано): ${reserved}`);
            Logger.log(`   Всего (present + reserved): ${total}`);
          } else {
            Logger.log(`⚪ ${tw.letter} (${tw.column}): "${tw.warehouseName}" [ID: ${tw.warehouseId}] — 0 шт.`);
          }
        });
      }
    } else {
      Logger.log(`❌ Ошибка API: код ${responseCode}`);
      Logger.log(response.getContentText().substring(0, 300));
    }
  } catch (e) {
    Logger.log(`❌ Исключение: ${e.message}`);
  }

  Logger.log("\n════════════════════════════════════════════════════════════════════════\n");
}

/**
 * Быстрая диагностика по нескольким SKU
 *
 * Использование:
 * diagnoseMultipleSkus([301916350, 986326117])
 *
 * ИЛИ выполните diagnoseTestSkus() для проверки на тестовых SKU
 */
function diagnoseMultipleSkus(skuList) {
  if (!skuList || !Array.isArray(skuList)) {
    Logger.log("❌ Ошибка: skuList не передан или не является массивом");
    Logger.log("\n💡 Использование:");
    Logger.log("   diagnoseMultipleSkus([301916350, 986326117])");
    Logger.log("\n   Или выполните: diagnoseTestSkus()");
    return;
  }

  skuList.forEach(sku => diagnoseSku(sku));
}

/**
 * Тестовая функция - проверяет известные проблемные SKU
 * Выполните эту функцию для быстрой диагностики
 */
function diagnoseTestSkus() {
  const testSkus = [301916350, 986326117];
  Logger.log(`🔍 Проверка ${testSkus.length} тестовых SKU: ${testSkus.join(", ")}\n`);
  diagnoseMultipleSkus(testSkus);
}

/**
 * Проверка дубликатов warehouse_id
 * Показывает какие TARGET_WAREHOUSES используют один и тот же warehouse_id
 */
function checkWarehouseDuplicates() {
  const scriptProperties = PropertiesService.getScriptProperties();
  const warehousesJson = scriptProperties.getProperty("ozon_warehouses");

  if (!warehousesJson) {
    Logger.log("❌ Список складов не найден. Сначала выполните: fetchAndUpdateAll()");
    return;
  }

  let warehouses;
  try {
    warehouses = JSON.parse(warehousesJson);
  } catch (e) {
    Logger.log("❌ Ошибка парсинга списка складов: " + e.message);
    Logger.log("   Выполните: fetchAndUpdateAll() для получения свежего списка");
    return;
  }

  if (!Array.isArray(warehouses)) {
    Logger.log("❌ Неверный формат списка складов (не массив)");
    return;
  }

  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ПРОВЕРКА ДУБЛИКАТОВ WAREHOUSE_ID                                   ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");

  // Проверяем каждое название из TARGET_WAREHOUSES
  const results = [];

  TARGET_WAREHOUSES.forEach(target => {
    // Находим все склады которые соответствуют названию
    const matchingWarehouses = warehouses.filter(wh =>
      wh.name === target.name ||
      (wh.name && wh.name.toLowerCase().includes(target.name.toLowerCase()))
    );

    if (matchingWarehouses.length > 0) {
      matchingWarehouses.forEach(wh => {
        results.push({
          target: target.name,
          targetColumn: target.letter,
          targetNumber: target.column,
          warehouseId: wh.warehouse_id,
          warehouseName: wh.name
        });
      });
    } else {
      results.push({
        target: target.name,
        targetColumn: target.letter,
        targetNumber: target.column,
        warehouseId: null,
        warehouseName: "НЕ НАЙДЕН"
      });
    }
  });

  // Группируем по warehouse_id
  const byWarehouseId = {};
  results.forEach(r => {
    if (r.warehouseId) {
      const id = r.warehouseId;
      if (!byWarehouseId[id]) {
        byWarehouseId[id] = [];
      }
      byWarehouseId[id].push(r);
    }
  });

  Logger.log("\n📊 ГРУППИРОВКА ПО WAREHOUSE_ID:");

  let duplicateCount = 0;

  Object.keys(byWarehouseId).sort().forEach(id => {
    const group = byWarehouseId[id];
    if (group.length > 1) {
      duplicateCount++;
      Logger.log(`\n⚠️  warehouse_id ${id} используется ${group.length} раза:`);
      group.forEach(g => {
        Logger.log(`   → "${g.target}" (${g.targetColumn}, кол ${g.targetNumber})`);
        Logger.log(`      "${g.warehouseName}"`);
      });
    } else {
      Logger.log(`\n✅ warehouse_id ${id}:`);
      Logger.log(`   → "${group[0].target}" (${group[0].targetColumn}, кол ${group[0].targetNumber})`);
      Logger.log(`      "${group[0].warehouseName}"`);
    }
  });

  // Итог
  Logger.log("\n╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ИТОГИ                                                             ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");

  const uniqueIds = Object.keys(byWarehouseId).length;
  Logger.log(`📦 Всего уникальных warehouse_id: ${uniqueIds}`);
  Logger.log(`📦 Всего целевых складов: ${TARGET_WAREHOUSES.length}`);

  if (duplicateCount > 0) {
    Logger.log(`\n❌ ОБНАРУЖЕНО: ${duplicateCount} warehouse_id используются несколько раз!`);
    Logger.log("💡 Решение:");
    Logger.log("   1. Проверьте точность названий в константе TARGET_WAREHOUSES");
    Logger.log("   2. Измените названия чтобы они соответствовали точным названиям в Ozon");
  } else {
    Logger.log("\n✅ Дубликатов не обнаружено!");
  }

  Logger.log("════════════════════════════════════════════════════════════════════════\n");
}
