// ============================================
// TRANSISTOR API (Arlight) - Импорт из JSON
// ============================================
//
// АЛЬТЕРНАТИВНЫЙ ВАРИАНТ: Если API требует авторизации через сессию
// можно вручную скачать JSON и импортировать его в таблицу
//
// ИНСТРУКЦИЯ:
// 1. Откройте https://assets.transistor.ru/catalog/v3/sites/products.json в браузере
// 2. Авторизуйтесь если требуется
// 3. Сохраните JSON файл на компьютер
// 4. Загрузите JSON в Google Drive или вставьте в ячейку
// 5. Используйте функции ниже для импорта данных
// ============================================

/**
 * КОНФИГУРАЦИЯ
 */
const TRANSISTOR_SHEET_NAME = "ARL TR";

/**
 * Импортирует данные из JSON файла на Google Drive
 *
 * @param {string} fileName - Имя файла на Google Drive
 */
function importTransistorStocksFromDrive(fileName) {
  Logger.log("╔════════════════════════════════════════════════════════════╗");
  Logger.log("║   ИМПОРТ TRANSISTOR API ИЗ GOOGLE DRIVE                        ║");
  Logger.log("╚════════════════════════════════════════════════════════════╝");

  if (!fileName) {
    fileName = "transistor-products.json"; // имя по умолчанию
  }

  Logger.log(`📁 Поиск файла: ${fileName}`);

  // Ищем файл на Google Drive
  const files = DriveApp.getFilesByName(fileName);

  if (!files.hasNext()) {
    Logger.log(`❌ Файл "${fileName}" не найден на Google Drive`);
    Logger.log(``);
    Logger.log(`📋 ИНСТРУКЦИЯ:`);
    Logger.log(`1. Скачайте JSON с https://assets.transistor.ru/catalog/v3/sites/products.json`);
    Logger.log(`2. Загрузите файл на Google Drive`);
    Logger.log(`3. Укажите имя файла при вызове функции:`);
    Logger.log(`   importTransistorStocksFromDrive("имя_файла.json")`);
    return;
  }

  const file = files.next();
  const jsonContent = file.getBlob().getDataAsString();

  Logger.log(`✅ Файл найден: ${file.getName()} (${file.getSize()} байт)`);

  // Парсим JSON
  try {
    const data = JSON.parse(jsonContent);
    processTransistorData(data);
  } catch (e) {
    Logger.log(`❌ Ошибка парсинга JSON: ${e.message}`);
  }
}

/**
 * Импортирует данные из JSON строки (вставленной в ячейку или переменную)
 *
 * @param {string} jsonString - JSON строка с данными Transistor
 * @param {string} sheetName - Имя листа (по умолчанию "ARL TR")
 */
function importTransistorStocksFromJSON(jsonString, sheetName) {
  Logger.log("╔════════════════════════════════════════════════════════════╗");
  Logger.log("║   ИМПОРТ TRANSISTOR API ИЗ JSON СТРОКИ                        ║");
  Logger.log("╚════════════════════════════════════════════════════════════╝");

  if (!jsonString) {
    Logger.log("❌ Не указана JSON строка");
    return;
  }

  const targetSheet = sheetName || TRANSISTOR_SHEET_NAME;

  try {
    const data = typeof jsonString === 'string' ? JSON.parse(jsonString) : jsonString;
    processTransistorData(data, targetSheet);
  } catch (e) {
    Logger.log(`❌ Ошибка парсинга JSON: ${e.message}`);
    Logger.log(``);
    Logger.log(`💡 Возможно JSON слишком большой для ячейки.`);
    Logger.log(`   Используйте importTransistorStocksFromDrive() вместо этого.`);
  }
}

/**
 * Импортирует данные из ячейки на текущем листе
 *
 * @param {string} cellAddress - Адрес ячейки с JSON (например, "A1")
 * @param {string} sheetName - Имя листа с JSON (по умолчанию "Settings")
 */
