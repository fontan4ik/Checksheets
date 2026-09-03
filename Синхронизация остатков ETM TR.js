/**
 * РАБОТА С ЛИСТОМ "StreamSupps"
 *
 * 1. updateETMStocksInSheet() - подтягивает остатки из API (если нужно)
 * 2. syncETMTableToMarketplaces() - выгружает данные из таблицы на маркетплейсы
 */

// ============================================
// КОНФИГУРАЦИЯ
// ============================================

const ETM_SHEET_NAME = "StreamSupps";

// Фиксированные ID складов для Ozon и WB
const ETM_OZON_WAREHOUSE_ID = 1020005000689690;  // ЭТМ САМАРА
const ETM_WB_WAREHOUSE_ID = 798761;            // ВольтМир

// Колонки (1-based индекс)
// A = 1 - Артикул (offer_id Ozon)
// G = 7 - chrlid (WB character ID)
// S = 19 - ЭТМ САМАРА (остаток для выгрузки после вставки H)
const ETM_COL_ARTICUL = 1;   // A - Артикул (offer_id Ozon)
const ETM_COL_CHRT_ID = 7;   // G - chrlid (WB)
const ETM_COL_STOCK = 19;    // S - ЭТМ САМАРА

const ETM_MIN_STOCK_THRESHOLD = 5; // Минимальный остаток для выгрузки (> 4)

// ============================================
// 1. ФУНКЦИИ ДЛЯ ЧТЕНИЯ ДАННЫХ ИЗ ЛИСТА
// ============================================

/**
 * Читает данные из листа "StreamSupps"
 * @returns {Array} Массив объектов с данными товаров
 */
function readETMStocksFromSheet() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(ETM_SHEET_NAME);

  if (!sheet) {
    Logger.log(`❌ Лист "${ETM_SHEET_NAME}" не найден!`);
    return [];
  }

  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log(`❌ Нет данных на листе "${ETM_SHEET_NAME}"`);
    return [];
  }

  // Динамически ищем колонки по заголовкам (1-я строка)
  const lastCol = sheet.getLastColumn();
  const headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0].map(h => String(h).trim().toLowerCase());

  // Функция для поиска колонки (возвращает 1-based индекс, или fallback)
  const findCol = (name, fallback) => {
    const idx = headers.indexOf(name.toLowerCase());
    return idx >= 0 ? idx + 1 : fallback;
  };

  const dynamicColOfferId = findCol("артикул продавца", ETM_COL_ARTICUL);
  const dynamicColChrtId = findCol("chrlid", ETM_COL_CHRT_ID);
  const dynamicColStock = findCol("этм самара", ETM_COL_STOCK);

  Logger.log(`🔍 Колонки: Артикул=${dynamicColOfferId}, chrlid=${dynamicColChrtId}, ЭТМ САМАРА=${dynamicColStock}`);

  // Читаем нужные колонки
  const maxCol = Math.max(dynamicColOfferId, dynamicColChrtId, dynamicColStock);
  const data = sheet.getRange(2, 1, lastRow - 1, maxCol).getValues();

  const stocks = [];

  for (let i = 0; i < data.length; i++) {
    const row = data[i];

    const offerId = row[dynamicColOfferId - 1];
    const chrtId = row[dynamicColChrtId - 1];
    const stockForUpload = row[dynamicColStock - 1];

    // Пропускаем пустые строки
    if (!offerId) {
      continue;
    }

    let stock = parseInt(stockForUpload) || 0;

    // Применяем порог: если остаток < ETM_MIN_STOCK_THRESHOLD, выгружаем 0
    const originalStock = stock;
    if (stock < ETM_MIN_STOCK_THRESHOLD) {
      stock = 0;
    }

    stocks.push({
      offer_id: offerId,
      chrt_id: chrtId,
      stock: stock,
      original_stock: originalStock
    });
  }

  const aboveThreshold = stocks.filter(s => s.original_stock >= ETM_MIN_STOCK_THRESHOLD).length;
  const belowThreshold = stocks.filter(s => s.original_stock > 0 && s.original_stock < ETM_MIN_STOCK_THRESHOLD).length;

  Logger.log(`📊 Прочитано ${stocks.length} товаров из листа "${ETM_SHEET_NAME}"`);
  Logger.log(`   С остатком >= ${ETM_MIN_STOCK_THRESHOLD}: ${aboveThreshold}`);
  Logger.log(`   С остатком < ${ETM_MIN_STOCK_THRESHOLD} (будет 0): ${belowThreshold}`);
  Logger.log(`   С chrlid: ${stocks.filter(s => s.chrt_id).length}`);

  return stocks;
}

