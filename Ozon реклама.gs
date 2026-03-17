/**
 * OZON РЕКЛАМА - Performance API (полный поток с асинхронными отчётами)
 *
 * Заполняет колонку:
 * - AU (47): Расход по рекламе по ску ОЗОН в месяц
 *
 * API Эндпоинты:
 * - OAuth: POST https://api-performance.ozon.ru/api/client/token
 * - Кампании: GET https://api-performance.ozon.ru/api/client/campaign
 * - Создать отчёт: POST https://api-performance.ozon.ru/api/client/statistics
 * - Статус отчёта: GET https://api-performance.ozon.ru/api/client/statistics/report?UUID=...
 * - Скачать отчёт: GET https://api-performance.ozon.ru/api/client/statistics/report?UUID=...&download=1
 *
 * Ограничения API:
 * - Максимум 60 дней для одного отчёта
 * - Максимум 10 кампаний за один запрос
 * - Отчёты создаются асинхронно
 * - Результат скачивается как ZIP-архив с CSV внутри (или CSV напрямую)
 */

/**
 * Получает OAuth токен для Performance API
 * @returns {string} - JWT токен или null
 */
function getPerformanceAuthToken() {
  const clientId = '92353868-1771409527407@advertising.performance.ozon.ru';
  const clientSecret = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw';

  const url = "https://api-performance.ozon.ru/api/client/token";

  // Правильный формат: JSON body вместо form-encoded
  const body = {
    client_id: clientId,
    client_secret: clientSecret,
    grant_type: "client_credentials"
  };

  const options = {
    method: "post",
    contentType: "application/json",  // JSON вместо form-encoded
    headers: {
      "Accept": "application/json"
    },
    payload: JSON.stringify(body),
    muteHttpExceptions: true
  };

  try {
    const response = UrlFetchApp.fetch(url, options);
    const responseCode = response.getResponseCode();
    const responseText = response.getContentText();

    if (responseCode !== 200) {
      Logger.log(`❌ Performance API: ошибка получения токена (${responseCode})`);
      Logger.log(`   ${responseText}`);
      return null;
    }

    const data = JSON.parse(responseText);
    const token = data.access_token;

    if (!token) {
      Logger.log("❌ Performance API: токен не найден в ответе");
      return null;
    }

    Logger.log("✅ Performance API: токен получен");
    return token;
  } catch (e) {
    Logger.log(`❌ Performance API: ошибка при получении токена - ${e.message}`);
    return null;
  }
}

/**
 * Получает список кампаний из Performance API
 * @param {string} authToken - OAuth токен
 * @returns {Array} - Массив кампаний или null
 */
function getPerformanceCampaigns(authToken) {
  const url = "https://api-performance.ozon.ru/api/client/campaign";

  const options = {
    method: "get",
    headers: {
      "Authorization": "Bearer " + authToken,
      "Content-Type": "application/json"
    },
    muteHttpExceptions: true
  };

  try {
    const response = UrlFetchApp.fetch(url, options);
    const responseCode = response.getResponseCode();

    if (responseCode !== 200) {
      Logger.log(`❌ Performance API: ошибка получения кампаний (${responseCode})`);
      return null;
    }

    const data = JSON.parse(response.getContentText());
    const campaigns = data.list || [];

    Logger.log(`✅ Performance API: получено ${campaigns.length} кампаний`);
    return campaigns;
  } catch (e) {
    Logger.log(`❌ Performance API: ошибка при получении кампаний - ${e.message}`);
    return null;
  }
}

/**
 * Создаёт запрос на статистику кампаний
 * @param {string} authToken - OAuth токен
 * @param {Array} campaignIds - Массив ID кампаний
 * @param {string} dateFrom - Начальная дата (YYYY-MM-DD)
 * @param {string} dateTo - Конечная дата (YYYY-MM-DD)
 * @returns {string} - UUID отчёта или null
 */
function createStatisticsReport(authToken, campaignIds, dateFrom, dateTo) {
  const url = "https://api-performance.ozon.ru/api/client/statistics";

  const body = {
    campaigns: campaignIds,
    dateFrom: dateFrom,
    dateTo: dateTo,
    groupBy: "SKU"
  };

  const options = {
    method: "post",
    headers: {
      "Authorization": "Bearer " + authToken,
      "Content-Type": "application/json"
    },
    payload: JSON.stringify(body),
    muteHttpExceptions: true
  };

  try {
    const response = UrlFetchApp.fetch(url, options);
    const responseCode = response.getResponseCode();

    if (responseCode !== 200) {
      const responseText = response.getContentText();

      // При 502 возвращаем undefined для повтора
      if (responseCode === 502) {
        Logger.log(`⚠️ Performance API: ошибка 502 (Bad Gateway) - можно повторить`);
        return undefined; // undefined означает "повторить"
      }

      Logger.log(`❌ Performance API: ошибка создания отчёта (${responseCode})`);
      Logger.log(`   ${responseText}`);
      return null;
    }

    const data = JSON.parse(response.getContentText());
    const uuid = data.UUID;

    if (!uuid) {
      Logger.log("❌ Performance API: UUID не найден в ответе");
      return null;
    }

    return uuid;
  } catch (e) {
    Logger.log(`❌ Performance API: ошибка при создании отчёта - ${e.message}`);
    return null;
  }
}

