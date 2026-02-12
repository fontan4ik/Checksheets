// ============================================
// FETCHAPP - HTTP библиотека с retry логикой
// ============================================

/**
 * retryFetch - Выполняет HTTP запрос с повторными попытками
 *
 * @param {string} url - URL для запроса
 * @param {Object} options - Опции UrlFetchApp
 * @param {number} maxRetries - Максимальное количество попыток (по умолчанию 5)
 * @returns {URLFetchApp.HTTPResponse|null} Ответ сервера или null при неудаче
 */
function retryFetch(url, options, maxRetries) {
  // Если maxRetries не указан, используем 5
  const retries = maxRetries || 5;

  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      const response = UrlFetchApp.fetch(url, options);
      const responseCode = response.getResponseCode();

      // Если запрос успешен (200-299) или это клиентская ошибка (400-499),
      // возвращаем ответ без повторных попыток
      if (responseCode >= 200 && responseCode < 500) {
        return response;
      }

      // Серверная ошибка (500-599) - пробуем снова
      Logger.log(`Request failed for ${url} with response code ${responseCode}. Attempt ${attempt}`);

    } catch (e) {
      // Ошибка сети или другая исключительная ситуация
      if (attempt === retries) {
        Logger.log(`Max retries reached for URL: ${url}`);
        return null;
      }
    }

    // Если это не последняя попытка, ждём перед повтором
    if (attempt < retries) {
      // Экспоненциальная задержка: 1с, 2с, 4с, 8с...
      const waitTime = Math.pow(2, attempt - 1) * 1000;
      Utilities.sleep(waitTime);
    }
  }

  Logger.log(`Max retries reached for URL: ${url}`);
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
