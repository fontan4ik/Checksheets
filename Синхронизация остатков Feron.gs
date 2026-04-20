/**
 * СИНХРОНИЗАЦИЯ ОСТАТКОВ С ЛИСТА "FERON TR"
 *
 * Читает остатки из листа "FERON TR" и выгружает на 3 склада:
 * Ozon: Москва (Подорожник ФБС), Самара (Feron ФБС), Новосибирск (Feron)
 * WB: Москва, Самара, Новосибирск
 *
 * Структура листа "FERON TR":
 * A: Артикул (offer_id)
 * Q: MSK остаток → Москва
 * R: SMR остаток → Самара
 * S: NSB остаток → Новосибирск
 * T: chrtId для WB API
 */

const FERON_TR_SHEET_NAME = "FERON TR";

const FERON_TR_OZON_WAREHOUSES = {
  MSK: 1020005000217829,
  SMR: 1020005000234124,
  NSB: 1020005008262970
};

const FERON_TR_WB_WAREHOUSE = {
  MSK: 1449484,
  SMR: 798761,
  NSB: 1724900
};

const FERON_TR_COLS = {
  VENDOR_CODE: 1,
  STOCK_MSK: 17,
  STOCK_SMR: 18,
  STOCK_NSB: 19,
  CHRT_ID: 20
};

function readFeronStocksFromSheet() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(FERON_TR_SHEET_NAME);

  if (!sheet) {
    Logger.log(`❌ Лист "${FERON_TR_SHEET_NAME}" не найден!`);
    return [];
  }

  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log(`❌ Нет данных на листе "${FERON_TR_SHEET_NAME}"`);
    return [];
  }

  const lastCol = sheet.getLastColumn();
  const headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0].map(h => String(h).trim().toLowerCase());

  const findCol = (name, fallback) => {
    const idx = headers.indexOf(name.toLowerCase());
    return idx >= 0 ? idx + 1 : fallback;
  };

  const colVendor = findCol("артикул", FERON_TR_COLS.VENDOR_CODE);
  const colStockMsk = findCol("msk", FERON_TR_COLS.STOCK_MSK);
  const colStockSmr = findCol("smr", FERON_TR_COLS.STOCK_SMR);
  const colStockNsb = findCol("nsb", FERON_TR_COLS.STOCK_NSB);
  const colChrtId = findCol("chrtid", FERON_TR_COLS.CHRT_ID);

  Logger.log(`🔍 Колонки: offer_id=${colVendor}, MSK=${colStockMsk}, SMR=${colStockSmr}, NSB=${colStockNsb}, chrtId=${colChrtId}`);

  const maxCol = Math.max(colVendor, colStockMsk, colStockSmr, colStockNsb, colChrtId);
  const data = sheet.getRange(2, 1, lastRow - 1, maxCol).getValues();

  const stocks = [];

  for (let i = 0; i < data.length; i++) {
    const row = data[i];

    const vendorCode = row[colVendor - 1];
    const stockMsk = parseInt(row[colStockMsk - 1]) || 0;
    const stockSmr = parseInt(row[colStockSmr - 1]) || 0;
    const stockNsb = parseInt(row[colStockNsb - 1]) || 0;
    const chrtId = row[colChrtId - 1];

    if (!vendorCode) {
      continue;
    }

    stocks.push({
      offer_id: vendorCode,
      stock_msk: stockMsk,
      stock_smr: stockSmr,
      stock_nsb: stockNsb,
      chrt_id: chrtId
    });
  }

  Logger.log(`📊 Прочитано ${stocks.length} товаров из листа "${FERON_TR_SHEET_NAME}"`);

  const withStock = stocks.filter(s => s.stock_msk > 0 || s.stock_smr > 0 || s.stock_nsb > 0).length;
  const withChrtId = stocks.filter(s => s.chrt_id).length;
  Logger.log(`   С остатком > 0: ${withStock}`);
  Logger.log(`   С chrtId: ${withChrtId}`);

  return stocks;
}