/**
 * Проверяет статус отчёта
 * @param {string} authToken - OAuth токен
 * @param {string} uuid - UUID отчёта
 * @returns {Object} - { status: "IN_PROGRESS" | "OK" | "ERROR", error: string, isZip: boolean }
 */
function getReportStatus(authToken, uuid) {
  const url = `https://api-performance.ozon.ru/api/client/statistics/report?UUID=${uuid}`;

  const options = {
    method: "get",
    headers: {
      "Authorization": "Bearer " + authToken,
      "Content-Type": "application/json"
    },
    muteHttpExceptions: true
  };

  let responseText = '';

  try {
    const response = UrlFetchApp.fetch(url, options);
    const responseCode = response.getResponseCode();
    responseText = response.getContentText();

    if (responseCode === 404) {
      // 404 означает, что отчёт создаётся
      return { status: "IN_PROGRESS", error: null, isZip: false };
    }

    if (responseCode !== 200) {
      return { status: "ERROR", error: `HTTP ${responseCode}`, isZip: false };
    }

    // Убираем BOM если есть
    const trimmed = responseText.replace(/^\uFEFF/, '').trim();

    // Проверяем ZIP (PK\x03\x04)
    if (trimmed.substring(0, 2) === "PK") {
      return { status: "OK", error: null, isZip: true };
    }

    // Проверяем CSV (начинается с ;Кампания, sku, или Дата)
    if (trimmed.startsWith(';Кампания') || trimmed.startsWith('sku') || trimmed.startsWith('Дата')) {
      return { status: "OK", error: null, isZip: false };
    }

    // Иначе пытаемся распарсить как JSON
    const data = JSON.parse(responseText);
    return { status: data.state, error: null, isZip: false };

  } catch (e) {
    if (responseText && responseText.substring(0, 2) === "PK") {
      return { status: "OK", error: null, isZip: true };
    }
    return { status: "ERROR", error: e.message, isZip: false };
  }
}

/**
 * Скачивает отчёт по UUID
 * @param {string} authToken - OAuth токен
 * @param {string} uuid - UUID отчёта
 * @returns {Blob} - ZIP-архив как Blob или null
 */
function downloadReport(authToken, uuid) {
  const url = `https://api-performance.ozon.ru/api/client/statistics/report?UUID=${uuid}&download=1`;

  const options = {
    method: "get",
    headers: {
      "Authorization": "Bearer " + authToken
    },
    muteHttpExceptions: true
  };

  try {
    const response = UrlFetchApp.fetch(url, options);
    const responseCode = response.getResponseCode();

    if (responseCode !== 200) {
      Logger.log(`❌ Performance API: ошибка скачивания (${responseCode})`);
      return null;
    }

    return response.getBlob();
  } catch (e) {
    Logger.log(`❌ Performance API: ошибка при скачивании - ${e.message}`);
    return null;
  }
}

/**
 * Распаковывает ZIP-архив и парсит CSV файл со статистикой
 * @param {Blob} blob - ZIP-архив или CSV напрямую
 * @returns {Object} - { sku: expense }
 */
