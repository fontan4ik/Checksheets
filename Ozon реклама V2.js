/**
 * OZON РЕКЛАМА - Performance API (отчёт по ЗАКАЗАМ)
 *
 * Заполняет колонки:
 * - BA (53): Реклама Количество (количество заказов)
 * - BB (54): Реклама Стоимость (выручка/доход)
 * - BC (55): Реклама Расход (расход на рекламу)
 *
 * API Эндпоинты:
 * - OAuth: POST https://api-performance.ozon.ru/api/client/token
 * - Кампании: GET https://api-performance.ozon.ru/api/client/campaign
 * - Отчёт по заказам: POST https://api-performance.ozon.ru/api/client/statistic/orders/generate
 * - Статус отчёта: GET https://api-performance.ozon.ru/api/client/statistic/orders/status?UUID=...
 * - Скачать отчёт: GET https://api-performance.ozon.ru/api/client/statistic/orders/download?UUID=...
 *
 * Ограничения API:
 * - Максимум 60 дней для одного отчёта
 * - Максимум 10 кампаний за один запрос
 * - Отчёты создаются асинхронно
 */

const PERFORMANCE_BASE_URL = "https://api-performance.ozon.ru";

function getPerformanceAuthTokenV2() {
  const clientId = '92353868-1771409527407@advertising.performance.ozon.ru';
  const clientSecret = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw';

  const url = `${PERFORMANCE_BASE_URL}/api/client/token`;

  const body = {
    client_id: clientId,
    client_secret: clientSecret,
    grant_type: "client_credentials"
  };

  const options = {
    method: "post",
    contentType: "application/json",
    headers: {
      "Accept": "application/json"
    },
    payload: JSON.stringify(body),
    muteHttpExceptions: true
  };

  try {
    const response = UrlFetchApp.fetch(url, options);
    const responseCode = response.getResponseCode();
    const responseText = response.getContentText();

    if (responseCode !== 200) {
      Logger.log(`❌ Token error: ${responseCode} - ${responseText}`);
      return null;
    }

    const data = JSON.parse(responseText);
    const token = data.access_token;

    if (!token) {
      Logger.log("❌ Token not found in response");
      return null;
    }

    Logger.log("✅ Performance token obtained");
    return token;
  } catch (e) {
    Logger.log(`❌ Token error: ${e.message}`);
    return null;
  }
}

function getPerformanceCampaignsV2(authToken) {
  const url = `${PERFORMANCE_BASE_URL}/api/client/campaign`;

  const options = {
    method: "get",
    headers: {
      "Authorization": "Bearer " + authToken,
      "Content-Type": "application/json"
    },
    muteHttpExceptions: true
  };

  try {
    const response = UrlFetchApp.fetch(url, options);
    const responseCode = response.getResponseCode();

    if (responseCode !== 200) {
      Logger.log(`❌ Campaigns error: ${responseCode}`);
      return null;
    }

    const data = JSON.parse(response.getContentText());
    const campaigns = data.list || [];

    Logger.log(`✅ Got ${campaigns.length} campaigns`);
    return campaigns;
  } catch (e) {
    Logger.log(`❌ Campaigns error: ${e.message}`);
    return null;
  }
}

function createOrdersReportV2(authToken, campaignIds, dateFrom, dateTo) {
  const url = `${PERFORMANCE_BASE_URL}/api/client/statistic/orders/generate`;

  const body = {
    campaigns: campaignIds,
    dateFrom: dateFrom,
    dateTo: dateTo
  };

  const options = {
    method: "post",
    headers: {
      "Authorization": "Bearer " + authToken,
      "Content-Type": "application/json"
    },
    payload: JSON.stringify(body),
    muteHttpExceptions: true
  };

  try {
    const response = UrlFetchApp.fetch(url, options);
    const responseCode = response.getResponseCode();
    const responseText = response.getContentText();

    if (responseCode !== 200) {
      Logger.log(`❌ Create orders report error: ${responseCode}`);
      Logger.log(`   ${responseText}`);
      return null;
    }

    const data = JSON.parse(responseText);
    const uuid = data.UUID;

    if (!uuid) {
      Logger.log("❌ UUID not found in response");
      return null;
    }

    Logger.log(`✅ Orders report UUID: ${uuid}`);
    return uuid;
  } catch (e) {
    Logger.log(`❌ Create orders report error: ${e.message}`);
    return null;
  }
}

