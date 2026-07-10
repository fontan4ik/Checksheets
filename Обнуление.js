/**
 * ОБНУЛЕНИЕ ОСТАТКОВ NA СКЛАДЕ ОЗОН "ФЕРОН ФБС"
 *
 * Функция zeroOutOzonStocks() - обнуляет остатки товаров на Ozon складе "ФЕРОН ФБС".
 */

// ============================================
// КОНФИГУРАЦИЯ
// ============================================

const ZERO_OUT_SHEET_NAME = "РуСВ TR";  // Используем тот же лист что и в синхронизации
const ZERO_OUT_OZON_WH_NAME = "ФЕРОН ФБС"; // Целевой склад Ozon для обнуления

// Фоллбек колонки (если заголовки не найдены)
const ZERO_OUT_COL_OFFER_ID = 1;     // A - Артикул (offer_id Ozon)

// ============================================
// ОСНОВНАЯ ФУНКЦИЯ ОБНУЛЕНИЯ ОСТАТКОВ
// ============================================

/**
 * Обнуляет остатки товаров на Ozon складе "ФЕРОН ФБС"
 */
function zeroOutOzonStocks() {
  Logger.log("=== ШАГ: ОБНУЛЕНИЕ ОСТАТКОВ НА OZON СКЛАДЕ 'ФЕРОН ФБС' ===");

  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(ZERO_OUT_SHEET_NAME);

  if (!sheet) {
    Logger.log(`❌ Лист "${ZERO_OUT_SHEET_NAME}" не найден!`);
    return;
  }

  const lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    Logger.log("⚠️ Нет данных для обнуления (меньше 2 строк)");
    return;
  }

  // Динамический поиск колонки Артикул
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0].map(h => String(h).trim().toLowerCase());
  const colOfferId = headers.indexOf("артикул") + 1 || ZERO_OUT_COL_OFFER_ID;

  const offerIds = sheet.getRange(2, colOfferId, lastRow - 1, 1).getValues().flat();

  // Подготовка данных для обнуления (все остатки устанавливаются в 0)
  const stocksToZeroOut = [];

  for (let i = 0; i < offerIds.length; i++) {
    const offerId = String(offerIds[i]).trim();

    if (offerId && offerId !== "undefined" && offerId !== "") {
      stocksToZeroOut.push({
        offer_id: offerId,
        stock: 0, // Устанавливаем остаток в 0
        warehouse_id: 1020005000217829 // Жестко заданный ID склада "ФЕРОН ФБС"
      });
    }
  }

  if (stocksToZeroOut.length > 0) {
    Logger.log(`📤 Отправка обнуления ${stocksToZeroOut.length} товаров на Ozon...`);
    Logger.log(`🎯 Склад: ${ZERO_OUT_OZON_WH_NAME} (ID: 1020005000217829)`);

    // Обновление остатков на Ozon (установка в 0)
    updateOzonStocksToZero(stocksToZeroOut, 1020005000217829);

    Logger.log("✅ Обнуление остатков на Ozon завершено.");
  } else {
    Logger.log("⚠️ Нет данных для обнуления (проверьте колонку Артикул).");
  }
}

// ============================================
// ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
// ============================================

function updateOzonStocksToZero(stocks, warehouseId) {
  const batchSize = 100;

  for (let i = 0; i < stocks.length; i += batchSize) {
    const batch = stocks.slice(i, i + batchSize);
    const body = {
      stocks: batch.map(item => ({
        offer_id: item.offer_id,
        stock: item.stock, // всегда 0 для обнуления
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

    const response = retryFetch("https://api-seller.ozon.ru/v2/products/stocks", options);

    if (response) {
      const code = response.getResponseCode();
      const text = response.getContentText();

      if (code >= 200 && code < 300) {
        Logger.log(`✅ Пачка ${Math.floor(i / batchSize) + 1} успешно обнулена (${batch.length} товаров)`);
      } else {
        Logger.log(`❌ Ошибка обнуления пачки ${Math.floor(i / batchSize) + 1}: ${code}`);
        Logger.log((text || "").substring(0, 500));
      }
    } else {
      Logger.log(`❌ Нет ответа при обнулении пачки ${Math.floor(i / batchSize) + 1}`);
    }
  }
}

/**
 * Альтернативная функция для обнуления конкретных товаров по offer_id
 */
function zeroSpecificOzonStocks(offerIds) {
  if (!Array.isArray(offerIds) || offerIds.length === 0) {
    Logger.log("⚠️ Не передан массив offer_id для обнуления");
    return;
  }

  Logger.log(`=== ОБНУЛЕНИЕ КОНКРЕТНЫХ ТОВАРОВ (${offerIds.length} шт.) ===`);

  const stocksToZeroOut = offerIds.map(offerId => ({
    offer_id: String(offerId),
    stock: 0, // Устанавливаем остаток в 0
    warehouse_id: 1020005000217829 // ID склада "ФЕРОН ФБС"
  }));

  Logger.log(`📤 Отправка обнуления ${stocksToZeroOut.length} товаров на Ozon...`);
  Logger.log(`🎯 Склад: ${ZERO_OUT_OZON_WH_NAME} (ID: 1020005000217829)`);

  updateOzonStocksToZero(stocksToZeroOut, 1020005000217829);
  Logger.log("✅ Конкретные остатки на Ozon обнулены.");
}
