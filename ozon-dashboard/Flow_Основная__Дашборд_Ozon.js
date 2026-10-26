const OZON_DASHBOARD_SHEET_ = 'Основная';
const OZON_DASHBOARD_TAB_ = 'Дашборд управления';
const OZON_DASHBOARD_STATE_KEY_ = 'ozonDashboardSyncState';
const OZON_DASHBOARD_CONTINUATION_HANDLER_ = 'continueOzonDashboardSync';

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Ozon: обновить')
    .addItem('Загрузить цены', 'ozonDashboardLoadPrices')
    .addItem('Загрузить остатки', 'ozonDashboardLoadStocks')
    .addItem('Загрузить цены и остатки', 'ozonDashboardLoadPricesAndStocks')
    .addToUi();
}

function setupOzonDashboardButtons() {
  return runWithTelegramAlertGAS_('setupOzonDashboardButtons', function() {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(OZON_DASHBOARD_TAB_);
    if (!sheet) throw new Error('Не найден лист «' + OZON_DASHBOARD_TAB_ + '»');

    const positions = [
      {key: 'prices', title: 'Загрузить цены', handler: 'ozonDashboardLoadPrices', column: 2},
      {key: 'stocks', title: 'Загрузить остатки', handler: 'ozonDashboardLoadStocks', column: 6},
      {key: 'both', title: 'Цены и остатки', handler: 'ozonDashboardLoadPricesAndStocks', column: 10}
    ];
    const ownedPrefix = 'Ozon dashboard button:';
    sheet.getImages().forEach(function(image) {
      if (String(image.getAltTextTitle() || '').indexOf(ownedPrefix) === 0) image.remove();
    });

    positions.forEach(function(button) {
      const blob = Utilities.newBlob(
        Utilities.base64Decode(OZON_DASHBOARD_BUTTONS[button.key]),
        'image/png',
        'ozon-' + button.key + '-button.png'
      );
      const image = sheet.insertImage(blob, button.column, 2);
      image.setWidth(300).setHeight(76);
      image.setAltTextTitle(ownedPrefix + ' ' + button.title);
      image.setAltTextDescription('Запускает синхронизацию данных Ozon: ' + button.title);
      image.assignScript(button.handler);
    });

    Logger.log('На «' + OZON_DASHBOARD_TAB_ + '» установлены три кнопки Ozon.');
    return positions.length;
  });
}

function ozonDashboardLoadPrices() {
  return runWithTelegramAlertGAS_('ozonDashboardLoadPrices', function() {
    return ozonDashboardStartSync_('prices');
  });
}

function ozonDashboardLoadStocks() {
  return runWithTelegramAlertGAS_('ozonDashboardLoadStocks', function() {
    return ozonDashboardStartSync_('stocks');
  });
}

function ozonDashboardLoadPricesAndStocks() {
  return runWithTelegramAlertGAS_('ozonDashboardLoadPricesAndStocks', function() {
    return ozonDashboardStartSync_('both');
  });
}

function continueOzonDashboardSync() {
  return runWithTelegramAlertGAS_('continueOzonDashboardSync', function() {
    const lock = LockService.getScriptLock();
    if (!lock.tryLock(30000)) throw new Error('Другая синхронизация Ozon уже выполняется');
    try {
      ozonDashboardContinueCore_();
    } catch (error) {
      ozonDashboardClearSync_();
      throw error;
    } finally {
      lock.releaseLock();
    }
  });
}

function ozonDashboardStartSync_(mode) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) throw new Error('Другая синхронизация Ozon уже выполняется');
  try {
    const properties = PropertiesService.getScriptProperties();
    const existing = properties.getProperty(OZON_DASHBOARD_STATE_KEY_);
    if (existing) {
      const previous = JSON.parse(existing);
      throw new Error('Уже выполняется синхронизация Ozon (' + previous.mode + ', строка ' +
        previous.rowOffset + ' из ' + previous.lastRow + ')');
    }

    const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
    const sheet = spreadsheet.getSheetByName(OZON_DASHBOARD_SHEET_);
    if (!sheet) throw new Error('Не найден лист «' + OZON_DASHBOARD_SHEET_ + '»');

    const state = {
      runId: Utilities.getUuid(),
      mode: mode,
      phase: mode === 'stocks' ? 'stocks' : 'prices',
      rowOffset: 2,
      lastRow: sheet.getLastRow(),
      lastOzonRequestAt: 0,
      startedAt: new Date().toISOString()
    };
    properties.setProperty(OZON_DASHBOARD_STATE_KEY_, JSON.stringify(state));

    try {
      if (mode === 'stocks' || mode === 'both') {
        state.warehouseIds = ozonDashboardFetchTargetWarehouseIds_(state);
      }
      properties.setProperty(OZON_DASHBOARD_STATE_KEY_, JSON.stringify(state));
      ozonDashboardContinueCore_();
    } catch (error) {
      ozonDashboardClearSync_();
      throw error;
    }
  } finally {
    lock.releaseLock();
  }
}

