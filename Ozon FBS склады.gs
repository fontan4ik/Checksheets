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
 * 1. ШАГ 1 (один раз): fetchAndSaveWarehouses() - получить список складов через /v1/warehouse/list
 * 2. ШАГ 2 (основной): updateAllFBSWarehouses() - получить остатки по каждому складу
 *
 * Официальная документация Ozon Seller API:
 * - https://docs.ozon.ru/api/seller/#v1/warehouse/list
 * - https://docs.ozon.ru/api/seller/#v1/product/info/stocks-by-warehouse/fbs
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

  const url = "https://api-seller.ozon.ru/v1/warehouse/list";

  // ИСПРАВЛЕНО: API Ozon принимает limit только до 200 (не 1000!)
  // Добавляем пагинацию для получения всех складов
  const limit = 200; // макс. допустимое значение для /v1/warehouse/list
  const maxPages = 10; // защита от бесконечного цикла (макс. 2000 складов)

  let allWarehouses = [];
  let offset = 0;
  let pageCount = 0;
  let lastRequestTime = Date.now() - 1000 / RPS();

  Logger.log("\n📤 Загрузка списка складов (с пагинацией)...");

  try {
    // Цикл пагинации
    while (pageCount < maxPages) {
      pageCount++;

      // Rate limiting
      lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

      const payload = {
        "limit": limit,
        "offset": offset
      };

      const options = {
        "method": "post",
        "contentType": "application/json",
        "headers": ozonHeaders(),
        "payload": JSON.stringify(payload),
        "muteHttpExceptions": true
      };

      if (pageCount === 1 || pageCount % 5 === 0) {
        Logger.log(`   📤 Страница ${pageCount} (offset: ${offset}, limit: ${limit})...`);
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

        if (data && data.result && Array.isArray(data.result)) {
          const warehouses = data.result;
          allWarehouses.push(...warehouses);

          // Если вернулось меньше чем limit - это последняя страница
          if (warehouses.length < limit) {
            Logger.log(`   ✅ Загружена последняя страница (${warehouses.length} складов)`);
            break;
          }

          // Увеличиваем offset для следующей итерации
          offset += limit;
        } else {
          Logger.log(`   ❌ Неверный формат ответа на странице ${pageCount}`);
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
 * Официальный endpoint: POST /v1/product/info/stocks-by-warehouse/fbs
 * Документация: https://docs.ozon.ru/api/seller/#v1/product/info/stocks-by-warehouse/fbs
 *
 * Формат запроса:
 * {
 *   "sku": [123, 456, 789],      // массив SKU (числа) - МАКС 500!
 *   "warehouse_id": 1234567890,   // ID склада (число)
 *   "limit": 1000                // опционально, макс. количество результатов
 * }
 *
 * Формат ответа:
 * {
 *   "result": [
 *     {
 *       "sku": 123,              // SKU товара
 *       "warehouse_id": 1234567890,  // ID склада
 *       "present": 10,           // доступно для продажи (шт)
 *       "reserved": 2            // зарезервировано под заказы (шт)
 *     }
 *   ]
 * }
 *
 * ВАЖНО: Мы записываем present + reserved (всего на складе), а не только present!
 *
 * КРИТИЧЕСКОЕ: API возвращает данные по ВСЕМ складам в одном ответе!
 * Поэтому мы фильтруем result по warehouse_id чтобы взять только текущий склад.
 */
function updateAllFBSWarehouses() {
  const startTime = new Date();

  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ШАГ 2: ОБНОВЛЕНИЕ ОСТАТКОВ ПО FBS СКЛАДАМ                             ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");

  // 1. Загружаем список складов из PropertiesService
  const scriptProperties = PropertiesService.getScriptProperties();
  const warehousesJson = scriptProperties.getProperty("ozon_warehouses");

  if (!warehousesJson) {
    Logger.log("❌ Список складов не найден в PropertiesService");
    Logger.log("   Сначала выполните: fetchAndSaveWarehouses()");
    Logger.log("   Или выполните: fetchAndUpdateAll() - сделает всё автоматически");
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

  // 2. Ищем целевые склады
  const targetWarehouses = findTargetWarehouses(warehouses);

  if (targetWarehouses.length === 0) {
    Logger.log("❌ Целевые склады не найдены!");
    Logger.log("   Проверьте названия в TARGET_WAREHOUSES");
    return;
  }

  Logger.log(`\n🎯 Найдено целевых складов: ${targetWarehouses.length}`);

  targetWarehouses.forEach(tw => {
    Logger.log(`   ✅ "${tw.warehouseName}" (ID: ${tw.warehouseId}) → ${tw.letter} (${tw.column})`);
  });

  // 3. Читаем SKU из таблицы (колонка V = 22)
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("❌ Нет данных в таблице");
    return;
  }

  const skuRange = sheet.getRange(2, 22, lastRow - 1); // V (22): SKU Ozon
  const skuValuesRaw = skuRange.getValues().flat();

  // Фильтруем валидные SKU
  const validSkuEntries = skuValuesRaw
    .map((sku, index) => ({ index, sku: sku ? Number(sku) : null }))
    .filter(entry => entry.sku && !isNaN(entry.sku) && entry.sku > 0);

  if (validSkuEntries.length === 0) {
    Logger.log("❌ Нет валидных SKU в колонке V (22)");
    Logger.log("   Сначала заполните SKU: выполните OzonMain()");
    return;
  }

  const validSkus = validSkuEntries.map(e => e.sku);

  Logger.log(`\n📦 Всего SKU в таблице: ${validSkuEntries.length}`);

  // 4. Подготавливаем массивы для записи (инициализируем нулями)
  const columnsData = {};
  targetWarehouses.forEach(tw => {
    columnsData[tw.column] = new Array(skuValuesRaw.length).fill(0);
  });

  // 5. Для каждого склада получаем остатки
  const chunkSize = 500; // Ozon API limit для /v1/product/info/stocks-by-warehouse/fbs (МАКС: 500!)
  let totalUpdated = 0;

  targetWarehouses.forEach(tw => {
    Logger.log(`\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);
    Logger.log(`📦 Склад: "${tw.warehouseName}" (ID: ${tw.warehouseId}) → ${tw.letter} (${tw.column})`);

    const stockMap = {}; // sku -> present + reserved (всего на складе)
    let lastRequestTime = Date.now() - 1000 / RPS();
    let processedCount = 0;
    let filteredCount = 0; // ИСПРАВЛЕНО: считаем отфильтрованные строки

    // Запрашиваем остатки по чанкам
    for (let i = 0; i < validSkus.length; i += chunkSize) {
      lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

      const chunk = validSkus.slice(i, i + chunkSize);
      const chunkNum = Math.floor(i / chunkSize) + 1;
      const totalChunks = Math.ceil(validSkus.length / chunkSize);

      if (chunkNum === 1 || chunkNum % 5 === 0 || chunkNum === totalChunks) {
        Logger.log(`   📤 Чанк ${chunkNum}/${totalChunks} (${chunk.length} SKU)...`);
      }

      // Payload запроса (согласно документации Ozon)
      const payload = {
        "sku": chunk,
        "warehouse_id": tw.warehouseId,
        "limit": chunkSize
      };

      const options = {
        "method": "post",
        "contentType": "application/json",
        "headers": ozonHeaders(),
        "payload": JSON.stringify(payload),
        "muteHttpExceptions": true
      };

      try {
        const url = "https://api-seller.ozon.ru/v1/product/info/stocks-by-warehouse/fbs";
        const response = retryFetch(url, options);

        if (!response) {
          Logger.log(`❌ Не удалось получить FBS остатки для чанка`);
          continue;
        }

        const responseCode = response.getResponseCode();

        if (responseCode === 200) {
          const data = JSON.parse(response.getContentText());

          if (data && data.result && Array.isArray(data.result)) {
            data.result.forEach(item => {
              // КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: фильтруем по warehouse_id текущего склада!
              // API может возвращать данные по нескольким складам в одном ответе
              if (String(item.warehouse_id) !== String(tw.warehouseId)) {
                filteredCount++; // считаем отфильтрованные
                return; // пропускаем строки других складов
              }

              const sku = item.sku;
              // ИСПРАВЛЕНО: Берём present + reserved (всего на складе), а не только present
              const present = Number(item.present) || 0;
              const reserved = Number(item.reserved) || 0;
              stockMap[sku] = present + reserved;
            });

            processedCount += data.result.length;
          }
        } else {
          Logger.log(`   ❌ Ошибка API: код ${responseCode}`);
        }
      } catch (e) {
        Logger.log(`   ❌ Исключение: ${e.message}`);
      }
    }

    Logger.log(`   ✅ Обработано записей: ${processedCount}`);
    if (filteredCount > 0) {
      Logger.log(`   📊 Отфильтровано (другие склады): ${filteredCount} строк`);
    }

    // 6. Заполняем массив для записи
    validSkuEntries.forEach(entry => {
      const arrIndex = entry.index; // индекс в массиве (0-based)
      const sku = entry.sku;
      const present = stockMap[sku] || 0;

      if (present > 0) {
        columnsData[tw.column][arrIndex] = present;
        totalUpdated++;
      }
    });

    const withStock = Object.values(stockMap).filter(v => v > 0).length;
    Logger.log(`   ✅ Товаров с остатками: ${withStock}`);
  });

  // 7. Записываем данные в таблицу (все колонки сразу для оптимизации)
  Logger.log(`\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);
  Logger.log(`📥 ЗАПИСЬ В ТАБЛИЦУ...`);

  targetWarehouses.forEach(tw => {
    const values = columnsData[tw.column].map(v => [v]); // преобразуем в 2D массив
    sheet.getRange(2, tw.column, values.length, 1).setValues(values);

    const withStock = values.filter(v => v[0] > 0).length;
    Logger.log(`   ✅ ${tw.letter} (${tw.column}): "${tw.warehouseName}" - ${withStock} товаров с остатками`);
  });

  // 8. Итоги
  const endTime = new Date();
  const seconds = Math.round((endTime - startTime) / 1000);

  Logger.log("\n╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ИТОГИ                                                             ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");
  Logger.log(`📊 Обновлено складов: ${targetWarehouses.length}`);
  Logger.log(`📦 Всего SKU обработано: ${validSkuEntries.length}`);
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
  Logger.log(`║   ДИАГНОСТИКА SKU: ${skuToCheck}                                        ║`);
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");

  // Загружаем список складов
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

  const targetWarehouses = findTargetWarehouses(warehouses);

  if (targetWarehouses.length === 0) {
    Logger.log("❌ Целевые склады не найдены");
    return;
  }

  Logger.log(`\n🔍 Проверяю SKU ${skuToCheck} на ${targetWarehouses.length} складах...\n`);

  // Запрашиваем остатки для каждого склада
  const url = "https://api-seller.ozon.ru/v1/product/info/stocks-by-warehouse/fbs";

  targetWarehouses.forEach(tw => {
    const payload = {
      "sku": [skuToCheck],
      "warehouse_id": tw.warehouseId,
      "limit": 1
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
      const responseCode = response.getResponseCode();

      if (responseCode === 200) {
        const data = JSON.parse(response.getContentText());

        if (data && data.result && Array.isArray(data.result) && data.result.length > 0) {
          const item = data.result[0];
          const present = Number(item.present) || 0;
          const reserved = Number(item.reserved) || 0;
          const total = present + reserved;

          Logger.log(`${tw.letter} (${tw.column}): "${tw.warehouseName}" [ID: ${tw.warehouseId}]`);
          Logger.log(`   Present (доступно): ${present}`);
          Logger.log(`   Reserved (зарезервировано): ${reserved}`);
          Logger.log(`   Всего (present + reserved): ${total}`);
        } else {
          Logger.log(`${tw.letter} (${tw.column}): "${tw.warehouseName}" [ID: ${tw.warehouseId}]`);
          Logger.log(`   ❌ Нет данных (SKU не найден на этом складе)`);
        }
      } else {
        Logger.log(`${tw.letter} (${tw.column}): ❌ Ошибка API: код ${responseCode}`);
      }
    } catch (e) {
      Logger.log(`${tw.letter} (${tw.column}): ❌ Исключение: ${e.message}`);
    }
  });

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
