function updatePricesAndImages() {
  const sheet = mainSheet();
  const priceColumn = columnByHeader_(sheet, "ЦЕНА ВБ");

  const limit = 1000;
  const state = wbMainState_("prices", { offset: 0, goods: null, itemIndex: 0 });
  let offset = state.offset;
  let moreData = true;

  // Считаем, какие артикулы уже есть (vendorCode в столбце A)
  const lastRow = sheet.getLastRow();
  let existingVendorCodes = [];
  let existingPrices = [];
  if (lastRow >= 2) {
    existingVendorCodes = sheet.getRange(2, 1, lastRow - 1).getValues().flat();
    existingPrices = sheet.getRange(2, priceColumn, lastRow - 1).getValues().flat(); // M (13): ЦЕНА ВБ
  }

  // Создаем словарь: vendorCode → массив номеров строк
  // vendorCode → { rows: [], prices: [] }
  const vendorCodeToRows = {};
  existingVendorCodes.forEach((code, i) => {
    const id = code ? code.toString().trim() : "";
    if (id) {
      if (!vendorCodeToRows[id]) {
        vendorCodeToRows[id] = { rows: [], prices: [] };
      }
      vendorCodeToRows[id].rows.push(i + 2);   // sheet row number (+2 for header)
      vendorCodeToRows[id].prices.push(existingPrices[i]);
    }
  });

  let lastRequestTime = Date.now() - 1000 / WB_RPS();

  // Итерации

  let updatedCount = 0;
  let existingPricesChanged = false;
  while (moreData) {
    wbMainCheckBudget_();
    lastRequestTime = rateLimitRPS(lastRequestTime, WB_RPS());

    const url = `https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter?limit=${limit}&offset=${offset}`;
    const options = {
      method: "get",
      headers: wbHeaders(),
    };

    let response;
    response = state.goods ? null : wbMainFetch_(url, options);

    if (!response && !state.goods) {
      Logger.log(`❌ Не удалось получить цены WB (offset: ${offset})`);
      moreData = false;
      break;
    }

    const data = state.goods ? { data: { listGoods: state.goods } } : JSON.parse(response.getContentText());
    if (!data || !data.data || !Array.isArray(data.data.listGoods)) {
      throw new Error("WB цены: ответ не содержит data.listGoods; страница не завершена.");
    }
    if (data.data.listGoods.length === 0) {
      moreData = false;
      break;
    }
    
    const listGoods = data.data.listGoods;
    state.goods = listGoods;

    for (let itemIndex = state.itemIndex; itemIndex < listGoods.length; itemIndex++) {
      if (wbMainContext_ && Date.now() > wbMainContext_.deadline - 60000) {
        if (existingPricesChanged) {
          sheet.getRange(2, priceColumn, existingPrices.length, 1).setValues(existingPrices.map(price => [price]));
        }
        wbMainPause_("Цены WB: продолжение страницы");
      }
      const item = listGoods[itemIndex];
      const vendorCode = item.vendorCode;
      const sizes = item.sizes || [];
      const price = sizes.length > 0 ? sizes[0].price : null;
      if (!vendorCode || price === null) { state.itemIndex = itemIndex + 1; continue; }

      if (vendorCodeToRows[vendorCode]) {
        // Compare before updating
        vendorCodeToRows[vendorCode].rows.forEach((row, idx) => {
          const oldPrice = vendorCodeToRows[vendorCode].prices[idx];
          if (oldPrice !== price) {
            existingPrices[row - 2] = price;
            vendorCodeToRows[vendorCode].prices[idx] = price; // sync in memory
            existingPricesChanged = true;
            updatedCount++;
          }
        });
      } else {
        // Add new row
        const newRow = addAndFormatRow(sheet, 1, vendorCode); // A: vendorCode
        sheet.getRange(newRow, priceColumn).setValue(price);           // M (13): ЦЕНА ВБ
        vendorCodeToRows[vendorCode] = { rows: [newRow], prices: [price] };
        updatedCount++;
      }
      state.itemIndex = itemIndex + 1;
    }

    // Фиксируем только полностью обработанную страницу до продвижения offset.
    if (existingPricesChanged) {
      sheet.getRange(2, priceColumn, existingPrices.length, 1).setValues(existingPrices.map(price => [price]));
      existingPricesChanged = false;
    }
    state.goods = null;
    state.itemIndex = 0;
    if (listGoods.length < limit) {
      moreData = false;
    } else {
      offset += limit;
      state.offset = offset;
    }
  };

  if (existingPricesChanged) {
    sheet.getRange(2, priceColumn, existingPrices.length, 1)
      .setValues(existingPrices.map(price => [price]));
  }

  Logger.log(`Обновлено цен: ${updatedCount}`);
}
