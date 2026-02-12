function updateStockFBO() {
  const sheet = mainSheet();

  const lastRow = sheet.getLastRow();
  // ИСПРАВЛЕНО: читаем product_id из U (21), а не из R (18)
  const fullProductIds = sheet.getRange(2, 21, lastRow - 1).getValues().flat();

  Logger.log("=== ОБНОВЛЕНИЕ FBO (F, 6) ===");
  Logger.log("Всего product_id: " + fullProductIds.filter(id => id).length);

  // Фильтруем валидные product_id: должны быть > 0
  const fullProductIdsFull = fullProductIds
    .filter(id => id !== '' && id !== null && id !== undefined && id > 0);

  const batchSize = 1000;

  // Общий словарь для всех батчей
  const stockMap = {};

  let lastRequestTime = Date.now() - 1000 / RPS();

  // Итерации
  for (let i = 0; i < fullProductIdsFull.length; i += batchSize) {
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

    const batch = fullProductIdsFull.slice(i, i + batchSize);

    // Пропускаем если batch пустой
    if (batch.length === 0) continue;

    const payload = {
      filter: {
        product_id: batch
      },
      limit: batch.length
    };

    const options = {
      method: 'post',
      contentType: 'application/json',
      headers: ozonHeaders(),
      payload: JSON.stringify(payload)
    };

    const response = retryFetch(ozonStocksApiURL(), options);

    if (!response) {
      Logger.log(`❌ Не удалось получить остатки FBO для батча`);
      continue;
    }

    const json = JSON.parse(response.getContentText());
    const items = json.items || [];

    for (const item of items) {
      const pid = item.product_id;
      // ИЩЕМ ВСЕ FBO записи и суммируем (могут быть дубликаты)
      const fboStocks = item.stocks?.filter(s => s.type === 'fbo') || [];
      const totalFbo = fboStocks.reduce((sum, s) => sum + (s.present || 0), 0);
      if (pid) stockMap[pid] = totalFbo;

      // ЛОГИРОВАНИЕ ДЛЯ ДИАГНОСТИКИ
      if (pid === 109652992) {
        Logger.log("22068-1 (product_id: " + pid + "):");
        Logger.log("  FBO остаток: " + totalFbo);
      }
    }
  }

  const count = Object.keys(stockMap).length;
  Logger.log(`Всего ключей ${count}`);

  // Исправляем: используем fullProductIdsFull (отфильтрованную версию)
  for (const product of fullProductIdsFull) {
    if (product && !(product in stockMap)) {
      Logger.log(`Озон - Нет данных по продукту: ${product}`);
    }
  }

  Logger.log(`Найдено информации о продуктах: ${fullProductIdsFull.length}`);

  // Подготовим значения - ИСПРАВЛЕНО: пишем для ВСЕХ строк, не только отфильтрованных
  const valuesToWrite = fullProductIds.map(pid => {
    const key = pid?.toString();
    // Проверяем: ключ есть в stockMap И product_id валидный
    if (key && key !== "" && pid !== '' && pid !== null && pid !== undefined && pid > 0) {
      return [stockMap[key] ?? ''];
    }
    return [''];
  });

  // Запись в столбец F (номер 6) - Остаток ФБО ОЗОН
  // ИСПРАВЛЕНО: пишем для всех строк из fullProductIds
  sheet.getRange(2, 6, valuesToWrite.length, 1).setValues(valuesToWrite);

  // ДИАГНОСТИКА для 22068-1
  const testProductId = 109652992; // product_id для 22068-1
  if (stockMap[testProductId]) {
    Logger.log("");
    Logger.log(`=== ДИАГНОСТИКА 22068-1 (product_id: ${testProductId}) ===`);
    Logger.log(`   Остаток ФБО ОЗОН: ${stockMap[testProductId]} (ожидается 1069)`);
    Logger.log(`${stockMap[testProductId] >= 1000 && stockMap[testProductId] <= 1100 ? '✅' : '⚠️'} Проверка данных`);
  }

  Logger.log("Остатки FBO обновлены.");

  // ИСПРАВЛЕНО: Также обновляем G (7) - суммируем ВСЕ FBS остатки
  updateAllFBSStocks();
}

/**
 * ИСПРАВЛЕНИЕ: Обновляет G (7) - сумму ВСЕХ FBS складов
 * Не только конкретного склада Москва
 */
function updateAllFBSStocks() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) return;

  // Читаем product_id из U (21)
  const fullProductIds = sheet.getRange(2, 21, lastRow - 1).getValues().flat();
  const validProductIds = fullProductIds
    .filter(id => id !== '' && id !== null && id !== undefined && id > 0);

  const batchSize = 1000;
  const fbsMap = {};
  let lastRequestTime = Date.now() - 1000 / RPS();

  // Получаем данные из v4/product/info/stocks (тот же что для FBO)
  for (let i = 0; i < validProductIds.length; i += batchSize) {
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

    const batch = validProductIds.slice(i, i + batchSize);
    if (batch.length === 0) continue;

    const payload = {
      filter: { product_id: batch },
      limit: batch.length
    };

    const options = {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify(payload)
    };

    try {
      const response = retryFetch(ozonStocksApiURL(), options);
      const json = JSON.parse(response.getContentText());
      const items = json.items || [];

      items.forEach(item => {
        const pid = item.product_id;
        // СУММИРУЕМ ВСЕ FBS остатки (не только по конкретному складу)
        const fbsStocks = item.stocks?.filter(s => s.type === 'fbs') || [];
        const totalFbs = fbsStocks.reduce((sum, s) => sum + (s.present || 0), 0);
        if (pid) fbsMap[pid] = totalFbs;
      });
    } catch (e) {
      Logger.log("Ошибка при получении FBS: " + e.message);
    }
  }

  // Записываем в G (7) - ИСПРАВЛЕНО: пишем для ВСЕХ строк
  const valuesToWrite = fullProductIds.map(pid => {
    const key = pid?.toString();
    // Проверяем: ключ есть в fbsMap И product_id валидный
    if (key && key !== "" && pid !== '' && pid !== null && pid !== undefined && pid > 0) {
      return [fbsMap[key] ?? 0];
    }
    return [0];
  });

  sheet.getRange(2, 7, valuesToWrite.length, 1).setValues(valuesToWrite);
  Logger.log("Остатки FBS (G, 7) обновлены - сумма всех FBS складов.");
}