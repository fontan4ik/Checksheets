/**
 * WB ТЕХ ДАННЫЕ
 *
 * Выгружает в лист "ТЕХ данные wb" 3 колонки:
 * A: Артикул продавца
 * B: Код размера (chrt_id)
 * C: Артикул WB
 *
 * Источник: WB Content API /content/v2/get/cards/list
 * Поля карточки:
 * - vendorCode -> Артикул продавца
 * - sizes[].chrtID / sizes[].chrtId -> Код размера (chrt_id)
 * - nmID / nmId -> Артикул WB
 *
 * Логика:
 * - Загружаем ВСЕ карточки продавца с пагинацией
 * - Для каждой карточки разворачиваем все размеры в отдельные строки
 * - Полностью перезаписываем лист "ТЕХ данные wb"
 */
const WB_TECH_DATA_SHEET_NAME = 'ТЕХ данные wb';

/**
 * Диагностическая функция: проверяет видимость конкретного товара через API.
 * Запустите её вручную, если в списке не хватает товаров.
 */
function debugSpecificWBItem() {
  const vendorCode = "126411212-DMA-1"; // Артикул со скриншота
  const baseUrl = 'https://content-api.wildberries.ru/content/v2/get/cards/list';
  
  Logger.log(`🔍 Проверка артикула: ${vendorCode}`);
  
  const payload = {
    settings: {
      cursor: { limit: 10 },
      filter: {
        textSearch: vendorCode, // В v2 лучше использовать textSearch
        withPhoto: -1
      }
    }
  };
  
  const response = retryFetch(baseUrl, {
    method: 'post',
    contentType: 'application/json',
    headers: wbHeaders(),
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });
  
  if (response) {
    const text = response.getContentText();
    Logger.log("--- ОТВЕТ API ---");
    Logger.log(text);
    
    if (text.includes(vendorCode)) {
      Logger.log("✅ ТОВАР НАЙДЕН! Значит, проблема в параметрах общего списка.");
    } else {
      Logger.log("❌ ТОВАР НЕ НАЙДЕН. Значит, API-токен не имеет доступа к этому товару.");
    }
  } else {
    Logger.log("❌ Нет ответа от API");
  }
}

function updateWBTechDataSheet() {
  const sheetName = 'ТЕХ данные wb';
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = getOrCreateSheet_(ss, sheetName);

  Logger.log('╔════════════════════════════════════════════════════════════════════════╗');
  Logger.log('║   WB ТЕХ ДАННЫЕ: vendorCode + chrt_id + nmId                         ║');
  Logger.log('╚════════════════════════════════════════════════════════════════════════╝');

    const cards = fetchAllWBCardsForTechData_();
    const errorCards = fetchWBCardsWithErrors_();
    
    const allCards = [...cards, ...errorCards];

    if (!allCards || allCards.length === 0) {
      Logger.log('⚠️ Карточки WB не получены (ни из основы, ни из ошибок).');
      return;
    }
    
    const cardsToProcess = allCards;

  // Если количество карточек подозрительно мало (например, меньше 10, а было явно больше), 
  // стоит предупредить, но здесь мы продолжаем, так как fetchAllWBCardsForTechData_ уже имеет свои проверки.
  
  const rows = [];
  const seen = new Set();
  let cardsWithSizes = 0;
  let cardsWithoutSizes = 0;

  allCards.forEach(card => {
    const vendorCode = (card.vendorCode || '').toString().trim();
    const nmId = card.nmID || card.nmId || '';
    const sizes = Array.isArray(card.sizes) ? card.sizes : [];

    if (!vendorCode || !nmId) {
      return;
    }

    if (!sizes.length) {
      cardsWithoutSizes++;
      const key = `${vendorCode}||${nmId}`;
      if (!seen.has(key)) {
        seen.add(key);
        rows.push([vendorCode, '', nmId.toString()]);
      }
      return;
    }

    cardsWithSizes++;

    sizes.forEach(size => {
      const chrtId = size?.chrtID || size?.chrtId || '';
      const key = `${vendorCode}|${chrtId}|${nmId}`;

      if (seen.has(key)) return;
      seen.add(key);

      rows.push([
        vendorCode,
        chrtId ? chrtId.toString() : '',
        nmId.toString()
      ]);
    });
  });

  // Если строк получилось слишком мало по сравнению с тем, что было в листе,
  // это может быть признаком проблемы с API WB (вернул не все данные).
  const currentCount = sheet.getLastRow() > 1 ? sheet.getLastRow() - 1 : 0;
  if (currentCount > 100 && rows.length < 10) {
    Logger.log(`❌ ОПАСНОСТЬ: В листе было ${currentCount} строк, а получено всего ${rows.length}.`);
    Logger.log('🛑 Обновление отменено. Пожалуйста, проверьте API токен и состояние кабинета WB.');
    return;
  }

  rows.sort((a, b) => {
    const vendorCompare = a[0].localeCompare(b[0], 'ru');
    if (vendorCompare !== 0) return vendorCompare;
    const chrtA = a[1] || '';
    const chrtB = b[1] || '';
    return chrtA.localeCompare(chrtB, 'ru');
  });

  prepareWBTechDataSheet_(sheet, rows);

  Logger.log(`✅ Готово. Карточек загружено всего: ${allCards.length}`);
  Logger.log(`📊 Из них новых/валидных: ${cards.length}`);
  Logger.log(`📊 Из них с ошибками: ${errorCards.length}`);
  Logger.log(`✅ Карточек с размерами: ${cardsWithSizes}`);
  Logger.log(`⚠️ Карточек без размеров: ${cardsWithoutSizes}`);
  Logger.log(`✅ Строк записано в лист "${sheetName}": ${rows.length}`);
}

