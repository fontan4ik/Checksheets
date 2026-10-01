// ============================================
// FETCHAPP - HTTP библиотека с retry логикой
// ============================================

function retryAfterDelayMs_(response) {
  let headers = {};
  try {
    headers = response.getAllHeaders ? response.getAllHeaders() : {};
  } catch (e) {
    return null;
  }

  const key = Object.keys(headers).find(name => name.toLowerCase() === 'retry-after');
  if (!key) return null;
  const rawValue = Array.isArray(headers[key]) ? headers[key][0] : headers[key];
  const seconds = Number(rawValue);
  if (Number.isFinite(seconds) && seconds >= 0) return seconds * 1000;

  const retryAt = Date.parse(String(rawValue));
  return Number.isFinite(retryAt) ? Math.max(0, retryAt - Date.now()) : null;
}

/**
 * retryFetch - Выполняет HTTP запрос с повторными попытками
 *
 * @param {string} url - URL для запроса
 * @param {Object} options - Опции UrlFetchApp
 * @param {number} maxRetries - Максимальное количество попыток (по умолчанию 5)
 * @returns {URLFetchApp.HTTPResponse|null} Ответ сервера или null при неудаче
 */
function retryFetch(url, options, maxRetries) {
  const retries = maxRetries || 5;
  const rateLimitWaitBudgetMs = 90 * 1000;
  let rateLimitWaitedMs = 0;

  for (let attempt = 1; attempt <= retries; attempt++) {
    let waitTime = null;
    try {
      const response = UrlFetchApp.fetch(url, options);
      const responseCode = response.getResponseCode();

      // Успех (2xx) или Клиентская ошибка (4xx) кроме 429
      if (responseCode >= 200 && responseCode < 500 && responseCode !== 429) {
        return response;
      }

      // Если 429 или 5xx - логируем и пробуем снова
      const responseText = response.getContentText();
      Logger.log(`⚠️ HTTP ${responseCode} для ${url}. Попытка ${attempt}/${retries}`);
      if (responseCode === 429 || responseCode >= 500) {
        Logger.log(`   Ответ сервера: ${responseText.substring(0, 500)}`);
      }

      if (attempt === retries) {
        Logger.log(`🚫 Достигнуто макс. число попыток (${retries}) для: ${url}`);
        return response; // Возвращаем последний ответ чтобы вызывающий видел ошибку
      }

      if (responseCode === 429) {
        const retryAfterMs = retryAfterDelayMs_(response);
        waitTime = retryAfterMs === null
          ? Math.pow(2, attempt) * 1500
          : retryAfterMs;
        if (rateLimitWaitedMs + waitTime > rateLimitWaitBudgetMs) {
          Logger.log(`🚫 Retry-After для HTTP 429 превышает бюджет ожидания ${rateLimitWaitBudgetMs / 1000}с; возвращаю ответ вызывающему коду`);
          return response;
        }
        rateLimitWaitedMs += waitTime;
      }

    } catch (e) {
      Logger.log(`❌ Ошибка сети в retryFetch (попытка ${attempt}/${retries}): ${e.toString()}`);
      
      if (attempt === retries) {
        Logger.log(`🚫 Достигнуто макс. число попыток для: ${url}`);
        return null;
      }
    }

    if (attempt < retries) {
      // Honor Ozon's Retry-After on 429; keep exponential backoff for 5xx,
      // network failures, and 429 responses without that header.
      if (waitTime === null) waitTime = Math.pow(2, attempt) * 1500;
      Logger.log(`   Пауза ${waitTime / 1000}с...`);
      Utilities.sleep(waitTime);
    }
  }

  return null;
}

/**
 * rateLimitRPS - Применяет rate limiting к запросам
 *
 * @param {number} lastRequestTime - Время последнего запроса (timestamp)
 * @param {number} rps - Ограничение запросов в секунду
 * @returns {number} Время текущего запроса (timestamp)
 */
function rateLimitRPS(lastRequestTime, rps) {
  const now = Date.now();
  const minTimeBetweenRequests = 1000 / rps;
  const timeSinceLastRequest = now - lastRequestTime;

  if (timeSinceLastRequest < minTimeBetweenRequests) {
    const sleepTime = minTimeBetweenRequests - timeSinceLastRequest;
    Utilities.sleep(sleepTime);
  }

  return Date.now();
}

/** Writes only rows with a complete source value, preserving unresolved rows. */
function writeMaskedColumnValues_(sheet, column, values, writeMask, startRow) {
  const firstRow = startRow || 2;
  if (values.length !== writeMask.length) {
    throw new Error(`Masked write has ${values.length} values and ${writeMask.length} mask entries`);
  }

  let written = 0;
  let index = 0;
  while (index < writeMask.length) {
    if (!writeMask[index]) {
      index++;
      continue;
    }

    const start = index;
    while (index + 1 < writeMask.length && writeMask[index + 1]) index++;
    const block = values.slice(start, index + 1);
    if (block.some(value => !Array.isArray(value) || value.length !== 1)) {
      throw new Error(`Masked write contains an invalid cell value at row ${firstRow + start}`);
    }
    sheet.getRange(firstRow + start, column, block.length, 1).setValues(block);
    written += block.length;
    index++;
  }

  return written;
}
