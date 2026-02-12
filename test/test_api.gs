// ============================================
// ТЕСТОВЫЕ ФУНКЦИИ ДЛЯ ПРОВЕРКИ API И ЗАПОЛНЕНИЯ КОЛОНОК
// ============================================

/**
 * testAllColumns() - Главная тестовая функция
 * Проверяет все колонки и выводит отчёт о заполнении
 */
function testAllColumns() {
  Logger.log("========================================");
  Logger.log("🧪 НАЧАЛО ТЕСТИРОВАНИЯ ВСЕХ КОЛОНОК");
  Logger.log("========================================");

  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();
  const testRows = Math.min(lastRow - 1, 100); // Проверяем первые 100 строк

  const results = [];

  // 1. Проверка заполнения колонок
  Logger.log("\n📊 ЗАПОЛНЕНИЕ КОЛОНОК (первые " + testRows + " строк):");
  Logger.log("----------------------------------------");

  const columns = [
    { num: 1, letter: "A", name: "Артикул" },
    { num: 3, letter: "C", name: "Бренд" },
    { num: 4, letter: "D", name: "Связка" },
    { num: 5, letter: "E", name: "Картинка" },
    { num: 6, letter: "F", name: "Остаток ФБО ОЗОН" },
    { num: 7, letter: "G", name: "Остаток ФБС ОЗОН" },
    { num: 8, letter: "H", name: "ОСТ ФБС МСК ОЗОН" },
    { num: 9, letter: "I", name: "Уход Мес ОЗОН" },
    { num: 10, letter: "J", name: "Уход КВ" },
    { num: 11, letter: "K", name: "ЦЕНА ОЗОН" },
    { num: 12, letter: "L", name: "Сумма заказов Мес ОЗОН" },
    { num: 13, letter: "M", name: "ЦЕНА ВБ" },
    { num: 14, letter: "N", name: "Сумма заказов Мес ВБ" },
    { num: 15, letter: "O", name: "Остаток ФБО ВБ" },
    { num: 16, letter: "P", name: "Остаток ФБС ВБ" },
    { num: 18, letter: "R", name: "Уход Мес ВБ" },
    { num: 19, letter: "S", name: "Уход КВ ВБ" },
    { num: 20, letter: "T", name: "Артикул ВБ" },
    { num: 21, letter: "U", name: "Product_id Ozon" },
    { num: 22, letter: "V", name: "SKU Ozon" },
    { num: 24, letter: "X", name: "Название модели" },
    { num: 25, letter: "Y", name: "Категория товара" }
  ];

  columns.forEach(col => {
    const range = sheet.getRange(2, col.num, testRows, 1);
    const values = range.getValues().flat();
    const filled = values.filter(v => v !== "" && v !== null && v !== undefined).length;
    const percentage = ((filled / testRows) * 100).toFixed(1);

    Logger.log(`${col.letter} (${col.num}) ${col.name}: ${filled}/${testRows} (${percentage}%)`);

    // Проверка первых 5 значений
    const samples = values.slice(0, 5).filter(v => v !== "" && v !== null && v !== undefined);
    if (samples.length > 0) {
      Logger.log(`  Примеры: ${samples.map(s => `"${String(s).substring(0, 30)}"`).join(", ")}`);
    }
  });

  Logger.log("\n========================================");
  Logger.log("🔍 ПРОВЕРКА КРИТИЧЕСКИХ ПРОБЛЕМ:");
  Logger.log("========================================");

  // Проверка Product_id Ozon (колонка U)
  checkProductIds(sheet);

  // Проверка Артикул ВБ (колонка T)
  checkWBArticles(sheet);

  // Проверка WB analytics
  checkWBAnalytics(sheet);
}

/**
 * checkProductIds() - Проверка product_id в колонке U (21)
 */
