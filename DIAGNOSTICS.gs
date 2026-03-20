/**
 * ДИАГНОСТИЧЕСКИЙ СКРИПТ
 * Запустите эту функцию для проверки всех проблем
 */

function runDiagnostics() {
  console.log('');
  console.log('========================================');
  console.log('   ДИАГНОСТИКА СИСТЕМЫ');
  console.log('========================================');
  console.log('');
  
  checkSheetData();
  checkAPIKeys();
  checkFunctionsExist();
}

function checkSheetData() {
  console.log('1. ПРОВЕРКА ДАННЫХ В ТАБЛИЦЕ');
  console.log('========================================');
  
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();
  
  console.log('Всего строк: ' + lastRow);
  
  if (lastRow < 2) {
    console.log('❌ НЕТ ДАННЫХ В ТАБЛИЦЕ');
    return;
  }
  
  // Проверяем колонку A (артикулы)
  const articles = sheet.getRange(2, 1, Math.min(lastRow - 1, 10)).getValues().flat();
  const validArticles = articles.filter(a => a);
  console.log('Артикулов в первых 10 строках: ' + validArticles.length + '/10');
  
  // Проверяем Product_id Ozon (колонка U, 21)
  const productIds = sheet.getRange(2, 21, Math.min(lastRow - 1, 10)).getValues().flat();
  const validProductIds = productIds.filter(p => p && p > 0);
  console.log('Product_id Ozon заполнено: ' + validProductIds.length + '/10');
  
  // Проверяем Артикул ВБ (колонка T, 20)
  const wbArticles = sheet.getRange(2, 20, Math.min(lastRow - 1, 10)).getValues().flat();
  const validWbArticles = wbArticles.filter(w => w);
  console.log('Артикул ВБ заполнено: ' + validWbArticles.length + '/10');
  
  console.log('');
}

function checkAPIKeys() {
  console.log('2. ПРОВЕРКА API КЛЮЧЕЙ');
  console.log('========================================');
  
  try {
    const ozonKey = OZON_API_KEY();
    console.log('✅ Ozon API Key: ' + (ozonKey ? 'НАСТРОЕН' : 'ПУСТОЙ'));
  } catch (e) {
    console.log('❌ Ozon API Key: ОШИБКА - ' + e.message);
  }
  
  try {
    const wbKey = WB_API_TOKEN();
    console.log('✅ WB API Token: ' + (wbKey ? 'НАСТРОЕН' : 'ПУСТОЙ'));
  } catch (e) {
    console.log('❌ WB API Token: ОШИБКА - ' + e.message);
  }
  
  console.log('');
}

function checkFunctionsExist() {
  console.log('3. ПРОВЕРКА ФУНКЦИЙ');
  console.log('========================================');
  
  const functions = [
    'syncOfferIdWithProductId',
    'updateWBArticles',
    'updateWBAnalytics',
    'main'
  ];
  
  functions.forEach(funcName => {
    try {
      const func = this[funcName];
      if (typeof func === 'function') {
        console.log('✅ ' + funcName + ' - СУЩЕСТВУЕТ');
      } else {
        console.log('❌ ' + funcName + ' - НЕ НАЙДЕНА');
      }
    } catch (e) {
      console.log('❌ ' + funcName + ' - ОШИБКА: ' + e.message);
    }
  });
  
  console.log('');
}

function testAPIConnections() {
  console.log('4. ТЕСТ API СОЕДИНЕНИЙ');
  console.log('========================================');
  
  // Тест Ozon API
  try {
    const url = ozonProductsApiURL();
    console.log('Ozon API URL: ' + url);
    
    const payload = {
      filter: {},
      limit: 1
    };
    
    const options = {
      method: 'post',
      contentType: 'application/json',
      headers: ozonHeaders(),
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    };
    
    const response = UrlFetchApp.fetch(url, options);
    const code = response.getResponseCode();
    console.log('Ozon API Response: ' + code);
    
    if (code === 200) {
      console.log('✅ Ozon API РАБОТАЕТ');
    } else {
      console.log('❌ Ozon API ОШИБКА: ' + code);
      console.log('Response: ' + response.getContentText().substring(0, 200));
    }
  } catch (e) {
    console.log('❌ Ozon API ОШИБКА: ' + e.message);
  }
  
  console.log('');
  
  // Тест WB API
  try {
    const url = 'https://statistics-api.wildberries.ru/api/v1/supplier/orders?dateFrom=2024-01-01';
    console.log('WB API URL: ' + url);
    
    const options = {
      method: 'get',
      headers: wbHeaders(),
      muteHttpExceptions: true
    };
    
    const response = UrlFetchApp.fetch(url, options);
    const code = response.getResponseCode();
    console.log('WB API Response: ' + code);
    
    if (code === 200) {
      console.log('✅ WB API РАБОТАЕТ');
    } else if (code === 401) {
      console.log('❌ WB API: НЕВАЛИДНЫЙ ТОКЕН (401)');
    } else {
      console.log('❌ WB API ОШИБКА: ' + code);
      console.log('Response: ' + response.getContentText().substring(0, 200));
    }
  } catch (e) {
    console.log('❌ WB API ОШИБКА: ' + e.message);
  }
  
  console.log('');
}