function importTransistorStocksFromCell(cellAddress, sheetName) {
  Logger.log("╔════════════════════════════════════════════════════════════╗");
  Logger.log("║   ИМПОРТ TRANSISTOR API ИЗ ЯЧЕЙКИ                               ║");
  Logger.log("╚════════════════════════════════════════════════════════════╝");

  if (!cellAddress) {
    cellAddress = "B1"; // по умолчанию
  }

  const sourceSheetName = sheetName || "Settings";

  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sourceSheet = spreadsheet.getSheetByName(sourceSheetName);

  if (!sourceSheet) {
    Logger.log(`❌ Лист "${sourceSheetName}" не найден`);
    return;
  }

  // Получаем JSON из ячейки
  const jsonString = sourceSheet.getRange(cellAddress).getValue();

  if (!jsonString) {
    Logger.log(`❌ Ячейка ${cellAddress} на листе "${sourceSheetName}" пуста`);
    Logger.log(``);
    Logger.log(`📋 ИНСТРУКЦИЯ:`);
    Logger.log(`1. Вставьте JSON данные в ячейку ${cellAddress} листа "${sourceSheetName}"`);
    Logger.log(`2. Выполните функцию:`);
    Logger.log(`   importTransistorStocksFromCell("${cellAddress}", "${sourceSheetName}")`);
    return;
  }

  Logger.log(`✅ JSON прочитан из ячейки ${cellAddress} (${jsonString.length} символов)`);

  try {
    const data = JSON.parse(jsonString);
    processTransistorData(data);
  } catch (e) {
    Logger.log(`❌ Ошибка парсинга JSON: ${e.message}`);
  }
}

/**
 * Обрабатывает данные Transistor и записывает в лист "ARL TR"
 *
 * @param {Array} data - Массив товаров из Transistor API
 * @param {string} sheetName - Имя листа для записи (по умолчанию "ARL TR")
 */
