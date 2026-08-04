/**
 * РАБОТА С ЛИСТОМ "РуСВ TR"
 *
 * 1. updateRSStocksInSheet() - подтягивает остатки из RS API в таблицу.
 * 2. syncRSTableToMarketplaces() - выгружает данные из таблицы на маркетплейсы.
 */

// ============================================
// КОНФИГУРАЦИЯ
// ============================================

const RS_SHEET_NAME = "РуСВ TR";
const RS_WAREHOUSE_ID = 96; // По умолчанию (Самара)


// Фиксированные ID складов для Ozon и WB (как в ARL файле)

const RS_OZON_WAREHOUSE_ID = 1020005005049870;  // Резерв

const RS_WB_WAREHOUSE_ID = 798761;              // ВольтМир


// Фоллбек колонки (если заголовки не найдены)
const RS_COL_VENDOR_CODE = 2; // B - Модель
const RS_COL_ARTICUL = 1;     // A - Артикул (offer_id Ozon)
const RS_COL_CHRT_ID = 9;     // I - chrlid (WB) - ИСПРАВЛЕНО с 10 на 9
const RS_COL_STOCK_API = 6;   // F - Остаток АПИ
const RS_COL_COOLING = 7;     // G - Охлад
const RS_COL_ROUNDED = 8;     // H - Округление (Stock для выгрузки)

const RS_MIN_STOCK_THRESHOLD = 5; // Минимальный остаток для выгрузки (> 4)

// Задержки пост-проверки Ozon (из sync-etm-stocks.js)
const RS_OZON_POSTCHECK_DELAY_MS = 30000;       // 30 сек перед первой пост-проверкой
const RS_OZON_POSTCHECK_RETRY_DELAY_MS = 60000;  // 60 сек перед повторной проверкой
const RS_OZON_BASE_DELAY = 1000;                 // Базовый delay для Ozon retry (429/transport)
const RS_WB_BASE_DELAY = 3000;                   // Базовый delay для WB retry (429/transport)
const RS_OZON_MAX_RETRIES = 3;
const RS_WB_MAX_RETRIES = 3;

// ============================================
// 1. ОБНОВЛЕНИЕ ТАБЛИЦЫ ИЗ API
// ============================================

/**
 * Подтягивает актуальные остатки из RS API и записывает в "Остаток АПИ"
 */
