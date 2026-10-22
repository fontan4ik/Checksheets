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

/**
 * Точка входа для уже существующего триггера updateProductsV2.
 * Обновляет поля карточек по артикулам из A. Тот же обработчик используется
 * существующим maintainArticleColumn; A/U обновляет OzonMain/syncOfferIdWithProductId.
 */
function updateProductsV2() {
  return runWithTelegramAlertGAS_("updateProductsV2", updateProductsV2AlertCore_);
}

function updateProductsV2AlertCore_() {
  return runWithOzonProductSyncLock_("updateProductsV2", function() {
    // A/U обновляет отдельный существующий триггер syncOfferIdWithProductId.
    // Повторная полная синхронизация здесь удваивала длительность запуска.
    return updateProductsV2Core_();
  });
}

function updateProductsV2Core_() {
  const startedAt = Date.now();
  const sheet = mainSheet();
  if (sheet.getLastRow() < 2) return { complete: true, processed: 0, nextIndex: 0, total: 0, writeMode: "none" };

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
    // Ozon всегда возвращает offer_id строкой. Нормализация нужна, чтобы
    // числовые артикулы из Sheets совпадали с ключами в resultsMap.
    offerId: row[0] === "" || row[0] === null || row[0] === undefined
      ? ""
      : String(row[0]).trim()
  }));

  const validRows = rowData.filter(r => r.offerId);
  const batchSize = 1000;
  const props = PropertiesService.getScriptProperties();
  const nativeWriteKey = 'OZON_PRODUCTS_V2_NATIVE_WRITE';
  const maxRowsPerSlice = props.getProperty(nativeWriteKey) === '1' ? 4000 : 8000;
  const cursorKey = 'OZON_PRODUCTS_V2_NEXT_OFFER';
  const signatureKey = 'OZON_PRODUCTS_V2_SHEET_SIGNATURE';
  // Appending new catalog rows must not restart an unfinished enrichment pass.
  const scope = sheet.getParent().getId() + ':' + sheet.getSheetId();
  const signature = `${scope}:${validRows[0]?.offerId || ''}`;
  const savedCursor = props.getProperty(signatureKey) === signature ? Number(props.getProperty(cursorKey)) || 0 : 0;
  const startIndex = savedCursor >= 0 && savedCursor < validRows.length ? savedCursor : 0;
  let nextIndex = startIndex;
  const resultsMap = new Map(); // key: offer_id, value: { данные }
  const categoryIdSet = new Set();
  let lastRequestTime = Date.now() - 1000 / RPS();
  let sampleLogged = false;

  Logger.log(`🚀 Выгрузка товаров: ${validRows.length}, продолжение с ${startIndex + 1}`);

  // Первый проход: получаем базовую информацию + атрибуты
  // Используем v4/product/info/attributes - возвращает атрибуты с брендом и моделью
  for (let i = startIndex; i < validRows.length; i += batchSize) {
    if (i > startIndex && (i - startIndex >= maxRowsPerSlice || Date.now() - startedAt >= 2.5 * 60 * 1000)) break;
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

    const batch = validRows.slice(i, i + batchSize);
    const batchIds = batch.map(r => r.offerId);

    const payload = {
      filter: {
        offer_id: batchIds,
        visibility: "ALL"
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
      throw new Error(`Ozon товары: нет ответа для batch ${i}`);
    }

    const responseText = response.getContentText();
    if (!responseText) {
      throw new Error(`Ozon товары: пустой ответ для batch ${i}`);
    }

    const data = JSON.parse(responseText);

    if (!Array.isArray(data.result)) throw new Error(`Ozon товары: нет result для batch ${i}`);

    const items = data.result;
    // Attributes supplies brand/model; v3 supplies SKU and image URLs.
    // v4 does not guarantee either field, so using it alone erased valid SKU/images.
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());
    const infoResponse = retryFetch('https://api-seller.ozon.ru/v3/product/info/list', {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify({ offer_id: batchIds })
    });
    if (!infoResponse) throw new Error(`Ozon товары: нет product/info/list для batch ${i}`);
    const infoData = JSON.parse(infoResponse.getContentText());
    if (!Array.isArray(infoData.items)) throw new Error(`Ozon товары: нет items product/info/list для batch ${i}`);
    const infoMap = new Map(infoData.items.map(item => [String(item.offer_id).trim(), item]));

    items.forEach(item => {
      const offerId = item.offer_id === null || item.offer_id === undefined
        ? ""
        : String(item.offer_id).trim();
      if (!offerId) return;

      const info = infoMap.get(offerId);
      if (!info) throw new Error(`Ozon товары: product/info/list не вернул ${offerId}; пакет будет повторён`);
      const categoryId = item.description_category_id || info.description_category_id || "";
      if (categoryId) categoryIdSet.add(categoryId);

      // Логируем структуру первого товара для диагностики
      if (!sampleLogged) {
        Logger.log(`🔍 Структура ответа (первый товар):`);
        Logger.log(`   - offer_id: ${item.offer_id}`);
        Logger.log(`   - product_id: ${item.product_id}`);
        Logger.log(`   - Name: ${item.name}`);
        Logger.log(`   - Has attributes: ${!!item.attributes}`);
        if (item.attributes) {
          Logger.log(`   - Attributes count: ${item.attributes.length}`);
          Logger.log(`   - First 3 attributes: ${JSON.stringify(item.attributes.slice(0, 3))}`);
        }
        sampleLogged = true;
      }

      // Извлекаем бренд из атрибутов (ID 85 = Бренд)
      const brand = extractBrand(item);

      // Извлекаем название модели для объединения карточек (multiplicity)
      // ВАЖНО: Берем только из атрибутов Ozon. Если нет - оставляем пустым.
      const modelName = extractModelAttribute(item);

      resultsMap.set(offerId, {
        product_id: item.product_id || "",
        sku: info.sku || (info.sources || []).map(source => source.sku).find(Boolean) || "",
        name: info.name || item.name || "",
        description_category_name: "",
        description_category_id: categoryId,
        primary_image: firstOzonImageUrl_(info.primary_image) || firstOzonImageUrl_(info.images) || firstOzonImageUrl_(item.primary_image),
        brand: brand,
        model_name: modelName
      });
    });

    // A card can be available in info/list before attributes becomes available.
    // Populate API metadata now and preserve fields owned by attributes.
    infoMap.forEach((info, offerId) => {
      if (resultsMap.has(offerId)) return;
      resultsMap.set(offerId, {
        sku: info.sku || (info.sources || []).map(source => source.sku).find(Boolean) || "",
        primary_image: firstOzonImageUrl_(info.primary_image) || firstOzonImageUrl_(info.images),
        preserveAttributeFields: true
      });
    });

    Logger.log(`✅ Обработано ${Math.min(i + batchSize, validRows.length)}/${validRows.length} товаров`);
    nextIndex = i + batch.length;
  }

  if (nextIndex === startIndex) return { complete: validRows.length === 0, processed: 0, nextIndex: nextIndex, total: validRows.length, writeMode: "none" };
  const processedRows = validRows.slice(startIndex, nextIndex);
  const firstRow = processedRows[0].rowIndex;
  const lastRow = processedRows[processedRows.length - 1].rowIndex;
  const targetRows = rowData.slice(firstRow - 2, lastRow - 1);

  // Получаем дерево категорий
  const categoryTreeOptions = {
    method: "post",
    contentType: "application/json",
    headers: ozonHeaders(),
    payload: JSON.stringify({})
  };

  const treeResponse = retryFetch('https://api-seller.ozon.ru/v1/description-category/tree', categoryTreeOptions);

  if (!treeResponse) {
    throw new Error('Ozon товары: не удалось получить дерево категорий');
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
  if (!Array.isArray(treeData.result)) throw new Error('Ozon товары: дерево категорий имеет неверный формат');
  traverseTree(treeData.result);

  // Обновляем названия категорий
  for (const [_, data] of resultsMap.entries()) {
    const name = categoryNameMap.get(data.description_category_id);
    if (name) {
      data.description_category_name = name;
    }
  }

  // Записываем данные пакетами. Смежные колонки объединяем, чтобы сократить
  // количество обращений к Spreadsheet Service и не упираться в таймаут.
  const valuesByKey = {};
  for (const [colLetter, key] of Object.entries(columnKeyMap)) {
    valuesByKey[key] = targetRows.map(r => {
      const result = resultsMap.get(r.offerId);
      return result
        ? key === "primary_image"
          ? result[key] ? `=IMAGE("${String(result[key]).replace(/"/g, '""')}")` : ""
          : result[key] || ""
        : "";
    });
  }

  const missingOfferIds = [...new Set(processedRows.map(r => r.offerId))]
    .filter(offerId => !resultsMap.has(offerId));
  if (missingOfferIds.length > 0) {
    Logger.log(`⚠️ Ozon не вернул данные для ${missingOfferIds.length} артикулов. Старые значения этих строк будут сохранены.`);
    Logger.log(`⚠️ Первые отсутствующие артикулы: ${missingOfferIds.slice(0, 20).join(", ")}`);
  }

  const writeColumns = {
    C: "Бренд", D: "Связка", E: "Картинка",
    V: "SKU Ozon", X: "Название модели", Y: "Категория товара"
  };

  const pendingWrites = [];
  for (const [colLetter, header] of Object.entries(writeColumns)) {
    const resolvedColumn = columnByHeader_(sheet, header);
    const range = sheet.getRange(firstRow, resolvedColumn, targetRows.length, 1);
    const existingValues = range.getValues();
    const existingFormulas = range.getFormulas();
    const formulaFlags = [];
    const values = targetRows.map((row, rowIndex) => {
      if (!row.offerId) return [""];
      const result = resultsMap.get(row.offerId);
      if (!result || (result.preserveAttributeFields && !["V", "E"].includes(colLetter))) {
        formulaFlags[rowIndex] = Boolean(existingFormulas[rowIndex][0]);
        return [existingFormulas[rowIndex][0] || existingValues[rowIndex][0]];
      }
      formulaFlags[rowIndex] = colLetter === "E" && Boolean(result.primary_image);
      return [valuesByKey[columnKeyMap[colLetter]][rowIndex]];
    });
    pendingWrites.push({ range: range, column: resolvedColumn, values: values, formulaFlags: formulaFlags });
    const key = columnKeyMap[colLetter];
    Logger.log(`📝 Колонка ${header} (${resolvedColumn}): ${key} - обновлено ${valuesByKey[key].filter(Boolean).length} строк`);
  }
  const writeMode = writeOzonProductColumns_(sheet, firstRow, pendingWrites);
  if (nextIndex < validRows.length) {
    props.setProperty(signatureKey, signature);
    props.setProperty(cursorKey, String(nextIndex));
    Logger.log(`Товары Ozon: продолжим со SKU ${nextIndex + 1}/${validRows.length} при следующем штатном запуске`);
  } else {
    props.deleteProperty(signatureKey);
    props.deleteProperty(cursorKey);
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
  return { complete: nextIndex >= validRows.length, processed: nextIndex - startIndex, nextIndex: nextIndex, total: validRows.length, writeMode: writeMode };
}

/** Prepare all ranges before writing, then submit one Sheets transaction. */
function writeOzonProductColumns_(sheet, firstRow, pendingWrites) {
  if (typeof ScriptApp !== "undefined" && typeof ScriptApp.getOAuthToken === "function" &&
      typeof UrlFetchApp !== "undefined" && typeof UrlFetchApp.fetch === "function") {
    const sheetName = "'" + sheet.getName().replace(/'/g, "''") + "'";
    const data = pendingWrites.map(write => {
      let column = write.column, letters = "";
      while (column > 0) {
        column--;
        letters = String.fromCharCode(65 + column % 26) + letters;
        column = Math.floor(column / 26);
      }
      return {
        range: sheetName + "!" + letters + firstRow + ":" + letters + (firstRow + write.values.length - 1),
        majorDimension: "ROWS",
        // USER_ENTERED evaluates only known formulas. Every text literal gets
        // an apostrophe so numeric strings, leading zeros and '=' stay text.
        values: write.values.map((row, index) => row.map(value =>
          typeof value === "string" && value !== "" && !write.formulaFlags[index] ? "'" + value : value))
      };
    });
    const response = UrlFetchApp.fetch(
      "https://sheets.googleapis.com/v4/spreadsheets/" + encodeURIComponent(sheet.getParent().getId()) + "/values:batchUpdate",
      {
        method: "post", contentType: "application/json",
        headers: { Authorization: "Bearer " + ScriptApp.getOAuthToken() },
        payload: JSON.stringify({ valueInputOption: "USER_ENTERED", data: data }),
        muteHttpExceptions: true
      }
    );
    const code = response.getResponseCode();
    if (code >= 200 && code < 300) {
      PropertiesService.getScriptProperties().deleteProperty('OZON_PRODUCTS_V2_NATIVE_WRITE');
      Logger.log("Ozon товары: все колонки записаны одним Sheets values:batchUpdate.");
      return "rest";
    }
    if (code !== 403 && code !== 404) {
      // An uncertain or failed remote write must never cause native partial
      // writes or checkpoint advancement; retry the same slice next time.
      throw new Error("Ozon товары: Sheets values:batchUpdate HTTP " + code);
    }
    // Save before native writes: a hard timeout must leave the next slice
    // with a smaller write budget, while still probing REST for recovery.
    PropertiesService.getScriptProperties().setProperty('OZON_PRODUCTS_V2_NATIVE_WRITE', '1');
    Logger.log("Ozon товары: Sheets API недоступен HTTP " + code + "; native fallback.");
  } else {
    Logger.log("Ozon товары: Sheets REST недоступен; native fallback.");
  }
  pendingWrites.forEach(write => write.range.setValues(write.values));
  return "native";
}

function firstOzonImageUrl_(value) {
  if (Array.isArray(value)) return value.find(url => typeof url === "string" && url.trim()) || "";
  return typeof value === "string" ? value : "";
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
