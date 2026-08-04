/**
 * СИНХРОНИЗАЦИЯ ОСТАТКОВ С ЛИСТА "GAUSS TR"
 *
 * Читает остатки из листа "GAUSS TR" и выгружает на склады:
 * - Ozon: Gauss МСК
 * - WB: ФБС Ферон Москва
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
 *
 * ⚠️ ВАЖНО (с 9 февраля 2026):
 * WB API требует chrtId вместо sku.
 * Колонка J должна быть заполнена chrtId.
 */

// ============================================
// КОНФИГУРАЦИЯ
// ============================================

const GAUSS_SHEET_NAME = "GAUSS TR";
const GAUSS_OZON_WAREHOUSE_ID = 1020005005391400;  // Gauss МСК
const GAUSS_WB_WAREHOUSE_ID = 1449484;             // ФБС ФЕРОН МОСКВА

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

    // Пропускаем пустые строки (только если нет offer_id)
    if (!offerId) {
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
 * Возвращает ID склада Gauss МСК для Ozon
 * @returns {number} ID склада
 */
function getGaussWarehouseId() {
  Logger.log(`🔍 Склад Ozon: Gauss МСК (ID: ${GAUSS_OZON_WAREHOUSE_ID})`);
  return GAUSS_OZON_WAREHOUSE_ID;
}

/**
 * Возвращает ID склада ФБС Ферон Москва для WB
 * @returns {number} ID склада
 */
function getFeronWarehouseId() {
  Logger.log(`🔍 Склад WB: ФБС ФЕРОН МОСКВА (ID: ${GAUSS_WB_WAREHOUSE_ID})`);
  return GAUSS_WB_WAREHOUSE_ID;
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
// ОБНОВЛЕНИЕ ОСТАТКОВ WILDBERRIES
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

function sendWBStocksBatch(batch, warehouseId) {
  const body = { stocks: batch };
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
    return { ok: false, code: 0, text: '', cargoRestriction: false };
  }

  const code = response.getResponseCode();
  const text = response.getContentText();

  return {
    ok: code === 200 || code === 204,
    code,
    text,
    cargoRestriction: code === 409 && isWBCargoRestrictionError(text)
  };
}

function processWBConflictIndividually(validBatch, warehouseId, batchLabel) {
  let successCount = 0;
  let skippedCount = 0;
  let errorCount = 0;

  Logger.log(`🔍 ${batchLabel}: дробление до отдельных товаров...`);

  for (let j = 0; j < validBatch.length; j++) {
    const item = validBatch[j];
    const result = sendWBStocksBatch([item], warehouseId);

    if (result.ok) {
      successCount++;
      continue;
    }

    if (result.cargoRestriction) {
      Logger.log(`⏸️ ${batchLabel}: пропущен ODC/CD+ chrtId=${item.chrtId}, amount=${item.amount}`);
      skippedCount++;
      continue;
    }

    Logger.log(`❌ ${batchLabel}: ошибка для chrtId=${item.chrtId}, amount=${item.amount}, code=${result.code}`);
    if (result.text) {
      Logger.log(result.text.substring(0, 500));
    }
    errorCount++;
  }

  Logger.log(`📊 ${batchLabel}: поштучно ✅ ${successCount}, ⏸️ ${skippedCount}, ❌ ${errorCount}`);

  return { successCount, skippedCount, errorCount };
}

/**
 * Нормализует chrtId из ячейки/формулы Google Sheets.
 *
 * Возможные проблемы:
 * - число пришло как строка
 * - есть пробелы / неразрывные пробелы
 * - значение выглядит как "12345.0"
 * - формула вернула текст
 *
 * @param {*} value
 * @returns {number|null}
 */
function normalizeChrtId(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  // Если это уже число
  if (typeof value === 'number') {
    return Number.isFinite(value) ? Math.trunc(value) : null;
  }

  let str = String(value)
    .replace(/\u00A0/g, '')   // NBSP
    .replace(/\s+/g, '')      // любые пробелы
    .replace(/,/g, '.')        // на всякий случай
    .trim();

  if (!str) return null;

  // Формат вида 12345.0 -> 12345
  if (/^\d+\.0+$/.test(str)) {
    str = str.replace(/\.0+$/, '');
  }

  // Оставляем только валидные числовые значения
  if (!/^\d+(\.\d+)?$/.test(str)) {
    return null;
  }

  const num = Number(str);
  if (!Number.isFinite(num)) return null;

  return Math.trunc(num);
}

/**
 * Обновляет остатки на складе Wildberries (FBS)
 * Автоматически пропускает конфликтные товары ODC/CD+,
 * которые WB не даёт грузить на склад ФБС ФЕРОН МОСКВА.
 * При 409 батч дробится до отдельных товаров.
 * @param {Array} stocks - Массив товаров
 * @param {number} warehouseId - ID склада
 */
function updateWBStocks(stocks, warehouseId) {
  Logger.log(`🟣 Обновление остатков WB (склад ID: ${warehouseId})...`);

  const validStocks = stocks.filter(s => s.chrt_id);

  if (validStocks.length === 0) {
    Logger.log(`⚠️ Нет товаров с chrtId для обновления WB`);
    Logger.log(`⚠️ Проверьте что колонка J (chrtId) заполнена`);
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
      const idNum = normalizeChrtId(item.chrt_id);

      // Валидация chrtId
      if (!idNum) {
        Logger.log(`⚠️ Пропущен невалидный chrtId: raw="${item.chrt_id}" normalized="${idNum}" (offer_id: ${item.offer_id})`);
        errorCount++;
        continue;
      }

      validBatch.push({
        chrtId: idNum,
        amount: item.stock
      });
    }

    if (validBatch.length === 0) {
      Logger.log(`⏸️ Пачка ${i + 1}/${batches} пропущена (нет валидных chrtId)`);
      continue;
    }

    const result = sendWBStocksBatch(validBatch, warehouseId);

    if (result.ok) {
      successCount += validBatch.length;
      Logger.log(`✅ Пачка ${i + 1}/${batches} обработана (${validBatch.length} товаров)`);
      continue;
    }

    if (result.cargoRestriction) {
      Logger.log(`⚠️ WB 409 details (пачка ${i + 1}/${batches}): ${result.text.substring(0, 1000)}`);
      const fallback = processWBConflictIndividually(validBatch, warehouseId, `Пачка ${i + 1}/${batches}`);
      successCount += fallback.successCount;
      skippedCount += fallback.skippedCount;
      errorCount += fallback.errorCount;
      continue;
    }

    Logger.log(`❌ Ошибка API (пачка ${i + 1}/${batches}): ${result.code}`);
    if (result.text) {
      Logger.log(result.text.substring(0, 1000));
    }
    errorCount += validBatch.length;
  }

  Logger.log(`🟣 WB FBS: ✅ ${successCount} обновлено, ⏸️ ${skippedCount} пропущено ODC/CD+, ❌ ${errorCount} ошибок`);
}

