/**
 * OZON PERFORMANCE API - Финальная рабочая версия
 * 
 * Заполняет колонки (sheet "тест"):
 * - BA (53): Реклама Количество
 * - BB (54): Реклама Стоимость  
 * - BC (55): Реклама Расход
 * 
 * TARGET SKU: 1644174248 - ожидается 37 заказов, 43860₽, 521.15₽ расход
 * 
 * WORKING ENDPOINTS (тест подтвердил):
 * 1. POST /api/client/statistics - создание отчёта
 * 2. GET /api/client/statistics/{UUID} - проверка статуса (NOTE: NOT /statistic/orders/...)
 * 3. GET /api/client/statistics/report?UUID={UUID} - скачивание
 * 
 * CSV columns found: 0=sku, 9=Расход, 10=Заказы, 11=Продажи
 */

const PERFORMANCE_BASE_URL = "https://api-performance.ozon.ru";

function getPerfToken() {
  const CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru';
  const CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw';
  
  const response = UrlFetchApp.fetch(PERFORMANCE_BASE_URL + '/api/client/token', {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({
      client_id: CLIENT_ID,
      client_secret: CLIENT_SECRET,
      grant_type: 'client_credentials'
    }),
    muteHttpExceptions: true
  });
  
  if (response.getResponseCode() !== 200) {
    Logger.log('Token error: ' + response.getResponseCode());
    return null;
  }
  
  const data = JSON.parse(response.getContentText());
  Logger.log('Token OK');
  return data.access_token;
}

function getPerfCampaigns(token) {
  const response = UrlFetchApp.fetch(PERFORMANCE_BASE_URL + '/api/client/campaign', {
    method: 'get',
    headers: { 'Authorization': 'Bearer ' + token },
    muteHttpExceptions: true
  });
  
  if (response.getResponseCode() !== 200) return [];
  
  const data = JSON.parse(response.getContentText());
  return data.list || [];
}

function createPerfReport(token, campaignIds, dateFrom, dateTo) {
  // Working endpoint: /api/client/statistics with groupBy=SKU
  const response = UrlFetchApp.fetch(PERFORMANCE_BASE_URL + '/api/client/statistics', {
    method: 'post',
    contentType: 'application/json',
    headers: { 'Authorization': 'Bearer ' + token },
    payload: JSON.stringify({
      campaigns: campaignIds,
      dateFrom: dateFrom,
      dateTo: dateTo,
      groupBy: 'SKU'
    }),
    muteHttpExceptions: true
  });
  
  if (response.getResponseCode() !== 200) {
    Logger.log('Create error: ' + response.getResponseCode());
    return null;
  }
  
  const data = JSON.parse(response.getContentText());
  return data.UUID;
}

function waitPerfReport(token, uuid) {
  // CORRECT endpoint: /api/client/statistics/{UUID} (with 's')
  const url = PERFORMANCE_BASE_URL + '/api/client/statistics/' + uuid;
  
  for (let i = 0; i < 25; i++) {
    Utilities.sleep(5000);
    
    const response = UrlFetchApp.fetch(url, {
      method: 'get',
      headers: { 'Authorization': 'Bearer ' + token },
      muteHttpExceptions: true
    });
    
    if (response.getResponseCode() !== 200) continue;
    
    const data = JSON.parse(response.getContentText());
    
    if (data.state === 'OK' && data.link) {
      const downloadUrl = PERFORMANCE_BASE_URL + data.link;
      const raw = UrlFetchApp.fetch(downloadUrl, {
        method: 'get',
        headers: { 'Authorization': 'Bearer ' + token },
        muteHttpExceptions: true
      });
      
      return raw.getContent();
    }
  }
  
  return null;
}

function parsePerfCSV(content) {
  // Need to unzip if PK header
  let data = content;
  if (content.length > 4 && content[0] === 80 && content[1] === 75) {
    const blob = Utilities.newBlob(content);
    const zip = Utilities.unzip(blob);
    data = zip[0].getBytes();
  }
  
  const text = Utilities.newBlob(data).getDataAsString();
  const lines = text.replace(/^\uFEFF/, '').split('\n');
  
  const stats = {};
  
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line || line.startsWith('Всего') || line.startsWith('sku;')) continue;
    
    const parts = line.split(';');
    if (parts.length < 12) continue;
    
    const sku = parts[0].trim();
    if (!sku) continue;
    
    try {
      const spend = parseFloat(parts[9].replace(',', '.')) || 0;
      const orders = parseInt(parts[10]) || 0;
      const revenue = parseFloat(parts[11].replace(',', '.')) || 0;
      
      if (orders > 0 || revenue > 0 || spend > 0) {
        if (!stats[sku]) stats[sku] = { orders: 0, spend: 0, revenue: 0 };
        stats[sku].orders += orders;
        stats[sku].spend += spend;
        stats[sku].revenue += revenue;
      }
    } catch (e) {
      // Skip parsing errors
    }
  }
  
  Logger.log('Parsed: ' + Object.keys(stats).length + ' unique SKUs');
  return stats;
}