function checkProductIds(sheet) {
  Logger.log("\n📋 Product_id Ozon (колонка U, 21):");

  const lastRow = sheet.getLastRow();
  const range = sheet.getRange(2, 21, Math.min(lastRow - 1, 100), 1);
  const values = range.getValues().flat();

  const filled = values.filter(v => v && v > 0).length;
  const zeros = values.filter(v => v === 0 || v === "").length;
  const invalid = values.filter(v => v && v !== "" && v <= 0).length;

  Logger.log(`  Заполнено: ${filled}/${values.length}`);
  Logger.log(`  Пустые/ноль: ${zeros}`);
  Logger.log(`  Невалидные (<0): ${invalid}`);

  if (filled === 0) {
    Logger.log(`  ❌ ПРОБЛЕМА: Product_id не заполняются!`);
    Logger.log(`  Решение: Проверьте функцию updateProductsV2() в Ozon обновить товары V2.gs`);
  } else {
    Logger.log(`  ✅ Product_id заполняются`);
  }
}

/**
 * checkWBArticles() - Проверка Артикул ВБ в колонке T (20)
 */
function checkWBArticles(sheet) {
  Logger.log("\n📋 Артикул ВБ (колонка T, 20):");

  const lastRow = sheet.getLastRow();
  const range = sheet.getRange(2, 20, Math.min(lastRow - 1, 100), 1);
  const values = range.getValues().flat();

  const filled = values.filter(v => v !== "" && v !== null && v !== undefined).length;
  const looksLikeBarcode = values.filter(v => {
    const s = String(v);
    return s && s.length > 10 && /^\d+$/.test(s); // Баркод - длинная цифра
  }).length;

  Logger.log(`  Заполнено: ${filled}/${values.length}`);

  if (filled > 0 && looksLikeBarcode > 0) {
    Logger.log(`  ❌ ПРОБЛЕМА: ${looksLikeBarcode} значений похожи на баркоды!`);
    Logger.log(`  Пример баркода: ${values.find(v => v && String(v).length > 10 && /^\d+$/.test(v))}`);
    Logger.log(`  Решение: Нужна функция для получения реальных артикулов WB`);
  } else if (filled === 0) {
    Logger.log(`  ❌ ПРОБЛЕМА: Колонка пустая!`);
    Logger.log(`  Решение: Создать функцию для выгрузки артикулов WB`);
  } else {
    Logger.log(`  ✅ Артикулы WB выглядят корректно`);
  }
}

/**
 * checkWBAnalytics() - Проверка аналитики WB
 */
function checkWBAnalytics(sheet) {
  Logger.log("\n📋 Аналитика WB:");

  const lastRow = sheet.getLastRow();

  // Уход Мес ВБ (R, 18)
  const rRange = sheet.getRange(2, 18, Math.min(lastRow - 1, 100), 1);
  const rValues = rRange.getValues().flat();
  const rFilled = rValues.filter(v => v !== "" && v !== null && v !== undefined).length;

  // Уход КВ ВБ (S, 19)
  const sRange = sheet.getRange(2, 19, Math.min(lastRow - 1, 100), 1);
  const sValues = sRange.getValues().flat();
  const sFilled = sValues.filter(v => v !== "" && v !== null && v !== undefined).length;

  Logger.log(`  Уход Мес ВБ (R, 18): ${rFilled}/${rValues.length} заполнено`);
  Logger.log(`  Уход КВ ВБ (S, 19): ${sFilled}/${sValues.length} заполнено`);

  if (rFilled === 0 && sFilled === 0) {
    Logger.log(`  ❌ ПРОБЛЕМА: Аналитика WB не заполняется!`);
    Logger.log(`  Решение: Создать функцию getWBAnalytics() для выгрузки аналитики WB`);
  }
}

/**
 * testOzonAPI() - Тест Ozon API
 */
