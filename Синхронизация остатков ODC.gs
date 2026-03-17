/**
 * СИНХРОНИЗАЦИЯ ОСТАТКОВ С ЛИСТА "GAUSS TR" (С ПРОПУСКОМ ODC/CD+)
 *
 * Читает остатки из листа "GAUSS TR" (колонка I: Округлённое)
 * и выгружает на склады:
 * - Ozon: Gauss МСК
 * - WB: Feron Москва (FBS) - с пропуском товаров ODC/CD+
 *
 * Структура листа "GAUSS TR":
 * A: Арт производителя
 * B: Артикул продавца (offer_id) ← ключ для Ozon
 * C: (пусто)
 * D: SKU OZON
 * E: SKU WB (устарело, не используется)
 * F: Остаток
 * G: Кратность
 * H: (пусто)
 * I: Округлённое ← это stock для выгрузки
 * J: chrtId ← ключ для WB API
 */

// ============================================
// КОНФИГУРАЦИЯ
// ============================================

const GAUSS_SHEET_NAME = "GAUSS TR";
const GAUSS_WAREHOUSE_NAME = "Gauss МСК";
const FERON_WAREHOUSE_NAME = "ФЕРОН";  // Ищет "ФБС ФЕРОН МОСКВА"

// ============================================
// ЧТЕНИЕ ДАННЫХ ИЗ GOOGLE SHEETS
// ============================================

/**
 * Читает данные из листа "GAUSS TR"
 * @returns {Array} Массив объектов с данными товаров
 */
function readStocksFromSheet() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(GAUSS_SHEET_NAME);

  if (!sheet) {
    Logger.log(`❌ Лист "${GAUSS_SHEET_NAME}" не найден!`);
    return [];
  }

  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log(`❌ Нет данных на листе "${GAUSS_SHEET_NAME}"`);
    return [];
  }

  // Читаем все колонки: A(1) - J(10)
  // A=Арт производителя, B=Артикул продавца, D=SKU OZON, I=Округлённое, J=chrtId
  const data = sheet.getRange(2, 1, lastRow - 1, 10).getValues();

  const stocks = [];

  for (let i = 0; i < data.length; i++) {
    const row = data[i];

    const artProducer = row[0];      // A: Арт производителя
    const offerId = row[1];          // B: Артикул продавца ← ключ для Ozon
    const skuOzon = row[3];          // D: SKU OZON
    const ostatok = row[5];          // F: Остаток
    const kratnost = row[6];         // G: Кратность
    const okruglenoe = row[8];       // I: Округлённое ← stock для выгрузки
    const chrtId = row[9];           // J: chrtId ← ключ для WB API

    // Пропускаем пустые строки
    if (!offerId && !skuOzon && !chrtId) {
      continue;
    }

    const stock = parseInt(okruglenoe) || 0;

    stocks.push({
      art_producer: artProducer,
      offer_id: offerId,
      sku_ozon: skuOzon,
      chrt_id: chrtId,               // ✅ chrtId для WB API (из колонки J)
      ostatok: ostatok,
      kratnost: kratnost,
      stock: stock
    });
  }

  Logger.log(`📊 Прочитано ${stocks.length} товаров из листа "${GAUSS_SHEET_NAME}"`);

  return stocks;
}

// ============================================
// ПОЛУЧЕНИЕ ID СКЛАДОВ
// ============================================

/**
 * Получает список складов Ozon
 * @returns {Array} Массив складов
 */
function getOzonWarehouses() {
  const url = "https://api-seller.ozon.ru/v1/warehouse/list";

  const options = {
    method: "post",
    contentType: "application/json",
    headers: ozonHeaders(),
    payload: JSON.stringify({}),
    muteHttpExceptions: true
  };

  const response = retryFetch(url, options);

  if (!response) {
    Logger.log("❌ Не удалось получить список складов Ozon");
    return [];
  }

  const responseCode = response.getResponseCode();

  if (responseCode !== 200) {
    Logger.log(`❌ Ошибка получения складов Ozon: ${responseCode}`);
    Logger.log(response.getContentText());
    return [];
  }

  const data = JSON.parse(response.getContentText());
  const warehouses = data.result || [];

  Logger.log(`📦 Получено ${warehouses.length} складов Ozon`);

  return warehouses;
}

