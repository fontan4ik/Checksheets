function ozonDashboardFetchTargetWarehouseIds_(state) {
  const wantedByName = Object.create(null);
  Object.keys(OZON_DASHBOARD_TARGET_HEADERS_.fbsWarehouses).forEach(function(header) {
    const name = OZON_DASHBOARD_TARGET_HEADERS_.fbsWarehouses[header];
    wantedByName[ozonDashboardNormalize_(name)] = {header: header, name: name};
  });

  const found = Object.create(null);
  let cursor = '';
  let pageCount = 0;
  const seenCursors = Object.create(null);
  do {
    const payload = {limit: 200};
    if (cursor) payload.cursor = cursor;
    const data = ozonDashboardPostJson_(OZON_DASHBOARD_API_.warehouses, payload, state, 250);
    const warehouses = Array.isArray(data.warehouses) ? data.warehouses :
      (Array.isArray(data.result) ? data.result : null);
    if (!warehouses || typeof data.has_next !== 'boolean') {
      throw new Error('Ozon warehouse list: в ответе отсутствует список складов или has_next');
    }
    warehouses.forEach(function(warehouse) {
      const name = ozonDashboardNormalize_(warehouse && warehouse.name);
      const match = wantedByName[name];
      if (!match) return;
      const id = warehouse && warehouse.warehouse_id;
      if (id === null || id === undefined || String(id).trim() === '') {
        throw new Error('Ozon warehouse list: у склада «' + match.name + '» отсутствует ID');
      }
      if (found[match.header] && String(found[match.header]) !== String(id)) {
        throw new Error('Ozon warehouse list: найдено несколько складов «' + match.name + '»');
      }
      found[match.header] = String(id);
    });

    pageCount++;
    if (pageCount > 10) throw new Error('Ozon warehouse list: превышено число страниц');
    const nextCursor = String(data.cursor || '').trim();
    if (data.has_next && (!nextCursor || nextCursor === cursor || seenCursors[nextCursor])) {
      throw new Error('Ozon warehouse list: курсор пагинации не продвигается');
    }
    if (nextCursor) seenCursors[nextCursor] = true;
    cursor = data.has_next ? nextCursor : '';
  } while (cursor);

  const missing = Object.keys(wantedByName).filter(function(name) {
    const item = wantedByName[name];
    return !found[item.header];
  });
  if (missing.length) {
    throw new Error('Ozon warehouse list: не найдены целевые склады — ' +
      missing.map(function(name) { return wantedByName[name].name; }).join(', '));
  }
  return found;
}