function updateOzonAdPerfFinal() {
  const TARGET_SKU = '1644174248';
  
  Logger.log('=== OZON AD PERFORMANCE (FINAL) ===');
  Logger.log('Target: ' + TARGET_SKU);
  
  const token = getPerfToken();
  if (!token) {
    Logger.log('FAIL: No token');
    return;
  }
  
  const campaigns = getPerfCampaigns(token);
  Logger.log('Campaigns: ' + campaigns.length);
  
  const allStats = {};
  const BATCH_SIZE = 10;
  
  for (let i = 0; i < Math.min(50, campaigns.length); i += BATCH_SIZE) {
    const batchIds = campaigns.slice(i, i + BATCH_SIZE).map(c => c.id);
    Logger.log('Batch ' + (i/BATCH_SIZE+1) + ': ' + batchIds.slice(0,3) + '...');
    
    const uuid = createPerfReport(token, batchIds, '2025-04-01', '2025-04-15');
    if (!uuid) continue;
    
    const raw = waitPerfReport(token, uuid);
    if (raw) {
      const batchStats = parsePerfCSV(raw);
      
      for (const sku in batchStats) {
        if (!allStats[sku]) allStats[sku] = { orders: 0, spend: 0, revenue: 0 };
        allStats[sku].orders += batchStats[sku].orders;
        allStats[sku].spend += batchStats[sku].spend;
        allStats[sku].revenue += batchStats[sku].revenue;
      }
      
      if (allStats[TARGET_SKU]) {
        Logger.log('*** FOUND TARGET ' + TARGET_SKU + ': orders=' + allStats[TARGET_SKU].orders + 
              ', spend=' + allStats[TARGET_SKU].spend.toFixed(2) + 
              ', revenue=' + allStats[TARGET_SKU].revenue.toFixed(2));
        break;
      }
    }
    
    if (i + BATCH_SIZE < campaigns.length) Utilities.sleep(15000);
  }
  
  // Update sheet if target found
  const sheet = mainSheet();
  const lastRow = Math.max(2, sheet.getLastRow());
  
  const skuCol = sheet.getRange(2, 22, lastRow - 1).getValues().flat();
  
  const ba = [], bb = [], bc = [];
  let filled = 0;
  
  for (let i = 0; i < skuCol.length; i++) {
    const sku = skuCol[i] ? skuCol[i].toString().trim() : '';
    
    if (sku && allStats[sku]) {
      ba.push([allStats[sku].orders]);
      bb.push([allStats[sku].revenue]);
      bc.push([allStats[sku].spend]);
      filled++;
    } else {
      ba.push([0]);
      bb.push([0]);
      bc.push([0]);
    }
  }
  
  sheet.getRange(2, 53, ba.length, 1).setValues(ba);
  sheet.getRange(2, 54, bb.length, 1).setValues(bb);
  sheet.getRange(2, 55, bc.length, 1).setValues(bc);
  
  Logger.log('Updated: ' + filled + ' rows');
  Logger.log('DONE');
}

function testPerfAPI() {
  Logger.log('=== TEST PERF API ===');
  
  const token = getPerfToken();
  if (!token) {
    Logger.log('FAIL: No token');
    return;
  }
  
  const campaigns = getPerfCampaigns(token);
  Logger.log('Campaigns: ' + campaigns.length);
  
  const testBatch = [campaigns[0].id];
  Logger.log('Testing: ' + testBatch);
  
  const uuid = createPerfReport(token, testBatch, '2025-04-01', '2025-04-15');
  Logger.log('UUID: ' + uuid);
  
  if (uuid) {
    const raw = waitPerfReport(token, uuid);
    if (raw) {
      const stats = parsePerfCSV(raw);
      Logger.log('Stats: ' + JSON.stringify(stats));
    }
  }
  
  Logger.log('DONE');
}