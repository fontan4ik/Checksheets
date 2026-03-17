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

// Названия складов для поиска ID
const RS_OZON_TARGET_WH_NAME = "1C трансляция"; // Самара
const RS_WB_TARGET_WH_NAME = "ВольтМир";

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
 * Выгружает данные из колонок "Артикул", "chrtId" и "Округление" на Ozon и WB
 */
function syncRSTableToMarketplaces() {
  Logger.log("=== ШАГ 2: ВЫГРУЗКА ИЗ ТАБЛИЦЫ НА МАРКЕТПЛЕЙСЫ ===");

  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(RS_SHEET_NAME);

  if (!sheet) {
    Logger.log(`❌ Лист "${RS_SHEET_NAME}" не найден!`);
    return;
  }

  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return;

  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0].map(h => String(h).trim().toLowerCase());
  const colOfferId = headers.indexOf("артикул") + 1 || RS_COL_ARTICUL;
  const colChrtId = (headers.indexOf("chrtid") + 1) || (headers.indexOf("chrlid") + 1) || RS_COL_CHRT_ID;
  const colRounded = headers.indexOf("округление") + 1 || RS_COL_ROUNDED;

  const maxCol = Math.max(colOfferId, colChrtId, colRounded);
  const data = sheet.getRange(2, 1, lastRow - 1, maxCol).getValues();

  const stocksForUpload = [];

  for (let i = 0; i < data.length; i++) {
    const row = data[i];
    const offerId = String(row[colOfferId - 1]).trim();
    const chrtId = row[colChrtId - 1];
    const stockValue = parseInt(row[colRounded - 1]) || 0;

    if (offerId && offerId !== "undefined") {
      stocksForUpload.push({
        offer_id: offerId,
        stock: stockValue,
        chrt_id: chrtId
      });
    }
  }

  if (stocksForUpload.length > 0) {
    Logger.log(`📤 Отправка ${stocksForUpload.length} товаров на Ozon и WB...`);
    
    // 1. Поиск ID склада Ozon
    const ozonWhId = ozonFBSWarehouseId(); // Используем центральную функцию из settings.gs
    if (ozonWhId) {
      Logger.log(`✅ Ozon склад найден: ${ozonWhId} (${RS_OZON_TARGET_WH_NAME})`);
      updateRSStocksOzonBatch(stocksForUpload, ozonWhId);
    } else {
      Logger.log(`❌ Ошибка: Склад Ozon "${RS_OZON_TARGET_WH_NAME}" не найден! Выгрузка отменена.`);
    }
    
    // 2. Поиск ID склада WB
    const wbWhId = findWBWarehouseIdByName(RS_WB_TARGET_WH_NAME) || 1449484;
    if (wbWhId) {
      Logger.log(`✅ WB склад найден: ${wbWhId} (${RS_WB_TARGET_WH_NAME})`);
      updateRSStocksWBBatch(stocksForUpload, wbWhId);
    } else {
      Logger.log(`❌ Ошибка: Склад WB "${RS_WB_TARGET_WH_NAME}" не найден! Выгрузка отменена.`);
    }
    
    Logger.log("✅ Синхронизация с маркетплейсами завершена.");
  } else {
    Logger.log("⚠️ Нет данных для выгрузки (проверьте колонку Артикул).");
  }
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
  for (let i = 0; i < stocks.length; i += batchSize) {
    const batch = stocks.slice(i, i + batchSize);
    const validBatch = batch.map(item => ({
      chrtId: Number(item.chrt_id),
      amount: item.stock
    })).filter(item => !isNaN(item.chrtId) && item.chrtId > 0);

    if (validBatch.length === 0) continue;

    const options = {
      method: "put",
      contentType: "application/json",
      headers: wbHeaders(),
      payload: JSON.stringify({ stocks: validBatch }),
      muteHttpExceptions: true
    };
    retryFetch(`https://marketplace-api.wildberries.ru/api/v3/stocks/${warehouseId}`, options);
  }
}

