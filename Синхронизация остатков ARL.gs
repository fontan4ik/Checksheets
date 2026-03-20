/**
 * СИНХРОНИЗАЦИЯ ОСТАТКОВ С ЛИСТА "ARL TR"
 *
 * Читает остатки из листа "ARL TR" и выгружает на склады:
 * - Ozon: Арлайт Москва
 * - WB: ФБС Ферон Москва
 *
 * Структура листа "ARL TR":
 * A: Артикул продавца (vendorCode) ← ключ для Ozon
 * B-I: (другие данные)
 * J: chrtId (ID размера для WB API) ✅ уже заполнен
 * ... остаток для выгрузки (укажите колонку в COL_STOCK ниже)
 *
 * ⚠️ ВАЖНО (с 9 февраля 2026):
 * WB API требует chrtId вместо sku.
 * Колонка J должна быть заполнена chrtId.
 */

// ============================================
// КОНФИГУРАЦИЯ
// ============================================

const ARL_SHEET_NAME = "ARL TR";
const ARL_OZON_WAREHOUSE_ID = 1020005004656250;  // Арлайт Москва
const ARL_WB_WAREHOUSE_ID = 1449484;               // ФБС ФЕРОН МОСКВА

// Колонки в листе "ARL TR"
const COL_VENDOR_CODE = 1;   // A - Артикул продавца (offer_id)
const COL_NMID = 5;          // E - SKU WB (nmID)
const COL_CHRT_ID = 10;       // J - chrtId для WB API
const COL_STOCK = 9;         // I - Остаток для выгрузки
const COL_PRICE = 16;        // P - Выставляемая цена для выгрузки

// ============================================
// ЧТЕНИЕ ДАННЫХ ИЗ GOOGLE SHEETS
// ============================================

/**
 * Читает данные из листа "ARL TR"
 * @returns {Array} Массив объектов с данными товаров
 */
function readARLStocksFromSheet() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(ARL_SHEET_NAME);

  if (!sheet) {
    Logger.log(`❌ Лист "${ARL_SHEET_NAME}" не найден!`);
    return [];
  }

  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log(`❌ Нет данных на листе "${ARL_SHEET_NAME}"`);
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

  const dynamicColVendor = findCol("Артикул продавца", COL_VENDOR_CODE);
  const dynamicColNmId = findCol("SKU WB", COL_NMID);
  const dynamicColChrtId = findCol("chrtid", COL_CHRT_ID);
  const dynamicColStock = findCol("Округлённое", COL_STOCK);
  const dynamicColPriceOzon = findCol("Выставляемая цена", COL_PRICE);
  const dynamicColPriceWb = findCol("Выставляемая цена", COL_PRICE); // Использовать ту же выставляеную цену для WB

  Logger.log(`🔍 Колонки: Артикул=${dynamicColVendor}, nmID=${dynamicColNmId}, chrtId=${dynamicColChrtId}, Остаток=${dynamicColStock}, Цена Ozon=${dynamicColPriceOzon}, Цена WB=${dynamicColPriceWb}`);

  // 🔎 ДИАГНОСТИКА: показываем заголовки колонок 14-18 и значения первого товара
  Logger.log(`🔎 ДИАГНОСТИКА заголовков (кол. 14-18):`);
  for (let c = 13; c < Math.min(18, headers.length); c++) {
    Logger.log(`   Колонка ${c+1}: "${headers[c]}"`);
  }
  const firstRow = sheet.getRange(2, 1, 1, Math.min(18, lastCol)).getValues()[0];
  Logger.log(`🔎 ДИАГНОСТИКА первый товар (кол. 14-18):`);
  Logger.log(`   Артикул: ${firstRow[0]}`);
  for (let c = 13; c < Math.min(18, firstRow.length); c++) {
    Logger.log(`   Колонка ${c+1}: "${firstRow[c]}"`);
  }

  // Читаем нужные колонки
  const maxCol = Math.max(dynamicColVendor, dynamicColNmId, dynamicColChrtId, dynamicColStock, dynamicColPriceOzon, dynamicColPriceWb);
  const data = sheet.getRange(2, 1, lastRow - 1, maxCol).getValues();

  const stocks = [];

  for (let i = 0; i < data.length; i++) {
    const row = data[i];

    const vendorCode = row[dynamicColVendor - 1];
    const nmIdValue = row[dynamicColNmId - 1];
    const chrtId = row[dynamicColChrtId - 1];
    const stockForUpload = row[dynamicColStock - 1];
    const priceOzonVal = row[dynamicColPriceOzon - 1];
    const priceWbVal = row[dynamicColPriceWb - 1];

    // Пропускаем пустые строки
    if (!vendorCode) {
      continue;
    }

    const stock = parseInt(stockForUpload) || 0;
    
    // Очистка цен от пробелов и валют
    const priceOzon = Math.floor(parseFloat(String(priceOzonVal).replace(/[^0-9.,]/g, '').replace(',', '.'))) || 0;
    const priceWb = Math.floor(parseFloat(String(priceWbVal).replace(/[^0-9.,]/g, '').replace(',', '.'))) || 0;

    stocks.push({
      offer_id: vendorCode,    // vendorCode для Ozon
      nm_id: nmIdValue,        // nmID для WB цены
      chrt_id: chrtId,         // chrtId для WB остатков
      stock: stock,
      price_ozon: priceOzon,   // цена для Ozon
      price_wb: priceWb        // цена для WB
    });
  }

  Logger.log(`📊 Прочитано ${stocks.length} товаров из листа "${ARL_SHEET_NAME}"`);

  // Статистика
  const withStock = stocks.filter(s => s.stock > 0).length;
  const withChrtId = stocks.filter(s => s.chrt_id).length;
  const withPriceO = stocks.filter(s => s.price_ozon > 0).length;
  const withPriceW = stocks.filter(s => s.price_wb > 0).length;
  Logger.log(`   С остатком > 0: ${withStock}`);
  Logger.log(`   С chrtId: ${withChrtId}`);
  Logger.log(`   С ценой Ozon > 0: ${withPriceO}`);
  Logger.log(`   С ценой WB > 0: ${withPriceW}`);

  return stocks;
}