function parseStatisticsZip(blob) {
  try {
    let csvData = "";

    // Проверяем, является ли blob ZIP-архивом
    const bytes = blob.getBytes();
    const isZip = bytes.length > 4 && bytes[0] === 0x50 && bytes[1] === 0x4B; // "PK"

    if (isZip) {
      // Это ZIP - распаковываем
      const unzipped = Utilities.unzip(blob);

      if (!unzipped || unzipped.length === 0) {
        Logger.log("❌ ZIP архив пуст");
        return {};
      }

      const csvBlob = unzipped[0];
      csvData = csvBlob.getDataAsString();

      Logger.log(`📦 Распаковано файлов: ${unzipped.length}`);
    } else {
      // Это CSV напрямую
      csvData = blob.getDataAsString();
      Logger.log(`📄 Получен CSV напрямую`);
    }

    // Убираем BOM если есть
    csvData = csvData.replace(/^\uFEFF/, '');

    const lines = csvData.split("\n");

    Logger.log(`📄 Строк в CSV: ${lines.length}`);

    // Логируем первые 3 строки для проверки формата
    const logLines = Math.min(3, lines.length);
    for (let i = 0; i < logLines; i++) {
      Logger.log(`📋 Строка ${i}: ${lines[i].substring(0, 200)}`);
    }

    // Ищем заголовок
    let headerIndex = -1;
    for (let i = 0; i < Math.min(5, lines.length); i++) {
      if (lines[i].includes('sku') && lines[i].includes('Расход')) {
        headerIndex = i;
        break;
      }
    }

    if (headerIndex === -1) {
      Logger.log("⚠️ Заголовок не найден, парсим со строки 1");
      headerIndex = 0;
    }

    // Пропускаем заголовок, парсим данные
    const stats = {};
    let parsedCount = 0;

    for (let i = headerIndex + 1; i < lines.length; i++) {
      const line = lines[i].trim();
      if (!line || line.startsWith('Всего')) continue;

      // CSV формат Ozon (разделитель - точка с запятой):
      // sku;Название;Цена;Показы;Клики;CTR;В корзину;CPC;Расход;Заказы;...
      // Индексы: 0=sku, 8=Расход
      const parts = line.split(";");

      if (parts.length >= 9) {
        const sku = parts[0].trim();
        // Заменяем запятую на точку для parseFloat (русский формат)
        const expenseStr = parts[8].trim().replace(',', '.');
        const expense = parseFloat(expenseStr) || 0;

        if (sku && expense > 0) {
          stats[sku] = (stats[sku] || 0) + expense;
          parsedCount++;
        }
      }
    }

    Logger.log(`✅ Распарсено строк с расходами: ${parsedCount}`);
    Logger.log(`✅ Уникальных SKU: ${Object.keys(stats).length}`);

    // Логируем топ-5 для отладки
    const topSKUs = Object.entries(stats)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5);

    if (topSKUs.length > 0) {
      Logger.log(`📊 ТОП-5 SKU по расходам:`);
      topSKUs.forEach(([sku, expense], i) => {
        Logger.log(`   ${i + 1}. SKU ${sku}: ${expense.toFixed(2)} руб.`);
      });
    }

    return stats;
  } catch (e) {
    Logger.log(`❌ Ошибка при распаковке/парсинге: ${e.message}`);
    return {};
  }
}

/**
 * Получает статистику за период с учётом ограничения 60 дней
 * @param {string} authToken - OAuth токен
 * @param {Array} campaigns - Все кампании
 * @param {Date} dateFrom - Начальная дата
 * @param {Date} dateTo - Конечная дата
 * @param {string} label - Лог для периода (Месяц/Квартал/Год)
 * @returns {Object} - { sku: expense }
 */
