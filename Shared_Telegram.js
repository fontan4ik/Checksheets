/**
 * Telegram Notifier for Google Apps Script.
 * Sends alerts to configured Telegram chat using UrlFetchApp.
 */

function sendTelegramMessageGAS(text, parseMode) {
  try {
    const token = (typeof TELEGRAM_CONFIG !== 'undefined' && TELEGRAM_CONFIG.BOT_TOKEN)
      ? TELEGRAM_CONFIG.BOT_TOKEN
      : '8657497257:AAFH9Sb6hNrKFL3WpDTuQd01FQbNB_I1-_o';
    const chatId = (typeof TELEGRAM_CONFIG !== 'undefined' && TELEGRAM_CONFIG.CHAT_ID)
      ? TELEGRAM_CONFIG.CHAT_ID
      : '-1004398203333';

    if (!token || !chatId) return false;

    let safeText = String(text || '');
    if (safeText.length > 4000) {
      safeText = safeText.slice(0, 3950) + '\n... [обрезано]';
    }

    const url = 'https://api.telegram.org/bot' + token + '/sendMessage';
    const payload = {
      chat_id: chatId,
      text: safeText,
      parse_mode: parseMode || 'HTML',
      disable_web_page_preview: true
    };

    const options = {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    };

    const response = UrlFetchApp.fetch(url, options);
    return response.getResponseCode() === 200;
  } catch (err) {
    Logger.log('Telegram send error: ' + err);
    return false;
  }
}

function sendTelegramAlertGAS(serviceName, errorMessage, details) {
  const now = new Date();
  const dateStr = Utilities.formatDate(now, 'GMT+4', 'dd.MM.yyyy');
  const timeStr = Utilities.formatDate(now, 'GMT+4', 'HH:mm:ss');
  const message = String(errorMessage === null || errorMessage === undefined ? '' : errorMessage);
  const detailText = details ? String(details) : '';
  recordTelegramAlertForLocalSyncGAS_(serviceName, message, detailText, now);
  const lines = [
    '🚨 <b>Сбой триггера (Apps Script): ' + escapeTelegramHtmlGAS_(serviceName) + '</b>',
    '📅 <b>Дата ошибки:</b> <code>' + dateStr + '</code>',
    '⏰ <b>Время ошибки:</b> <code>' + timeStr + '</code>',
    '❌ <b>Ошибка:</b> <code>' + escapeTelegramHtmlGAS_(message) + '</code>'
  ];


  if (detailText) {
    let detailsStr = detailText;
    if (detailsStr.length > 1500) {
      detailsStr = detailsStr.slice(-1500);
    }
    lines.push('\n<b>Детали:</b>\n<pre>' + escapeTelegramHtmlGAS_(detailsStr) + '</pre>');
  }

  return sendTelegramMessageGAS(lines.join('\n'), 'HTML');
}

/** Persist GAS alerts in a sheet so the local error-log sync can collect them. */
function recordTelegramAlertForLocalSyncGAS_(serviceName, errorMessage, details, timestamp) {
  try {
    const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
    if (!spreadsheet) throw new Error('Active spreadsheet is unavailable');

    const lock = LockService.getScriptLock();
    lock.waitLock(5000);
    try {
      const sheetName = 'Лог ошибок';
      let sheet = spreadsheet.getSheetByName(sheetName);
      if (!sheet) {
        sheet = spreadsheet.insertSheet(sheetName);
        sheet.getRange(1, 1, 1, 6).setValues([[
          'id', 'timestamp', 'source', 'service', 'error', 'details'
        ]]);
      }
      const recordId = Utilities.getUuid();
      sheet.appendRow([
        recordId,
        timestamp.toISOString(),
        'Apps Script',
        String(serviceName || 'unknown'),
        String(errorMessage || '').slice(0, 10000),
        String(details || '').slice(0, 30000)
      ]);
      try { sheet.hideSheet(); } catch (ignored) {}
      return recordId;
    } finally {
      lock.releaseLock();
    }
  } catch (err) {
    // Local logging must never prevent the original Telegram alert or rethrow.
    Logger.log('Failed to queue Telegram alert for local log sync: ' + err);
    return '';
  }
}

function escapeTelegramHtmlGAS_(value) {
  return String(value === null || value === undefined ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Alert once for a failure that bubbles through multiple trigger wrappers. */
function runWithTelegramAlertGAS_(name, callback) {
  try {
    return callback();
  } catch (error) {
    if (!error || (typeof error !== 'object' && typeof error !== 'function') ||
        !error.__telegramAlertSentGAS) {
      if (error && (typeof error === 'object' || typeof error === 'function')) {
        try { error.__telegramAlertSentGAS = true; } catch (ignored) {}
      }
      sendTelegramAlertGAS(name, error && error.message ? error.message : String(error),
        error && error.stack ? error.stack : null);
    }
    throw error;
  }
}
