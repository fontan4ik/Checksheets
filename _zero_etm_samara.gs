// ============================================
// СКРИПТ ДЛЯ ЗАНУЛЕНИЯ ОСТАТКОВ НА СКЛАДЕ ЭТМ САМАРА
// Warehouse ID: 1020005000689690
// ============================================

const ETT_SAMARA_WAREHOUSE_ID = '1020005000689690';

function zeroETMSamaraStocks() {
  Logger.log('=== ЗАНУЛЕНИЕ ОСТАТКОВ ЭТМ САМАРА (склад: ' + ETT_SAMARA_WAREHOUSE_ID + ') ===');
  
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();
  
  if (lastRow < 2) {
    Logger.log('⚠️ Нет данных в таблице');
    return;
  }
  
  const articles = sheet.getRange(2, 1, lastRow - 1).getValues().flat(); // A: Артикул
  const chrtIds = sheet.getRange(2, 52, lastRow - 1).getValues().flat(); // AZ (52): chrtId
  
  const validItems = [];
  
  for (let i = 0; i < articles.length; i++) {
    const article = String(articles[i]).trim();
    const chrtId = chrtIds[i];
    
    if (article && chrtId && !isNaN(Number(chrtId)) && Number(chrtId) > 0) {
      validItems.push({
        offer_id: article,
        chrtId: Number(chrtId),
        row: i + 2
      });
    }
  }
  
  Logger.log(`📋 Найдено ${validItems.length} товаров с chrtId для обновления`);
  
  if (validItems.length === 0) {
    Logger.log('⚠️ Нет товаров с chrtId! Попробую использовать nmId из колонки T...');
    return zeroETMSamaraStocksByNmId();
  }
  
  const batchSize = 1000;
  let successCount = 0;
  let failCount = 0;
  
  for (let i = 0; i < validItems.length; i += batchSize) {
    const batch = validItems.slice(i, i + batchSize);
    const batchNum = Math.floor(i / batchSize) + 1;
    const totalBatches = Math.ceil(validItems.length / batchSize);
    
    Logger.log(`📦 Обработка пачки ${batchNum}/${totalBatches} (${batch.length} товаров)...`);
    
    const stocksPayload = batch.map(item => ({
      chrtId: item.chrtId,
      amount: 0
    }));
    
    const result = sendZeroStocksBatch(stocksPayload, ETT_SAMARA_WAREHOUSE_ID);
    
    if (result.ok) {
      successCount += batch.length;
      Logger.log(`✅ Пачка ${batchNum} успешно обновлена`);
    } else {
      failCount += batch.length;
      const errText = result.text.substring(0, 300);
      Logger.log(`❌ Пачка ${batchNum} ошибка: ${result.code} - ${errText}`);
    }
    
    Utilities.sleep(600);
  }
  
  Logger.log(`🎯 Завершено! Успешно: ${successCount}, Ошибок: ${failCount}`);
  return { success: successCount, failed: failCount };
}

function zeroETMSamaraStocksByNmId() {
  Logger.log('=== Пробую использовать nmId из колонки T ===');
  
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();
  
  if (lastRow < 2) {
    Logger.log('⚠️ Нет данных в таблице');
    return;
  }
  
  const articles = sheet.getRange(2, 1, lastRow - 1).getValues().flat(); // A: Артикул
  const nmIds = sheet.getRange(2, 20, lastRow - 1).getValues().flat(); // T (20): nmId
  
  const validItems = [];
  
  for (let i = 0; i < articles.length; i++) {
    const article = String(articles[i]).trim();
    const nmId = nmIds[i];
    
    if (article && nmId && !isNaN(Number(nmId)) && Number(nmId) > 0) {
      validItems.push({
        offer_id: article,
        nmId: Number(nmId),
        row: i + 2
      });
    }
  }
  
  Logger.log(`📋 Найдено ${validItems.length} товаров с nmId для обновления`);
  
  if (validItems.length === 0) {
    Logger.log('⚠️ Нет товаров с nmId! Необходимо сначала заполнить колонку T (Артикул ВБ)');
    return;
  }
  
  const batchSize = 1000;
  let successCount = 0;
  let failCount = 0;
  
  for (let i = 0; i < validItems.length; i += batchSize) {
    const batch = validItems.slice(i, i + batchSize);
    const batchNum = Math.floor(i / batchSize) + 1;
    const totalBatches = Math.ceil(validItems.length / batchSize);
    
    Logger.log(`📦 Обработка пачки ${batchNum}/${totalBatches} (${batch.length} товаров)...`);
    
    const stocksPayload = batch.map(item => ({
      nmId: item.nmId,
      amount: 0
    }));
    
    const result = sendZeroStocksBatch(stocksPayload, ETT_SAMARA_WAREHOUSE_ID);
    
    if (result.ok) {
      successCount += batch.length;
      Logger.log(`✅ Пачка ${batchNum} успешно обновлена`);
    } else {
      failCount += batch.length;
      const errText = result.text.substring(0, 300);
      Logger.log(`❌ Пачка ${batchNum} ошибка: ${result.code} - ${errText}`);
    }
    
    Utilities.sleep(600);
  }
  
  Logger.log(`🎯 Завершено! Успешно: ${successCount}, Ошибок: ${failCount}`);
  return { success: successCount, failed: failCount };
}