/**
 * Тестовый запуск с логом первых строк
 */
function testWBTechDataSheet() {
  const cards = fetchAllWBCardsForTechData_();
  const preview = [];

  cards.slice(0, 10).forEach(card => {
    const vendorCode = card.vendorCode || '';
    const nmId = card.nmID || card.nmId || '';
    const sizes = Array.isArray(card.sizes) ? card.sizes : [];

    if (!sizes.length) {
      preview.push([vendorCode, '', nmId]);
      return;
    }

    sizes.forEach(size => {
      preview.push([
        vendorCode,
        size?.chrtID || size?.chrtId || '',
        nmId
      ]);
    });
  });

  Logger.log(`Preview rows: ${preview.length}`);
  preview.slice(0, 30).forEach((row, i) => {
    Logger.log(`${i + 1}. ${row[0]} | ${row[1]} | ${row[2]}`);
  });
}

/**
 * Загружает все карточки WB через пагинацию Content API
 *
 * @returns {Array<Object>}
 */
function fetchAllWBCardsForTechData_() {
  const baseUrl = 'https://content-api.wildberries.ru';
  const headers = wbHeaders();
  const cards = [];
  let cursor = null;
  let page = 0;
  let hasMore = true;
  let safetyCounter = 0;
  let totalInCabinet = -1;

  while (hasMore) {
    safetyCounter++;
    page++;

    const payload = {
      settings: {
        sort: {
          ascending: true
        },
        cursor: {
          limit: 100 
        },
        filter: {
          withPhoto: -1
        }
      }
    };

    // Передаем курсор пагинации целиком, обновляя только лимит
    if (cursor) {
      payload.settings.cursor = cursor;
      payload.settings.cursor.limit = 100;
      
      // На всякий случай дублируем nmID/nmId, если API их потерял
      if (!payload.settings.cursor.nmID && payload.settings.cursor.nmId) {
        payload.settings.cursor.nmID = payload.settings.cursor.nmId;
      }
    }

    const options = {
      method: 'post',
      contentType: 'application/json',
      headers,
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    };

    const response = retryFetch(baseUrl + '/content/v2/get/cards/list', options);

    if (!response) {
      Logger.log(`❌ Не удалось получить карточки WB (ошибка сети), page=${page}`);
      break;
    }

    const code = response.getResponseCode();
    const text = response.getContentText();

    if (code !== 200) {
      Logger.log(`❌ WB Content API вернул код ${code}`);
      Logger.log(text.substring(0, 1000));
      break;
    }

    let data;
    try {
      data = JSON.parse(text);
    } catch (e) {
      Logger.log(`❌ Не удалось распарсить ответ WB Content API: ${e.message}`);
      break;
    }

    const pageCards = Array.isArray(data?.cards) ? data.cards : [];
    
    if (page === 1 && data?.cursor?.total !== undefined) {
      Logger.log(`   (Загрузка первой страницы...)`);
    }

    if (!pageCards.length) {
      if (page === 1) {
        Logger.log('⚠️ WB API вернул 0 карточек на первой странице.');
      } else {
        Logger.log(`ℹ️ Пустая страница, page=${page}`);
      }
      break;
    }

    cards.push(...pageCards);
    Logger.log(`   page ${page}: +${pageCards.length}, всего ${cards.length}`);

    const nextCursor = data?.cursor;
    
    // Проверка конца пагинации: если пришло меньше, чем просили (100), значит это последняя страница
    if (pageCards.length < 100) {
      hasMore = false;
      break;
    }

    if (!nextCursor || !nextCursor.updatedAt || !(nextCursor.nmID || nextCursor.nmId)) {
      hasMore = false;
      break;
    }

    // Защита от зацикливания курсора
    if (
      cursor &&
      String(cursor.updatedAt) === String(nextCursor.updatedAt) &&
      String(cursor.nmID || cursor.nmId) === String(nextCursor.nmID || nextCursor.nmId)
    ) {
      Logger.log('⚠️ Курсор перестал двигаться, остановка пагинации');
      break;
    }

    cursor = nextCursor;

    // Мягкий rate limit
    Utilities.sleep(350);

    if (safetyCounter >= 1000) {
      Logger.log('⚠️ Достигнут safety limit по страницам (1000)');
      break;
    }
  }

  // Логирование итогов
  return cards;
}

