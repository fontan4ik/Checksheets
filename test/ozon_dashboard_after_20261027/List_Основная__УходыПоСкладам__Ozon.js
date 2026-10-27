const OZON_DASHBOARD_OUTFLOW_TIME_ZONE_ = 'Asia/Dubai';
const OZON_DASHBOARD_OUTFLOW_TEMP_PREFIX_ = '__OzonOutflows_';
const OZON_DASHBOARD_OUTFLOW_PAGE_SIZE_ = 100;
const OZON_DASHBOARD_OUTFLOW_REQUEST_INTERVAL_MS_ = 1000;
const OZON_DASHBOARD_OUTFLOW_EXECUTION_BUDGET_MS_ = 4 * 60 * 1000;

function ozonDashboardBeginOutflows_(sheet, state) {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const period = ozonDashboardOutflowPeriod_();
  Object.keys(OZON_DASHBOARD_OUTFLOW_HEADERS_).forEach(function(stockHeader) {
    ozonDashboardColumnByHeader_(sheet, OZON_DASHBOARD_OUTFLOW_HEADERS_[stockHeader]);
  });
  const warehouseHeaders = ozonDashboardFetchFboWarehouseHeaders_(state);
  const tempSheetName = OZON_DASHBOARD_OUTFLOW_TEMP_PREFIX_ + String(state.runId).replace(/-/g, '').slice(0, 12);
  if (spreadsheet.getSheetByName(tempSheetName)) {
    throw new Error('Временный лист уходов Ozon уже существует: ' + tempSheetName);
  }
  const tempSheet = spreadsheet.insertSheet(tempSheetName);
  tempSheet.getRange(1, 1, 1, 3).setValues([['SKU', 'Заголовок ухода', 'Количество']]);
  tempSheet.hideSheet();

  state.phase = 'outflows';
  state.outflowDateFrom = period.from;
  state.outflowDateTo = period.to;
  state.outflowCursor = '';
  state.outflowPages = 0;
  state.outflowPostings = 0;
  state.outflowTempSheetName = tempSheetName;
  state.outflowTempRow = 2;
  state.outflowPendingPage = null;
  state.outflowWarehouseHeaders = warehouseHeaders;
  PropertiesService.getScriptProperties().setProperty(OZON_DASHBOARD_STATE_KEY_, JSON.stringify(state));
}

function ozonDashboardOutflowPeriod_() {
  const today = Utilities.formatDate(new Date(), OZON_DASHBOARD_OUTFLOW_TIME_ZONE_, 'yyyy-MM-dd')
    .split('-').map(Number);
  const year = today[0];
  const month = today[1];
  const day = today[2];
  const previousMonth = month === 1 ? 12 : month - 1;
  const previousYear = month === 1 ? year - 1 : year;
  const previousMonthDays = new Date(Date.UTC(previousYear, previousMonth, 0)).getUTCDate();
  const startDay = Math.min(day, previousMonthDays);
  const pad = function(value) { return String(value).padStart(2, '0'); };
  const startDate = previousYear + '-' + pad(previousMonth) + '-' + pad(startDay);
  const endDate = year + '-' + pad(month) + '-' + pad(day);
  return {
    from: new Date(startDate + 'T00:00:00.000+04:00').toISOString(),
    to: new Date(endDate + 'T23:59:59.999+04:00').toISOString(),
    fromLabel: startDate,
    toLabel: endDate
  };
}

function ozonDashboardFetchFboWarehouseHeaders_(state) {
  const response = ozonDashboardPostJson_(
    OZON_DASHBOARD_API_.fboClusters,
    {},
    state,
    OZON_DASHBOARD_OUTFLOW_REQUEST_INTERVAL_MS_
  );
  const clusters = Array.isArray(response.result) ? response.result :
    (response.result && Array.isArray(response.result.clusters) ? response.result.clusters : null);
  if (!clusters) throw new Error('Ozon cluster list: в ответе отсутствует список кластеров');

  const warehouseHeaders = Object.create(null);
  const unmappedRegions = Object.create(null);
  clusters.forEach(function(cluster) {
    const data = cluster && cluster.data || {};
    const regionName = String(data.macrolocal_cluster && data.macrolocal_cluster.name || '').trim();
    const stockHeader = OZON_DASHBOARD_REGION_HEADERS_[ozonDashboardNormalize_(regionName)];
    const outflowHeader = stockHeader && OZON_DASHBOARD_OUTFLOW_HEADERS_[stockHeader];
    const warehouses = Array.isArray(data.fulfillments) ? data.fulfillments : [];
    warehouses.forEach(function(warehouse) {
      const warehouseName = String(warehouse && warehouse.name || '').trim();
      const warehouseKey = ozonDashboardNormalize_(warehouseName);
      if (!warehouseKey) throw new Error('Ozon cluster list: у склада отсутствует название');
      if (!outflowHeader) {
        unmappedRegions[regionName || '(без названия)'] = true;
        return;
      }
      if (warehouseHeaders[warehouseKey] && warehouseHeaders[warehouseKey] !== outflowHeader) {
        throw new Error('Ozon cluster list: склад «' + warehouseName + '» связан с несколькими регионами');
      }
      warehouseHeaders[warehouseKey] = outflowHeader;
    });
  });
  const unmapped = Object.keys(unmappedRegions);
  if (unmapped.length) {
    throw new Error('Ozon cluster list: регионы «' + unmapped.join('», «') +
      '» не сопоставлены с колонками уходов');
  }
  if (!Object.keys(warehouseHeaders).length) throw new Error('Ozon cluster list: не найдено ни одного склада FBO');
  return warehouseHeaders;
}

