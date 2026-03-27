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

const RS_OZON_WAREHOUSE_ID = 1020005000234124;  // ФЕРОН ФБС

const RS_WB_WAREHOUSE_ID = 798761;              // ВольтМир


// Фоллбек колонки (если заголовки не найдены)
const RS_COL_VENDOR_CODE = 2; // B - Модель
const RS_COL_ARTICUL = 1;     // A - Артикул (offer_id Ozon)
const RS_COL_CHRT_ID = 9;     // I - chrlid (WB) - ИСПРАВЛЕНО с 10 на 9
const RS_COL_STOCK_API = 6;   // F - Остаток АПИ
const RS_COL_COOLING = 7;     // G - Охлад
const RS_COL_ROUNDED = 8;     // H - Округление (Stock для выгрузки)

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

    const stock = parseInt(stockForUpload) || 0;

    stocks.push({
      offer_id: offerId,    // offer_id для Ozon
      chrt_id: chrtId,      // chrtId для WB
      stock: stock
    });
  }

  Logger.log(`📊 Прочитано ${stocks.length} товаров из листа "${RS_SHEET_NAME}"`);

  // Статистика
  const withStock = stocks.filter(s => s.stock > 0).length;
  const withChrtId = stocks.filter(s => s.chrt_id).length;
  Logger.log(`   С остатком > 0: ${withStock}`);
  Logger.log(`   С chrtId: ${withChrtId}`);

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

  // Фильтруем товары с offer_id и stock > 0
  const validStocks = stocks.filter(s => s.offer_id && s.stock > 0);

  if (validStocks.length === 0) {
    Logger.log(`⚠️ Нет товаров с offer_id и stock > 0 для обновления Ozon`);
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

  // Лимит: 1000 товаров за запрос (для стабильности)
  const batchSize = 1000;
  const batches = Math.ceil(validStocks.length / batchSize);

  let lastRequestTime = Date.now() - 1000 / WB_RPS();
  let successCount = 0;
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
        chrtId: idNum,  // chrtId
        amount: item.stock  // 0 тоже валидное значение
      });
    }

    if (validBatch.length === 0) {
      Logger.log(`⏸️ Пачка ${i + 1}/${batches} пропущена (нет валидных chrtId)`);
      continue;
    }

    const body = {
      stocks: validBatch  // "stocks" (множественное число)
    };

    const url = `https://marketplace-api.wildberries.ru/api/v3/stocks/${warehouseId}`;

    const options = {
      method: "put",  // WB требует PUT метод
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
    const responseText = response.getContentText();

    if (responseCode !== 200 && responseCode !== 204) {
      Logger.log(`❌ Ошибка API (пачка ${i + 1}/${batches}): ${responseCode}`);

      try {
        const result = JSON.parse(responseText);
        if (result.errors) {
          Logger.log(`❌ WB API ошибки: ${JSON.stringify(result.errors).substring(0, 500)}`);
        }
      } catch (e) {
        Logger.log(responseText.substring(0, 500));
      }

      errorCount += validBatch.length;
      continue;
    }

    successCount += validBatch.length;
    Logger.log(`✅ Пачка ${i + 1}/${batches} обработана (${validBatch.length} товаров)`);
  }

  Logger.log(`🟣 WB FBS: ✅ ${successCount} обновлено, ❌ ${errorCount} ошибок`);
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
  updateRSStocksWB(stocks, rsWbId);

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
  updateRSStocksWB(stocks, rsWbId);

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