function ozonDashboardContinueCore_() {
  const properties = PropertiesService.getScriptProperties();
  const saved = properties.getProperty(OZON_DASHBOARD_STATE_KEY_);
  if (!saved) return;
  const state = JSON.parse(saved);
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(OZON_DASHBOARD_SHEET_);
  if (!sheet) throw new Error('Не найден лист «' + OZON_DASHBOARD_SHEET_ + '»');

  ozonDashboardScheduleWatchdog_();
  if (state.phase === 'prices') {
    ozonDashboardSyncPrices_(sheet, state);
    if (state.mode === 'prices') {
      ozonDashboardClearSync_();
      Logger.log('Синхронизация цен Ozon завершена. runId=' + state.runId);
      return;
    }
    state.phase = 'stocks';
    state.rowOffset = 2;
    properties.setProperty(OZON_DASHBOARD_STATE_KEY_, JSON.stringify(state));
    ozonDashboardScheduleContinuation_();
    Logger.log('Синхронизация цен Ozon завершена; остатки продолжатся отдельным запуском. runId=' + state.runId);
    return;
  }
  if (state.phase === 'outflows') {
    ozonDashboardSyncOutflowPages_(sheet, state);
    properties.setProperty(OZON_DASHBOARD_STATE_KEY_, JSON.stringify(state));
    ozonDashboardScheduleContinuation_();
    Logger.log('Синхронизация уходов Ozon продолжится. runId=' + state.runId +
      ', pages=' + state.outflowPages + ', период=' + state.outflowDateFrom + ' — ' + state.outflowDateTo);
    return;
  }
  if (state.phase === 'outflowCommit') {
    const result = ozonDashboardCommitOutflows_(sheet, state);
    ozonDashboardClearSync_();
    Logger.log('Синхронизация уходов Ozon завершена. runId=' + state.runId +
      ', период=' + state.outflowDateFrom + ' — ' + state.outflowDateTo +
      ', отправлений=' + state.outflowPostings + ', ячеек=' + result.cellsWritten);
    return;
  }
  if (state.phase !== 'stocks') throw new Error('Неизвестная фаза синхронизации Ozon: ' + state.phase);

  if (state.rowOffset > state.lastRow) {
    ozonDashboardBeginOutflows_(sheet, state);
    ozonDashboardScheduleContinuation_();
    Logger.log('Синхронизация остатков Ozon завершена; началась загрузка уходов. runId=' + state.runId);
    return;
  }

  ozonDashboardSyncStockSlice_(sheet, state);
  if (state.rowOffset > state.lastRow) {
    ozonDashboardBeginOutflows_(sheet, state);
    ozonDashboardScheduleContinuation_();
    Logger.log('Синхронизация остатков Ozon завершена; началась загрузка уходов. runId=' + state.runId);
  } else {
    properties.setProperty(OZON_DASHBOARD_STATE_KEY_, JSON.stringify(state));
    ozonDashboardScheduleContinuation_();
    Logger.log('Синхронизация Ozon продолжится с строки ' + state.rowOffset + '. runId=' + state.runId);
  }
}

function ozonDashboardScheduleContinuation_() {
  ozonDashboardDeleteContinuationTriggers_();
  ScriptApp.newTrigger(OZON_DASHBOARD_CONTINUATION_HANDLER_).timeBased().after(60000).create();
}

function ozonDashboardScheduleWatchdog_() {
  ozonDashboardDeleteContinuationTriggers_();
  ScriptApp.newTrigger(OZON_DASHBOARD_CONTINUATION_HANDLER_).timeBased().after(7 * 60 * 1000).create();
}

function ozonDashboardClearSync_() {
  const properties = PropertiesService.getScriptProperties();
  const saved = properties.getProperty(OZON_DASHBOARD_STATE_KEY_);
  if (saved) {
    try {
      const state = JSON.parse(saved);
      if (state.outflowTempSheetName) {
        const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
        const tempSheet = spreadsheet.getSheetByName(state.outflowTempSheetName);
        if (tempSheet) spreadsheet.deleteSheet(tempSheet);
      }
    } catch (error) {
      Logger.log('Не удалось удалить временный лист уходов Ozon: ' + error.message);
    }
  }
  properties.deleteProperty(OZON_DASHBOARD_STATE_KEY_);
  ozonDashboardDeleteContinuationTriggers_();
}

function ozonDashboardDeleteContinuationTriggers_() {
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (trigger.getHandlerFunction() === OZON_DASHBOARD_CONTINUATION_HANDLER_) {
      ScriptApp.deleteTrigger(trigger);
    }
  });
}

function testOzonDashboardOutflowsOnly20261026() {
  return runWithTelegramAlertGAS_('testOzonDashboardOutflowsOnly20261026', function() {
    const lock = LockService.getScriptLock();
    if (!lock.tryLock(30000)) throw new Error('Не удалось заблокировать тест уходов Ozon');
    try {
      const properties = PropertiesService.getScriptProperties();
      if (properties.getProperty(OZON_DASHBOARD_STATE_KEY_)) {
        throw new Error('Нельзя запускать тест уходов: уже выполняется синхронизация Ozon');
      }
      const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(OZON_DASHBOARD_SHEET_);
      if (!sheet) throw new Error('Не найден лист «' + OZON_DASHBOARD_SHEET_ + '»');
      const lastRow = sheet.getLastRow();
      const state = {
        runId: Utilities.getUuid(),
        mode: 'stocks',
        phase: 'stocks',
        rowOffset: lastRow + 1,
        lastRow: lastRow,
        lastOzonRequestAt: 0,
        startedAt: new Date().toISOString()
      };
      properties.setProperty(OZON_DASHBOARD_STATE_KEY_, JSON.stringify(state));
      ozonDashboardContinueCore_();
      Logger.log('Изолированный тест уходов запущен. runId=' + state.runId);
    } catch (error) {
      ozonDashboardClearSync_();
      throw error;
    } finally {
      lock.releaseLock();
    }
  });
}


