const OZON_DASHBOARD_SHEET_ = 'Основная';
const OZON_DASHBOARD_TAB_ = 'Дашборд управления';
const OZON_DASHBOARD_STATE_KEY_ = 'ozonDashboardSyncState';
const OZON_DASHBOARD_CONTINUATION_HANDLER_ = 'continueOzonDashboardSync';
const OZON_DASHBOARD_LOCK_WAIT_MS_ = 5000;
const OZON_DASHBOARD_MAX_TRANSIENT_RETRIES_ = 8;
const OZON_DASHBOARD_RETRY_BASE_MS_ = 60000;
const OZON_DASHBOARD_RETRY_MAX_MS_ = 10 * 60 * 1000;

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
    if (!lock.tryLock(OZON_DASHBOARD_LOCK_WAIT_MS_)) {
      Logger.log('Продолжение синхронизации Ozon пропущено: другой запуск ещё выполняется.');
      return false;
    }
    try {
      try {
        ozonDashboardContinueCore_();
      } catch (error) {
        if (ozonDashboardScheduleTransientRetry_(error)) return false;
        ozonDashboardClearSync_();
        throw error;
      }
    } finally {
      lock.releaseLock();
    }
  });
}

function ozonDashboardStartSync_(mode) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(OZON_DASHBOARD_LOCK_WAIT_MS_)) {
    ozonDashboardNotifyUser_('Синхронизация Ozon уже запускается или продолжает работу.');
    Logger.log('Повторное нажатие кнопки Ozon пропущено: занят скриптовый замок.');
    return false;
  }
  try {
    const properties = PropertiesService.getScriptProperties();
    const existing = properties.getProperty(OZON_DASHBOARD_STATE_KEY_);
    if (existing) {
      const previous = JSON.parse(existing);
      const progress = previous.phase === 'prices' ? 'обновляются цены' :
        (previous.phase === 'stocks' ? 'обновляются остатки, строка ' + previous.rowOffset +
          ' из ' + previous.lastRow : 'обновляются уходы');
      const hasContinuation = ScriptApp.getProjectTriggers().some(function(trigger) {
        return trigger.getHandlerFunction() === OZON_DASHBOARD_CONTINUATION_HANDLER_;
      });
      if (!hasContinuation) ozonDashboardScheduleContinuation_();
      ozonDashboardNotifyUser_('Синхронизация Ozon уже выполняется: ' + progress + '.');
      Logger.log('Повторное нажатие кнопки Ozon пропущено. runId=' + previous.runId +
        ', режим=' + previous.mode + ', фаза=' + previous.phase);
      return false;
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
      transientRetryCount: 0,
      startedAt: new Date().toISOString()
    };
    properties.setProperty(OZON_DASHBOARD_STATE_KEY_, JSON.stringify(state));

    try {
      ozonDashboardScheduleContinuation_();
      ozonDashboardNotifyUser_(mode === 'prices' ? 'Загрузка цен Ozon запущена.' :
        (mode === 'stocks' ? 'Загрузка остатков и уходов Ozon запущена.' :
          'Загрузка цен, остатков и уходов Ozon запущена.'));
      Logger.log('Синхронизация Ozon запущена. runId=' + state.runId + ', режим=' + mode);
      return true;
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
  ozonDashboardScheduleWatchdog_();
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(OZON_DASHBOARD_SHEET_);
  if (!sheet) throw new Error('Не найден лист «' + OZON_DASHBOARD_SHEET_ + '»');

  if (state.phase === 'prices') {
    ozonDashboardSyncPrices_(sheet, state);
    if (state.mode === 'prices') {
      ozonDashboardClearSync_();
      Logger.log('Синхронизация цен Ozon завершена. runId=' + state.runId);
      return;
    }
    state.phase = 'stocks';
    state.rowOffset = 2;
    state.transientRetryCount = 0;
    properties.setProperty(OZON_DASHBOARD_STATE_KEY_, JSON.stringify(state));
    ozonDashboardScheduleContinuation_();
    Logger.log('Синхронизация цен Ozon завершена; остатки продолжатся отдельным запуском. runId=' + state.runId);
    return;
  }
  if (state.phase === 'outflows') {
    ozonDashboardSyncOutflowPages_(sheet, state);
    state.transientRetryCount = 0;
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

  if (!state.warehouseIds) {
    state.warehouseIds = ozonDashboardFetchTargetWarehouseIds_(state);
    properties.setProperty(OZON_DASHBOARD_STATE_KEY_, JSON.stringify(state));
  }
  ozonDashboardSyncStockSlice_(sheet, state);
  state.transientRetryCount = 0;
  properties.setProperty(OZON_DASHBOARD_STATE_KEY_, JSON.stringify(state));
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

function ozonDashboardScheduleContinuation_(delayMs) {
  ozonDashboardDeleteContinuationTriggers_();
  ScriptApp.newTrigger(OZON_DASHBOARD_CONTINUATION_HANDLER_).timeBased()
    .after(Math.max(60000, Number(delayMs) || 60000)).create();
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

function ozonDashboardNotifyUser_(message) {
  try {
    SpreadsheetApp.getActiveSpreadsheet().toast(message, 'Ozon', 8);
  } catch (error) {
    Logger.log('Не удалось показать уведомление Ozon в таблице: ' + error.message);
  }
}

function ozonDashboardScheduleTransientRetry_(error) {
  if (!error || (!error.ozonTransient && !error.ozonRetryable)) return false;
  const properties = PropertiesService.getScriptProperties();
  const saved = properties.getProperty(OZON_DASHBOARD_STATE_KEY_);
  if (!saved) return false;

  const state = JSON.parse(saved);
  state.transientRetryCount = Number(state.transientRetryCount || 0) + 1;
  if (state.transientRetryCount > OZON_DASHBOARD_MAX_TRANSIENT_RETRIES_) return false;
  const backoff = Math.min(
    OZON_DASHBOARD_RETRY_BASE_MS_ * Math.pow(2, state.transientRetryCount - 1),
    OZON_DASHBOARD_RETRY_MAX_MS_
  );
  const delayMs = Math.max(backoff, Number(error.retryAfterMs) || 0);
  state.lastTransientError = String(error.message || error).slice(0, 500);
  state.nextRetryAt = new Date(Date.now() + delayMs).toISOString();
  properties.setProperty(OZON_DASHBOARD_STATE_KEY_, JSON.stringify(state));
  ozonDashboardScheduleContinuation_(delayMs);
  Logger.log('Временный сбой Ozon API; состояние сохранено, повтор через ' +
    Math.ceil(delayMs / 1000) + ' сек. runId=' + state.runId + ', попытка=' +
    state.transientRetryCount + '/' + OZON_DASHBOARD_MAX_TRANSIENT_RETRIES_ +
    ', ошибка=' + state.lastTransientError);
  ozonDashboardNotifyUser_('Ozon временно ограничил запросы. Прогресс сохранён, выгрузка продолжится автоматически.');
  return true;
}