function processTransistorData(data, sheetName) {
  const targetSheet = sheetName || TRANSISTOR_SHEET_NAME;

  Logger.log(``);
  Logger.log(`📊 Обработка данных...`);

  if (!Array.isArray(data)) {
    throw new Error(`Неверный формат данных Transistor API: ожидается массив, получен ${typeof data}`);
  }
  if (data.length === 0) throw new Error("Transistor API вернул пустой список; таблица не обновлена");

  Logger.log(`✅ Получено товаров: ${data.length}`);

  // Создаём мапу article → stock
  Logger.log(``);
  Logger.log(`📋 Создание мапы артикулов...`);

  const stockMap = {};
  let withStock = 0;

  for (const item of data) {
    const article = String(item?.article ?? "").trim();
    if (!article || !Array.isArray(item?.instock)) {
      throw new Error("Transistor API вернул товар без артикула или массива instock; таблица не обновлена");
    }
    const freeStocks = item.instock.filter(stock => stock?.type === "free");
    if (freeStocks.length !== 1) {
      throw new Error(`Transistor API вернул неполный остаток free для артикула ${article}`);
    }
    const rawStock = String(freeStocks[0].stock ?? "").trim();
    if (!/^\d+$/.test(rawStock)) {
      throw new Error(`Transistor API вернул некорректный остаток для артикула ${article}`);
    }
    const stock = Number(rawStock);
    if (!Number.isSafeInteger(stock)) {
      throw new Error(`Transistor API вернул остаток вне допустимого диапазона для артикула ${article}`);
    }
    if (Object.prototype.hasOwnProperty.call(stockMap, article) && stockMap[article] !== stock) {
      throw new Error(`Transistor API вернул разные остатки по артикулу ${article}`);
    }
    stockMap[article] = stock;

    if (stock > 0) {
      withStock++;
    }
  }

  Logger.log(`✅ Мапа создана: ${Object.keys(stockMap).length} артикулов`);
  Logger.log(`📦 С остатком > 0: ${withStock}`);
  Logger.log(`📦 Без остатка: ${Object.keys(stockMap).length - withStock}`);

  // Читаем данные из листа "ARL TR"
  Logger.log(``);
  Logger.log(`📊 Чтение данных из листа "${targetSheet}"...`);

  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(targetSheet);

  if (!sheet) {
    Logger.log(`❌ Лист "${targetSheet}" не найден!`);
    Logger.log(`Создайте лист с именем "${targetSheet}"`);
    return;
  }

  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log(`❌ Нет данных на листе "${targetSheet}"`);
    return;
  }

  const articles = sheet.getRange(2, columnByHeader_(sheet, 'Артикул продавца'), lastRow - 1, 1).getValues().flat();

  Logger.log(`📋 Прочитано строк: ${articles.length}`);

  // Подготовка данных для записи
  Logger.log(``);
  Logger.log(`📝 Подготовка данных для записи...`);

  let matched = 0;
  let notFound = 0;

  const writeMask = articles.map(article => {
    const art = article?.toString().trim();
    return Boolean(art && Object.prototype.hasOwnProperty.call(stockMap, art));
  });
  const valuesToWrite = articles.map((article, index) => {
    const art = article?.toString().trim();

    if (writeMask[index]) {
      matched++;
      return [stockMap[art]];
    } else {
      if (art) notFound++;
      return [""];
    }
  });

  Logger.log(`✅ Найдено в Transistor: ${matched}`);
  Logger.log(`❌ Не найдено: ${notFound}`);
  Logger.log(`📊 Пустых артикулов: ${articles.length - matched - notFound}`);

  // Запись в колонку с заголовком «Остаток».
  Logger.log(``);
  Logger.log(`💾 Запись в колонку «Остаток»...`);

  const written = writeMaskedColumnValues_(
    sheet,
    columnByHeader_(sheet, 'Остаток'),
    valuesToWrite,
    writeMask,
  );

  Logger.log(``);
  Logger.log("╔════════════════════════════════════════════════════════════╗");
  Logger.log("║   ✅ ИМПОРТ ЗАВЕРШЁН                                        ║");
  Logger.log("╚════════════════════════════════════════════════════════════╝");
  Logger.log(`📦 Обработано строк: ${written}`);
  Logger.log(`✅ Найдено совпадений: ${matched}`);
  Logger.log(`❌ Не найдено: ${notFound}`);
  Logger.log(`════════════════════════════════════════════════════════════`);
}

/**
 * Создаёт тестовые данные (для проверки импорта)
 */
function testImportWithMockData() {
  Logger.log("╔════════════════════════════════════════════════════════════╗");
  Logger.log("║   ТЕСТ ИМПОРТА С МОКОВЫМИ ДАННЫМИ                             ║");
  Logger.log("╚════════════════════════════════════════════════════════════╝");

  const mockData = [
    {
      "article": "22068-1",
      "name": "Светильник светодиодный Arlight",
      "instock": [
        {
          "type": "free",
          "stock": 150,
          "unit": 1
        }
      ]
    },
    {
      "article": "48724-1",
      "name": "Лампа LED Arlight E27 9W",
      "instock": [
        {
          "type": "free",
          "stock": 500,
          "unit": 1
        }
      ]
    },
    {
      "article": "10001-AR",
      "name": "Люстра Arlight Chrome",
      "instock": [
        {
          "type": "free",
          "stock": 0,
          "unit": 1
        }
      ]
    }
  ];

  Logger.log(``);
  Logger.log(`📋 Используется ${mockData.length} тестовых товара`);
  Logger.log(``);
  Logger.log(`Артикулы в тесте:`);
  mockData.forEach(item => {
    Logger.log(`  - ${item.article}: ${item.instock?.[0]?.stock || 0} шт.`);
  });

  processTransistorData(mockData);
}