function getOrdersReportStatusV2(authToken, uuid) {
  const url = `${PERFORMANCE_BASE_URL}/api/client/statistic/orders/status?UUID=${uuid}`;

  const options = {
    method: "get",
    headers: {
      "Authorization": "Bearer " + authToken,
      "Content-Type": "application/json"
    },
    muteHttpExceptions: true
  };

  try {
    const response = UrlFetchApp.fetch(url, options);
    const responseCode = response.getResponseCode();
    const responseText = response.getContentText();

    if (responseCode === 404) {
      return { status: "IN_PROGRESS", error: null };
    }

    if (responseCode !== 200) {
      return { status: "ERROR", error: `HTTP ${responseCode}` };
    }

    const trimmed = responseText.replace(/^\uFEFF/, '').trim();

    if (trimmed.startsWith('PK')) {
      return { status: "OK", error: null, isZip: true };
    }

    if (trimmed.startsWith('sku') || trimmed.startsWith(';') || trimmed.startsWith('Дата')) {
      return { status: "OK", error: null, isZip: false };
    }

    const data = JSON.parse(responseText);
    return { status: data.state || "IN_PROGRESS", error: null };

  } catch (e) {
    if (responseText && responseText.startsWith('PK')) {
      return { status: "OK", error: null, isZip: true };
    }
    return { status: "ERROR", error: e.message };
  }
}

function downloadOrdersReportV2(authToken, uuid) {
  const url = `${PERFORMANCE_BASE_URL}/api/client/statistic/orders/download?UUID=${uuid}`;

  const options = {
    method: "get",
    headers: {
      "Authorization": "Bearer " + authToken
    },
    muteHttpExceptions: true
  };

  try {
    const response = UrlFetchApp.fetch(url, options);
    const responseCode = response.getResponseCode();

    if (responseCode !== 200) {
      Logger.log(`❌ Download error: ${responseCode}`);
      return null;
    }

    return response.getBlob();
  } catch (e) {
    Logger.log(`❌ Download error: ${e.message}`);
    return null;
  }
}