function ozonDashboardSyncOutflowPages_(sheet, state) {
  const tempSheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(state.outflowTempSheetName);
  if (!tempSheet) throw new Error('Не найден временный лист уходов Ozon');
  ozonDashboardRecoverPendingOutflowPage_(tempSheet, state);

  const startedAt = Date.now();
  let processedPages = 0;
  while (Date.now() - startedAt < OZON_DASHBOARD_OUTFLOW_EXECUTION_BUDGET_MS_) {
    const payload = {
      dir: 'ASC',
      filter: {since: state.outflowDateFrom, to: state.outflowDateTo},
      limit: OZON_DASHBOARD_OUTFLOW_PAGE_SIZE_,
      with: {analytics_data: true, financial_data: false}
    };
    if (state.outflowCursor) payload.cursor = state.outflowCursor;
    const response = ozonDashboardPostJson_(
      OZON_DASHBOARD_API_.fboPostings,
      payload,
      state,
      OZON_DASHBOARD_OUTFLOW_REQUEST_INTERVAL_MS_
    );
    const postings = Array.isArray(response.postings) ? response.postings : null;
    if (!postings || typeof response.has_next !== 'boolean') {
      throw new Error('Ozon FBO postings: в ответе отсутствует список отправлений или has_next');
    }

    const nextCursor = String(response.cursor || '').trim();
    if (response.has_next && (!nextCursor || nextCursor === state.outflowCursor)) {
      throw new Error('Ozon FBO postings: курсор пагинации не продвигается');
    }
    const pageTotals = ozonDashboardAggregateOutflowPostings_(postings, state.outflowWarehouseHeaders);
    const rows = [];
    Object.keys(pageTotals).forEach(function(sku) {
      Object.keys(pageTotals[sku]).forEach(function(header) {
        rows.push([sku, header, pageTotals[sku][header]]);
      });
    });

    if (rows.length) {
      state.outflowPendingPage = {row: state.outflowTempRow, count: rows.length};
      PropertiesService.getScriptProperties().setProperty(OZON_DASHBOARD_STATE_KEY_, JSON.stringify(state));
      const requiredLastRow = state.outflowTempRow + rows.length - 1;
      if (requiredLastRow > tempSheet.getMaxRows()) {
        tempSheet.insertRowsAfter(tempSheet.getMaxRows(), requiredLastRow - tempSheet.getMaxRows());
      }
      tempSheet.getRange(state.outflowTempRow, 1, rows.length, 3).setValues(rows);
      state.outflowTempRow += rows.length;
    }
    state.outflowCursor = response.has_next ? nextCursor : '';
    state.outflowPages++;
    state.outflowPostings += postings.length;
    state.outflowPendingPage = null;
    processedPages++;
    if (state.outflowPages > 10000) throw new Error('Ozon FBO postings: превышено число страниц');
    if (!response.has_next) {
      state.phase = 'outflowCommit';
    }
    PropertiesService.getScriptProperties().setProperty(OZON_DASHBOARD_STATE_KEY_, JSON.stringify(state));
    if (!response.has_next) break;
  }
  Logger.log(JSON.stringify({
    service: 'Ozon monthly FBO outflows',
    runId: state.runId,
    dateFrom: state.outflowDateFrom,
    dateTo: state.outflowDateTo,
    pagesThisExecution: processedPages,
    pagesTotal: state.outflowPages,
    postingsTotal: state.outflowPostings,
    nextCursorAvailable: Boolean(state.outflowCursor),
    phase: state.phase
  }));
}