function fetchStatisticsWithPeriodLimit(authToken, campaigns, dateFrom, dateTo, label) {
  const formatDate = date => Utilities.formatDate(date, "GMT+3", "yyyy-MM-dd");
  const stats = {};

  // Ограничения API: максимум 60 дней, максимум 10 кампаний
  const MAX_DAYS = 60;
  const MAX_CAMPAIGNS = 10;

  const startDate = new Date(dateFrom);
  const endDate = new Date(dateTo);
  const totalDays = Math.ceil((endDate - startDate) / (1000 * 60 * 60 * 24));

  Logger.log(`📊 [${label}] Период: ${formatDate(dateFrom)} → ${formatDate(dateTo)} (${totalDays} дней)`);
  Logger.log(`📊 [${label}] Кампаний: ${campaigns.length} (лимит API: ${MAX_CAMPAIGNS} за запрос)`);

  if (totalDays <= MAX_DAYS && campaigns.length <= MAX_CAMPAIGNS) {
    // Период и количество кампаний подходят под лимиты - один запрос
    const campaignIds = campaigns.map(c => c.id);
    const uuid = createStatisticsReport(authToken, campaignIds, formatDate(dateFrom), formatDate(dateTo));

    if (!uuid) {
      Logger.log(`❌ [${label}] Не удалось создать отчёт`);
      return {};
    }

    Logger.log(`✅ [${label}] UUID отчёта: ${uuid}`);

    // Ожидание готовности отчёта (УВЕЛИЧЕНО до 60 попыток по 5 секунд = 5 минут)
    let attempts = 0;
    const maxAttempts = 60;

    while (attempts < maxAttempts) {
      attempts++;
      Utilities.sleep(5000); // 5 секунд между проверками

      const status = getReportStatus(authToken, uuid);

      if (status.status === "OK") {
        Logger.log(`✅ [${label}] Отчёт готов (попытка ${attempts})`);
        const zipBlob = downloadReport(authToken, uuid);
        return parseStatisticsZip(zipBlob);
      } else if (status.status === "ERROR") {
        if (status.error && status.error.includes("404")) {
          if (attempts % 10 === 0) {
            Logger.log(`⏳ [${label}] Отчёт создаётся... (${attempts}/${maxAttempts})`);
          }
          continue;
        }
        Logger.log(`❌ [${label}] Ошибка отчёта: ${status.error}`);
        return {};
      }

      if (attempts % 10 === 0) {
        Logger.log(`⏳ [${label}] Ожидание... (${attempts}/${maxAttempts})`);
      }
    }

    Logger.log(`❌ [${label}] Таймаут ожидания отчёта`);
    return {};
  } else {
    // Превышен лимит - разбиваем на части
    let reason = "";
    if (totalDays > MAX_DAYS) reason += `дней (${totalDays} > ${MAX_DAYS}) `;
    if (campaigns.length > MAX_CAMPAIGNS) reason += `кампаний (${campaigns.length} > ${MAX_CAMPAIGNS})`;

    Logger.log(`⚠️ [${label}] Превышен лимит по ${reason.trim()}, разбиваем на части`);

    // Разбиваем кампании на чанки по MAX_CAMPAIGNS
    const campaignChunks = [];
    for (let i = 0; i < campaigns.length; i += MAX_CAMPAIGNS) {
      campaignChunks.push(campaigns.slice(i, i + MAX_CAMPAIGNS));
    }

    Logger.log(`📦 [${label}] Разбито на ${campaignChunks.length} чанков по кампаниям`);

    // Обрабатываем каждый чанк кампаний
    for (let i = 0; i < campaignChunks.length; i++) {
      const campaignChunk = campaignChunks[i];
      const campaignIds = campaignChunk.map(c => c.id);

      Logger.log(`📦 [${label}] Чанк ${i + 1}/${campaignChunks.length}: ${campaignIds.length} кампаний`);

      const uuid = createStatisticsReport(authToken, campaignIds, formatDate(dateFrom), formatDate(dateTo));

      if (!uuid) {
        Logger.log(`❌ [${label}] Чанк ${i + 1}: не удалось создать отчёт`);
        continue;
      }

      Logger.log(`✅ [${label}] Чанк ${i + 1}: UUID отчёта: ${uuid}`);

      // Ожидание готовности (УВЕЛИЧЕНО)
      let attempts = 0;
      const maxAttempts = 60;

      while (attempts < maxAttempts) {
        attempts++;
        Utilities.sleep(5000);

        const status = getReportStatus(authToken, uuid);

        if (status.status === "OK") {
          Logger.log(`✅ [${label}] Чанк ${i + 1}: отчёт готов (попытка ${attempts})`);
          const zipBlob = downloadReport(authToken, uuid);
          const chunkStats = parseStatisticsZip(zipBlob);

          // Агрегируем
          for (const sku in chunkStats) {
            if (!stats[sku]) stats[sku] = 0;
            stats[sku] += chunkStats[sku];
          }

          Logger.log(`✅ [${label}] Чанк ${i + 1}: добавлено ${Object.keys(chunkStats).length} SKU`);
          break;
        } else if (status.status === "ERROR") {
          if (status.error && status.error.includes("404")) {
            if (attempts % 10 === 0) {
              Logger.log(`⏳ [${label}] Чанк ${i + 1}: отчёт создаётся... (${attempts}/${maxAttempts})`);
            }
            continue;
          }
          Logger.log(`❌ [${label}] Чанк ${i + 1}: ошибка отчёта: ${status.error}`);
          break;
        }

        if (attempts % 10 === 0) {
          Logger.log(`⏳ [${label}] Чанк ${i + 1}: ожидание... (${attempts}/${maxAttempts})`);
        }
      }

      // Пауза между чанками
      if (i < campaignChunks.length - 1) {
        Logger.log(`⏸️ [${label}] Пауза 15 сек. перед следующим чанком...`);
        Utilities.sleep(15000);
      }
    }

    Logger.log(`✅ [${label}] Обработано ${Object.keys(stats).length} уникальных SKU из ${campaignChunks.length} чанков`);
    return stats;
  }
}

/**
 * Главная функция: обновляет расходы на рекламу
 */
