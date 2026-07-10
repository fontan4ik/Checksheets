function updatePricesAndImages() {
  const sheet = mainSheet();

  const limit = 1000;
  let offset = 0;
  let moreData = true;

  // Считаем, какие артикулы уже есть (vendorCode в столбце A)
  const lastRow = sheet.getLastRow();
  let existingVendorCodes = [];
  if (lastRow >= 2) {
    existingVendorCodes = sheet.getRange(2, 1, lastRow - 1).getValues().flat();
    existingPrices = sheet.getRange(2, 13, lastRow - 1).getValues().flat();     // M (13): ЦЕНА ВБ
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
  while (moreData) {
    lastRequestTime = rateLimitRPS(lastRequestTime, WB_RPS());

    const url = `https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter?limit=${limit}&offset=${offset}`;
    const options = {
      method: "get",
      headers: wbHeaders(),
    };

    let response;
    response = retryFetch(url, options);

    if (!response) {
      Logger.log(`❌ Не удалось получить цены WB (offset: ${offset})`);
      moreData = false;
      break;
    }

    const data = JSON.parse(response.getContentText());
    if (!data || !data.data || !data.data.listGoods || data.data.listGoods.length === 0) {
      moreData = false;
      break;
    }
    
    const listGoods = data.data.listGoods;

    listGoods.forEach(item => {
      const vendorCode = item.vendorCode;
      const sizes = item.sizes || [];
      const price = sizes.length > 0 ? sizes[0].price : null;
      if (!vendorCode || price === null) return;

      if (vendorCodeToRows[vendorCode]) {
        // Compare before updating
        vendorCodeToRows[vendorCode].rows.forEach((row, idx) => {
          const oldPrice = vendorCodeToRows[vendorCode].prices[idx];
          if (oldPrice !== price) {
            sheet.getRange(row, 13).setValue(price); // M (13): ЦЕНА ВБ
            vendorCodeToRows[vendorCode].prices[idx] = price; // sync in memory
            updatedCount++;
          }
        });
      } else {
        // Add new row
        const newRow = addAndFormatRow(sheet, 1, vendorCode); // A: vendorCode
        sheet.getRange(newRow, 13).setValue(price);           // M (13): ЦЕНА ВБ
        vendorCodeToRows[vendorCode] = { rows: [newRow], prices: [price] };
        updatedCount++;
      }
    });

    if (listGoods.length < limit) {
      moreData = false;
    } else {
      offset += limit;
    }
  };

  Logger.log(`Обновлено цен: ${updatedCount}`);
}