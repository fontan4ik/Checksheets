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
  const retries = maxRetries || 5;

  for (let attempt = 1; attempt <= retries; attempt++) {
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

    } catch (e) {
      Logger.log(`❌ Ошибка сети в retryFetch (попытка ${attempt}/${retries}): ${e.toString()}`);
      
      if (attempt === retries) {
        Logger.log(`🚫 Достигнуто макс. число попыток для: ${url}`);
        return null;
      }
    }

    // Экспоненциальная задержка: 3с, 6с, 12с... (увеличено для WB)
    if (attempt < retries) {
      const waitTime = Math.pow(2, attempt) * 1500; 
      Logger.log(`   Пауза ${waitTime/1000}с...`);
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