function parseOrdersReportV2(blob) {
  try {
    let csvData = "";

    const bytes = blob.getBytes();
    const isZip = bytes.length > 4 && bytes[0] === 0x50 && bytes[1] === 0x4B;

    if (isZip) {
      const unzipped = Utilities.unzip(blob);
      if (!unzipped || unzipped.length === 0) {
        Logger.log("❌ ZIP empty");
        return {};
      }
      csvData = unzipped[0].getDataAsString();
      Logger.log(`📦 Unpacked ${unzipped.length} files`);
    } else {
      csvData = blob.getDataAsString();
      Logger.log(`📄 Got CSV directly`);
    }

    csvData = csvData.replace(/^\uFEFF/, '');
    const lines = csvData.split("\n");

    Logger.log(`📄 Total lines: ${lines.length}`);

    if (lines.length > 0) {
      Logger.log(`📋 First line: ${lines[0].substring(0, 200)}`);
    }

    let headerIndex = -1;
    for (let i = 0; i < Math.min(5, lines.length); i++) {
      if (lines[i].toLowerCase().includes('sku') && (lines[i].toLowerCase().includes('заказ') || lines[i].toLowerCase().includes('order') || lines[i].toLowerCase().includes('выруч'))) {
        headerIndex = i;
        break;
      }
    }

    if (headerIndex === -1) {
      Logger.log("⚠️ Header not found, using line 0");
      headerIndex = 0;
    }

    const stats = {};
    let parsedCount = 0;

    const headerLine = lines[headerIndex].toLowerCase();
    const parts = lines[headerIndex].split(";");

    let skuIndex = -1;
    let ordersIndex = -1;
    let revenueIndex = -1;
    let spendIndex = -1;

    for (let i = 0; i < parts.length; i++) {
      const col = parts[i].toLowerCase().trim();
      if (col === 'sku' || col.includes('артикул')) {
        skuIndex = i;
      } else if (col.includes('заказ') || col === 'orders') {
        ordersIndex = i;
      } else if (col.includes('выручк') || col.includes('доход') || col.includes('сумм') || col === 'revenue' || col === 'sum') {
        revenueIndex = i;
      } else if (col.includes('расход') || col.includes('spent') || col === 'cost' || col === 'spend') {
        spendIndex = i;
      }
    }

    Logger.log(`📊 Column indexes: sku=${skuIndex}, orders=${ordersIndex}, revenue=${revenueIndex}, spend=${spendIndex}`);

    for (let i = headerIndex + 1; i < lines.length; i++) {
      const line = lines[i].trim();
      if (!line || line.startsWith('Всего') || line.startsWith('Total')) continue;

      const lineParts = line.split(";");
      const sku = skuIndex >= 0 ? lineParts[skuIndex]?.trim() : lineParts[0]?.trim();

      if (!sku) continue;

      const orders = ordersIndex >= 0 ? parseInt(lineParts[ordersIndex]?.trim() || '0') : 0;
      const revenue = revenueIndex >= 0 ? parseFloat(lineParts[revenueIndex]?.trim().replace(',', '.') || '0') : 0;
      const spend = spendIndex >= 0 ? parseFloat(lineParts[spendIndex]?.trim().replace(',', '.') || '0') : 0;

      if (orders > 0 || revenue > 0 || spend > 0) {
        if (!stats[sku]) {
          stats[sku] = { orders: 0, revenue: 0, spend: 0 };
        }
        stats[sku].orders += orders;
        stats[sku].revenue += revenue;
        stats[sku].spend += spend;
        parsedCount++;
      }
    }

    Logger.log(`✅ Parsed: ${parsedCount} rows, ${Object.keys(stats).length} unique SKUs`);

    const totalOrders = Object.values(stats).reduce((sum, s) => sum + s.orders, 0);
    const totalRevenue = Object.values(stats).reduce((sum, s) => sum + s.revenue, 0);
    const totalSpend = Object.values(stats).reduce((sum, s) => sum + s.spend, 0);
    Logger.log(`📊 TOTAL: orders=${totalOrders}, revenue=${totalRevenue.toFixed(2)} RUB, spend=${totalSpend.toFixed(2)} RUB`);

    const topSKUs = Object.entries(stats)
      .sort((a, b) => b[1].orders - a[1].orders)
      .slice(0, 5);

    if (topSKUs.length > 0) {
      Logger.log(`📊 TOP 5 by orders:`);
      topSKUs.forEach(([sku, data], i) => {
        Logger.log(`   ${i + 1}. SKU ${sku}: orders=${data.orders}, revenue=${data.revenue.toFixed(2)}, spend=${data.spend.toFixed(2)}`);
      });
    }

    return stats;
  } catch (e) {
    Logger.log(`❌ Parse error: ${e.message}`);
    return {};
  }
}