function updateRSStocksInSheet() {
  Logger.log("=== ШАГ 1: ПОЛУЧЕНИЕ ОСТАТКОВ ИЗ RS API В ТАБЛИЦУ ===");

  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(RS_SHEET_NAME);

  if (!sheet) {
    Logger.log(`❌ Лист "${RS_SHEET_NAME}" не найден!`);
    return;
  }

  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return;

  // Динамический поиск колонок
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0].map(h => String(h).trim().toLowerCase());
  const colModel = headers.indexOf("модель") + 1 || RS_COL_VENDOR_CODE;
  const colStockApi = headers.indexOf("остаток апи") + 1 || RS_COL_STOCK_API;
  const colCooling = headers.indexOf("охлад") + 1 || RS_COL_COOLING;
  const colRounded = headers.indexOf("округление") + 1 || RS_COL_ROUNDED;

  const models = sheet.getRange(2, colModel, lastRow - 1, 1).getValues().flat();

  // 1. Загружаем карту Артикул -> Код РС один раз
  const codeMap = fetchRSCodeMap(RS_WAREHOUSE_ID);

  const resultsStockApi = [];
  const resultsCooling = [];
  const resultsRounded = [];

  // Используем PropertiesService для возможности продолжения после таймаута
  const props = PropertiesService.getScriptProperties();
  const startRowKey = `rs_sync_start_row`;
  let startRow = parseInt(props.getProperty(startRowKey)) || 2;

  // Если мы начинаем заново (прошло много времени или сбросили), сбрасываем индекс
  // Но для автоматизации лучше просто продолжить если разница во времени небольшая

  Logger.log(`⏱️ Обработка ${models.length} моделей (начинаем с ряда ${startRow})...`);

  // Мы будем читать существующие данные из таблицы чтобы не затирать то, что уже обработано
  // если произошел перезапуск после таймаута.
  const existingStockData = sheet.getRange(2, colStockApi, lastRow - 1, 3).getValues();

  for (let i = 0; i < models.length; i++) {
    const currentRow = i + 2;

    // Если этот ряд уже обработан в предыдущем запуске (таймаут), пропускаем
    if (currentRow < startRow) {
      resultsStockApi.push([existingStockData[i][0]]);
      resultsCooling.push([existingStockData[i][1]]);
      resultsRounded.push([existingStockData[i][2]]);
      continue;
    }

    const model = String(models[i]).trim();
    let stock = 0;

    if (model) {
      // Ищем код РС в нашей карте (без запроса к API)
      const rsCode = codeMap[model];

      if (rsCode) {
        const rsData = fetchRSStockByCode(rsCode, RS_WAREHOUSE_ID);
        if (rsData) {
          stock = (rsData.rsStock || 0) + (rsData.partnerStock || 0);
        }
      } else {
        // Если кода нет в каталоге склада
        // Logger.log(`⚠️ Модель ${model} не найдена в каталоге склада ${RS_WAREHOUSE_ID}`);
      }
    }

    const cooling = stock / 4;
    const rounded = Math.ceil(cooling);

    resultsStockApi.push([stock]);
    resultsCooling.push([cooling]);
    resultsRounded.push([rounded]);

    // Каждые 20 строк сохраняем прогресс и проверяем время
    if (currentRow % 20 === 0) {
      props.setProperty(startRowKey, (currentRow + 1).toString());
      Logger.log(`   Прогресс: ${currentRow}/${lastRow}...`);
    }
  }

  // Сбрасываем прогресс после успешного завершения
  props.deleteProperty(startRowKey);

  // Запись в таблицу
  sheet.getRange(2, colStockApi, resultsStockApi.length, 1).setValues(resultsStockApi);
  sheet.getRange(2, colCooling, resultsCooling.length, 1).setValues(resultsCooling);
  sheet.getRange(2, colRounded, resultsRounded.length, 1).setValues(resultsRounded);

  Logger.log("✅ Таблица успешно обновлена данными из RS API.");
  Logger.log("============================================");
}

// ============================================
// 2. СИНХРОНИЗАЦИЯ ТАБЛИЦЫ С МАРКЕТПЛЕЙСАМИ
// ============================================

/**
 * Читает данные из листа "РуСВ TR"
 * @returns {Array} Массив объектов с данными товаров
 */
function readRSStocksFromSheet() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(RS_SHEET_NAME);

  if (!sheet) {
    Logger.log(`❌ Лист "${RS_SHEET_NAME}" не найден!`);
    return [];
  }

  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log(`❌ Нет данных на листе "${RS_SHEET_NAME}"`);
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

  const dynamicColOfferId = findCol("артикул", RS_COL_ARTICUL);
  const dynamicColChrtId = findCol("chrtid", RS_COL_CHRT_ID) || findCol("chrlid", RS_COL_CHRT_ID);
  const dynamicColStock = findCol("округление", RS_COL_ROUNDED);

  Logger.log(`🔍 Колонки: Артикул=${dynamicColOfferId}, chrtId=${dynamicColChrtId}, Остаток=${dynamicColStock}`);

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

    // Применяем порог: если остаток < RS_MIN_STOCK_THRESHOLD, выгружаем 0
    const originalStock = stock;
    if (stock < RS_MIN_STOCK_THRESHOLD) {
      stock = 0;
    }

    stocks.push({
      offer_id: offerId,
      chrt_id: chrtId,
      stock: stock,
      original_stock: originalStock
    });
  }

  const aboveThreshold = stocks.filter(s => s.original_stock >= RS_MIN_STOCK_THRESHOLD).length;
  const belowThreshold = stocks.filter(s => s.original_stock > 0 && s.original_stock < RS_MIN_STOCK_THRESHOLD).length;

  Logger.log(`📊 Прочитано ${stocks.length} товаров из листа "${RS_SHEET_NAME}"`);
  Logger.log(`   С остатком >= ${RS_MIN_STOCK_THRESHOLD}: ${aboveThreshold}`);
  Logger.log(`   С остатком < ${RS_MIN_STOCK_THRESHOLD} (будет 0): ${belowThreshold}`);
  Logger.log(`   С chrtId: ${stocks.filter(s => s.chrt_id).length}`);

  return stocks;
}