/**
 * Находит ID склада Gauss МСК
 * @returns {number|null} ID склада или null
 */
function getGaussWarehouseId() {
  Logger.log(`🔍 Поиск склада "${GAUSS_WAREHOUSE_NAME}"...`);

  const warehouses = getOzonWarehouses();

  // Ищем склад по имени (содержит "Gauss")
  const gaussWarehouse = warehouses.find(w =>
    w.name && (w.name.includes("Gauss") || w.name.includes("GAUSS"))
  );

  if (!gaussWarehouse) {
    Logger.log(`❌ Склад "${GAUSS_WAREHOUSE_NAME}" не найден!`);
    Logger.log("Доступные склады:");
    warehouses.forEach(w => {
      Logger.log(`  - ${w.name} (ID: ${w.warehouse_id})`);
    });
    return null;
  }

  Logger.log(`✅ Найден склад: ${gaussWarehouse.name} (ID: ${gaussWarehouse.warehouse_id})`);

  return gaussWarehouse.warehouse_id;
}

/**
 * Получает список складов Wildberries
 * @returns {Array} Массив складов
 */
function getWBWarehouses() {
  const url = "https://marketplace-api.wildberries.ru/api/v3/warehouses";

  const options = {
    method: "get",
    headers: wbHeaders(),
    muteHttpExceptions: true
  };

  const response = retryFetch(url, options);

  if (!response) {
    Logger.log("❌ Не удалось получить список складов WB");
    return [];
  }

  const responseCode = response.getResponseCode();

  if (responseCode !== 200) {
    Logger.log(`❌ Ошибка получения складов WB: ${responseCode}`);
    Logger.log(response.getContentText());
    return [];
  }

  const data = JSON.parse(response.getContentText());

  Logger.log(`📦 Получено ${data.length} складов WB`);

  return data;
}

/**
 * Находит ID склада Feron Москва
 * @returns {number|null} ID склада или null
 */
function getFeronWarehouseId() {
  Logger.log(`🔍 Поиск склада "${FERON_WAREHOUSE_NAME}"...`);

  const warehouses = getWBWarehouses();

  // Ищем склад по имени (содержит "ФЕРОН", "Feron" в любом регистре)
  const feronWarehouse = warehouses.find(w =>
    w.name && w.name.toLowerCase().includes("ферон")
  );

  if (!feronWarehouse) {
    Logger.log(`❌ Склад "${FERON_WAREHOUSE_NAME}" не найден!`);
    Logger.log("Доступные склады:");
    warehouses.forEach(w => {
      Logger.log(`  - ${w.name} (ID: ${w.id})`);
    });
    return null;
  }

  Logger.log(`✅ Найден склад: ${feronWarehouse.name} (ID: ${feronWarehouse.id})`);

  return feronWarehouse.id;
}

// ============================================
// ОБНОВЛЕНИЕ ОСТАТКОВ OZON
// ============================================

/**
 * Обновляет остатки на складе Ozon
 * @param {Array} stocks - Массив товаров
 * @param {number} warehouseId - ID склада
 */