function fetchOrdersStatsV2(authToken, campaigns, dateFrom, dateTo, label) {
  const formatDate = date => Utilities.formatDate(date, "GMT+3", "yyyy-MM-dd");
  const stats = {};

  const MAX_DAYS = 60;
  const MAX_CAMPAIGNS = 10;

  const startDate = new Date(dateFrom);
  const endDate = new Date(dateTo);
  const totalDays = Math.ceil((endDate - startDate) / (1000 * 60 * 60 * 24));

  Logger.log(`📊 [${label}] Period: ${formatDate(dateFrom)} → ${formatDate(dateTo)} (${totalDays} days)`);
  Logger.log(`📊 [${label}] Campaigns: ${campaigns.length} (limit: ${MAX_CAMPAIGNS})`);

  if (totalDays <= MAX_DAYS && campaigns.length <= MAX_CAMPAIGNS) {
    const campaignIds = campaigns.map(c => c.id);
    const uuid = createOrdersReportV2(authToken, campaignIds, formatDate(dateFrom), formatDate(dateTo));

    if (!uuid) {
      Logger.log(`❌ [${label}] Failed to create report`);
      return {};
    }

    Logger.log(`✅ [${label}] UUID: ${uuid}, waiting...`);

    let attempts = 0;
    const maxAttempts = 60;

    while (attempts < maxAttempts) {
      attempts++;
      Utilities.sleep(5000);

      const status = getOrdersReportStatusV2(authToken, uuid);

      if (status.status === "OK") {
        Logger.log(`✅ [${label}] Report ready (attempt ${attempts})`);
        const blob = downloadOrdersReportV2(authToken, uuid);
        return parseOrdersReportV2(blob);
      } else if (status.status === "ERROR") {
        Logger.log(`❌ [${label}] Error: ${status.error}`);
        return {};
      }

      if (attempts % 10 === 0) {
        Logger.log(`⏳ [${label}] Waiting... (${attempts}/${maxAttempts})`);
      }
    }

    Logger.log(`❌ [${label}] Timeout`);
    return {};
  } else {
    Logger.log(`⚠️ [${label}] Splitting into chunks...`);

    const campaignChunks = [];
    for (let i = 0; i < campaigns.length; i += MAX_CAMPAIGNS) {
      campaignChunks.push(campaigns.slice(i, i + MAX_CAMPAIGNS));
    }

    Logger.log(`📦 [${label}] ${campaignChunks.length} chunks`);

    for (let i = 0; i < campaignChunks.length; i++) {
      const chunk = campaignChunks[i];
      const campaignIds = chunk.map(c => c.id);

      Logger.log(`📦 [${label}] Chunk ${i + 1}/${campaignChunks.length}: ${campaignIds.length} campaigns`);

      const uuid = createOrdersReportV2(authToken, campaignIds, formatDate(dateFrom), formatDate(dateTo));

      if (!uuid) {
        Logger.log(`❌ Chunk ${i + 1}: failed to create report`);
        continue;
      }

      let attempts = 0;
      const maxAttempts = 60;

      while (attempts < maxAttempts) {
        attempts++;
        Utilities.sleep(5000);

        const status = getOrdersReportStatusV2(authToken, uuid);

        if (status.status === "OK") {
          Logger.log(`✅ Chunk ${i + 1}: ready`);
          const blob = downloadOrdersReportV2(authToken, uuid);
          const chunkStats = parseOrdersReportV2(blob);

          for (const sku in chunkStats) {
            if (!stats[sku]) stats[sku] = { orders: 0, revenue: 0, spend: 0 };
            stats[sku].orders += chunkStats[sku].orders;
            stats[sku].revenue += chunkStats[sku].revenue;
            stats[sku].spend += chunkStats[sku].spend;
          }

          Logger.log(`✅ Chunk ${i + 1}: added ${Object.keys(chunkStats).length} SKUs`);
          break;
        } else if (status.status === "ERROR") {
          Logger.log(`❌ Chunk ${i + 1}: error`);
          break;
        }

        if (attempts % 10 === 0) {
          Logger.log(`⏳ Chunk ${i + 1}: waiting...`);
        }
      }

      if (i < campaignChunks.length - 1) {
        Utilities.sleep(15000);
      }
    }

    return stats;
  }
}

