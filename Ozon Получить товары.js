function syncOfferIdWithProductId() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) return; // nothing to process

  // Read existing data into memory
  const offerIds = sheet.getRange(2, 1, lastRow - 1).getValues().flat(); // column A
  const productIds = sheet.getRange(2, 21, lastRow - 1).getValues().flat(); // column U (21) - Product_id Ozon

  // Map offerId -> row index in the sheet
  const offerMap = new Map();
  const sheetData = [];
  offerIds.forEach((id, index) => {
    const trimmedId = id.toString().trim();
    if (trimmedId) {
      offerMap.set(trimmedId, index); // 0-based index in sheetData
      sheetData.push({ offerId: trimmedId, productId: productIds[index] || "" });
    } else {
      sheetData.push({ offerId: "", productId: productIds[index] || "" });
    }
  });

  const limit = 1000;
  let last_id = "";
  let processedCount = 0;
  let lastRequestTime = Date.now() - 1000 / RPS();

  const newRowsToAdd = []; // store new rows to add at the end

  while (true) {
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

    const payload = { filter: {}, limit: limit, last_id: last_id };
    const options = {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify(payload),
    };

    const response = retryFetch(ozonProductsApiURL(), options);

    if (!response) {
      Logger.log(`❌ Не удалось получить данные с Ozon API (last_id: ${last_id})`);
      break;
    }

    const json = JSON.parse(response.getContentText());
    const items = json?.result?.items || [];

    if (!items.length) break;

    items.forEach(product => {
      const offerId = (product.offer_id || "").trim();
      const productId = product.product_id;

      if (!offerId || !productId) return;

      if (offerMap.has(offerId)) {
        // update existing row in memory
        const index = offerMap.get(offerId);
        if (sheetData[index].productId !== productId) {
          sheetData[index].productId = productId;
          processedCount++;
        }
      } else {
        // schedule new row
        newRowsToAdd.push({ offerId, productId });
        processedCount++;
      }
    });

    if (items.length < limit) break;
    last_id = json.result.last_id || "";
  }

  // Write updates back to sheet in batch
  const productColumnRange = sheet.getRange(2, 21, sheetData.length, 1); // U (21): Product_id Ozon
  const updatedProductIds = sheetData.map(row => [row.productId]);
  productColumnRange.setValues(updatedProductIds);

  // Append new rows at the end in batch
  if (newRowsToAdd.length > 0) {
    const startRow = sheet.getLastRow() + 1;
    const newOfferIds = newRowsToAdd.map(row => [row.offerId]);
    const newProductIds = newRowsToAdd.map(row => [row.productId]);

    // Insert new offerIds in column A
    sheet.getRange(startRow, 1, newOfferIds.length, 1).setValues(newOfferIds);
    // Insert corresponding productIds in column U (21)
    sheet.getRange(startRow, 21, newProductIds.length, 1).setValues(newProductIds);
  }

  Logger.log(`Синхронизация завершена. Обработано строк: ${processedCount}`);
}