function updateOzonAdExpenses() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("❌ Нет данных для обновления");
    return;
  }

  Logger.log("=== ОБНОВЛЕНИЕ РАСХОДОВ НА РЕКЛАМУ OZON ===");
  Logger.log("Колонка AU (47): Расход по рекламе по ску ОЗОН в месяц");

  // 1. Получаем OAuth токен
  const authToken = getPerformanceAuthToken();
  if (!authToken) {
    Logger.log("❌ Не удалось получить токен Performance API");
    return;
  }

  // 2. Получаем кампании
  const campaigns = getPerformanceCampaigns(authToken);
  if (!campaigns || campaigns.length === 0) {
    Logger.log("❌ Не удалось получить кампании");
    return;
  }

  Logger.log(`📊 Всего кампаний: ${campaigns.length}`);

  // Ограничиваем количество кампаний для укладки в лимит 6 минут
  const MAX_CAMPAIGNS_TOTAL = 100;
  let campaignsToUse = campaigns;

  if (campaignsToUse.length > MAX_CAMPAIGNS_TOTAL) {
    Logger.log(`⚠️ Слишком много кампаний (${campaignsToUse.length}), ограничиваем первыми ${MAX_CAMPAIGNS_TOTAL}`);
    campaignsToUse = campaignsToUse.slice(0, MAX_CAMPAIGNS_TOTAL);
  }

  Logger.log(`📊 Кампаний для обработки: ${campaignsToUse.length}`);

  // 3. Определяем период: последние 30 дней, сдвинутое на 2 дня назад
  const today = new Date();
  const monthTo = new Date(today);
  monthTo.setDate(today.getDate() - 2);

  const monthFrom = new Date(monthTo);
  monthFrom.setDate(monthTo.getDate() - 30);

  const formatDate = date => Utilities.formatDate(date, "GMT+3", "yyyy-MM-dd");

  Logger.log(`📅 Период: ${formatDate(monthFrom)} → ${formatDate(monthTo)}`);

  // 4. Получаем статистику за месяц
  const monthStats = fetchStatisticsWithPeriodLimit(authToken, campaignsToUse, monthFrom, monthTo, "Месяц");

  // 5. Читаем SKU из колонки V (22)
  const skuRange = sheet.getRange(2, 22, lastRow - 1);
  const skuRawValues = skuRange.getValues().flat();

  Logger.log(`📋 Прочитано SKU из таблицы: ${skuRawValues.length}`);

  // Показываем примеры SKU для отладки
  const sampleSKUs = skuRawValues.filter(s => s).slice(0, 5);
  if (sampleSKUs.length > 0) {
    Logger.log(`📋 Примеры SKU из таблицы: ${sampleSKUs.join(', ')}`);
  }

  // 6. Формируем данные для записи
  const colAU = [];
  let withMonthExpense = 0;

  for (let i = 0; i < skuRawValues.length; i++) {
    const sku = skuRawValues[i] ? skuRawValues[i].toString().trim() : "";

    if (sku) {
      const monthExpense = monthStats[sku] || 0;
      colAU.push([monthExpense]);

      if (monthExpense > 0) withMonthExpense++;
    } else {
      colAU.push([0]);
    }
  }

  // 7. Записываем в таблицу
  sheet.getRange(2, 47, colAU.length, 1).setValues(colAU);

  // 8. Статистика
  Logger.log(``);
  Logger.log(`📊 СТАТИСТИКА:`);
  Logger.log(`   Обновлено строк: ${skuRawValues.length}`);
  Logger.log(`   С расходами за месяц: ${withMonthExpense}`);
  Logger.log(`   Уникальных SKU в отчёте: ${Object.keys(monthStats).length}`);
  Logger.log(`✅ Завершено`);
}

// ============================================
// ЦИКЛИЧЕСКОЕ ОБНОВЛЕНИЕ (2 ПРОГОНА)
// ============================================

/**
 * ПРОГОН 1: Создаём все отчёты и сохраняем UUID
 * Обрабатывает ВСЕ кампании (без ограничения 100)
 */
