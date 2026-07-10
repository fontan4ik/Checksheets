/**
 * ДИАГНОСТИКА: Расхождения продаж для конкретного артикула
 * Запустить с нужным offer_id
 */
function diagnoseSalesDiscrepancy() {
  const targetOfferId = "48806-1";
  
  const today = new Date();
  const dateFrom = new Date(today.getFullYear(), today.getMonth() - 1, today.getDate());
  
  const formatDate = d => d.toISOString().slice(0, 10);
  const formatTimestamp = d => d.toISOString();
  
  Logger.log(`=== Диагностика для артикула: ${targetOfferId} ===`);
  Logger.log(`Период: ${formatDate(dateFrom)} → ${formatDate(today)}`);
  
  // 1. Общие продажи через analytics API
  Logger.log(`\n--- 1. ОБЩИЕ ПРОДАЖИ (analytics API) ---`);
  
  let totalFromAnalytics = 0;
  let offset = 0;
  let hasMore = true;
  
  while (hasMore) {
    const body = {
      date_from: formatDate(dateFrom),
      date_to: formatDate(today),
      dimension: ["sku"],
      metrics: ["ordered_units"],
      limit: 1000,
      offset: offset
    };
    
    const options = {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify(body)
    };
    
    const response = retryFetch(ozonAnalyticsData(), options);
    if (!response) break;
    
    const data = JSON.parse(response.getContentText());
    const items = data.result?.data || [];
    hasMore = items.length >= 1000;
    
    items.forEach(entry => {
      const name = entry.dimensions[0]?.name || "";
      if (name.includes(targetOfferId.split("-")[0])) {
        const sku = entry.dimensions[0]?.id;
        const units = entry.metrics[0] || 0;
        Logger.log(`  SKU: ${sku}, Название: ${name}, Единицы: ${units}`);
        totalFromAnalytics += units;
      }
    });
    
    offset += items.length;
  }
  
  Logger.log(`Итого из analytics API: ${totalFromAnalytics}`);
  
  // 2. FBS продажи по всем статусам
  Logger.log(`\n--- 2. FBS ПРОДАЖИ (posting API) ---`);
  
  const url = "https://api-seller.ozon.ru/v3/posting/fbs/list";
  const statuses = ["awaiting_packaging", "awaiting_deliver", "delivered", "cancelled", "last_mile", "not_accepted"];
  
  let totalFBS = 0;
  const fbsByStatus = {};
  
  statuses.forEach(status => {
    let fbsOffset = 0;
    let fbsHasMore = true;
    let statusCount = 0;
    
    while (fbsHasMore) {
      const body = {
        dir: "ASC",
        filter: {
          since: formatTimestamp(dateFrom),
          to: formatTimestamp(today),
          status: status
        },
        limit: 1000,
        offset: fbsOffset,
        with: {
          analytics_data: false,
          financial_data: false,
          translit: false
        }
      };
      
      const options = {
        method: "post",
        contentType: "application/json",
        headers: ozonHeaders(),
        payload: JSON.stringify(body),
        muteHttpExceptions: true
      };
      
      const response = retryFetch(url, options);
      if (!response) break;
      
      try {
        const data = JSON.parse(response.getContentText());
        const postings = data.result?.postings || [];
        fbsHasMore = data.result?.has_next || false;
        
        postings.forEach(posting => {
          if (posting.products) {
            posting.products.forEach(product => {
              if (product.offer_id === targetOfferId) {
                const qty = product.quantity || 0;
                statusCount += qty;
                Logger.log(`  ${status}: posting=${posting.posting_number}, sku=${product.sku}, qty=${qty}`);
              }
            });
          }
        });
        
        fbsOffset += postings.length;
      } catch (e) {
        Logger.log(`  Ошибка: ${e.message}`);
        break;
      }
    }
    
    fbsByStatus[status] = statusCount;
    totalFBS += statusCount;
    Logger.log(`  Статус "${status}": ${statusCount} шт`);
    
    Utilities.sleep(1000);
  });
  
  Logger.log(`\nИтого FBS (все статусы): ${totalFBS} шт`);
  
  // 3. FBO расчет
  Logger.log(`\n--- 3. РАСЧЕТ FBO ---`);
  const fbo = totalFromAnalytics - totalFBS;
  Logger.log(`Общие: ${totalFromAnalytics}`);
  Logger.log(`FBS: ${totalFBS}`);
  Logger.log(`FBO (общие - FBS): ${fbo}`);
  
  // 4. Проверка через FBO posting API
  Logger.log(`\n--- 4. FBO ПРОДАЖИ (posting rfb/fbo API) ---`);
  
  const fboUrl = "https://api-seller.ozon.ru/v3/posting/fbo/list";
  let fboCount = 0;
  let fboOffset = 0;
  let fboHasMore = true;
  
  const fboStatuses = ["awaiting_packaging", "awaiting_deliver", "delivered"];
  
  fboStatuses.forEach(status => {
    let statusFboCount = 0;
    fboOffset = 0;
    fboHasMore = true;
    
    while (fboHasMore) {
      const body = {
        dir: "ASC",
        filter: {
          since: formatTimestamp(dateFrom),
          to: formatTimestamp(today),
          status: status
        },
        limit: 1000,
        offset: fboOffset,
        with: {
          analytics_data: false,
          financial_data: false,
          translit: false
        }
      };
      
      const options = {
        method: "post",
        contentType: "application/json",
        headers: ozonHeaders(),
        payload: JSON.stringify(body),
        muteHttpExceptions: true
      };
      
      const response = retryFetch(fboUrl, options);
      if (!response) break;
      
      try {
        const data = JSON.parse(response.getContentText());
        const postings = data.result?.postings || [];
        fboHasMore = data.result?.has_next || false;
        
        postings.forEach(posting => {
          if (posting.products) {
            posting.products.forEach(product => {
              if (product.offer_id === targetOfferId) {
                const qty = product.quantity || 0;
                statusFboCount += qty;
                Logger.log(`  ${status}: posting=${posting.posting_number}, sku=${product.sku}, qty=${qty}`);
              }
            });
          }
        });
        
        fboOffset += postings.length;
      } catch (e) {
        Logger.log(`  Ошибка: ${e.message}`);
        break;
      }
    }
    
    fboCount += statusFboCount;
    Logger.log(`  FBO статус "${status}": ${statusFboCount} шт`);
    Utilities.sleep(1000);
  });
  
  Logger.log(`\nИтого FBO (posting API): ${fboCount} шт`);
  
  // 5. Итоговая сводка
  Logger.log(`\n=== ИТОГОВАЯ СВОДКА ===`);
  Logger.log(`Analytics API (общие): ${totalFromAnalytics}`);
  Logger.log(`FBS posting API (все статусы): ${totalFBS}`);
  Logger.log(`FBO posting API: ${fboCount}`);
  Logger.log(`FBO расчет (общие - FBS): ${fbo}`);
  Logger.log(`FBO + FBS = ${fboCount + totalFBS}`);
  Logger.log(`\nОжидается: 95`);
  Logger.log(`Разница: ${95 - totalFromAnalytics}`);
}
