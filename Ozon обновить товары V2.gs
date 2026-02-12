/**
 * УЛУЧШЕННАЯ ВЕРСИЯ - Обновляет колонки из Ozon API
 *
 * Обновляет колонки в таблице:
 * - C (3): Бренд (brand) - атрибут id=85
 * - D (4): Связка (model_name) - для объединения карточек, атрибут id=9048
 * - E (5): Картинка (primary_image)
 * - U (21): Product_id Ozon
 * - V (22): SKU Ozon
 * - X (24): Название товара (name)
 * - Y (25): Категория товара (description_category_name)
 *
 * ВАЖНО:
 * - B (2): Модель - НЕ трогаем (формула пользователя)
 * - D (4): Связка берется ТОЛЬКО из атрибутов Ozon, если нет - пусто
 */

/**
 * Преобразует буквенное обозначение колонки в числовой индекс
 * Пример: A -> 1, B -> 2, Z -> 26, AA -> 27
 *
 * @param {string} letter - Буквенное обозначение колонки
 * @returns {number} Числовой индекс колонки
 */
function columnLetterToIndex(letter) {
  let index = 0;
  for (let i = 0; i < letter.length; i++) {
    index = index * 26 + (letter.charCodeAt(i) - 64);
  }
  return index;
}

function updateProductsV2() {
  const sheet = mainSheet();

  const sourceColumnLetter = "A"; // Колонка A - Артикул (offer_id)
  const sourceColumnIndex = columnLetterToIndex(sourceColumnLetter);

  // Карта колонок для обновления (с учетом текущей структуры)
  // ВАЖНО: U (21) product_id НЕ обновляем здесь - заполняется syncOfferIdWithProductId()
  const columnKeyMap = {
    "C": "brand",                    // C (3): Бренд
    "D": "model_name",               // D (4): Связка (для объединения карточек)
    "E": "primary_image",            // E (5): Картинка
    // "U": "product_id",            // U (21): Product_id Ozon - ЗАКОММЕНТИРОВАНО!
                                     // Не перезаписываем данные из syncOfferIdWithProductId()
    "V": "sku",                      // V (22): SKU Ozon
    "X": "name",                     // X (24): Название товара
    "Y": "description_category_name" // Y (25): Категория товара
  };

  const rawValues = sheet.getRange(2, sourceColumnIndex, sheet.getLastRow() - 1).getValues();
  const rowData = rawValues.map((row, i) => ({
    rowIndex: i + 2,
    offerId: row[0]
  }));

  const validRows = rowData.filter(r => r.offerId);
  const batchSize = 1000;
  const resultsMap = new Map(); // key: offer_id, value: { данные }
  const categoryIdSet = new Set();
  let lastRequestTime = Date.now() - 1000 / RPS();

  Logger.log(`🚀 Начало выгрузки. Всего товаров: ${validRows.length}`);

  // Первый проход: получаем базовую информацию + атрибуты
  // Используем v4/product/info/attributes - возвращает атрибуты с брендом и моделью
  for (let i = 0; i < validRows.length; i += batchSize) {
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

    const batch = validRows.slice(i, i + batchSize);
    const batchIds = batch.map(r => r.offerId);

    const payload = {
      filter: {
        offer_id: batchIds
      },
      limit: batchIds.length
    };

    const options = {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify(payload)
    };

    const response = retryFetch('https://api-seller.ozon.ru/v4/product/info/attributes', options);

    if (!response) {
      Logger.log(`❌ Ошибка: null response для batch ${i}`);
      continue;
    }

    const responseText = response.getContentText();
    if (!responseText) {
      Logger.log(`❌ Ошибка: пустой response для batch ${i}`);
      continue;
    }

    const data = JSON.parse(responseText);

    if (!data.result || data.result.length === 0) {
      Logger.log(`⚠️ Пустой результат для batch ${i}`);
      continue;
    }

    const items = data.result || [];  // v4 API возвращает result

    items.forEach(item => {
      const offerId = item.offer_id;
      if (!offerId) return;

      const categoryId = item.description_category_id || "";
      if (categoryId) categoryIdSet.add(categoryId);

      // Логируем структуру первого товара для диагностики
      if (i === 0) {
        Logger.log(`🔍 Структура ответа (первый товар):`);
        Logger.log(`   - offer_id: ${item.offer_id}`);
        Logger.log(`   - product_id: ${item.product_id}`);
        Logger.log(`   - Name: ${item.name}`);
        Logger.log(`   - Has attributes: ${!!item.attributes}`);
        if (item.attributes) {
          Logger.log(`   - Attributes count: ${item.attributes.length}`);
          Logger.log(`   - First 3 attributes: ${JSON.stringify(item.attributes.slice(0, 3))}`);
        }
      }

      // Извлекаем бренд из атрибутов (ID 85 = Бренд)
      const brand = extractBrand(item);

      // Извлекаем название модели для объединения карточек (multiplicity)
      // ВАЖНО: Берем только из атрибутов Ozon. Если нет - оставляем пустым.
      const modelName = extractModelAttribute(item);

      resultsMap.set(offerId, {
        product_id: item.product_id || "",
        sku: item.sku || "",
        name: item.name || "",
        description_category_name: "",
        description_category_id: categoryId,
        primary_image: item.primary_image || "",
        brand: brand,
        model_name: modelName
      });
    });

    Logger.log(`✅ Обработано ${Math.min(i + batchSize, validRows.length)}/${validRows.length} товаров`);
  }

  // Получаем дерево категорий
  const categoryTreeOptions = {
    method: "post",
    contentType: "application/json",
    headers: ozonHeaders(),
    payload: JSON.stringify({})
  };

  const treeResponse = retryFetch('https://api-seller.ozon.ru/v1/description-category/tree', categoryTreeOptions);

  if (!treeResponse) {
    Logger.log(`❌ Не удалось получить дерево категорий`);
    return;
  }

  const treeData = JSON.parse(treeResponse.getContentText());

  const categoryNameMap = new Map();
  function traverseTree(nodes) {
    for (const node of nodes) {
      if (node.description_category_id && node.category_name) {
        categoryNameMap.set(node.description_category_id, node.category_name);
      }
      if (node.children && node.children.length > 0) {
        traverseTree(node.children);
      }
    }
  }
  traverseTree(treeData.result);

  // Обновляем названия категорий
  for (const [_, data] of resultsMap.entries()) {
    const name = categoryNameMap.get(data.description_category_id);
    if (name) {
      data.description_category_name = name;
    }
  }

  // Записываем данные в колонки
  for (const [colLetter, key] of Object.entries(columnKeyMap)) {
    const colIndex = columnLetterToIndex(colLetter);
    const values = rowData.map(r => {
      const result = resultsMap.get(r.offerId);
      return [result
        ? key === "primary_image"
          ? result[key] ? `=IMAGE("${result[key]}")` : ""
          : result[key] || ""
        : ""
      ];
    });
    sheet.getRange(2, colIndex, values.length, 1).setValues(values);
    Logger.log(`📝 Колонка ${colLetter} (${colIndex}): ${key} - обновлено ${values.filter(v => v[0]).length} строк`);
  }

  // Статистика
  const brandStats = {};
  let modelCount = 0;
  for (const [_, data] of resultsMap.entries()) {
    if (data.brand) {
      brandStats[data.brand] = (brandStats[data.brand] || 0) + 1;
    }
    if (data.model_name) {
      modelCount++;
    }
  }
  Logger.log(`✅ Обновление завершено!`);
  Logger.log(`🏷️ Уникальных брендов: ${Object.keys(brandStats).length}`);
  Logger.log(`📦 Товаров с моделью: ${modelCount}`);
}