/**
 * Нормализует chrlid (убирает пробелы, неразрывные пробелы, преобразует в число)
 */
function normalizeETMChrtId(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  if (typeof value === "number") {
    return Number.isFinite(value) ? Math.trunc(value) : null;
  }

  let str = String(value)
    .replace(/\u00A0/g, "")
    .replace(/\s+/g, "")
    .replace(/,/g, ".")
    .trim();

  if (!str) return null;

  if (/^\d+\.0+$/.test(str)) {
    str = str.replace(/\.0+$/, "");
  }

  if (!/^\d+(\.\d+)?$/.test(str)) {
    return null;
  }

  const num = Number(str);
  return Number.isFinite(num) ? Math.trunc(num) : null;
}

// ============================================
// 2. ФУНКЦИИ ДЛЯ ОБНОВЛЕНИЯ ОСТАТКОВ НА МАРКЕТПЛЕЙСАХ
// ============================================

function isWBCargoRestrictionError(responseText) {
  try {
    const errorData = JSON.parse(responseText);
    const errorItems = Array.isArray(errorData)
      ? errorData
      : (errorData?.errors || errorData?.error || []);

    if (!errorItems || errorItems.length === 0) {
      return false;
    }

    return errorItems.some(err => {
      const code = String(err.code || err.error || '');
      const message = String(err.message || err.detail || '');
      return code.includes('CargoWarehouseRestriction') ||
             message.includes('CargoWarehouseRestriction') ||
             code.includes('SGTKGTPlus') ||
             message.includes('SGTKGTPlus') ||
             message.includes('ODC') ||
             message.includes('CD+');
    });
  } catch (e) {
    return responseText.includes('CargoWarehouseRestriction') ||
           responseText.includes('SGTKGTPlus') ||
           responseText.includes('ODC') ||
           responseText.includes('CD+');
  }
}

function sendETMStocksBatch(batch, warehouseId, retryCount) {
  retryCount = retryCount || 0;

  const url = `https://marketplace-api.wildberries.ru/api/v3/stocks/${warehouseId}`;
  const body = { stocks: batch };

  const options = {
    method: "put",
    contentType: "application/json",
    headers: wbHeaders(),
    payload: JSON.stringify(body),
    muteHttpExceptions: true
  };

  const response = retryFetch(url, options);

  if (!response) {
    return { ok: false, code: 0, text: '', cargoRestriction: false, retryCount: retryCount };
  }

  const code = response.getResponseCode();
  const text = response.getContentText();

  // Retry для 429
  if (code === 429 && retryCount < 2) {
    Utilities.sleep(5000);
    return sendETMStocksBatch(batch, warehouseId, retryCount + 1);
  }

  return {
    ok: code === 200 || code === 204,
    code,
    text,
    cargoRestriction: code === 409 && isWBCargoRestrictionError(text),
    retryCount: retryCount
  };
}

function processETMConflictIndividually(validBatch, warehouseId, batchLabel) {
  let successCount = 0;
  let skippedCount = 0;
  let errorCount = 0;

  Logger.log("🔍 " + batchLabel + ": дробление до отдельных товаров...");

  for (let j = 0; j < validBatch.length; j++) {
    const item = validBatch[j];

    // Rate limiting для поштучных запросов - пауза каждые 10 запросов
    if (j > 0 && j % 10 === 0) {
      Utilities.sleep(2000);
    }

    const result = sendETMStocksBatch([item], warehouseId);

    if (result.ok) {
      successCount++;
      continue;
    }

    if (result.cargoRestriction) {
      Logger.log("⏸️ " + batchLabel + ": пропущен ODC/CD+ chrtId=" + item.chrtId + ", amount=" + item.amount);
      skippedCount++;
      continue;
    }

    Logger.log("❌ " + batchLabel + ": ошибка для chrtId=" + item.chrtId + ", amount=" + item.amount + ", code=" + result.code);
    if (result.text) {
      Logger.log(result.text.substring(0, 500));
    }
    errorCount++;
  }

  Logger.log("📊 " + batchLabel + ": поштучно ✅ " + successCount + ", ⏸️ " + skippedCount + ", ❌ " + errorCount);

  return { successCount, skippedCount, errorCount };
}

/**
 * Обновляет остатки на складе Ozon
 * @param {Array} stocks - Массив товаров
 * @param {number} warehouseId - ID склада
 */