/**
 * Получает список карточек с ошибками (черновиков), которые не попали в основной список.
 */
function fetchWBCardsWithErrors_() {
  const baseUrl = 'https://content-api.wildberries.ru/content/v2/cards/error/list';
  const headers = wbHeaders();
  const options = {
    method: 'get',
    headers,
    muteHttpExceptions: true
  };

  Logger.log('🔄 Загрузка карточек с ошибками (черновиков)...');
  const response = retryFetch(baseUrl, options);

  if (!response) return [];
  
  try {
    const data = JSON.parse(response.getContentText());
    const errorCards = data?.data || [];
    if (errorCards.length > 0) {
      Logger.log(`   Найдено в ошибках: ${errorCards.length}`);
    }
    return errorCards;
  } catch (e) {
    Logger.log(`⚠️ Ошибка при парсинге списка ошибок: ${e.message}`);
    return [];
  }
}

/**
 * Подготовка и запись данных в лист
 *
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet
 * @param {Array<Array<string>>} rows
 */
function prepareWBTechDataSheet_(sheet, rows) {
  const headers = [
    'Артикул продавца',
    'Код размера (chrt_id)',
    'Артикул WB'
  ];

  sheet.clearContents();
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);

  if (rows.length) {
    sheet.getRange(2, 1, rows.length, headers.length).setValues(rows);
  }

  sheet.getRange('A:C').setNumberFormat('@');
  sheet.setFrozenRows(1);
  autoResizeColumnsSafe_(sheet, 1, 3);
}

/**
 * Создаёт лист, если его нет
 */
function getOrCreateSheet_(ss, sheetName) {
  return ss.getSheetByName(sheetName) || ss.insertSheet(sheetName);
}

/**
 * Безопасный auto resize
 */
function autoResizeColumnsSafe_(sheet, startColumn, numColumns) {
  try {
    sheet.autoResizeColumns(startColumn, numColumns);
  } catch (e) {
    Logger.log(`⚠️ Не удалось autoResizeColumns: ${e.message}`);
  }
}
