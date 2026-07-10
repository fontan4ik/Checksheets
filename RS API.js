// ============================================
// RS API (Русский Свет) - Интеграция
// ============================================

/**
 * Получить заголовки для RS API (Basic Auth)
 */
function rsHeaders() {
  const login = rsLogin();
  const password = rsPassword();
  const base64 = Utilities.base64Encode(`${login}:${password}`);
  
  return {
    "Authorization": `Basic ${base64}`,
    "Accept": "application/json"
  };
}

/**
 * Получить карту соответствия Артикул производителя -> Код РС (Оптимизировано)
 * Загружает весь каталог товаров со склада и строит маппинг в памяти.
 * 
 * @param {number} warehouseId - ID склада
 * @returns {Object} Карта vendor_code -> rs_code
 */
function fetchRSCodeMap(warehouseId) {
  const map = {};
  const categories = ["instock", "custom"];
  
  Logger.log(`📦 Загрузка каталога RS для склада ${warehouseId}...`);
  
  for (const cat of categories) {
    let page = 1;
    let lastPage = 1;
    
    do {
      //rows=1000 - максимально допустимое значение согласно п 1.10 документации
      const url = `${rsApiBaseUrl()}/position/${warehouseId}/${cat}?page=${page}&rows=1000`;
      
      const options = {
        method: "get",
        headers: rsHeaders(),
        muteHttpExceptions: true
      };
      
      const response = retryFetch(url, options);
      if (!response) {
        Logger.log(`⚠️ Не удалось получить страницу ${page} категории ${cat}`);
        break;
      }
      
      const responseCode = response.getResponseCode();
      if (responseCode !== 200) {
        Logger.log(`⚠️ Ошибка API при загрузке каталога (${responseCode}): ${response.getContentText()}`);
        break;
      }
      
      const data = JSON.parse(response.getContentText());
      if (data && data.items) {
        data.items.forEach(item => {
          if (item.VENDOR_CODE) {
            // Очищаем артикул от лишних пробелов для точного совпадения
            const vCode = String(item.VENDOR_CODE).trim();
            if (vCode) {
              map[vCode] = item.CODE;
            }
          }
        });
        
        lastPage = (data.meta && data.meta.last_page) ? data.meta.last_page : 1;
        
        if (page === 1) {
          Logger.log(`   Категория ${cat}: всего товаров ~${data.meta ? data.meta.rows_count : "???"}, страниц: ${lastPage}`);
        }
      }
      
      page++;
      
      // Небольшая пауза чтобы не превысить лимит 150/30сек при очень большом каталоге
      if (page % 5 === 0) Utilities.sleep(100);
      
    } while (page <= lastPage);
  }
  
  Logger.log(`✅ Каталог загружен. Уникальных артикулов: ${Object.keys(map).length}`);
  return map;
}

/**
 * Найти внутренний код РС по артикулу производителя (vendor code)
 * 
 * @deprecated Используйте fetchRSCodeMap для массовой обработки
 * @param {string} vendorCode - Артикул производителя (из колонки Модель)
 * @returns {string|null} Код РС или null
 */
function getRSCodeByVendorCode(vendorCode) {
  const url = `${rsApiBaseUrl()}/items/search/vendor_code?code=${encodeURIComponent(vendorCode)}`;
  
  const options = {
    method: "get",
    headers: rsHeaders(),
    muteHttpExceptions: true
  };
  
  try {
    const response = retryFetch(url, options);
    if (!response) return null;
    
    const responseCode = response.getResponseCode();
    if (responseCode !== 200) return null;
    
    const responseText = response.getContentText();
    const data = JSON.parse(responseText);
    
    // Судя по документации, API может вернуть объект товара или массив
    if (data && data.CODE) {
      return data.CODE;
    }
    
    if (Array.isArray(data) && data.length > 0) {
      return data[0].CODE;
    }
    
    return null;
  } catch (e) {
    Logger.log(`❌ Ошибка RS поиска (${vendorCode}): ${e.message}`);
    return null;
  }
}

/**
 * Получить остаток по коду РС
 * 
 * @param {string} rsCode - Внутренний код РС
 * @param {number} warehouseId - ID склада РС
 * @returns {Object|null} Объект с остатком
 */
function fetchRSStockByCode(rsCode, warehouseId) {
  const url = `${rsApiBaseUrl()}/residue/${warehouseId}/${rsCode}`;
  
  const options = {
    method: "get",
    headers: rsHeaders(),
    muteHttpExceptions: true
  };
  
  try {
    const response = retryFetch(url, options);
    if (!response) return null;
    
    const responseCode = response.getResponseCode();
    if (responseCode !== 200) return null;
    
    const data = JSON.parse(response.getContentText());
    return {
      rsStock: data.Residue || 0,
      partnerStock: (data.partnerQuantityInfo && data.partnerQuantityInfo.partnerQuantity) || 0
    };
  } catch (e) {
    Logger.log(`❌ Ошибка RS остатка (${rsCode}): ${e.message}`);
    return null;
  }
}

/**
 * Функция для получения списка всех складов РС
 */
function listRSStocks() {
  const url = `${rsApiBaseUrl()}/stocks`;
  
  const options = {
    method: "get",
    headers: rsHeaders(),
    muteHttpExceptions: true
  };
  
  const response = retryFetch(url, options);
  if (!response) return;
  
  Logger.log("=== СКЛАДЫ RS ===");
  Logger.log(response.getContentText());
}