function updateETMStocksOzon(stocks, warehouseId) {
  Logger.log(`🟠 Обновление остатков Ozon (склад ID: ${warehouseId})...`);

  // Фильтруем товары с offer_id (включая нулевые остатки)
  const validStocks = stocks.filter(s => s.offer_id);

  if (validStocks.length === 0) {
    Logger.log(`⚠️ Нет товаров с offer_id для обновления Ozon`);
    return;
  }

  Logger.log(`📦 Товаров для обработки: ${validStocks.length}`);

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
      Logger.log(responseText.substring(0, 500));
      errorCount += batch.length;
      continue;
    }

    const result = JSON.parse(responseText);

    if (result.result) {
      result.result.forEach(r => {
        if (r.errors && r.errors.length > 0) {
          const isError = !r.errors.some(e => e.code === 'TOO_MANY_REQUESTS');

          if (isError) {
            Logger.log(`❌ Ozon ошибка для ${r.offer_id}: ${r.errors.map(e => e.message || e.code).join(", ")}`);
            errorCount++;
          } else {
            successCount++;
          }
        } else if (r.updated) {
          successCount++;
        }
      });
    }

    Logger.log("✅ Пачка " + (i + 1) + "/" + batches + " обработана (" + batch.length + " товаров)");
  }

  Logger.log(`🟠 Ozon: ✅ ${successCount} обновлено, ❌ ${errorCount} ошибок`);
}

/**
 * Обновляет остатки на складе Wildberries (FBS)
 * Автоматически пропускает конфликтные товары ODC/CD+,
 * которые WB не даёт грузить на склад.
 * При 409 батч дробится до отдельных товаров.
 * @param {Array} stocks - Массив товаров
 * @param {number} warehouseId - ID склада
 */
function updateETMStocksWB(stocks, warehouseId) {
  Logger.log(`🟣 Обновление остатков WB (склад ID: ${warehouseId})...`);

  const validStocks = stocks.filter(s => s.chrt_id);

  if (validStocks.length === 0) {
    Logger.log(`⚠️ Нет товаров с chrlid для обновления WB`);
    Logger.log(`⚠️ Проверьте что колонка Q (chrlid) заполнена`);
    return;
  }

  Logger.log(`📦 Товаров для обработки: ${validStocks.length}`);

  const batchSize = 1000;
  const batches = Math.ceil(validStocks.length / batchSize);

  let lastRequestTime = Date.now() - 1000 / WB_RPS();
  let successCount = 0;
  let skippedCount = 0;
  let errorCount = 0;

  for (let i = 0; i < batches; i++) {
    lastRequestTime = rateLimitRPS(lastRequestTime, WB_RPS());

    const batch = validStocks.slice(i * batchSize, (i + 1) * batchSize);
    const validBatch = [];

    for (let j = 0; j < batch.length; j++) {
      const item = batch[j];
      const idNum = normalizeETMChrtId(item.chrt_id);

      if (!idNum) {
        Logger.log(`⚠️ Пропущен невалидный chrlid: raw="${item.chrt_id}" normalized="${idNum}" (offer_id: ${item.offer_id})`);
        errorCount++;
        continue;
      }

      validBatch.push({
        chrtId: idNum,
        amount: item.stock
      });
    }

    if (validBatch.length === 0) {
      Logger.log(`⏸️ Пачка ${i + 1}/${batches} пропущена (нет валидных chrlid)`);
      continue;
    }

    const result = sendETMStocksBatch(validBatch, warehouseId);

    if (result.ok) {
      successCount += validBatch.length;
      Logger.log(`✅ Пачка ${i + 1}/${batches} обработана (${validBatch.length} товаров)`);
      continue;
    }

    if (result.cargoRestriction) {
      Logger.log(`⚠️ WB 409 details (пачка ${i + 1}/${batches}): ${result.text.substring(0, 1000)}`);
      const fallback = processETMConflictIndividually(validBatch, warehouseId, `Пачка ${i + 1}/${batches}`);
      successCount += fallback.successCount;
      skippedCount += fallback.skippedCount;
      errorCount += fallback.errorCount;
      continue;
    }

    Logger.log(`❌ Ошибка API (пачка ${i + 1}/${batches}): ${result.code}`);
    if (result.text) {
      Logger.log(result.text.substring(0, 500));
    }
    errorCount += validBatch.length;
  }

  Logger.log(`🟣 WB FBS: ✅ ${successCount} обновлено, ⏸️ ${skippedCount} пропущено (ODC/CD+), ❌ ${errorCount} ошибок`);
}