// ============================================
// ПОЛУЧЕНИЕ ID СКЛАДОВ
// ============================================

/**
 * Находит ID склада Арлайт Москва для Ozon
 * @returns {number} ID склада
 */
function getArlightOzonWarehouseId() {
  Logger.log(`🔍 Склад Ozon: Арлайт Москва (ID: ${ARL_OZON_WAREHOUSE_ID})`);
  return ARL_OZON_WAREHOUSE_ID;
}

/**
 * Находит ID склада ФБС Ферон Москва для WB
 * @returns {number} ID склада
 */
function getFeronWBWarehouseId() {
  Logger.log(`🔍 Склад WB: ФБС ФЕРОН МОСКВА (ID: ${ARL_WB_WAREHOUSE_ID})`);
  return ARL_WB_WAREHOUSE_ID;
}

// ============================================
// ОБНОВЛЕНИЕ ОСТАТКОВ OZON
// ============================================

/**
 * Обновляет остатки на складе Ozon
 * @param {Array} stocks - Массив товаров
 * @param {number} warehouseId - ID склада
 */
function updateARLStocksOzon(stocks, warehouseId) {
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

// ============================================
// ОБНОВЛЕНИЕ ОСТАТКОВ WILDBERRIES (FBS)
// ============================================

/**
 * Обновляет остатки на складе Wildberries FBS
 * @param {Array} stocks - Массив товаров
 * @param {number} warehouseId - ID склада
 */
function updateARLStocksWB(stocks, warehouseId) {
  Logger.log(`🟣 Обновление остатков WB FBS (склад ID: ${warehouseId})...`);

  // Фильтруем товары с chrt_id
  const validStocks = stocks.filter(s => s.chrt_id);

  if (validStocks.length === 0) {
    Logger.log(`⚠️ Нет товаров с chrtId для обновления WB`);
    Logger.log(`⚠️ Проверьте что колонка J (chrtId) заполнена`);
    return;
  }

  Logger.log(`📦 Товаров для обработки: ${validStocks.length}`);

  // Лимит: 200 товаров за запрос (для стабильности)
  const batchSize = 200;
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
      // ✅ Используем chrtId из колонки J
      const idNum = Number(item.chrt_id);

      // Валидация chrtId
      if (isNaN(idNum) || !item.chrt_id) {
        Logger.log(`⚠️ Пропущен невалидный chrtId: ${item.chrt_id} (offer_id: ${item.offer_id})`);
        errorCount++;
        continue;
      }

      validBatch.push({
        chrtId: idNum,  // ✅ chrtId из колонки J
        amount: item.stock  // 0 тоже валидное значение
      });
    }

    if (validBatch.length === 0) {
      Logger.log(`⏸️ Пачка ${i + 1}/${batches} пропущена (нет валидных chrtId)`);
      continue;
    }

    const body = {
      stocks: validBatch  // ✅ "stocks" (множественное число)
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

// ============================================
// ОБНОВЛЕНИЕ ЦЕН OZON
// ============================================

/**
 * Обновляет цены на Ozon
 * @param {Array} stocks - Массив товаров с ценами
 */
function updateARLPricesOzon(stocks) {
  Logger.log(`🟢 Обновление цен Ozon...`);

  // Если функция запущена вручную напрямую
  if (!stocks) {
    Logger.log(`📥 Извлечение данных из таблицы, так как функция запущена отдельно...`);
    stocks = readARLStocksFromSheet();
  }

  if (!stocks || stocks.length === 0) {
    Logger.log(`⚠️ Нет данных для обновления цен Ozon`);
    return;
  }

  // Фильтруем товары с offer_id, ценой и остатком > 0
  const validStocks = stocks.filter(s => s.offer_id && s.price_ozon > 0 && s.stock > 0);

  const zeroStockCount = stocks.filter(s => s.offer_id && s.price_ozon > 0 && s.stock <= 0).length;
  if (zeroStockCount > 0) {
    Logger.log(`⏭️ Пропущено товаров с остатком 0 для Ozon: ${zeroStockCount}`);
  }

  if (validStocks.length === 0) {
    Logger.log(`⚠️ Нет товаров с offer_id и ценой для обновления Ozon`);
    return;
  }

  Logger.log(`📦 Товаров для обработки: ${validStocks.length}`);

  // Лимит: 1000 товаров за запрос
  const batchSize = 1000;
  const batches = Math.ceil(validStocks.length / batchSize);

  let lastRequestTime = Date.now() - 1000 / RPS();
  let successCount = 0;
  let errorCount = 0;

  for (let i = 0; i < batches; i++) {
    // Rate limiting
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

    const batch = validStocks.slice(i * batchSize, (i + 1) * batchSize);

    const validBatch = [];

    for (const item of batch) {
      const priceValue = parseFloat(item.price_ozon);

      // Валидация offer_id и цены
      if (!item.offer_id || priceValue <= 0) {
        Logger.log(`⚠️ Пропущен невалидный элемент: offer_id=${item.offer_id}, цена=${item.price_ozon}`);
        errorCount++;
        continue;
      }

      validBatch.push({
        offer_id: String(item.offer_id),  // offer_id из колонки A
        price: String(priceValue),
        old_price: "0", // 0 чтобы сбросить или не использовать
        min_price: "0",
        currency_code: "RUB"
      });
    }

    if (validBatch.length === 0) {
      Logger.log(`⏸️ Пачка ${i + 1}/${batches} пропущена (нет валидных элементов)`);
      continue;
    }

    const body = {
      prices: validBatch  // "prices" для Ozon API
    };

    const url = `https://api-seller.ozon.ru/v1/product/import/prices`;

    const options = {
      method: "post",  // Ozon использует POST метод для обновления цен
      contentType: "application/json",
      headers: ozonHeaders(),
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

    if (responseCode !== 200) {
      Logger.log(`❌ Ошибка API (пачка ${i + 1}/${batches}): ${responseCode}`);

      try {
        const result = JSON.parse(responseText);
        if (result.error) {
          Logger.log(`❌ Ozon API ошибка: ${JSON.stringify(result.error).substring(0, 500)}`);
        }
      } catch (e) {
        Logger.log(responseText.substring(0, 500));
      }

      errorCount += validBatch.length;
      continue;
    }

    const result = JSON.parse(responseText);

    if (result.result && result.result.task_id) {
      Logger.log(`✅ Пачка ${i + 1}/${batches} отправлена на обработку, task_id: ${result.result.task_id}`);
      successCount += validBatch.length;
    } else {
      Logger.log(`❌ Пачка ${i + 1}/${batches} не была обработана корректно`);
      errorCount += validBatch.length;
    }
  }

  Logger.log(`🟢 Ozon Цены: ✅ ${successCount} обновлено, ❌ ${errorCount} ошибок`);
}

// ============================================
// ОБНОВЛЕНИЕ ЦЕН WILDBERRIES
// ============================================

/**
 * Обновляет цены на Wildberries
 * @param {Array} stocks - Массив товаров с ценами
 */
function updateARLPricesWB(stocks) {
  Logger.log(`🟡 Обновление цен WB...`);

  // Если функция запущена вручную напрямую
  if (!stocks) {
    Logger.log(`📥 Извлечение данных из таблицы, так как функция запущена отдельно...`);
    stocks = readARLStocksFromSheet();
  }

  if (!stocks || stocks.length === 0) {
    Logger.log(`⚠️ Нет данных для обновления цен WB`);
    return;
  }

  // Список nmID товаров, которые НЕ нужно обновлять на WB
  const excludedNmIds = [
    489278756, 496999561, 669242824, 496999610, 
    496999577, 497000509, 496999558, 496999574, 
    669242859, 497000511, 669242747, 497000793, 
    497000792, 497000510, 497000508, 496957697
  ];

  // Фильтруем товары с nm_id и ценой, исключая заданные nmID и товары с нулевым остатком
  const validStocks = stocks.filter(s => 
    s.nm_id && 
    s.price_wb > 0 && 
    s.stock > 0 && 
    !excludedNmIds.includes(Number(s.nm_id))
  );

  const zeroStockCount = stocks.filter(s => s.nm_id && s.price_wb > 0 && s.stock <= 0).length;
  if (zeroStockCount > 0) {
    Logger.log(`⏭️ Пропущено товаров с остатком 0 для WB: ${zeroStockCount}`);
  }

  const excludedCount = stocks.filter(s => s.nm_id && s.price_wb > 0 && excludedNmIds.includes(Number(s.nm_id))).length;
  if (excludedCount > 0) {
    Logger.log(`⏭️ Пропущено товаров по списку исключений: ${excludedCount}`);
  }

  if (validStocks.length === 0) {
    Logger.log(`⚠️ Нет товаров с nmID и ценой для обновления WB`);
    Logger.log(`⚠️ Проверьте что колонка E (nmID) и колонка FBS заполнены`);
    return;
  }

  Logger.log(`📦 Товаров для обработки: ${validStocks.length}`);

  // ЛИМИТ: 100 товаров (API v2 стабильно работает с пачками до 1000)
  const batchSize = 100;
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
      const nmId = Number(item.nm_id);
      const priceValue = Math.floor(item.price_wb); // WB принимает целые числа

      // Валидация nmId и цены
      if (isNaN(nmId) || !item.nm_id || priceValue <= 0) {
        Logger.log(`⚠️ Пропущен невалидный элемент: nmID=${item.nm_id}, цена=${item.price_wb}`);
        errorCount++;
        continue;
      }

      validBatch.push({
        nmID: nmId,  // ✅ nmID из колонки E
        price: priceValue
      });
    }

    if (validBatch.length === 0) {
      Logger.log(`⏸️ Пачка ${i + 1}/${batches} пропущена (нет валидных элементов)`);
      continue;
    }

    const body = {
      data: validBatch  // ✅ "data"
    };

    const url = `https://discounts-prices-api.wildberries.ru/api/v2/upload/task`;

    const options = {
      method: "POST",  // WB требует POST метод для обновления цен
      contentType: "application/json; charset=utf-8",
      headers: {
        ...wbHeaders(),
        "Accept": "application/json"
      },
      payload: JSON.stringify(body),
      muteHttpExceptions: true
    };

    if (i === 0) {
      Logger.log(`📤 Тестовый payload (первая пачка): ${JSON.stringify(body).substring(0, 500)}`);
    }

    const response = retryFetch(url, options);

    // Дополнительная пауза между пачками для WB (v2 лимитирован)
    Utilities.sleep(3000);

    if (!response) {
      Logger.log(`❌ Ошибка запроса (нет ответа) (пачка ${i + 1}/${batches})`);
      errorCount += validBatch.length;
      continue;
    }

    const responseCode = response.getResponseCode();
    const responseText = response.getContentText();

    if (responseCode !== 200 && responseCode !== 201) {
      try {
        const result = JSON.parse(responseText);
        
        // WB API 400 error: "Such prices and discounts are already set"
        if (responseCode === 400 && result.errorText === "Such prices and discounts are already set") {
          Logger.log(`✅ Пачка ${i + 1}/${batches}: Цены на WB уже актуальны (изменений не требуется)`);
          successCount += validBatch.length;
          continue;
        }

        Logger.log(`❌ Ошибка API (пачка ${i + 1}/${batches}): ${responseCode}`);
        if (result.errors || result.errorText || result.error) {
          Logger.log(`❌ WB API ошибки: ${JSON.stringify(result.errors || result.errorText || result.error).substring(0, 1000)}`);
        }
      } catch (e) {
        Logger.log(`❌ Ошибка API (пачка ${i + 1}/${batches}): ${responseCode}`);
        Logger.log(`❌ Тело ответа: ${responseText.substring(0, 1000)}`);
      }

      errorCount += validBatch.length;
      continue;
    }

    Logger.log(`✅ Пачка ${i + 1}/${batches} отправлена успешно (${validBatch.length} товаров)`);
    successCount += validBatch.length;
  }

  Logger.log(`🟡 WB Цены: ✅ ${successCount} обновлено, ❌ ${errorCount} ошибок`);
}

// ============================================
// ГЛАВНАЯ ФУНКЦИЯ
// ============================================

/**
 * Главная функция синхронизации остатков ARL
 */
function syncARLStocks() {
  Logger.log("============================================");
  Logger.log("🔄 СИНХРОНИЗАЦИЯ ОСТАТКОВ ARL (Arlight)");
  Logger.log("============================================");

  const startTime = new Date();

  // Шаг 1: Читаем данные из Google Sheets
  Logger.log(`📊 Шаг 1: Чтение данных из листа "${ARL_SHEET_NAME}"...`);
  const stocks = readARLStocksFromSheet();

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
  Logger.log(`📦 Шаг 2: Получение ID складов...`);

  const arlightOzonId = getArlightOzonWarehouseId();
  const feronWbId = getFeronWBWarehouseId();

  // Шаг 3: Обновляем остатки Ozon
  Logger.log(``);
  Logger.log(`🟠 Шаг 3: Обновление остатков Ozon (Арлайт Москва)...`);
  updateARLStocksOzon(stocks, arlightOzonId);

  // Шаг 4: Обновляем остатки WB
  Logger.log(``);
  Logger.log(`🟣 Шаг 4: Обновление остатков WB FBS (ФБС Ферон Москва)...`);
  updateARLStocksWB(stocks, feronWbId);



  const endTime = new Date();
  const duration = Math.round((endTime - startTime) / 1000);

  Logger.log(``);
  Logger.log("============================================");
  Logger.log(`✅ Синхронизация завершена за ${duration} сек.`);
  Logger.log("============================================");
}

// ============================================
// ТЕСТОВЫЕ ФУНКЦИИ
// ============================================

/**
 * Тестовая функция - проверяет чтение данных и поиск складов
 */
function testARLStockSync() {
  Logger.log("============================================");
  Logger.log("🧪 ТЕСТ СИНХРОНИЗАЦИИ ОСТАТКОВ ARL");
  Logger.log("============================================");

  // Тест 1: Чтение данных
  Logger.log(``);
  Logger.log(`📊 Тест 1: Чтение данных из листа...`);
  const stocks = readARLStocksFromSheet();

  if (stocks.length === 0) {
    Logger.log("❌ Нет данных");
    return;
  }

  Logger.log(`✅ Прочитано ${stocks.length} товаров`);
  Logger.log(`📋 Первые 5 товаров:`);
  stocks.slice(0, 5).forEach(s => {
    Logger.log(`  - offer_id: ${s.offer_id}, chrt_id: ${s.chrt_id || '(нет)'}, stock: ${s.stock}`);
  });

  // Подсчёт с остатком > 0
  const withStock = stocks.filter(s => s.stock > 0).length;
  const withChrtId = stocks.filter(s => s.chrt_id).length;
  Logger.log(``);
  Logger.log(`📦 С остатком > 0: ${withStock}`);
  Logger.log(`📦 С остатком = 0: ${stocks.length - withStock}`);
  Logger.log(`📦 С chrtId: ${withChrtId}`);

  // Тест 2: Проверка складов
  Logger.log(``);
  Logger.log(`📦 Тест 2: Проверка складов...`);

  const arlightOzonId = getArlightOzonWarehouseId();
  const feronWbId = getFeronWBWarehouseId();

  Logger.log(``);
  Logger.log(`Результат:`);
  Logger.log(`  - Арлайт Москва (Ozon): ✅ ID: ${arlightOzonId}`);
  Logger.log(`  - ФБС Ферон Москва (WB): ✅ ID: ${feronWbId}`);

  // Тест 3: Подготовка данных для Ozon
  Logger.log(``);
  Logger.log(`🟠 Тест 3: Подготовка данных для Ozon...`);

  const ozonStocks = stocks.filter(s => s.offer_id && s.stock > 0);
  Logger.log(`  Товаров с offer_id и stock > 0: ${ozonStocks.length}`);

  if (ozonStocks.length > 0) {
    Logger.log(`  Примеры payload (первые 3):`);
    ozonStocks.slice(0, 3).forEach(s => {
      Logger.log(`    { offer_id: "${s.offer_id}", stock: ${s.stock}, warehouse_id: ${arlightOzonId} }`);
    });
  }

  // Тест 4: Подготовка данных для WB
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

  // Тест 5: Подготовка данных для цен Ozon
  Logger.log(``);
  Logger.log(`🟢 Тест 5: Подготовка данных для цен Ozon...`);

  const ozonPrices = stocks.filter(s => s.offer_id && s.price_ozon > 0 && s.stock > 0);
  Logger.log(`  Товаров с offer_id, ценой и остатком > 0: ${ozonPrices.length}`);

  if (ozonPrices.length > 0) {
    Logger.log(`  Примеры payload для цен (первые 3):`);
    ozonPrices.slice(0, 3).forEach(s => {
      Logger.log(`    { offer_id: "${s.offer_id}", price: ${s.price_ozon} }`);
    });
  }

  // Тест 6: Подготовка данных для цен WB
  Logger.log(``);
  Logger.log(`🟡 Тест 6: Подготовка данных для цен WB...`);

  const wbPrices = stocks.filter(s => s.nm_id && s.price_wb > 0 && s.stock > 0);
  Logger.log(`  Товаров с nmID, ценой и остатком > 0: ${wbPrices.length}`);

  if (wbPrices.length > 0) {
    Logger.log(`  Примеры payload для цен (первые 3):`);
    wbPrices.slice(0, 3).forEach(s => {
      Logger.log(`    { nmID: ${s.nm_id}, price: ${Math.floor(s.price_wb)} }`);
    });
  }

  Logger.log(``);
  Logger.log("============================================");
  Logger.log(`✅ Тест завершён`);
  Logger.log(``);
  Logger.log(`Для запуска полноценной синхронизации выполните:`);
  Logger.log(`  syncARLStocks()`);
  Logger.log("============================================");
}

/**
 * Тестовая функция для проверки выгрузки цен на Ozon
 * Использует offer_id из колонки A и цены из колонки O
 */
function testOzonPriceUpload() {
  Logger.log("============================================");
  Logger.log("🧪 ТЕСТ ВЫГРУЗКИ ЦЕН НА OZON");
  Logger.log("============================================");

  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(ARL_SHEET_NAME);

  if (!sheet) {
    Logger.log(`❌ Лист "${ARL_SHEET_NAME}" не найден!`);
    return;
  }

  // Читаем первую строку с данными для теста
  const maxCol = Math.max(COL_VENDOR_CODE, COL_CHRT_ID, COL_STOCK, COL_PRICE);
  const data = sheet.getRange(2, 1, 1, maxCol).getValues()[0];

  const vendorCode = data[COL_VENDOR_CODE - 1];  // A
  const price = data[COL_PRICE - 1];             // O

  if (!vendorCode) {
    Logger.log(`❌ offer_id не найден в первой строке!`);
    Logger.log(``);
    Logger.log(`⚠️ Проверьте что колонка A (offer_id) заполнена`);
    return;
  }

  if (!price) {
    Logger.log(`❌ Цена не найдена в колонке O!`);
    Logger.log(``);
    Logger.log(`⚠️ Проверьте что колонка O (Цена) заполнена`);
    return;
  }

  const testVendorCode = String(vendorCode);
  const testPrice = parseFloat(price) || 1000;

  Logger.log(`📋 Тестовые данные:`);
  Logger.log(`  offer_id: ${testVendorCode}`);
  Logger.log(`  Цена: ${testPrice}`);
  Logger.log(``);

  const body = {
    prices: [
      {
        offer_id: testVendorCode,  // offer_id из колонки A
        price: String(testPrice),
        old_price: "0",
        min_price: "0",
        currency_code: "RUB"
      }
    ]
  };

  const url = `https://api-seller.ozon.ru/v1/product/import/prices`;

  Logger.log(`📤 URL: ${url}`);
  Logger.log(`📤 Method: POST`);
  Logger.log(`📤 Payload: ${JSON.stringify(body)}`);
  Logger.log(``);

  const options = {
    method: "post",
    contentType: "application/json",
    headers: ozonHeaders(),
    payload: JSON.stringify(body),
    muteHttpExceptions: true
  };

  Logger.log(`🔄 Отправка запроса...`);

  try {
    const response = UrlFetchApp.fetch(url, options);
    const responseCode = response.getResponseCode();
    const responseText = response.getContentText();

    Logger.log(``);
    Logger.log(`📥 РЕЗУЛЬТАТ:`);
    Logger.log(`  Status Code: ${responseCode}`);

    if (responseText) {
      Logger.log(`  Response Body: ${responseText.substring(0, 500)}`);
    }

    Logger.log(``);

    if (responseCode === 200) {
      try {
        const result = JSON.parse(responseText);
        if (result.result && result.result.task_id) {
          Logger.log(`✅ УСПЕХ! Цены успешно отправлены на обработку.`);
          Logger.log(`📋 Task ID: ${result.result.task_id}`);
        } else {
          Logger.log(`⚠️ Ответ получен, но структура неожиданная: ${responseText.substring(0, 200)}`);
        }
      } catch (e) {
        Logger.log(`✅ УСПЕХ! Status: ${responseCode}`);
      }
    } else {
      Logger.log(`❌ ОШИБКА! Status: ${responseCode}`);
      try {
        const result = JSON.parse(responseText);
        if (result.error) {
          Logger.log(`Ошибки API:`);
          Logger.log(`  - ${JSON.stringify(result.error)}`);
        }
      } catch (e) {
        // Не JSON ответ
      }
    }

  } catch (error) {
    Logger.log(``);
    Logger.log(`❌ ИСКЛЮЧЕНИЕ:`);
    Logger.log(`  ${error.toString()}`);
  }

  Logger.log("============================================");
  Logger.log(``);
  Logger.log(`📝 Если тест прошёл успешно, выполните:`);
  Logger.log(`  syncARLStocks() - для полной синхронизации`);
  Logger.log("============================================");
}

/**
 * Тестовая функция для проверки выгрузки цен на WB
 * Использует chrtId из колонки J и цены из колонки O
 */
function testWBPriceUpload() {
  Logger.log("============================================");
  Logger.log("🧪 ТЕСТ ВЫГРУЗКИ ЦЕН НА WB");
  Logger.log("============================================");

  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(ARL_SHEET_NAME);

  if (!sheet) {
    Logger.log(`❌ Лист "${ARL_SHEET_NAME}" не найден!`);
    return;
  }

  // Читаем первую строку с данными для теста
  const maxCol = Math.max(COL_VENDOR_CODE, COL_CHRT_ID, COL_STOCK, COL_PRICE, COL_NMID);
  const data = sheet.getRange(2, 1, 1, maxCol).getValues()[0];

  const vendorCode = data[COL_VENDOR_CODE - 1];  // A
  const nmId = data[COL_NMID - 1];               // E
  const price = data[COL_PRICE - 1];             // O

  if (!nmId) {
    Logger.log(`❌ nmID не найден в первой строке!`);
    Logger.log(``);
    Logger.log(`⚠️ Проверьте что колонка E (nmID) заполнена`);
    return;
  }

  if (!price) {
    Logger.log(`❌ Цена не найдена в колонке P!`);
    Logger.log(``);
    Logger.log(`⚠️ Проверьте что колонка P (Цена) заполнена`);
    return;
  }

  const testNmId = Number(nmId);
  const testPrice = Math.floor(parseFloat(price) || 1000); // Преобразуем в целое число

  Logger.log(`📋 Тестовые данные:`);
  Logger.log(`  offer_id: ${vendorCode}`);
  Logger.log(`  nmID: ${testNmId}`);
  Logger.log(`  Цена: ${testPrice}`);
  Logger.log(``);

  const body = {
    data: [
      {
        nmID: testNmId,  // ✅ nmID из колонки E
        price: testPrice
      }
    ]
  };

  const url = `https://discounts-prices-api.wildberries.ru/api/v2/upload/task`;

  Logger.log(`📤 URL: ${url}`);
  Logger.log(`📤 Method: POST`);
  Logger.log(`📤 Payload: ${JSON.stringify(body)}`);
  Logger.log(``);

  const options = {
    method: "post",
    contentType: "application/json",
    headers: wbHeaders(),
    payload: JSON.stringify(body),
    muteHttpExceptions: true
  };

  Logger.log(`🔄 Отправка запроса...`);

  try {
    const response = UrlFetchApp.fetch(url, options);
    const responseCode = response.getResponseCode();
    const responseText = response.getContentText();

    Logger.log(``);
    Logger.log(`📥 РЕЗУЛЬТАТ:`);
    Logger.log(`  Status Code: ${responseCode}`);

    if (responseText) {
      Logger.log(`  Response Body: ${responseText.substring(0, 500)}`);
    }

    Logger.log(``);

    if (responseCode === 200 || responseCode === 201) {
      try {
        const result = JSON.parse(responseText);
        if (result.errors && result.errors.length > 0) {
          Logger.log(`❌ Ошибки в ответе API:`);
          result.errors.forEach(err => {
            Logger.log(`  - ${err}`);
          });
        } else {
          Logger.log(`✅ УСПЕХ! Цены успешно обновлены.`);
        }
      } catch (e) {
        Logger.log(`✅ УСПЕХ! Status: ${responseCode}`);
      }
    } else {
      Logger.log(`❌ ОШИБКА! Status: ${responseCode}`);
      try {
        const result = JSON.parse(responseText);
        if (result.errors) {
          Logger.log(`Ошибки API:`);
          result.errors.forEach(err => {
            Logger.log(`  - ${JSON.stringify(err)}`);
          });
        }
      } catch (e) {
        // Не JSON ответ
      }
    }

  } catch (error) {
    Logger.log(``);
    Logger.log(`❌ ИСКЛЮЧЕНИЕ:`);
    Logger.log(`  ${error.toString()}`);
  }

  Logger.log("============================================");
  Logger.log(``);
  Logger.log(`📝 Если тест прошёл успешно, выполните:`);
  Logger.log(`  syncARLStocks() - для полной синхронизации`);
  Logger.log("============================================");
}

/**
 * Тестовая функция для проверки выгрузки на WB FBS
 * Использует chrtId из колонки J
 */
function testWBFBSUpload() {
  Logger.log("============================================");
  Logger.log("🧪 ТЕСТ ВЫГРУЗКИ НА WB FBS");
  Logger.log("============================================");

  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(ARL_SHEET_NAME);

  if (!sheet) {
    Logger.log(`❌ Лист "${ARL_SHEET_NAME}" не найден!`);
    return;
  }

  // Читаем первую строку с данными для теста
  const maxCol = Math.max(COL_VENDOR_CODE, COL_CHRT_ID, COL_STOCK);
  const data = sheet.getRange(2, 1, 1, maxCol).getValues()[0];

  const vendorCode = data[COL_VENDOR_CODE - 1];  // A
  const chrtId = data[COL_CHRT_ID - 1];          // J
  const stock = data[COL_STOCK - 1];             // K или другая колонка с остатком

  if (!chrtId) {
    Logger.log(`❌ chrtId не найден в первой строке!`);
    Logger.log(``);
    Logger.log(`⚠️ Проверьте что колонка J (chrtId) заполнена`);
    return;
  }

  const testChrtId = Number(chrtId);
  const testStock = parseInt(stock) || 120;
  const warehouseId = ARL_WB_WAREHOUSE_ID;

  Logger.log(`📋 Тестовые данные:`);
  Logger.log(`  offer_id: ${vendorCode}`);
  Logger.log(`  chrtId: ${testChrtId}`);
  Logger.log(`  Остаток: ${testStock}`);
  Logger.log(`  Склад ID: ${warehouseId} (ФБС ФЕРОН МОСКВА)`);
  Logger.log(``);

  const body = {
    stocks: [
      {
        chrtId: testChrtId,  // ✅ chrtId из колонки J
        amount: testStock
      }
    ]
  };

  const url = `https://marketplace-api.wildberries.ru/api/v3/stocks/${warehouseId}`;

  Logger.log(`📤 URL: ${url}`);
  Logger.log(`📤 Method: PUT`);
  Logger.log(`📤 Payload: ${JSON.stringify(body)}`);
  Logger.log(``);

  const options = {
    method: "put",
    contentType: "application/json",
    headers: wbHeaders(),
    payload: JSON.stringify(body),
    muteHttpExceptions: true
  };

  Logger.log(`🔄 Отправка запроса...`);

  try {
    const response = UrlFetchApp.fetch(url, options);
    const responseCode = response.getResponseCode();
    const responseText = response.getContentText();

    Logger.log(``);
    Logger.log(`📥 РЕЗУЛЬТАТ:`);
    Logger.log(`  Status Code: ${responseCode}`);

    if (responseText) {
      Logger.log(`  Response Body: ${responseText.substring(0, 500)}`);
    }

    Logger.log(``);

    if (responseCode === 200 || responseCode === 204) {
      try {
        const result = JSON.parse(responseText);
        if (result.errors && result.errors.length > 0) {
          Logger.log(`❌ Ошибки в ответе API:`);
          result.errors.forEach(err => {
            Logger.log(`  - ${err}`);
          });
        } else {
          Logger.log(`✅ УСПЕХ! Остатки успешно обновлены.`);
        }
      } catch (e) {
        Logger.log(`✅ УСПЕХ! Status: ${responseCode}`);
      }
    } else {
      Logger.log(`❌ ОШИБКА! Status: ${responseCode}`);
      try {
        const result = JSON.parse(responseText);
        if (result.errors) {
          Logger.log(`Ошибки API:`);
          result.errors.forEach(err => {
            Logger.log(`  - ${JSON.stringify(err)}`);
          });
        }
      } catch (e) {
        // Не JSON ответ
      }
    }

  } catch (error) {
    Logger.log(``);
    Logger.log(`❌ ИСКЛЮЧЕНИЕ:`);
    Logger.log(`  ${error.toString()}`);
  }

  Logger.log("============================================");
  Logger.log(``);
  Logger.log(`📝 Если тест прошёл успешно, выполните:`);
  Logger.log(`  syncARLStocks() - для полной синхронизации`);
  Logger.log("============================================");
}
