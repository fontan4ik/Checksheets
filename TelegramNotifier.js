/**
 * Telegram Notifier for Google Apps Script.
 * Sends alerts to configured Telegram chat using UrlFetchApp.
 */

function sendTelegramMessageGAS(text, parseMode) {
  try {
    const token = (typeof TELEGRAM_CONFIG !== 'undefined' && TELEGRAM_CONFIG.BOT_TOKEN)
      ? TELEGRAM_CONFIG.BOT_TOKEN
      : '8795048754:AAHXbXFhzTHa6ICvwyQ1sE2pBvb-ZgqZIac';
    const chatId = (typeof TELEGRAM_CONFIG !== 'undefined' && TELEGRAM_CONFIG.CHAT_ID)
      ? TELEGRAM_CONFIG.CHAT_ID
      : '-5299125247';

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
    '🚨 <b>Сбой триггера (Apps Script): ' + serviceName + '</b>',
    '📅 <b>Дата ошибки:</b> <code>' + dateStr + '</code>',
    '⏰ <b>Время ошибки:</b> <code>' + timeStr + '</code>',
    '❌ <b>Ошибка:</b> <code>' + errorMessage + '</code>'
  ];


  if (details) {
    let detailsStr = String(details);
    if (detailsStr.length > 1500) {
      detailsStr = detailsStr.slice(-1500);
    }
    lines.push('\n<b>Детали:</b>\n<pre>' + detailsStr + '</pre>');
  }

  return sendTelegramMessageGAS(lines.join('\n'), 'HTML');
}