/**
 * Извлекает атрибут товара по ID
 * Ozon API v4 возвращает атрибуты с id, но без attribute_name
 */
function extractAttribute(item, attributeId) {
  if (!item.attributes || !Array.isArray(item.attributes)) {
    return "";
  }

  const attr = item.attributes.find(a => a.id === attributeId);

  if (!attr || !attr.values || attr.values.length === 0) {
    return "";
  }

  // Значение может быть строкой или объектом {value: "..."}
  const value = attr.values[0];
  return typeof value === "string" ? value : (value.value || "");
}

/**
 * Извлекает бренд по известному ID атрибута (85 = Бренд)
 */
function extractBrand(item) {
  return extractAttribute(item, 85); // ID 85 = Бренд в Ozon
}

/**
 * Извлекает название модели для объединения карточек (multiplicity)
 *
 * ВАЖНО: Это атрибут Ozon, который используется для объединения
 * нескольких SKU в одну карточку на витрине.
 *
 * ID атрибутов для модели:
 * - 9048: Артикул производителя / Модель
 * - 22390: Другое поле модели
 *
 * Если атрибут отсутствует - возвращает пустую строку (НЕ генерируем).
 */
function extractModelAttribute(item) {
  // Проверяем различные ID для модели (в порядке приоритета)
  const modelIds = [9048, 22390]; // Ozon attribute IDs для модели

  for (const id of modelIds) {
    const value = extractAttribute(item, id);
    if (value) {
      return value;
    }
  }

  // Атрибут не найден - возвращаем пустую строку
  return "";
}

/**
 * Тестовая функция для проверки извлечения брендов и моделей
 */
function testBrandExtraction() {
  const sheet = mainSheet();
  const lastRow = Math.min(sheet.getLastRow(), 10); // Тестируем на первых 10 строках

  // Используем offer_id (артикул) из колонки A
  const offerIds = sheet.getRange(2, 1, lastRow - 1).getValues().flat(); // Колонка A
  const validIds = offerIds.filter(id => id);

  Logger.log(`🧪 Тестирование на ${validIds.length} товарах (используем offer_id)`);
  Logger.log(`📋 Offer IDs для запроса: ${JSON.stringify(validIds)}`);
  Logger.log("════════════════════════════════════════");

  // Используем v4 API с attributes - там есть бренд и модель
  const payload = {
    filter: {
      offer_id: validIds
    },
    limit: validIds.length
  };

  Logger.log(`📤 Payload: ${JSON.stringify(payload)}`);

  const options = {
    method: "post",
    contentType: "application/json",
    headers: ozonHeaders(),
    payload: JSON.stringify(payload)
  };

  const response = retryFetch('https://api-seller.ozon.ru/v4/product/info/attributes', options);
  const data = JSON.parse(response.getContentText());

  const items = data.result || [];  // v4 API возвращает result, не items

  let withModel = 0;
  let withoutModel = 0;

  items.forEach(item => {
    const brand = extractBrand(item) || "—";
    const model = extractModelAttribute(item);

    Logger.log(`📦 ${item.name}`);
    Logger.log(`   Бренд: ${brand}`);
    Logger.log(`   Модель: ${model || "(не задано)"}`);

    if (model) {
      withModel++;
    } else {
      withoutModel++;
    }
    Logger.log('---');
  });

  Logger.log("════════════════════════════════════════");
  Logger.log(`📊 Статистика:`);
  Logger.log(`   С моделью: ${withModel}`);
  Logger.log(`   Без модели: ${withoutModel}`);
  Logger.log(`   % заполненности: ${(withModel / items.length * 100).toFixed(1)}%`);
}

