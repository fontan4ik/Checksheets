/**
 * WB FBS МОСКВА - ИСПРАВЛЕННАЯ ВЕРСИЯ
 *
 * Заполняет колонку Q (17): ОСТ ФБС МСК ВБ
 *
 * ИСПРАВЛЕНО: Использует правильный API statistics-api
 * Фильтрует по warehouseId после получения всех данных
 */

function updateWBFBSMoscow() {
  const warehouseId = 1449484; // Коледино (Подмосковье)
  const column = 17; // Q (17): ОСТ ФБС МСК ВБ

  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет артикулов.");
    return;
  }

  Logger.log(`=== ОБНОВЛЕНИЕ FBS МОСКВА (склад ${warehouseId}, колонка Q) ===`);

  // ИСПРАВЛЕНО: используем statistics-api вместо marketplace-api
  const url = "https://statistics-api.wildberries.ru/api/v1/supplier/stocks?dateFrom=2019-06-20";

  const options = {
    method: "get",
    headers: wbHeaders(),
    muteHttpExceptions: true
  };

  try {
    const response = retryFetch(url, options);

    if (!response) {
      Logger.log(`❌ Не удалось получить остатки FBS Москва`);
      return;
    }

    const data = JSON.parse(response.getContentText());

    if (!Array.isArray(data)) {
      Logger.log(`❌ Ошибка ответа API: ${JSON.stringify(data).substring(0, 200)}`);
      return;
    }

    Logger.log(`✅ Получено записей: ${data.length}`);

    // ИСПРАВЛЕНО: фильтруем по warehouseId и агрегируем по supplierArticle
    const stockMap = {};

    data.forEach(item => {
      // Проверяем warehouseId
      if (item.warehouseId !== warehouseId) {
        return;
      }

      const supplierArticle = item.supplierArticle;
      const quantity = item.quantity || 0;

      if (supplierArticle) {
        // Суммируем если есть несколько записей
        if (!stockMap[supplierArticle]) {
          stockMap[supplierArticle] = 0;
        }
        stockMap[supplierArticle] += quantity;
      }
    });

    // Читаем артикулы из таблицы
    const articles = sheet.getRange(2, 1, lastRow - 1).getValues().flat();
    const currentStocks = sheet.getRange(2, column, lastRow - 1).getValues().flat();

    let updatedCount = 0;
    let foundCount = 0;

    // Создаем мап для базовых артикулов
    const baseArticleIndexMap = new Map();
    articles.forEach((art, i) => {
      if (art) {
        const baseArt = String(art).trim().split('-')[0];
        baseArticleIndexMap.set(baseArt, i);
      }
    });

    for (let i = 0; i < articles.length; i++) {
      const art = articles[i];

      if (!art) {
        continue;
      }

      const artStr = String(art).trim();

      // Ищем по базовому артикулу (API возвращает без суффикса)
      const baseArt = artStr.split('-')[0];
      const quantity = stockMap[baseArt] || 0;

      if (quantity > 0) {
        foundCount++;
      }

      const oldValue = currentStocks[i];

      // ИСПРАВЛЕНО: используем != вместо !== для корректного сравнения с undefined
      if (oldValue != quantity) {
        sheet.getRange(i + 2, column).setValue(quantity);
        updatedCount++;
      }
    }

    // ДИАГНОСТИКА для 22068-1
    const testArticle = "22068-1";
    const testBase = "22068";
    const testQuantity = stockMap[testBase] || 0;
    Logger.log(``);
    Logger.log(`=== ДИАГНОСТИКА ${testArticle} ===`);
    Logger.log(`   Базовый артикул: ${testBase}`);
    Logger.log(`   ОСТ ФБС МСК ВБ: ${testQuantity}`);

    Logger.log(`Найдено товаров на складе: ${foundCount}`);
    Logger.log(`Обновлено строк: ${updatedCount}`);
    Logger.log(`✅ Завершено`);

  } catch (e) {
    Logger.log(`❌ Ошибка: ${e.message}`);
  }
}
