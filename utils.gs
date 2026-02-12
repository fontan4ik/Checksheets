// ============================================
// УТИЛИТЫ И ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
// ============================================

/**
 * Выполняет HTTP-запрос с повторными попытками при неудаче
 *
 * @param {string} url - URL для запроса
 * @param {Object} options - Опции UrlFetchApp
 * @param {number} maxRetries - Максимальное количество попыток (по умолчанию 5)
 * @returns {URLFetchApp.HTTPResponse|null} Ответ сервера или null при неудаче
 */
function retryFetch(url, options, maxRetries) {
  const retries = maxRetries || 5;

  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      const response = UrlFetchApp.fetch(url, options);
      const responseCode = response.getResponseCode();

      if (responseCode >= 200 && responseCode < 500) {
        return response;
      }

      Logger.log(`Request failed for ${url} with response code ${responseCode}. Attempt ${attempt}`);

    } catch (e) {
      if (attempt === retries) {
        Logger.log(`Max retries reached for URL: ${url}`);
        return null;
      }
    }

    if (attempt < retries) {
      const waitTime = Math.pow(2, attempt - 1) * 1000;
      Utilities.sleep(waitTime);
    }
  }

  Logger.log(`Max retries reached for URL: ${url}`);
  return null;
}

/**
 * Ограничение частоты запросов (RPS)
 *
 * @param {number} lastRequestTime - Время последнего запроса
 * @param {number} rps - Requests per second
 * @returns {number} Время текущего запроса
 */
function rateLimitRPS(lastRequestTime, rps) {
  const now = Date.now();
  const minTimeBetweenRequests = 1000 / rps;
  const timeSinceLastRequest = now - lastRequestTime;

  if (timeSinceLastRequest < minTimeBetweenRequests) {
    Utilities.sleep(minTimeBetweenRequests - timeSinceLastRequest);
  }

  return Date.now();
}
