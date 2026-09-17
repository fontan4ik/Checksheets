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
  const lines = [
    '🚨 <b>Сбой триггера (Apps Script): ' + escapeTelegramHtmlGAS_(serviceName) + '</b>',
    '📅 <b>Дата ошибки:</b> <code>' + dateStr + '</code>',
    '⏰ <b>Время ошибки:</b> <code>' + timeStr + '</code>',
    '❌ <b>Ошибка:</b> <code>' + escapeTelegramHtmlGAS_(errorMessage) + '</code>'
  ];


  if (details) {
    let detailsStr = String(details);
    if (detailsStr.length > 1500) {
      detailsStr = detailsStr.slice(-1500);
    }
    lines.push('\n<b>Детали:</b>\n<pre>' + escapeTelegramHtmlGAS_(detailsStr) + '</pre>');
  }

  return sendTelegramMessageGAS(lines.join('\n'), 'HTML');
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