function updateFeronStocksOzon(stocks) {
  Logger.log(`🟠 Обновление остатков Ozon (3 склада)...`);

  if (!stocks) {
    Logger.log(`📥 Извлечение данных из таблицы...`);
    stocks = readFeronStocksFromSheet();
  }

  if (!stocks || stocks.length === 0) {
    Logger.log(`⚠️ Нет данных для обновления Ozon`);
    return;
  }

  const validStocks = stocks.filter(s => s.offer_id);

  if (validStocks.length === 0) {
    Logger.log(`⚠️ Нет товаров с offer_id для обновления Ozon`);
    return;
  }

  Logger.log(`📦 Товаров для обработки: ${validStocks.length}`);

  const warehouses = [
    { key: 'MSK', name: 'Москва', id: FERON_TR_OZON_WAREHOUSES.MSK, col: 'stock_msk' },
    { key: 'SMR', name: 'Самара', id: FERON_TR_OZON_WAREHOUSES.SMR, col: 'stock_smr' },
    { key: 'NSB', name: 'Новосибирск', id: FERON_TR_OZON_WAREHOUSES.NSB, col: 'stock_nsb' }
  ];

  let lastRequestTime = Date.now() - 1000 / RPS();
  let totalSuccess = 0;
  let totalError = 0;

  for (const wh of warehouses) {
    Logger.log(`\n📦 Обработка склада: ${wh.name} (ID: ${wh.id})...`);

    const batchSize = 100;
    const batches = Math.ceil(validStocks.length / batchSize);

    let warehouseSuccess = 0;
    let warehouseError = 0;

    for (let i = 0; i < batches; i++) {
      lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

      const batch = validStocks.slice(i * batchSize, (i + 1) * batchSize);

      const body = {
        stocks: batch.map(item => ({
          offer_id: String(item.offer_id),
          stock: item[wh.col],
          warehouse_id: wh.id
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
        warehouseError += batch.length;
        continue;
      }

      const responseCode = response.getResponseCode();
      const responseText = response.getContentText();

      if (responseCode !== 200) {
        Logger.log(`❌ Ошибка API (пачка ${i + 1}/${batches}): ${responseCode}`);
        warehouseError += batch.length;
        continue;
      }

      const result = JSON.parse(responseText);

      if (result.result) {
        result.result.forEach(r => {
          if (r.errors && r.errors.length > 0) {
            const isError = !r.errors.some(e => e.code === 'TOO_MANY_REQUESTS');
            if (isError) {
              Logger.log(`❌ Ozon ошибка для ${r.offer_id}: ${r.errors.map(e => e.message || e.code).join(", ")}`);
              warehouseError++;
            } else {
              warehouseSuccess++;
            }
          } else if (r.updated) {
            warehouseSuccess++;
          }
        });
      }

      Logger.log(`✅ Пачка ${i + 1}/${batches} обработана`);
    }

    Logger.log(`🟠 ${wh.name}: ✅ ${warehouseSuccess} обновлено, ❌ ${warehouseError} ошибок`);
    totalSuccess += warehouseSuccess;
    totalError += warehouseError;
  }

  Logger.log(`\n🟠 Ozon Всего: ✅ ${totalSuccess} обновлено, ❌ ${totalError} ошибок`);
}

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

function sendFeronWBStocksBatch(batch, warehouseId, retryCount = 0) {
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
    if (retryCount < 2) {
      Utilities.sleep(3000);
      return sendFeronWBStocksBatch(batch, warehouseId, retryCount + 1);
    }
    return { ok: false, code: 0, text: '', cargoRestriction: false };
  }

  const code = response.getResponseCode();
  const text = response.getContentText();

  if (code === 429 && retryCount < 2) {
    Utilities.sleep(5000);
    return sendFeronWBStocksBatch(batch, warehouseId, retryCount + 1);
  }

  return {
    ok: code === 200 || code === 204,
    code,
    text,
    cargoRestriction: code === 409 && isWBCargoRestrictionError(text)
  };
}

function processFeronWBConflictIndividually(validBatch, warehouseId, batchLabel, whCol) {
  let successCount = 0;
  let skippedCount = 0;
  let errorCount = 0;

  Logger.log(`🔍 ${batchLabel}: дробление до отдельных товаров (${validBatch.length} шт)...`);

  for (let j = 0; j < validBatch.length; j++) {
    if (j > 0 && j % 20 === 0) {
      Utilities.sleep(2000);
    }

    const item = validBatch[j];
    const result = sendFeronWBStocksBatch([item], warehouseId);

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

function updateFeronStocksWB(stocks) {
  Logger.log(`🟣 Обновление остатков WB FBS (3 склада)...`);

  if (!stocks) {
    Logger.log(`📥 Извлечение данных из таблицы...`);
    stocks = readFeronStocksFromSheet();
  }

  if (!stocks || stocks.length === 0) {
    Logger.log(`⚠️ Нет данных для обновления WB`);
    return;
  }

  const validStocks = stocks.filter(s => s.chrt_id);

  if (validStocks.length === 0) {
    Logger.log(`⚠️ Нет товаров с chrtId для обновления WB`);
    return;
  }

  Logger.log(`📦 Товаров для обработки: ${validStocks.length}`);

  const warehouses = [
    { key: 'MSK', name: 'Москва', id: FERON_TR_WB_WAREHOUSE.MSK, col: 'stock_msk' },
    { key: 'SMR', name: 'Самара', id: FERON_TR_WB_WAREHOUSE.SMR, col: 'stock_smr' },
    { key: 'NSB', name: 'Новосибирск', id: FERON_TR_WB_WAREHOUSE.NSB, col: 'stock_nsb' }
  ];

  let lastRequestTime = Date.now() - 1000 / WB_RPS();
  let totalSuccess = 0;
  let totalSkipped = 0;
  let totalError = 0;

  for (const wh of warehouses) {
    Logger.log(`\n📦 Обработка склада: ${wh.name} (ID: ${wh.id})...`);

    const batchSize = 200;
    const batches = Math.ceil(validStocks.length / batchSize);

    let warehouseSuccess = 0;
    let warehouseSkipped = 0;
    let warehouseError = 0;

    for (let i = 0; i < batches; i++) {
      lastRequestTime = rateLimitRPS(lastRequestTime, WB_RPS());

      const batch = validStocks.slice(i * batchSize, (i + 1) * batchSize);

      const validBatch = [];

      for (const item of batch) {
        const idNum = Number(item.chrt_id);

        if (isNaN(idNum) || !item.chrt_id) {
          warehouseError++;
          continue;
        }

        validBatch.push({
          chrtId: idNum,
          amount: item[wh.col]
        });
      }

      if (validBatch.length === 0) {
        continue;
      }

      lastRequestTime = rateLimitRPS(lastRequestTime, WB_RPS());

      const result = sendFeronWBStocksBatch(validBatch, wh.id);

      if (result.ok) {
        warehouseSuccess += validBatch.length;
        Logger.log(`✅ Пачка ${i + 1}/${batches} обработана (${validBatch.length} товаров)`);
        continue;
      }

      if (result.cargoRestriction) {
        Logger.log(`⚠️ WB 409 ODC/CD+ (пачка ${i + 1}/${batches}): дробление...`);
        const fallback = processFeronWBConflictIndividually(validBatch, wh.id, `Пачка ${i + 1}/${batches}`, wh.col);
        warehouseSuccess += fallback.successCount;
        warehouseSkipped += fallback.skippedCount;
        warehouseError += fallback.errorCount;
        continue;
      }

      Logger.log(`❌ Ошибка API (пачка ${i + 1}/${batches}): ${result.code}`);
      if (result.text) {
        Logger.log(result.text.substring(0, 500));
      }
      warehouseError += validBatch.length;
    }

    Logger.log(`🟣 ${wh.name}: ✅ ${warehouseSuccess} обновлено, ⏸️ ${warehouseSkipped} пропущено ODC/CD+, ❌ ${warehouseError} ошибок`);
    totalSuccess += warehouseSuccess;
    totalSkipped += warehouseSkipped;
    totalError += warehouseError;
  }

  Logger.log(`\n🟣 WB Всего: ✅ ${totalSuccess} обновлено, ⏸️ ${totalSkipped} пропущено ODC/CD+, ❌ ${totalError} ошибок`);
}

function syncFeronStocks() {
  Logger.log("============================================");
  Logger.log("🔄 СИНХРОНИЗАЦИЯ ОСТАТКОВ FERON");
  Logger.log("============================================");

  const startTime = new Date();

  Logger.log(`📊 Шаг 1: Чтение данных из листа "${FERON_TR_SHEET_NAME}"...`);
  const stocks = readFeronStocksFromSheet();

  if (stocks.length === 0) {
    Logger.log("❌ Нет данных для синхронизации");
    return;
  }

  Logger.log(`� Примеры данных (первые 5):`);
  stocks.slice(0, 5).forEach(s => {
    Logger.log(`  - ${s.offer_id} | MSK: ${s.stock_msk} | SMR: ${s.stock_smr} | NSB: ${s.stock_nsb} | chrtId: ${s.chrt_id || '(нет)'}`);
  });

  Logger.log(``);
  Logger.log(`🟠 Шаг 2: Обновление остатков Ozon (3 склада)...`);
  updateFeronStocksOzon(stocks);

  Logger.log(``);
  Logger.log(`🟣 Шаг 3: Обновление остатков WB (3 склада)...`);
  updateFeronStocksWB(stocks);

  const endTime = new Date();
  const duration = Math.round((endTime - startTime) / 1000);

  Logger.log(``);
  Logger.log("============================================");
  Logger.log(`✅ Синхронизация завершена за ${duration} сек.`);
  Logger.log("============================================");
}

function testFeronStockSync() {
  Logger.log("============================================");
  Logger.log("🧪 ТЕСТ СИНХРОНИЗАЦИИ ОСТАТКОВ FERON");
  Logger.log("============================================");

  Logger.log(``);
  Logger.log(`📊 Тест 1: Чтение данных из листа...`);
  const stocks = readFeronStocksFromSheet();

  if (stocks.length === 0) {
    Logger.log("❌ Нет данных");
    return;
  }

  Logger.log(`✅ Прочитано ${stocks.length} товаров`);
  Logger.log(`� Первые 5 товаров:`);
  stocks.slice(0, 5).forEach(s => {
    Logger.log(`  - ${s.offer_id} | MSK: ${s.stock_msk} | SMR: ${s.stock_smr} | NSB: ${s.stock_nsb} | chrtId: ${s.chrt_id || '(нет)'}`);
  });

  Logger.log(``);
  Logger.log(`� Склады Ozon:`);
  Logger.log(`  - Москва: ${FERON_TR_OZON_WAREHOUSES.MSK}`);
  Logger.log(`  - Самара: ${FERON_TR_OZON_WAREHOUSES.SMR}`);
  Logger.log(`  - Новосибирск: ${FERON_TR_OZON_WAREHOUSES.NSB}`);

  Logger.log(``);
  Logger.log(`� Склады WB:`);
  Logger.log(`  - Москва: ${FERON_TR_WB_WAREHOUSE.MSK}`);
  Logger.log(`  - Самара: ${FERON_TR_WB_WAREHOUSE.SMR}`);
  Logger.log(`  - Новосибирск: ${FERON_TR_WB_WAREHOUSE.NSB}`);

  const withStock = stocks.filter(s => s.stock_msk > 0 || s.stock_smr > 0 || s.stock_nsb > 0).length;
  const withChrtId = stocks.filter(s => s.chrt_id).length;

  Logger.log(``);
  Logger.log(`� Статистика:`);
  Logger.log(`  - С остатком > 0: ${withStock}`);
  Logger.log(`  - С chrtId: ${withChrtId}`);

  Logger.log(``);
  Logger.log("============================================");
  Logger.log(`✅ Тест завершён`);
  Logger.log(``);
  Logger.log(`Для запуска полноценной синхронизации выполните:`);
  Logger.log(`  syncFeronStocks()`);
  Logger.log("============================================");
}