function step1_CreateReports() {
  Logger.log("============================================");
  Logger.log("🔄 ПРОГОН 1: СОЗДАНИЕ ОТЧЁТОВ");
  Logger.log("============================================");

  const props = PropertiesService.getScriptProperties();

  // 1. Получаем токен
  const authToken = getPerformanceAuthToken();
  if (!authToken) {
    Logger.log("❌ Не удалось получить токен");
    return;
  }

  // 2. Получаем ВСЕ кампании
  const campaigns = getPerformanceCampaigns(authToken);
  if (!campaigns || campaigns.length === 0) {
    Logger.log("❌ Не удалось получить кампании");
    return;
  }

  Logger.log(`📊 Всего кампаний: ${campaigns.length}`);

  // 3. Определяем период
  const today = new Date();
  const dateTo = new Date(today);
  dateTo.setDate(today.getDate() - 2);

  const dateFrom = new Date(dateTo);
  dateFrom.setDate(dateTo.getDate() - 30);

  const formatDate = date => Utilities.formatDate(date, "GMT+3", "yyyy-MM-dd");

  const dateFromStr = formatDate(dateFrom);
  const dateToStr = formatDate(dateTo);

  Logger.log(`📅 Период: ${dateFromStr} → ${dateToStr}`);

  // 4. Создаём отчёты для всех кампаний С ожиданием готовности каждого
  const BATCH = 10;
  const totalChunks = Math.ceil(campaigns.length / BATCH);
  const uuids = [];
  let failedCount = 0;

  for (let i = 0; i < campaigns.length; i += BATCH) {
    const chunk = campaigns.slice(i, i + BATCH);
    const campaignIds = chunk.map(c => c.id);
    const campaignNames = chunk.map(c => `"${c.title}"`).join(', ');

    const chunkNum = Math.floor(i / BATCH) + 1;

    Logger.log(`📦 Чанк ${chunkNum}/${totalChunks}: ${campaignIds.length} кампаний (ID: ${campaignIds.join(', ')})`);
    Logger.log(`   Названия: ${campaignNames}`);

    // Пытаемся создать отчёт с повтором при ошибке 502
    let uuid = null;
    let retries = 0;
    const maxRetries = 3;

    while (uuid === null && retries < maxRetries) {
      if (retries > 0) {
        Logger.log(`🔄 Повторная попытка ${retries}/${maxRetries}...`);
        Utilities.sleep(10000); // 10 секунд паузы перед повтором
      }

      const result = createStatisticsReport(authToken, campaignIds, dateFromStr, dateToStr);

      // undefined = 502, пробуем ещё раз
      // null = фатальная ошибка, прекращаем
      // string = UUID, успех
      if (result === undefined) {
        // Повторяем
      } else {
        uuid = result;
      }

      retries++;
    }

    if (uuid) {
      uuids.push(uuid);
      Logger.log(`✅ Чанк ${chunkNum}: UUID ${uuid} - ожидание готовности...`);

      // Ждём готовности отчёта (УВЕЛИЧЕНО до 60 попыток)
      let attempts = 0;
      const maxAttempts = 60;
      let isReady = false;

      while (attempts < maxAttempts && !isReady) {
        attempts++;
        Utilities.sleep(5000); // 5 секунд

        const status = getReportStatus(authToken, uuid);

        if (status.status === 'OK') {
          Logger.log(`✅ Чанк ${chunkNum}: отчёт готов (попытка ${attempts})`);
          isReady = true;
        } else if (status.status === 'ERROR') {
          if (status.error && !status.error.includes("404")) {
            Logger.log(`❌ Чанк ${chunkNum}: ошибка - ${status.error}`);
            uuids.pop();
            failedCount++;
            isReady = true;
            break;
          }

          if (attempts % 10 === 0) {
            Logger.log(`⏳ Чанк ${chunkNum}: ожидание... (${attempts}/${maxAttempts})`);
          }
        }
      }

      if (!isReady) {
        Logger.log(`⚠️ Чанк ${chunkNum}: отчёт не готов за ${maxAttempts} попыток`);
        uuids.pop();
        failedCount++;
      }

    } else {
      failedCount++;
      Logger.log(`❌ Чанк ${chunkNum}: не удалось создать отчёт`);
    }
  }

  Logger.log(``);
  Logger.log(`✅ Создано ${uuids.length} готовых отчётов из ${totalChunks} чанков`);
  if (failedCount > 0) {
    Logger.log(`⚠️ Не удалось создать ${failedCount} отчётов`);
  }

  // 5. Сохраняем UUID и токен для второго прогона
  props.setProperty('PERF_UUIDS', JSON.stringify(uuids));
  props.setProperty('PERF_TOKEN', authToken);
  props.setProperty('PERF_DATE_FROM', dateFromStr);
  props.setProperty('PERF_DATE_TO', dateToStr);

  Logger.log(`💾 UUID сохранены в PropertiesService`);

  // 6. Планируем автоматический запуск step2 через 1 минуту
  deleteTrigger('step2_CollectReports');

  ScriptApp.newTrigger('step2_CollectReports')
    .timeBased()
    .after(1 * 60 * 1000)
    .create();

  Logger.log(`⏰ Автозапуск step2_CollectReports через 1 минуту`);
  Logger.log(`============================================`);
}

/**
 * ПРОГОН 2: Собираем готовые отчёты и записываем в таблицу
 */