function normalizeRSChrtId(value) {
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

/**
 * Обновляет остатки на складе Ozon
 * @param {Array} stocks - Массив товаров
 * @param {number} warehouseId - ID склада
 */
function updateRSStocksOzon(stocks, warehouseId) {
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

    Logger.log(`✅ Пачка ${i + 1}/${batches} обработана (${batch.length} товаров)`);
  }

  Logger.log(`🟠 Ozon: ✅ ${successCount} обновлено, ❌ ${errorCount} ошибок`);
}

function fetchRSOzonWarehouseStocks(offerIds, warehouseId) {
  const stockMap = {};
  const chunkSize = 500;
  let lastRequestTime = Date.now() - 1000 / RPS();

  for (let i = 0; i < offerIds.length; i += chunkSize) {
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

    const chunk = offerIds.slice(i, i + chunkSize);
    const response = retryFetch("https://api-seller.ozon.ru/v2/product/info/stocks-by-warehouse/fbs", {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify({
        offer_id: chunk,
        warehouse_id: warehouseId,
        limit: 1000
      }),
      muteHttpExceptions: true
    });

    if (!response || response.getResponseCode() !== 200) {
      continue;
    }

    const data = JSON.parse(response.getContentText());
    const products = Array.isArray(data.products) ? data.products : [];
    products.forEach(item => {
      if (String(item.warehouse_id) !== String(warehouseId)) return;
      stockMap[String(item.offer_id)] = (Number(item.present) || 0) + (Number(item.reserved) || 0);
    });
  }

  return stockMap;
}

function verifyRSOzonStocks(stocks, warehouseId) {
  const expected = stocks.filter(s => s.offer_id);
  if (expected.length === 0) {
    return;
  }

  const actualMap = fetchRSOzonWarehouseStocks(expected.map(s => String(s.offer_id)), warehouseId);
  const mismatches = [];

  expected.forEach(item => {
    const expectedStock = Number(item.stock) || 0;
    const actualStock = Number(actualMap[String(item.offer_id)] || 0);
    if (expectedStock !== actualStock && mismatches.length < 10) {
      mismatches.push(`${item.offer_id}: sheet=${expectedStock}, ozon=${actualStock}`);
    }
  });

  if (mismatches.length === 0) {
    Logger.log(`✅ Ozon post-check: расхождений по складу ${warehouseId} не найдено`);
    return 0;
  }

  Logger.log(`⚠️ Ozon post-check: найдено ${mismatches.length} расхождений по складу ${warehouseId}`);
  mismatches.forEach(line => Logger.log(`   - ${line}`));
  return mismatches.length;
}

// ============================================
// ODC/CD+ DETECTION (из sync-etm-stocks.js)
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

function sendRSWBStocksBatch(batch, warehouseId, retryCount = 0) {
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
    if (retryCount < RS_WB_MAX_RETRIES) {
      const delay = RS_WB_BASE_DELAY * Math.pow(2, retryCount);
      Logger.log(`⏳ WB transport error: ожидание ${delay/1000} сек перед retry ${retryCount + 1}/${RS_WB_MAX_RETRIES}...`);
      Utilities.sleep(delay);
      return sendRSWBStocksBatch(batch, warehouseId, retryCount + 1);
    }
    Logger.log(`⏭️ WB transport error: пропуск после ${RS_WB_MAX_RETRIES} попыток`);
    return { ok: false, code: 0, text: '', cargoRestriction: false };
  }

  const code = response.getResponseCode();
  const text = response.getContentText();

  if (code === 429 && retryCount < RS_WB_MAX_RETRIES) {
    const delay = RS_WB_BASE_DELAY * Math.pow(2, retryCount);
    Logger.log(`⏳ WB 429: ожидание ${delay/1000} сек перед retry ${retryCount + 1}/${RS_WB_MAX_RETRIES}...`);
    Utilities.sleep(delay);
    return sendRSWBStocksBatch(batch, warehouseId, retryCount + 1);
  }

  if (code === 429) {
    Logger.log(`⏭️ WB 429: пропуск после ${RS_WB_MAX_RETRIES} попыток`);
    return { ok: false, code, text, cargoRestriction: false };
  }

  return {
    ok: code === 200 || code === 204,
    code,
    text,
    cargoRestriction: code === 409 && isWBCargoRestrictionError(text)
  };
}