function updateOzonStocks(stocks, warehouseId) {
  Logger.log(`🟠 Обновление остатков Ozon (склад ID: ${warehouseId})...`);

  // Фильтруем товары с offer_id и stock > 0
  const validStocks = stocks.filter(s => s.offer_id && s.stock > 0);

  if (validStocks.length === 0) {
    Logger.log(`⚠️ Нет товаров с offer_id для обновления Ozon`);
    return;
  }

  Logger.log(`📦 Товаров для обновления: ${validStocks.length}`);

  // Лимит: 100 товаров за запрос
  const batchSize = 100;
  const batches = Math.ceil(validStocks.length / batchSize);

  let lastRequestTime = Date.now() - 1000 / RPS();
  let successCount = 0;
  let errorCount = 0;

  for (let i = 0; i < batches; i++) {
    // Rate limiting
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

    const batch = validStocks.slice(i * batchSize, (i + 1) * batchSize);

    const body = {
      stocks: batch.map(item => ({
        offer_id: String(item.offer_id),
        stock: item.stock,
        warehouse_id: warehouseId
      }))
    };

    const url = "https://api-seller.ozon.ru/v2/products/stocks";

    const options = {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify(body),
      muteHttpExceptions: true
    };

    const response = retryFetch(url, options);

    if (!response) {
      Logger.log(`❌ Ошибка запроса (пачка ${i + 1}/${batches})`);
      errorCount += batch.length;
      continue;
    }

    const responseCode = response.getResponseCode();
    const responseText = response.getContentText();

    if (responseCode !== 200) {
      Logger.log(`❌ Ошибка API (пачка ${i + 1}/${batches}): ${responseCode}`);
      Logger.log(responseText);
      errorCount += batch.length;
      continue;
    }

    const result = JSON.parse(responseText);

    if (result.result) {
      result.result.forEach(r => {
        if (r.errors && r.errors.length > 0) {
          const isError = !r.errors.some(e => e.code === 'TOO_MANY_REQUESTS');

          if (isError) {
            // Критическая ошибка
            Logger.log(`❌ Ozon ошибка для ${r.offer_id}: ${r.errors.map(e => e.message || e.code).join(", ")}`);
            errorCount++;
          } else {
            // TOO_MANY_REQUESTS - не критичная, товар обновлялся недавно
            Logger.log(`⏸️ ${r.offer_id}: обновлялся недавно (пропущен)`);
            // Не считаем ошибкой, но и не успехом
          }
        } else if (r.updated) {
          successCount++;
        }
      });
    }

    Logger.log(`✅ Пачка ${i + 1}/${batches} обработана`);
  }

  Logger.log(`🟠 Ozon: ✅ ${successCount} обновлено, ❌ ${errorCount} ошибок`);
}

// ============================================
// ОБНОВЛЕНИЕ ОСТАТКОВ WILDBERRIES (С ПРОПУСКОМ ODC/CD+)
// ============================================

/**
 * Обновляет остатки на складе Wildberries (FBS) - с пропуском товаров ODC/CD+
 * @param {Array} stocks - Массив товаров
 * @param {number} warehouseId - ID склада
 */
function updateWBStocks(stocks, warehouseId) {
  Logger.log(`🟣 Обновление остатков WB (склад ID: ${warehouseId})...`);

  // Фильтруем товары с chrt_id (включая stock = 0 - валидное значение)
  const validStocks = stocks.filter(s => s.chrt_id);

  if (validStocks.length === 0) {
    Logger.log(`⚠️ Нет товаров с chrtId для обновления`);
    return;
  }

  Logger.log(`📦 Товаров для обновления: ${validStocks.length}`);

  // Лимит: 1000 товаров за запрос
  const batchSize = 1000;
  const batches = Math.ceil(validStocks.length / batchSize);

  let lastRequestTime = Date.now() - 1000 / WB_RPS();
  let successCount = 0;
  let skippedCount = 0;  // Товары ODC/CD+ (пропущены)
  let errorCount = 0;

  for (let i = 0; i < batches; i++) {
    // Rate limiting
    lastRequestTime = rateLimitRPS(lastRequestTime, WB_RPS());

    const batch = validStocks.slice(i * batchSize, (i + 1) * batchSize);

    // ✅ Новый формат WB API (февраль 2026): chrtId + stocks
    const validBatch = [];
    for (let j = 0; j < batch.length; j++) {
      const item = batch[j];
      const idNum = Number(item.chrt_id);

      if (!isNaN(idNum) && idNum > 0) {
        validBatch.push({
          chrtId: idNum,  // ✅ chrtId из колонки J
          amount: item.stock  // 0 тоже валидное значение
        });
      } else {
        errorCount++;
      }
    }

    if (validBatch.length === 0) {
      Logger.log(`⚠️ Пачка ${i + 1}/${batches}: нет валидных товаров`);
      continue;
    }

    const body = {
      stocks: validBatch  // ✅ "stocks" (множественное число)
    };

    const url = `https://marketplace-api.wildberries.ru/api/v3/stocks/${warehouseId}`;

    const options = {
      method: "put",
      contentType: "application/json",
      headers: wbHeaders(),
      payload: JSON.stringify(body),
      muteHttpExceptions: true
    };

    const response = retryFetch(url, options);

    if (!response) {
      Logger.log(`❌ Ошибка запроса (пачка ${i + 1}/${batches})`);
      errorCount += validBatch.length;
      continue;
    }

    const responseCode = response.getResponseCode();

    if (responseCode !== 200 && responseCode !== 204) {
      const responseText = response.getContentText();

      // ✅ Проверяем ошибку 409 - CargoWarehouseRestriction (ODC/CD+ товары)
      if (responseCode === 409) {
        try {
          const errorData = JSON.parse(responseText);
          if (errorData && errorData.length > 0) {
            const errorCode = errorData[0].code;
            if (errorCode === "CargoWarehouseRestrictionSGTKGTPlus" ||
                errorCode.includes("CargoWarehouseRestriction")) {
              Logger.log(`⏸️ Пачка ${i + 1}/${batches}: ${validBatch.length} товаров ODC/CD+ пропущены`);
              skippedCount += validBatch.length;
              continue;
            }
          }
        } catch (e) {
          // Если не удалось распарсить, считаем обычной ошибкой
        }
      }

      Logger.log(`❌ Ошибка API (пачка ${i + 1}/${batches}): ${responseCode}`);
      Logger.log(responseText);
      errorCount += validBatch.length;
      continue;
    }

    // WB API возвращает 200 OK или 204 No Content без детализации по каждому товару
    successCount += validBatch.length;
    Logger.log(`✅ Пачка ${i + 1}/${batches} обработана (${validBatch.length} товаров)`);
  }

  Logger.log(`🟣 WB: ✅ ${successCount} обновлено, ⏸️ ${skippedCount} пропущено (ODC/CD+), ❌ ${errorCount} ошибок`);
}