function step2_CollectReports() {
  Logger.log("============================================");
  Logger.log("🔄 ПРОГОН 2: СБОР ОТЧЁТОВ");
  Logger.log("============================================");

  const props = PropertiesService.getScriptProperties();

  // 1. Читаем сохранённые данные
  const uuidsRaw = props.getProperty('PERF_UUIDS');
  const authToken = props.getProperty('PERF_TOKEN');
  const dateFrom = props.getProperty('PERF_DATE_FROM');
  const dateTo = props.getProperty('PERF_DATE_TO');

  if (!uuidsRaw || !authToken) {
    Logger.log("❌ UUID или токен не найдены");
    Logger.log("   Сначала запустите step1_CreateReports");
    return;
  }

  const uuids = JSON.parse(uuidsRaw);

  Logger.log(`📋 UUID для сбора: ${uuids.length}`);
  Logger.log(`📅 Период: ${dateFrom} → ${dateTo}`);

  // 2. Собираем статистику из всех отчётов
  const allStats = {};
  let successCount = 0;
  let skippedCount = 0;
  const remainingUuids = [];

  for (let i = 0; i < uuids.length; i++) {
    const uuid = uuids[i];

    const status = getReportStatus(authToken, uuid);

    if (status.status === 'OK') {
      Logger.log(`📦 UUID ${i + 1}/${uuids.length}: готов`);

      const zipBlob = downloadReport(authToken, uuid);
      if (!zipBlob) {
        Logger.log(`❌ UUID ${i + 1}/${uuids.length}: не удалось скачать`);
        remainingUuids.push(uuid);
        continue;
      }

      const chunkStats = parseStatisticsZip(zipBlob);

      for (const sku in chunkStats) {
        allStats[sku] = (allStats[sku] || 0) + chunkStats[sku];
      }

      successCount++;
      Logger.log(`✅ UUID ${i + 1}/${uuids.length}: добавлено ${Object.keys(chunkStats).length} SKU`);

    } else if (status.status === 'IN_PROGRESS') {
      Logger.log(`⏳ UUID ${i + 1}/${uuids.length}: создаётся... (пропускаем)`);
      skippedCount++;
      remainingUuids.push(uuid);

    } else {
      Logger.log(`❌ UUID ${i + 1}/${uuids.length}: ошибка - ${status.error}`);
    }
  }

  Logger.log(``);
  Logger.log(`📊 СТАТИСТИКА СБОРА:`);
  Logger.log(`   Успешно собрано: ${successCount}/${uuids.length}`);
  Logger.log(`   Пропущено (не готовы): ${skippedCount}`);
  Logger.log(`   Уникальных SKU: ${Object.keys(allStats).length}`);

  // 3. Если есть не готовые отчёты — перезапланируем step2
  if (skippedCount > 0) {
    Logger.log(`⚠️ ${skippedCount} отчётов не готовы`);

    props.setProperty('PERF_UUIDS', JSON.stringify(remainingUuids));

    deleteTrigger('step2_CollectReports');

    ScriptApp.newTrigger('step2_CollectReports')
      .timeBased()
      .after(3 * 60 * 1000)
      .create();

    Logger.log(`⏰ Повторный запуск step2_CollectReports через 3 минуты`);
    Logger.log(`============================================`);

    return;
  }

  // 4. Все отчёты собраны — записываем в таблицу

  // Проверяем наличие целевого SKU для отладки
  const targetSKU = '3144953487';
  if (allStats[targetSKU]) {
    Logger.log(`🎯 Целевой SKU ${targetSKU} НАЙДЕН: ${allStats[targetSKU].toFixed(6)} руб.`);
  } else {
    Logger.log(`⚠️ Целевой SKU ${targetSKU} НЕ НАЙДЕН в отчётах!`);
    Logger.log(`   Всего SKU в отчётах: ${Object.keys(allStats).length}`);
  }

  writeStatsToSheet(allStats);

  // 5. Очищаем временные данные
  props.deleteProperty('PERF_UUIDS');
  props.deleteProperty('PERF_TOKEN');
  props.deleteProperty('PERF_DATE_FROM');
  props.deleteProperty('PERF_DATE_TO');

  Logger.log(`🗑️ Временные данные удалены`);

  // 6. Удаляем триггер step2
  deleteTrigger('step2_CollectReports');

  Logger.log(``);
  Logger.log(`✅ ГОТОВО!`);
  Logger.log(`============================================`);
}

/**
 * Записывает статистику в таблицу
 */
function writeStatsToSheet(allStats) {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("❌ Нет данных для записи");
    return;
  }

  // Читаем SKU из колонки V (22)
  const skuRange = sheet.getRange(2, 22, lastRow - 1);
  const skuRawValues = skuRange.getValues().flat();

  Logger.log(`📋 Прочитано SKU из таблицы: ${skuRawValues.length}`);

  // Показываем примеры SKU для отладки
  const sampleSKUs = skuRawValues.filter(s => s).slice(0, 5);
  if (sampleSKUs.length > 0) {
    Logger.log(`📋 Примеры SKU из таблицы: ${sampleSKUs.join(', ')}`);
  }

  // Формируем данные для записи
  const colAU = [];
  let withMonthExpense = 0;

  for (let i = 0; i < skuRawValues.length; i++) {
    const sku = skuRawValues[i] ? skuRawValues[i].toString().trim() : "";

    if (sku) {
      const monthExpense = allStats[sku] || 0;
      colAU.push([monthExpense]);

      if (monthExpense > 0) withMonthExpense++;
    } else {
      colAU.push([0]);
    }
  }

  // Записываем в таблицу
  sheet.getRange(2, 47, colAU.length, 1).setValues(colAU);

  Logger.log(`📊 Записано в таблицу:`);
  Logger.log(`   Обновлено строк: ${skuRawValues.length}`);
  Logger.log(`   С расходами за месяц: ${withMonthExpense}`);
  Logger.log(`   Уникальных SKU в отчёте: ${Object.keys(allStats).length}`);
}