function processRSWBConflictIndividually(validBatch, warehouseId, batchLabel) {
  let successCount = 0;
  let skippedCount = 0;
  let errorCount = 0;

  Logger.log(`🔍 ${batchLabel}: дробление до отдельных товаров (${validBatch.length} шт)...`);

  for (let j = 0; j < validBatch.length; j++) {
    if (j > 0 && j % 5 === 0) {
      Utilities.sleep(3000);
    }

    const item = validBatch[j];
    const result = sendRSWBStocksBatch([item], warehouseId);

    if (result.ok) {
      successCount++;
      continue;
    }

    if (result.cargoRestriction) {
      Logger.log(`⏸️ ${batchLabel}: пропущен ODC/CD+ chrtId=${item.chrtId}, amount=${item.amount}`);
      skippedCount++;
      continue;
    }

    Logger.log(`❌ ${batchLabel}: ошибка для chrtId=${item.chrtId}, code=${result.code}`);
    errorCount++;
  }

  Logger.log(`📊 ${batchLabel}: поштучно ✅ ${successCount}, ⏸️ ${skippedCount}, ❌ ${errorCount}`);

  return { successCount, skippedCount, errorCount };
}

/**
 * Обновляет остатки на складе Wildberries FBS
 * @param {Array} stocks - Массив товаров
 * @param {number} warehouseId - ID склада
 */