// ============================================
// ГЛАВНАЯ ФУНКЦИЯ
// ============================================

/**
 * Главная функция синхронизации остатков (с пропуском ODC/CD+)
 */
function syncStocksFromSheetsSkipODC() {
  Logger.log("============================================");
  Logger.log("🔄 СИНХРОНИЗАЦИЯ ОСТАТКОВ (С ПРОПУСКОМ ODC/CD+)");
  Logger.log("============================================");

  const startTime = new Date();

  // Шаг 1: Читаем данные из Google Sheets
  Logger.log(`📊 Шаг 1: Чтение данных из листа "${GAUSS_SHEET_NAME}"...`);
  const stocks = readStocksFromSheet();

  if (stocks.length === 0) {
    Logger.log("❌ Нет данных для синхронизации");
    return;
  }

  // Показываем примеры данных
  Logger.log(`📋 Примеры данных (первые 5):`);
  stocks.slice(0, 5).forEach(s => {
    Logger.log(`  - ${s.offer_id} | SKU_OZON: ${s.sku_ozon} | chrtId: ${s.chrt_id} | Stock: ${s.stock}`);
  });

  // Шаг 2: Получаем ID складов
  Logger.log(``);
  Logger.log(`📦 Шаг 2: Получение ID складов...`);

  const gaussWarehouseId = getGaussWarehouseId();
  const feronWarehouseId = getFeronWarehouseId();

  if (!gaussWarehouseId) {
    Logger.log("❌ Не найден ID склада Gauss МСК, пропуск обновления Ozon");
  }

  if (!feronWarehouseId) {
    Logger.log("❌ Не найден ID склада Feron Москва, пропуск обновления WB");
  }

  // Шаг 3: Обновляем остатки Ozon
  if (gaussWarehouseId) {
    Logger.log(``);
    Logger.log(`🟠 Шаг 3: Обновление остатков Ozon...`);
    updateOzonStocks(stocks, gaussWarehouseId);
  }

  // Шаг 4: Обновляем остатки WB (с пропуском ODC/CD+)
  if (feronWarehouseId) {
    Logger.log(``);
    Logger.log(`🟣 Шаг 4: Обновление остатков WB (с пропуском ODC/CD+)...`);
    updateWBStocks(stocks, feronWarehouseId);
  }

  const endTime = new Date();
  const duration = Math.round((endTime - startTime) / 1000);

  Logger.log(``);
  Logger.log("============================================");
  Logger.log(`✅ Синхронизация завершена за ${duration} сек.`);
  Logger.log("============================================");
}