function testOzonAPI() {
  Logger.log("========================================");
  Logger.log("🧪 ТЕСТ OZON API");
  Logger.log("========================================");

  const sheet = mainSheet();
  const testArticle = sheet.getRange("A2").getValue();

  Logger.log(`\n📦 Тестовый артикул: ${testArticle}`);

  // Тест v4/product/info/attributes
  Logger.log("\n1️⃣ Тест v4/product/info/attributes:");
  try {
    const payload = {
      filter: { offer_id: [testArticle] },
      limit: 1
    };
    const options = {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify(payload)
    };
    const response = UrlFetchApp.fetch("https://api-seller.ozon.ru/v4/product/info/attributes", options);
    const data = JSON.parse(response.getContentText());

    if (data.result && data.result.length > 0) {
      const item = data.result[0];
      Logger.log(`  ✅ Успешно!`);
      Logger.log(`  offer_id: ${item.offer_id}`);
      Logger.log(`  product_id: ${item.product_id || "НЕТ!"}`);
      Logger.log(`  name: ${item.name?.substring(0, 50) || "НЕТ"}...`);
      Logger.log(`  attributes: ${item.attributes?.length || 0} шт`);

      // Проверка атрибутов
      if (item.attributes) {
        const brand = item.attributes.find(a => a.id === 85);
        const model = item.attributes.find(a => a.id === 9048);
        Logger.log(`  Бренд (id=85): ${brand?.values[0]?.value || "НЕТ"}`);
        Logger.log(`  Модель (id=9048): ${model?.values[0]?.value || "НЕТ"}`);
      }
    } else {
      Logger.log(`  ❌ Пустой ответ`);
    }
  } catch (e) {
    Logger.log(`  ❌ Ошибка: ${e.message}`);
  }

  // Тест v4/product/info/stocks
  Logger.log("\n2️⃣ Тест v4/product/info/stocks:");
  try {
    const productId = sheet.getRange("U2").getValue();
    if (!productId || productId <= 0) {
      Logger.log(`  ⚠️ Нет валидного product_id в ячейке U2`);
    } else {
      const payload = {
        filter: { product_id: [productId] },
        limit: 1
      };
      const options = {
        method: "post",
        contentType: "application/json",
        headers: ozonHeaders(),
        payload: JSON.stringify(payload)
      };
      const response = UrlFetchApp.fetch("https://api-seller.ozon.ru/v4/product/info/stocks", options);
      const data = JSON.parse(response.getContentText());

      if (data.items && data.items.length > 0) {
        const item = data.items[0];
        const fbo = item.stocks?.find(s => s.type === "fbo");
        Logger.log(`  ✅ Успешно!`);
        Logger.log(`  product_id: ${item.product_id}`);
        Logger.log(`  FBO остаток: ${fbo?.present || 0}`);
      } else {
        Logger.log(`  ❌ Пустой ответ`);
      }
    }
  } catch (e) {
    Logger.log(`  ❌ Ошибка: ${e.message}`);
  }

  Logger.log("\n========================================");
}

/**
 * testWBAPI() - Тест Wildberries API
 */
function testWBAPI() {
  Logger.log("========================================");
  Logger.log("🧪 ТЕСТ WILDBERRIES API");
  Logger.log("========================================");

  // Тест stocks
  Logger.log("\n1️⃣ Тест stocks API:");
  try {
    const url = "https://statistics-api.wildberries.ru/api/v1/supplier/stocks?dateFrom=2019-06-20";
    const options = {
      method: "get",
      headers: wbHeaders()
    };
    const response = UrlFetchApp.fetch(url, options);
    const data = JSON.parse(response.getContentText());

    if (data && data.length > 0) {
      Logger.log(`  ✅ Успешно!`);
      Logger.log(`  Получено товаров: ${data.length}`);

      const first = data[0];
      Logger.log(`  Пример:`);
      Logger.log(`    supplierArticle: ${first.supplierArticle}`);
      Logger.log(`    quantity: ${first.quantity}`);
      Logger.log(`    nmId: ${first.nmId}`);
      Logger.log(`    barcode: ${first.barcode}`);
    } else {
      Logger.log(`  ❌ Пустой ответ`);
    }
  } catch (e) {
    Logger.log(`  ❌ Ошибка: ${e.message}`);
  }

  Logger.log("\n========================================");
}