function updateRSStocksWB(stocks, warehouseId) {
  Logger.log(`🟣 Обновление остатков WB FBS (склад ID: ${warehouseId})...`);

  // Фильтруем товары с chrt_id
  const validStocks = stocks.filter(s => s.chrt_id);

  if (validStocks.length === 0) {
    Logger.log(`⚠️ Нет товаров с chrtId для обновления WB`);
    Logger.log(`⚠️ Проверьте что колонка с chrtId заполнена`);
    return;
  }

  Logger.log(`📦 Товаров для обработки: ${validStocks.length}`);

  // Лимит: 200 товаров за запрос (для стабильности)
  const batchSize = 200;
  const batches = Math.ceil(validStocks.length / batchSize);

  let lastRequestTime = Date.now() - 1000 / WB_RPS();
  let successCount = 0;
  let skippedCount = 0;
  let errorCount = 0;

  for (let i = 0; i < batches; i++) {
    // Rate limiting
    lastRequestTime = rateLimitRPS(lastRequestTime, WB_RPS());

    const batch = validStocks.slice(i * batchSize, (i + 1) * batchSize);

    const validBatch = [];

    for (const item of batch) {
      // Используем chrtId
      const idNum = normalizeRSChrtId(item.chrt_id);

      // Валидация chrtId
      if (!idNum || isNaN(idNum) || !item.chrt_id) {
        Logger.log(`⚠️ Пропущен невалидный chrtId: ${item.chrt_id} (offer_id: ${item.offer_id})`);
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

    const result = sendRSWBStocksBatch(validBatch, warehouseId);

    if (result.ok) {
      successCount += validBatch.length;
      Logger.log(`✅ Пачка ${i + 1}/${batches} обработана (${validBatch.length} товаров)`);
      continue;
    }

    if (result.cargoRestriction) {
      Logger.log(`⚠️ WB 409 ODC/CD+ (пачка ${i + 1}/${batches}): дробление...`);
      const fallback = processRSWBConflictIndividually(validBatch, warehouseId, `Пачка ${i + 1}/${batches}`);
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

  Logger.log(`🟣 WB FBS: ✅ ${successCount} обновлено, ⏸️ ${skippedCount} пропущено ODC/CD+, ❌ ${errorCount} ошибок`);
}

/**
 * Выгружает данные из колонок "Артикул", "chrtId" и "Округление" на Ozon и WB
 */
function syncRSTableToMarketplaces() {
  Logger.log("=== ШАГ 2: ВЫГРУЗКА ИЗ ТАБЛИЦЫ НА МАРКЕТПЛЕЙСЫ ===");

  // Шаг 1: Читаем данные из Google Sheets
  Logger.log(`📊 Шаг 1: Чтение данных из листа "${RS_SHEET_NAME}"...`);
  const stocks = readRSStocksFromSheet();

  if (stocks.length === 0) {
    Logger.log("❌ Нет данных для синхронизации");
    return;
  }

  // Показываем примеры данных
  Logger.log(`📋 Примеры данных (первые 5):`);
  stocks.slice(0, 5).forEach(s => {
    Logger.log(`  - ${s.offer_id} | chrtId: ${s.chrt_id || '(нет)'} | Stock: ${s.stock}`);
  });

  // Шаг 2: Получаем ID складов
  Logger.log(``);
  Logger.log(`📦 Шаг 2: Использование фиксированных ID складов...`);

  const rsOzonId = RS_OZON_WAREHOUSE_ID;
  const rsWbId = RS_WB_WAREHOUSE_ID;

  Logger.log(`   - ФЕРОН ФБС (Ozon): ✅ ID: ${rsOzonId}`);
  Logger.log(`   - ВольтМир (WB): ✅ ID: ${rsWbId}`);

  // Шаг 3: Обновляем остатки Ozon
  Logger.log(``);
  Logger.log(`🟠 Шаг 3: Обновление остатков Ozon (ФЕРОН ФБС)...`);
  updateRSStocksOzon(stocks, rsOzonId);

  // Шаг 4: Обновляем остатки WB
  Logger.log(``);
  Logger.log(`🟣 Шаг 4: Обновление остатков WB FBS (ВольтМир)...`);
  // updateRSStocksWB(stocks, rsWbId); // Выгрузка на WB временно отключена.

  // Пост-проверка Ozon после завершения WB
  Logger.log(``);
  Logger.log(`🟠 Пост-проверка остатков Ozon после синхронизации WB...`);
  Logger.log(`⏳ Ожидание ${RS_OZON_POSTCHECK_DELAY_MS / 1000} сек...`);
  Utilities.sleep(RS_OZON_POSTCHECK_DELAY_MS);

  let mismatches = verifyRSOzonStocks(stocks, rsOzonId);
  if (mismatches > 0) {
    Logger.log(`⏳ Дополнительное ожидание ${RS_OZON_POSTCHECK_RETRY_DELAY_MS / 1000} сек перед повторной проверкой...`);
    Utilities.sleep(RS_OZON_POSTCHECK_RETRY_DELAY_MS);
    verifyRSOzonStocks(stocks, rsOzonId);
  }

  Logger.log("✅ Синхронизация с маркетплейсами завершена.");
}

// ============================================
// ГЛАВНАЯ ФУНКЦИЯ (совместимость с ARL подходом)
// ============================================

/**
 * Главная функция синхронизации остатков RS
 */
function syncRSStocks() {
  Logger.log("============================================");
  Logger.log("🔄 СИНХРОНИЗАЦИЯ ОСТАТКОВ RS (РуСВ)")
  Logger.log("============================================");

  const startTime = new Date();

  // Шаг 1: Читаем данные из Google Sheets
  Logger.log(`📊 Шаг 1: Чтение данных из листа "${RS_SHEET_NAME}"...`);
  const stocks = readRSStocksFromSheet();

  if (stocks.length === 0) {
    Logger.log("❌ Нет данных для синхронизации");
    return;
  }

  // Показываем примеры данных
  Logger.log(`📋 Примеры данных (первые 5):`);
  stocks.slice(0, 5).forEach(s => {
    Logger.log(`  - ${s.offer_id} | chrtId: ${s.chrt_id || '(нет)'} | Stock: ${s.stock}`);
  });

  // Шаг 2: Получаем ID складов
  Logger.log(``);
  Logger.log(`📦 Шаг 2: Использование фиксированных ID складов...`);

  const rsOzonId = RS_OZON_WAREHOUSE_ID;
  const rsWbId = RS_WB_WAREHOUSE_ID;

  Logger.log(`   - ФЕРОН ФБС (Ozon): ✅ ID: ${rsOzonId}`);
  Logger.log(`   - ВольтМир (WB): ✅ ID: ${rsWbId}`);

  // Шаг 3: Обновляем остатки Ozon
  Logger.log(``);
  Logger.log(`🟠 Шаг 3: Обновление остатков Ozon (ФЕРОН ФБС)...`);
  updateRSStocksOzon(stocks, rsOzonId);

  // Шаг 4: Обновляем остатки WB
  Logger.log(``);
  Logger.log(`🟣 Шаг 4: Обновление остатков WB FBS (ВольтМир)...`);
  // updateRSStocksWB(stocks, rsWbId); // Выгрузка на WB временно отключена.

  // Шаг 5: Пост-проверка Ozon после завершения WB
  Logger.log(``);
  Logger.log(`🟠 Шаг 5: Пост-проверка остатков Ozon после синхронизации WB...`);
  Logger.log(`⏳ Ожидание ${RS_OZON_POSTCHECK_DELAY_MS / 1000} сек перед пост-проверкой...`);
  Utilities.sleep(RS_OZON_POSTCHECK_DELAY_MS);

  let rsOzonMismatches = verifyRSOzonStocks(stocks, rsOzonId);
  if (rsOzonMismatches > 0) {
    Logger.log(`⏳ Дополнительное ожидание ${RS_OZON_POSTCHECK_RETRY_DELAY_MS / 1000} сек перед повторной проверкой...`);
    Utilities.sleep(RS_OZON_POSTCHECK_RETRY_DELAY_MS);
    verifyRSOzonStocks(stocks, rsOzonId);
  }

  const endTime = new Date();
  const duration = Math.round((endTime - startTime) / 1000);

  Logger.log(``);
  Logger.log("============================================");
  Logger.log(`✅ Синхронизация завершена за ${duration} сек.`);
  Logger.log("============================================");
}

// ============================================
// ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (ДЛЯ BATCH UPDATE)
// ============================================

function updateRSStocksOzonBatch(stocks, warehouseId) {
  const batchSize = 100;
  for (let i = 0; i < stocks.length; i += batchSize) {
    const batch = stocks.slice(i, i + batchSize);
    const body = {
      stocks: batch.map(item => ({
        offer_id: item.offer_id,
        stock: item.stock,
        warehouse_id: warehouseId
      }))
    };
    const options = {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify(body),
      muteHttpExceptions: true
    };
    retryFetch("https://api-seller.ozon.ru/v2/products/stocks", options);
  }
}

function updateRSStocksWBBatch(stocks, warehouseId) {
  const batchSize = 1000;
  let lastRequestTime = Date.now() - 1000 / WB_RPS();

  for (let i = 0; i < stocks.length; i += batchSize) {
    lastRequestTime = rateLimitRPS(lastRequestTime, WB_RPS());

    const batch = stocks.slice(i, i + batchSize);
    const validBatch = [];

    for (const item of batch) {
      const chrtId = normalizeRSChrtId(item.chrt_id);
      if (!chrtId || chrtId <= 0) {
        Logger.log(`⚠️ Пропущен невалидный chrtId: raw="${item.chrt_id}" (offer_id: ${item.offer_id})`);
        continue;
      }

      validBatch.push({
        chrtId,
        amount: item.stock
      });
    }

    if (validBatch.length === 0) {
      Logger.log(`⏸️ Пачка ${Math.floor(i / batchSize) + 1} пропущена: нет валидных chrtId`);
      continue;
    }

    const options = {
      method: "put",
      contentType: "application/json",
      headers: wbHeaders(),
      payload: JSON.stringify({ stocks: validBatch }),
      muteHttpExceptions: true
    };

    const response = retryFetch(`https://marketplace-api.wildberries.ru/api/v3/stocks/${warehouseId}`, options);
    if (!response) {
      Logger.log(`❌ WB: нет ответа по пачке ${Math.floor(i / batchSize) + 1}`);
      continue;
    }

    const code = response.getResponseCode();
    const text = response.getContentText();
    if (code !== 200 && code !== 204) {
      Logger.log(`❌ WB API ошибка по пачке ${Math.floor(i / batchSize) + 1}: ${code}`);
      Logger.log((text || "").substring(0, 500));
    } else {
      Logger.log(`✅ WB пачка ${Math.floor(i / batchSize) + 1} отправлена (${validBatch.length} товаров)`);
    }
  }
}