// ============================================
// ГЛАВНАЯ ФУНКЦИЯ
// ============================================

/**
 * Главная функция синхронизации остатков
 */
function syncStocksFromSheets() {
  Logger.log("============================================");
  Logger.log("🔄 СИНХРОНИЗАЦИЯ ОСТАТКОВ");
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
    Logger.log(`  - ${s.offer_id} | SKU_OZON: ${s.sku_ozon} | chrtId(raw): ${s.chrt_id} | chrtId(norm): ${normalizeChrtId(s.chrt_id)} | Stock: ${s.stock}`);
  });

  // Шаг 2: Получаем ID складов
  Logger.log(``);
  Logger.log(`📦 Шаг 2: Получение ID складов...`);

  const gaussWarehouseId = getGaussWarehouseId();
  const feronWarehouseId = getFeronWarehouseId();

  // Шаг 3: Обновляем остатки Ozon
  if (gaussWarehouseId) {
    Logger.log(``);
    Logger.log(`🟠 Шаг 3: Обновление остатков Ozon...`);
    updateOzonStocks(stocks, gaussWarehouseId);
  }

  // Шаг 4: Обновляем остатки WB
  if (feronWarehouseId) {
    Logger.log(``);
    Logger.log(`🟣 Шаг 4: Обновление остатков WB...`);
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
function testStockSync() {
  Logger.log("============================================");
  Logger.log("🧪 ТЕСТ СИНХРОНИЗАЦИИ ОСТАТКОВ");
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

  // Тест 2: Проверка складов
  Logger.log(``);
  Logger.log(`📦 Тест 2: Проверка складов...`);

  const gaussId = getGaussWarehouseId();
  const feronId = getFeronWarehouseId();

  Logger.log(``);
  Logger.log(`Результаты:`);
  Logger.log(`  - Gauss МСК (Ozon): ✅ ID: ${gaussId}`);
  Logger.log(`  - ФБС ФЕРОН МОСКВА (WB): ✅ ID: ${feronId}`);

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
  Logger.log(`  syncStocksFromSheets()`);
  Logger.log("============================================");
}