function sendZeroStocksBatch(stocks, warehouseId, retryCount = 0) {
  const url = `https://marketplace-api.wildberries.ru/api/v3/stocks/${warehouseId}`;
  
  const body = { stocks: stocks };
  
  const options = {
    method: "put",
    contentType: "application/json",
    headers: wbHeaders(),
    payload: JSON.stringify(body),
    muteHttpExceptions: true
  };
  
  Logger.log(`📤 PUT ${url}`);
  Logger.log(`📦 Payload: ${JSON.stringify(body).substring(0, 500)}`);
  
  const response = UrlFetchApp.fetch(url, options);
  
  if (!response) {
    return { ok: false, code: 0, text: 'No response' };
  }
  
  const code = response.getResponseCode();
  const text = response.getContentText();
  
  Logger.log(`📥 Response: ${code} - ${text.substring(0, 300)}`);
  
  if (code === 429 && retryCount < 3) {
    Logger.log('⏳ Rate limit, ждём 5 сек...');
    Utilities.sleep(5000);
    return sendZeroStocksBatch(stocks, warehouseId, retryCount + 1);
  }
  
  return {
    ok: code === 200 || code === 204,
    code,
    text
  };
}

// ============================================
// ПОЛУЧИТЬ СПИСОК СКЛАДОВ WB
// ============================================

function listWBWarehouses() {
  Logger.log('=== СПИСОК СКЛАДОВ WB ===');
  
  const url = 'https://marketplace-api.wildberries.ru/api/v3/warehouses';
  
  const options = {
    method: "get",
    headers: wbHeaders(),
    muteHttpExceptions: true
  };
  
  const response = UrlFetchApp.fetch(url, options);
  const code = response.getResponseCode();
  const text = response.getContentText();
  
  Logger.log(`📊 Код ответа: ${code}`);
  Logger.log(`📄 Ответ: ${text.substring(0, 2000)}`);
  
  try {
    const data = JSON.parse(text);
    if (data && Array.isArray(data)) {
      Logger.log('📦 Доступные склады:');
      data.forEach(wh => {
        Logger.log(`  ID: ${wh.id} - ${wh.name} (${wh.is_rfxs ? 'FBS' : 'FBO'})`);
      });
    }
  } catch (e) {
    Logger.log(`⚠️ Ошибка парсинга: ${e.message}`);
  }
  
  return { code, text };
}

// ============================================
// ТЕСТОВАЯ ФУНКЦИЯ (для проверки на 3 товарах)
// ============================================

function zeroETMSamaraTest() {
  Logger.log('=== ТЕСТ ЗАНУЛЕНИЯ ОСТАТКОВ ===');
  
  const sheet = mainSheet();
  const lastRow = Math.min(sheet.getLastRow(), 5);
  
  if (lastRow < 2) {
    Logger.log('⚠️ Нет данных в таблице');
    return;
  }
  
  const articles = sheet.getRange(2, 1, lastRow - 1).getValues().flat();
  const chrtIds = sheet.getRange(2, 52, lastRow - 1).getValues().flat();
  
  const testItems = [];
  for (let i = 0; i < articles.length; i++) {
    const chrtId = chrtIds[i];
    if (chrtId && !isNaN(Number(chrtId)) && Number(chrtId) > 0) {
      testItems.push({
        chrtId: Number(chrtId),
        amount: 0
      });
    }
  }
  
  if (testItems.length === 0) {
    Logger.log('⚠️ Нет chrtId, пробую nmId...');
    const nmIds = sheet.getRange(2, 20, lastRow - 1).getValues().flat();
    for (let i = 0; i < articles.length; i++) {
      const nmId = nmIds[i];
      if (nmId && !isNaN(Number(nmId)) && Number(nmId) > 0) {
        testItems.push({
          nmId: Number(nmId),
          amount: 0
        });
      }
    }
  }
  
  Logger.log(`🧪 Тест: ${testItems.length} товаров`);
  Logger.log(`📦 Тестовый payload: ${JSON.stringify({ stocks: testItems })}`);
  
  const result = sendZeroStocksBatch(testItems, ETT_SAMARA_WAREHOUSE_ID);
  
  Logger.log(`📊 Результат: код=${result.code}`);
  Logger.log(`📄 Ответ: ${result.text}`);
  
  return result;
}