/**
 * Удаляет триггер по имени функции
 */
function deleteTrigger(funcName) {
  const triggers = ScriptApp.getProjectTriggers();
  const deleted = triggers.filter(t => t.getHandlerFunction() === funcName);

  deleted.forEach(t => ScriptApp.deleteTrigger(t));

  if (deleted.length > 0) {
    Logger.log(`🗑️ Удалено триггеров: ${deleted.length}`);
  }
}

/**
 * Ручной запуск полного цикла
 */
function updateOzonAdExpenses_Full() {
  Logger.log("============================================");
  Logger.log("🔄 ПОЛНЫЙ ЦИКЛ (ручной режим)");
  Logger.log("============================================");
  Logger.log("⚠️ Используйте step1_CreateReports() для создания отчётов");
  Logger.log("   step2_CollectReports() запустится автоматически через 1 минуту");
  Logger.log("============================================");

  step1_CreateReports();
}

/**
 * Тестовая функция для проверки Performance API
 */
function testPerformanceAPI() {
  Logger.log("=== ТЕСТ PERFORMANCE API ===");

  const authToken = getPerformanceAuthToken();
  if (!authToken) {
    Logger.log("❌ Токен не получен");
    return;
  }

  const campaigns = getPerformanceCampaigns(authToken);
  if (!campaigns || campaigns.length === 0) {
    Logger.log("❌ Кампании не получены");
    return;
  }

  Logger.log(`📊 Всего кампаний: ${campaigns.length}`);

  Logger.log(`📊 Первые 5 кампаний:`);
  campaigns.slice(0, 5).forEach((c, i) => {
    Logger.log(`   ${i + 1}. ID: ${c.id}, Название: "${c.title}", Статус: ${c.status}, Бюджет: ${c.budget}`);
  });

  // Создаём тестовый отчёт
  const today = new Date();
  const dateFrom = new Date(today);
  dateFrom.setDate(today.getDate() - 7);

  const testCampaigns = campaigns.slice(0, 10).map(c => c.id);
  const formatDate = date => Utilities.formatDate(date, "GMT+3", "yyyy-MM-dd");

  Logger.log(`📅 Тестовый период: ${formatDate(dateFrom)} → ${formatDate(today)}`);
  Logger.log(`📊 Тестовые кампании: ${testCampaigns.length}`);

  const uuid = createStatisticsReport(authToken, testCampaigns, formatDate(dateFrom), formatDate(today));
  if (!uuid) {
    Logger.log("❌ Не удалось создать отчёт");
    return;
  }

  Logger.log(`✅ UUID отчёта: ${uuid}`);

  // Ожидание готовности
  Logger.log(`⏳ Ожидание готовности отчёта...`);
  let attempts = 0;

  while (attempts < 60) {
    attempts++;
    Utilities.sleep(5000);

    const status = getReportStatus(authToken, uuid);

    if (status.status === "OK") {
      Logger.log(`✅ Отчёт готов! (попытка ${attempts})`);

      Logger.log(`📥 Скачивание отчёта...`);
      const zipBlob = downloadReport(authToken, uuid);

      if (!zipBlob) {
        Logger.log("❌ Не удалось скачать отчёт");
        return;
      }

      Logger.log(`📦 Размер: ${zipBlob.getBytes().length} байт`);

      const stats = parseStatisticsZip(zipBlob);

      Logger.log(``);
      Logger.log(`📊 РЕЗУЛЬТАТЫ:`);
      Logger.log(`   Уникальных SKU: ${Object.keys(stats).length}`);

      const totalExpense = Object.values(stats).reduce((sum, val) => sum + val, 0);
      Logger.log(`   ИТОГО расходы: ${totalExpense.toFixed(2)} руб.`);

      Logger.log(``);
      Logger.log(`✅ ТЕСТ ПРОЙДЕН УСПЕШНО!`);
      return;
    } else if (status.status === "ERROR") {
      Logger.log(`❌ Ошибка отчёта: ${status.error}`);
      return;
    }

    if (attempts % 10 === 0) {
      Logger.log(`⏳ Ожидание... (${attempts}/60)`);
    }
  }

  Logger.log(`❌ Таймаут ожидания`);
}