function ozonDashboardSyncStockSlice_(sheet, state) {
  const layout = {
    fboSku: ozonDashboardColumnByHeader_(sheet, OZON_DASHBOARD_TARGET_HEADERS_.fboSku),
    fbsSku: ozonDashboardColumnByHeader_(sheet, OZON_DASHBOARD_TARGET_HEADERS_.fbsSku),
    fboClusters: OZON_DASHBOARD_TARGET_HEADERS_.fboClusters.map(function(header) {
      return {header: header, column: ozonDashboardColumnByHeader_(sheet, header)};
    }),
    fbsWarehouses: Object.keys(OZON_DASHBOARD_TARGET_HEADERS_.fbsWarehouses).map(function(header) {
      return {
        header: header,
        warehouseName: OZON_DASHBOARD_TARGET_HEADERS_.fbsWarehouses[header],
        warehouseId: String(state.warehouseIds && state.warehouseIds[header] || ''),
        column: ozonDashboardColumnByHeader_(sheet, header)
      };
    })
  };
  layout.fbsWarehouses.forEach(function(warehouse) {
    if (!warehouse.warehouseId) throw new Error('Не найден Ozon warehouse_id для «' + warehouse.warehouseName + '»');
  });

  const sliceSize = 1500;
  const startRow = state.rowOffset;
  const rowCount = Math.min(sliceSize, state.lastRow - startRow + 1);
  if (rowCount <= 0) return;

  const fboSkus = sheet.getRange(startRow, layout.fboSku, rowCount, 1).getValues()
    .map(function(row) { return ozonDashboardValidSku_(row[0]); });
  const fbsSkus = sheet.getRange(startRow, layout.fbsSku, rowCount, 1).getValues()
    .map(function(row, index) {
      return ozonDashboardValidSku_(row[0]) || fboSkus[index];
    });
  const uniqueFboSkus = ozonDashboardUniqueValues_(fboSkus);
  const uniqueFbsSkus = ozonDashboardUniqueValues_(fbsSkus);
  const fboBySku = Object.create(null);
  const fbsBySku = Object.create(null);
  const seenFbsSkuWarehouses = Object.create(null);
  const unmappedClusters = Object.create(null);

  for (let offset = 0; offset < uniqueFboSkus.length; offset += 100) {
    const requested = uniqueFboSkus.slice(offset, offset + 100);
    const requestedSet = Object.create(null);
    requested.forEach(function(sku) { requestedSet[sku] = true; });
    const data = ozonDashboardPostJson_(
      OZON_DASHBOARD_API_.analyticsStocks,
      {skus: requested},
      state,
      7000
    );
    const items = Array.isArray(data.items) ? data.items :
      (data.result && Array.isArray(data.result.items) ? data.result.items : null);
    if (!items) throw new Error('Ozon analytics stocks: в ответе отсутствует массив items');

    items.forEach(function(item) {
      const sku = ozonDashboardValidSku_(item && item.sku);
      const cluster = ozonDashboardNormalize_(item && item.cluster_name);
      if (!sku || !requestedSet[sku]) {
        throw new Error('Ozon analytics stocks: получена неожиданная SKU');
      }
      const count = Number(item.available_stock_count);
      if (!Number.isSafeInteger(count) || count < 0) {
        throw new Error('Ozon analytics stocks: некорректный остаток для SKU ' + sku);
      }
      const header = OZON_DASHBOARD_REGION_HEADERS_[cluster];
      if (!header) {
        unmappedClusters[cluster] = String(item.cluster_name || 'пустое название');
        return;
      }
      if (!fboBySku[sku]) fboBySku[sku] = Object.create(null);
      fboBySku[sku][header] = (fboBySku[sku][header] || 0) + count;
    });
  }
  const unmappedNames = Object.keys(unmappedClusters).map(function(key) {
    return unmappedClusters[key];
  });
  if (unmappedNames.length) {
    throw new Error('Ozon analytics stocks: кластеры «' + unmappedNames.sort().join('», «') +
      '» не сопоставлены с колонками листа «' + sheet.getName() + '»');
  }

  for (let offset = 0; offset < uniqueFbsSkus.length; offset += 200) {
    const requested = uniqueFbsSkus.slice(offset, offset + 200);
    const requestedSet = Object.create(null);
    requested.forEach(function(sku) { requestedSet[sku] = true; });
    let cursor = '';
    const seenCursors = Object.create(null);
    let pageCount = 0;
    do {
      const payload = {sku: requested.map(Number), limit: 1000};
      if (cursor) payload.cursor = cursor;
      const data = ozonDashboardPostJson_(OZON_DASHBOARD_API_.fbsStocks, payload, state, 250);
      const products = Array.isArray(data.products) ? data.products :
        (Array.isArray(data.result) ? data.result : null);
      if (!products || typeof data.has_next !== 'boolean') {
        throw new Error('Ozon FBS stocks: в ответе отсутствует список товаров или has_next');
      }
      products.forEach(function(item) {
        const sku = ozonDashboardValidSku_(item && item.sku);
        if (!sku || !requestedSet[sku]) {
          throw new Error('Ozon FBS stocks: получена неожиданная SKU');
        }
        const warehouseId = String(item.warehouse_id === null || item.warehouse_id === undefined ? '' : item.warehouse_id);
        const present = Number(item.present);
        const reserved = Number(item.reserved);
        if (!warehouseId || !Number.isSafeInteger(present) || present < 0 ||
            !Number.isSafeInteger(reserved) || reserved < 0) {
          throw new Error('Ozon FBS stocks: некорректная запись для SKU ' + sku);
        }
        const pairKey = sku + ':' + warehouseId;
        if (seenFbsSkuWarehouses[pairKey]) {
          throw new Error('Ozon FBS stocks: повторная запись для SKU ' + sku + ' и склада ' + warehouseId);
        }
        seenFbsSkuWarehouses[pairKey] = true;
        const target = layout.fbsWarehouses.find(function(warehouse) {
          return warehouse.warehouseId === warehouseId;
        });
        if (!target) return;
        if (!fbsBySku[sku]) fbsBySku[sku] = Object.create(null);
        fbsBySku[sku][target.header] = (fbsBySku[sku][target.header] || 0) + present + reserved;
      });

      pageCount++;
      if (pageCount > 100) throw new Error('Ozon FBS stocks: превышено число страниц');
      const nextCursor = String(data.cursor || '').trim();
      if (data.has_next && (!nextCursor || nextCursor === cursor || seenCursors[nextCursor])) {
        throw new Error('Ozon FBS stocks: курсор пагинации не продвигается');
      }
      if (nextCursor) seenCursors[nextCursor] = true;
      cursor = data.has_next ? nextCursor : '';
    } while (cursor);
  }

  const fboEligible = fboSkus.map(Boolean);
  const fbsEligible = fbsSkus.map(Boolean);
  let cellsWritten = 0;
  layout.fboClusters.forEach(function(target) {
    const values = fboSkus.map(function(sku) {
      return sku && fboBySku[sku] ? (fboBySku[sku][target.header] || 0) : 0;
    });
    cellsWritten += ozonDashboardWriteColumn_(sheet, target.column, startRow, values, fboEligible);
  });
  layout.fbsWarehouses.forEach(function(target) {
    const values = fbsSkus.map(function(sku) {
      return sku && fbsBySku[sku] ? (fbsBySku[sku][target.header] || 0) : 0;
    });
    cellsWritten += ozonDashboardWriteColumn_(sheet, target.column, startRow, values, fbsEligible);
  });

  state.rowOffset += rowCount;
  PropertiesService.getScriptProperties().setProperty(OZON_DASHBOARD_STATE_KEY_, JSON.stringify(state));
  Logger.log(JSON.stringify({
    service: 'Ozon stocks',
    runId: state.runId,
    rows: rowCount,
    fboSkus: uniqueFboSkus.length,
    fbsSkus: uniqueFbsSkus.length,
    cellsWritten: cellsWritten,
    nextRow: state.rowOffset
  }));
}

function ozonDashboardUniqueValues_(values) {
  const result = [];
  const seen = Object.create(null);
  values.forEach(function(value) {
    if (value && !seen[value]) {
      seen[value] = true;
      result.push(value);
    }
  });
  return result;
}
