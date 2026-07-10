function updateSkuByProductId() {
  const sheet = mainSheet();
  const startRow = 2; // с какой строки начинаем читать product_id
  // ИСПРАВЛЕНО: читаем product_id из U (21), а не из R (18)
  const productIdColumn = 21; // столбец U (21-й) = Product_id Ozon
  const skuColumn = 19; // столбец S (19-й)

  const lastRow = sheet.getLastRow();
  if (lastRow < startRow) {
    Logger.log("Нет данных для обработки");
    return;
  }

  Logger.log("=== ОБНОВЛЕНИЕ SKU (S, 19) ===");

  // Считываем все product_id из столбца U
  const productIdValues = sheet.getRange(startRow, productIdColumn, lastRow - startRow + 1).getValues();

  // ДИАГНОСТИКА: Проверяем текущие значения SKU
  const currentSkuValues = sheet.getRange(startRow, skuColumn, lastRow - startRow + 1).getValues().flat();
  const zeroCount = currentSkuValues.filter(s => s === "0" || s === 0).length;
  const emptyCount = currentSkuValues.filter(s => !s || s === "").length;
  const validCount = currentSkuValues.filter(s => s && s !== "" && s !== "0" && s !== 0).length;

  Logger.log(`Текущее состояние колонки S (19):`);
  Logger.log(`   Всего строк: ${currentSkuValues.length}`);
  Logger.log(`   Пустых: ${emptyCount}`);
  Logger.log(`   Нулей ("0"): ${zeroCount}`);
  Logger.log(`   Валидных SKU: ${validCount}`);
  Logger.log("");

  // Преобразуем в плоский массив строк/чисел, фильтруем пустые и нулевые
  const productIds = productIdValues.flat().filter(id => id !== "" && id != null && id !== undefined && id > 0);

  if (productIds.length === 0) {
    Logger.log("Нет product_id для обработки");
    return;
  }

  Logger.log(`Всего product_id для запроса: ${productIds.length}`);

  const batchSize = 1000; // максимум для запроса

  // Создаем мапу для sku по product_id
  const skuMap = {};

  let lastRequestTime = Date.now() - 1000 / RPS();

  // Итерации
  for (let i = 0; i < productIds.length; i += batchSize) {
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

    const batch = productIds.slice(i, i + batchSize);

    // Тело запроса
    const payload = {
      product_id: batch.map(String) // отправляем как строки
    };

    const options = {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify(payload),
    };

    const response = retryFetch(ozonProductsInfoApiURL(), options);

    if (!response) {
      Logger.log(`❌ Не удалось получить данные для батча product_id (offset: ${i})`);
      continue;
    }

    const data = JSON.parse(response.getContentText());
    const items = data.items || [];

    // Обрабатываем товары
    items.forEach(item => {
      const productId = String(item.id);
      // Берем sku из sources, если есть несколько - берем первый
      let sku = "";
      if (item.sources && item.sources.length > 0) {
        sku = item.sources[0].sku ? String(item.sources[0].sku) : "";
      }
      skuMap[productId] = sku;
    });

    Logger.log(`Обработано ${Math.min(i + batchSize, productIds.length)}/${productIds.length} product_id`);
  }

  // ДИАГНОСТИКА: Проверяем конкретный product_id
  const testProductId = "109652992"; // 22068-1
  const testSku = skuMap[testProductId];
  Logger.log("");
  Logger.log(`=== ДИАГНОСТИКА 22068-1 ===`);
  Logger.log(`product_id: ${testProductId}`);
  if (testSku) {
    Logger.log(`SKU: ${testSku} ✅`);
  } else {
    Logger.log(`SKU: НЕ НАЙДЕН ❌`);
  }
  Logger.log("");

  // Теперь записываем sku обратно в столбец S рядом с product_id
  const skuValues = productIdValues.map(row => {
    const productId = String(row[0]);
    return [skuMap[productId] || ""]; // если sku не найден, оставляем пусто
  });

  // Статистика перед записью
  const foundSkuCount = skuValues.filter(v => v[0] && v[0] !== "").length;
  const emptySkuCount = skuValues.filter(v => !v[0] || v[0] === "").length;

  Logger.log(`Результат получения SKU:`);
  Logger.log(`   Найдено SKU: ${foundSkuCount}`);
  Logger.log(`   Не найдено SKU: ${emptySkuCount}`);
  Logger.log("");

  sheet.getRange(startRow, skuColumn, skuValues.length, 1).setValues(skuValues);

  Logger.log("✅ Обновление sku завершено");
}