// ============================================
// 3. ГЛАВНАЯ ФУНКЦИЯ СИНХРОНИЗАЦИИ
// ============================================

/**
 * Выгружает данные из колонок "Артикул", "chrlid" и "stocks smr" на Ozon и WB
 */
function syncETMTableToMarketplaces() {
  Logger.log("=== ШАГ 2: ВЫГРУЗКА ИЗ ТАБЛИЦЫ НА МАРКЕТПЛЕЙСЫ ===");

  // Шаг 1: Читаем данные из Google Sheets
  Logger.log("📊 Шаг 1: Чтение данных из листа \"" + ETM_SHEET_NAME + "\"...");
  const stocks = readETMStocksFromSheet();

  if (stocks.length === 0) {
    Logger.log("❌ Нет данных для синхронизации");
    return;
  }

  // Показываем примеры данных
  Logger.log(`📋 Примеры данных (первые 5):`);
  stocks.slice(0, 5).forEach(s => {
    Logger.log(`  - ${s.offer_id} | chrlid: ${s.chrt_id || '(нет)'} | Stock: ${s.stock}`);
  });

  // Шаг 2: Получаем ID складов
  Logger.log(``);
  Logger.log(`📦 Шаг 2: Использование фиксированных ID складов...`);

  const etmOzonId = ETM_OZON_WAREHOUSE_ID;
  const etmWbId = ETM_WB_WAREHOUSE_ID;

  Logger.log(`   - ЭТМ САМАРА (Ozon): ✅ ID: ${etmOzonId}`);
  Logger.log(`   - ВольтМир (WB): ✅ ID: ${etmWbId}`);

  // Шаг 3: Обновляем остатки Ozon
  Logger.log("");
  Logger.log("🟠 Шаг 3: Обновление остатков Ozon (ЭТМ САМАРА)...");
  updateETMStocksOzon(stocks, etmOzonId);

  // Шаг 4: Обновляем остатки WB
  Logger.log("");
  Logger.log("🟣 Шаг 4: Обновление остатков WB FBS (ВольтМир)...");
  updateETMStocksWB(stocks, etmWbId);

  Logger.log("✅ Синхронизация с маркетплейсами завершена.");
}

/**
 * Главная функция синхронизации остатков ETM из StreamSupps
 */
function syncETMStocks() {
  Logger.log("============================================");
  Logger.log("🔄 СИНХРОНИЗАЦИЯ ОСТАТКОВ ETM ИЗ StreamSupps");
  Logger.log("============================================");

  const startTime = new Date();

  // Шаг 1: Читаем данные из Google Sheets
  Logger.log(`📊 Шаг 1: Чтение данных из листа "${ETM_SHEET_NAME}"...`);
  const stocks = readETMStocksFromSheet();

  if (stocks.length === 0) {
    Logger.log("❌ Нет данных для синхронизации");
    return;
  }

  // Показываем примеры данных
  Logger.log(`📋 Примеры данных (первые 5):`);
  stocks.slice(0, 5).forEach(s => {
    Logger.log(`  - ${s.offer_id} | chrlid: ${s.chrt_id || '(нет)'} | Stock: ${s.stock}`);
  });

  // Шаг 2: Получаем ID складов
  Logger.log(``);
  Logger.log(`📦 Шаг 2: Использование фиксированных ID складов...`);

  const etmOzonId = ETM_OZON_WAREHOUSE_ID;
  const etmWbId = ETM_WB_WAREHOUSE_ID;

  Logger.log(`   - ЭТМ САМАРА (Ozon): ✅ ID: ${etmOzonId}`);
  Logger.log(`   - ВольтМир (WB): ✅ ID: ${etmWbId}`);

  // Шаг 3: Обновляем остатки Ozon
  Logger.log("");
  Logger.log("🟠 Шаг 3: Обновление остатков Ozon (ЭТМ САМАРА)...");
  updateETMStocksOzon(stocks, etmOzonId);

  // Шаг 4: Обновляем остатки WB
  Logger.log("");
  Logger.log("🟣 Шаг 4: Обновление остатков WB FBS (ВольтМир)...");
  updateETMStocksWB(stocks, etmWbId);

  const endTime = new Date();
  const duration = Math.round((endTime - startTime) / 1000);

  Logger.log(``);
  Logger.log("============================================");
  Logger.log(`✅ Синхронизация завершена за ${duration} сек.`);
  Logger.log("============================================");
}