function updateOzonAdExpensesV2() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("❌ No data");
    return;
  }

  Logger.log("=== OZON AD EXPENSES V2 (ORDERS REPORT) ===");
  Logger.log("Column BA (53): Ad Quantity");
  Logger.log("Column BB (54): Ad Revenue");
  Logger.log("Column BC (55): Ad Spend");

  const authToken = getPerformanceAuthTokenV2();
  if (!authToken) {
    Logger.log("❌ Failed to get token");
    return;
  }

  const campaigns = getPerformanceCampaignsV2(authToken);
  if (!campaigns || campaigns.length === 0) {
    Logger.log("❌ No campaigns");
    return;
  }

  Logger.log(`📊 Total campaigns: ${campaigns.length}`);

  const today = new Date();
  const dateTo = new Date(today);
  dateTo.setDate(today.getDate() - 2);

  const dateFrom = new Date(dateTo);
  dateFrom.setDate(dateTo.getDate() - 30);

  const formatDate = date => Utilities.formatDate(date, "GMT+3", "yyyy-MM-dd");

  Logger.log(`📅 Period: ${formatDate(dateFrom)} → ${formatDate(dateTo)}`);

  const allStats = fetchOrdersStatsV2(authToken, campaigns, dateFrom, dateTo, "30 Days");

  const skuRange = sheet.getRange(2, 22, lastRow - 1);
  const skuValues = skuRange.getValues().flat();

  Logger.log(`📋 SKU count from table: ${skuValues.length}`);

  const sampleSKUs = skuValues.filter(s => s).slice(0, 5);
  if (sampleSKUs.length > 0) {
    Logger.log(`📋 Sample SKUs: ${sampleSKUs.join(', ')}`);
  }

  const colBA = [];
  const colBB = [];
  const colBC = [];
  let withData = 0;

  const targetSKU = '1644174248';
  if (allStats[targetSKU]) {
    const data = allStats[targetSKU];
    Logger.log(`🎯 TARGET SKU ${targetSKU}: orders=${data.orders}, revenue=${data.revenue.toFixed(2)}, spend=${data.spend.toFixed(2)}`);
  } else {
    Logger.log(`⚠️ TARGET SKU ${targetSKU} NOT FOUND`);
    Logger.log(`   Available SKUs: ${Object.keys(allStats).slice(0, 10).join(', ')}`);
  }

  for (let i = 0; i < skuValues.length; i++) {
    const sku = skuValues[i] ? skuValues[i].toString().trim() : "";

    if (sku && allStats[sku]) {
      const data = allStats[sku];
      colBA.push([data.orders]);
      colBB.push([data.revenue]);
      colBC.push([data.spend]);
      withData++;
    } else {
      colBA.push([0]);
      colBB.push([0]);
      colBC.push([0]);
    }
  }

  sheet.getRange(2, 53, colBA.length, 1).setValues(colBA);
  sheet.getRange(2, 54, colBB.length, 1).setValues(colBB);
  sheet.getRange(2, 55, colBC.length, 1).setValues(colBC);

  Logger.log(`📊 Updated: ${skuValues.length} rows, ${withData} with data`);
  Logger.log(`✅ DONE`);
}

function testOrdersReportV2() {
  Logger.log("=== TEST ORDERS REPORT V2 ===");

  const authToken = getPerformanceAuthTokenV2();
  if (!authToken) {
    Logger.log("❌ Token failed");
    return;
  }

  const campaigns = getPerformanceCampaignsV2(authToken);
  if (!campaigns || campaigns.length === 0) {
    Logger.log("❌ No campaigns");
    return;
  }

  Logger.log(`📊 Campaigns: ${campaigns.length}`);

  const testCampaigns = campaigns.slice(0, 3);
  const campaignIds = testCampaigns.map(c => c.id);

  Logger.log(`📊 Testing with campaigns: ${campaignIds.join(', ')}`);

  const today = new Date();
  const dateFrom = new Date(today);
  dateFrom.setDate(today.getDate() - 7);

  const formatDate = date => Utilities.formatDate(date, "GMT+3", "yyyy-MM-dd");

  Logger.log(`📅 Period: ${formatDate(dateFrom)} → ${formatDate(today)}`);

  const uuid = createOrdersReportV2(authToken, campaignIds, formatDate(dateFrom), formatDate(today));

  if (!uuid) {
    Logger.log("❌ Failed to create report");
    return;
  }

  Logger.log(`✅ UUID: ${uuid}`);

  Logger.log("⏳ Waiting for report...");
  let attempts = 0;

  while (attempts < 30) {
    attempts++;
    Utilities.sleep(5000);

    const status = getOrdersReportStatusV2(authToken, uuid);

    if (status.status === "OK") {
      Logger.log(`✅ Report ready (attempt ${attempts})`);

      const blob = downloadOrdersReportV2(authToken, uuid);
      if (!blob) {
        Logger.log("❌ Download failed");
        return;
      }

      Logger.log(`📦 Size: ${blob.getBytes().length} bytes`);

      const stats = parseOrdersReportV2(blob);

      if (!stats || Object.keys(stats).length === 0) {
        Logger.log("❌ Empty stats");
        return;
      }

      Logger.log(`✅ TEST PASSED! ${Object.keys(stats).length} SKUs`);
      return;
    } else if (status.status === "ERROR") {
      Logger.log(`❌ Error: ${status.error}`);
      return;
    }

    if (attempts % 5 === 0) {
      Logger.log(`⏳ Waiting... (${attempts}/30)`);
    }
  }

  Logger.log("❌ Timeout");
}