// ============================================
// ТЕСТОВАЯ ФУНКЦИЯ
// ============================================

/**
 * Тестовая функция - проверяет чтение данных и поиск складов
 */
function testStockSyncSkipODC() {
  Logger.log("============================================");
  Logger.log("🧪 ТЕСТ СИНХРОНИЗАЦИИ ОСТАТКОВ (С ПРОПУСКОМ ODC/CD+)");
  Logger.log("============================================");

  // Тест 1: Чтение данных
  Logger.log(``);
  Logger.log(`📊 Тест 1: Чтение данных из листа...`);
  const stocks = readStocksFromSheet();

  if (stocks.length === 0) {
    Logger.log("❌ Нет данных");
    return;
  }

  Logger.log(`✅ Прочитано ${stocks.length} товаров`);
  Logger.log(`📋 Первые 5 товаров:`);
  stocks.slice(0, 5).forEach(s => {
    Logger.log(`  - offer_id: ${s.offer_id}, sku_ozon: ${s.sku_ozon}, chrt_id: ${s.chrt_id}, stock: ${s.stock}`);
  });

  // Тест 2: Поиск складов
  Logger.log(``);
  Logger.log(`📦 Тест 2: Поиск складов...`);

  const gaussId = getGaussWarehouseId();
  const feronId = getFeronWarehouseId();

  Logger.log(``);
  Logger.log(`Результаты:`);
  Logger.log(`  - Gauss МСК: ${gaussId ? "✅ ID: " + gaussId : "❌ Не найден"}`);
  Logger.log(`  - Feron Москва: ${feronId ? "✅ ID: " + feronId : "❌ Не найден"}`);

  // Тест 3: Подготовка данных для Ozon
  if (gaussId) {
    Logger.log(``);
    Logger.log(`🟠 Тест 3: Подготовка данных для Ozon...`);

    const ozonStocks = stocks.filter(s => s.offer_id && s.stock > 0);
    Logger.log(`  Товаров с offer_id и stock > 0: ${ozonStocks.length}`);

    if (ozonStocks.length > 0) {
      Logger.log(`  Примеры payload (первые 3):`);
      ozonStocks.slice(0, 3).forEach(s => {
        Logger.log(`    { offer_id: "${s.offer_id}", stock: ${s.stock}, warehouse_id: ${gaussId} }`);
      });
    }
  }

  // Тест 4: Подготовка данных для WB
  if (feronId) {
    Logger.log(``);
    Logger.log(`🟣 Тест 4: Подготовка данных для WB...`);

    const wbStocks = stocks.filter(s => s.chrt_id);
    Logger.log(`  Товаров с chrtId: ${wbStocks.length}`);

    if (wbStocks.length > 0) {
      Logger.log(`  Примеры payload (первые 3):`);
      wbStocks.slice(0, 3).forEach(s => {
        Logger.log(`    { chrtId: ${s.chrt_id}, amount: ${s.stock} }`);
      });
    }
  }

  Logger.log(``);
  Logger.log("============================================");
  Logger.log(`✅ Тест завершён`);
  Logger.log(``);
  Logger.log(`Для запуска полноценной синхронизации выполните:`);
  Logger.log(`  syncStocksFromSheetsSkipODC()`);
  Logger.log("============================================");
}

// ============================================
// СПИСОК СКЛАДОВ WB
// ============================================

/**
 * Показывает все доступные склады Wildberries
 */
function listWBWarehouses() {
  Logger.log("============================================");
  Logger.log("📦 СПИСОК СКЛАДОВ WILDBERRIES");
  Logger.log("============================================");

  const warehouses = getWBWarehouses();

  if (warehouses.length === 0) {
    Logger.log("❌ Не удалось получить список складов");
    return;
  }

  Logger.log(`📦 Всего складов: ${warehouses.length}`);
  Logger.log(``);

  warehouses.forEach((w, index) => {
    Logger.log(`${index + 1}. ${w.name}`);
    Logger.log(`   ID: ${w.id}`);
    if (w.address) Logger.log(`   Адрес: ${w.address}`);
    Logger.log(``);
  });

  Logger.log("============================================");
}
