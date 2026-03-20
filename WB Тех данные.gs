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
function updateWBTechDataSheet() {
  const sheetName = 'ТЕХ данные wb';
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = getOrCreateSheet_(ss, sheetName);

  Logger.log('╔════════════════════════════════════════════════════════════════════════╗');
  Logger.log('║   WB ТЕХ ДАННЫЕ: vendorCode + chrt_id + nmId                         ║');
  Logger.log('╚════════════════════════════════════════════════════════════════════════╝');

  const cards = fetchAllWBCardsForTechData_();

  if (!cards.length) {
    Logger.log('⚠️ Карточки WB не получены');
    prepareWBTechDataSheet_(sheet, []);
    return;
  }

  const rows = [];
  const seen = new Set();
  let cardsWithSizes = 0;
  let cardsWithoutSizes = 0;

  cards.forEach(card => {
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

  rows.sort((a, b) => {
    const vendorCompare = a[0].localeCompare(b[0], 'ru');
    if (vendorCompare !== 0) return vendorCompare;
    const chrtA = a[1] || '';
    const chrtB = b[1] || '';
    return chrtA.localeCompare(chrtB, 'ru');
  });

  prepareWBTechDataSheet_(sheet, rows);

  Logger.log(`✅ Готово. Карточек загружено: ${cards.length}`);
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
        }
      },
      filter: {
        withPhoto: -1
      }
    };

    if (cursor && (cursor.updatedAt || cursor.nmID || cursor.nmId)) {
      payload.settings.cursor = {
        limit: 100,
        updatedAt: cursor.updatedAt,
        nmID: cursor.nmID || cursor.nmId
      };
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
      Logger.log(`❌ Не удалось получить карточки WB, page=${page}`);
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

    if (!pageCards.length) {
      Logger.log(`ℹ️ Пустая страница, page=${page}`);
      break;
    }

    cards.push(...pageCards);
    Logger.log(`   page ${page}: +${pageCards.length}, всего ${cards.length}`);

    const nextCursor = data?.cursor;
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
      Logger.log('⚠️ Достигнут safety limit по страницам');
      break;
    }
  }

  return cards;
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