function ozonDashboardAggregateOutflowPostings_(postings, warehouseHeaders) {
  const totals = Object.create(null);
  const unmappedWarehouses = Object.create(null);
  postings.forEach(function(posting) {
    const status = String(posting && posting.status || '').toLocaleLowerCase('en-US');
    if (status.indexOf('cancel') >= 0) return;
    const analytics = posting && posting.analytics_data || {};
    const warehouseName = String(analytics.warehouse_name || analytics.warehouse ||
      posting && posting.warehouse_name || '').trim();
    const warehouseKey = ozonDashboardNormalize_(warehouseName);
    const aliasStockHeader = OZON_DASHBOARD_FBO_WAREHOUSE_HEADERS_[warehouseKey];
    const header = warehouseHeaders[warehouseKey] ||
      (aliasStockHeader && OZON_DASHBOARD_OUTFLOW_HEADERS_[aliasStockHeader]);
    if (!header) {
      unmappedWarehouses[warehouseName || '(без названия склада)'] = true;
      return;
    }
    (Array.isArray(posting.products) ? posting.products : []).forEach(function(product) {
      const sku = ozonDashboardValidSku_(product && product.sku);
      const quantity = Number(product && product.quantity);
      if (!sku || !Number.isSafeInteger(quantity) || quantity <= 0) return;
      if (!totals[sku]) totals[sku] = Object.create(null);
      totals[sku][header] = (totals[sku][header] || 0) + quantity;
    });
  });
  const unknown = Object.keys(unmappedWarehouses);
  if (unknown.length) {
    throw new Error('Ozon FBO postings: склады не сопоставлены с регионами: «' + unknown.join('», «') + '»');
  }
  return totals;
}

function ozonDashboardRecoverPendingOutflowPage_(tempSheet, state) {
  const pending = state.outflowPendingPage;
  if (!pending) return;
  const lastRow = tempSheet.getLastRow();
  if (lastRow >= pending.row) {
    tempSheet.getRange(pending.row, 1, lastRow - pending.row + 1, 3).clearContent();
  }
  state.outflowTempRow = pending.row;
  state.outflowPendingPage = null;
  PropertiesService.getScriptProperties().setProperty(OZON_DASHBOARD_STATE_KEY_, JSON.stringify(state));
}

function ozonDashboardCommitOutflows_(sheet, state) {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const tempSheet = spreadsheet.getSheetByName(state.outflowTempSheetName);
  if (!tempSheet) throw new Error('Не найден временный лист уходов Ozon');
  const skuColumn = ozonDashboardColumnByHeader_(sheet, OZON_DASHBOARD_TARGET_HEADERS_.fboSku);
  const rowCount = Math.max(0, state.lastRow - 1);
  const skuRows = rowCount ? sheet.getRange(2, skuColumn, rowCount, 1).getValues() : [];
  const outputColumns = Object.keys(OZON_DASHBOARD_OUTFLOW_HEADERS_).map(function(stockHeader) {
    const header = OZON_DASHBOARD_OUTFLOW_HEADERS_[stockHeader];
    return {header: header, column: ozonDashboardColumnByHeader_(sheet, header)};
  });
  const totalsBySku = Object.create(null);
  const allowedHeaders = Object.create(null);
  Object.keys(OZON_DASHBOARD_OUTFLOW_HEADERS_).forEach(function(stockHeader) {
    allowedHeaders[OZON_DASHBOARD_OUTFLOW_HEADERS_[stockHeader]] = true;
  });
  const tempLastRow = tempSheet.getLastRow();
  if (tempLastRow > 1) {
    tempSheet.getRange(2, 1, tempLastRow - 1, 3).getValues().forEach(function(row) {
      const sku = ozonDashboardValidSku_(row[0]);
      const header = String(row[1] || '');
      const quantity = Number(row[2]);
      if (!sku || !allowedHeaders[header] || !Number.isSafeInteger(quantity) || quantity <= 0) return;
      if (!totalsBySku[sku]) totalsBySku[sku] = Object.create(null);
      totalsBySku[sku][header] = (totalsBySku[sku][header] || 0) + quantity;
    });
  }

  const eligible = skuRows.map(function(row) { return Boolean(ozonDashboardValidSku_(row[0])); });
  let cellsWritten = 0;
  outputColumns.forEach(function(target) {
    const values = skuRows.map(function(row) {
      const sku = ozonDashboardValidSku_(row[0]);
      return sku && totalsBySku[sku] ? (totalsBySku[sku][target.header] || 0) : 0;
    });
    cellsWritten += ozonDashboardWriteColumn_(sheet, target.column, 2, values, eligible);
  });
  return {cellsWritten: cellsWritten};
}
