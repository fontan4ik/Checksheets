/**
 * Записывает индекс цен Ozon по каждому артикулу в колонку BK.
 *
 * API: /v5/product/info/prices
 * Вход: offer_id из колонки A.
 * Выход: price_indexes.color_index.
 * Запись: BK (63) — "Индекс".
 */

const OZON_PRICE_INDEX_OFFER_ID_COLUMN = 1; // A
const OZON_PRICE_INDEX_COLUMN = 63; // BK
const OZON_PRICE_INDEX_BATCH_SIZE = 1000;

function updateOzonPriceIndexBK() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log("Нет строк для записи индекса Ozon");
    return;
  }

  const offerValues = sheet
    .getRange(2, OZON_PRICE_INDEX_OFFER_ID_COLUMN, lastRow - 1, 1)
    .getValues()
    .map(function(row) {
      return String(row[0] || "").trim();
    });

  const offerIds = [];
  const seen = {};

  offerValues.forEach(function(offerId) {
    if (offerId && !seen[offerId]) {
      seen[offerId] = true;
      offerIds.push(offerId);
    }
  });

  if (!offerIds.length) {
    sheet.getRange(1, OZON_PRICE_INDEX_COLUMN).setValue("Индекс");
    sheet.getRange(2, OZON_PRICE_INDEX_COLUMN, offerValues.length, 1).setValue("без индекса");
    Logger.log("В колонке A нет артикулов Ozon");
    return;
  }

  Logger.log("=== Ozon индекс цен поартикульно ===");
  Logger.log("Артикулов к проверке: " + offerIds.length);

  const indexMap = fetchOzonPriceIndexByOfferId_(offerIds);
  const valuesToWrite = offerValues.map(function(offerId) {
    return [offerId && indexMap[offerId] ? indexMap[offerId] : "без индекса"];
  });

  sheet.getRange(1, OZON_PRICE_INDEX_COLUMN).setValue("Индекс");
  sheet.getRange(2, OZON_PRICE_INDEX_COLUMN, valuesToWrite.length, 1).setValues(valuesToWrite);

  const filledCount = valuesToWrite.filter(function(row) {
    return row[0] !== "без индекса";
  }).length;

  Logger.log("Индекс Ozon записан в BK. С индексом: " + filledCount + ", без индекса: " + (valuesToWrite.length - filledCount));
}

function fetchOzonPriceIndexByOfferId_(offerIds) {
  const result = {};
  let lastRequestTime = Date.now() - 1000 / RPS();

  for (let i = 0; i < offerIds.length; i += OZON_PRICE_INDEX_BATCH_SIZE) {
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

    const chunk = offerIds.slice(i, i + OZON_PRICE_INDEX_BATCH_SIZE);
    const payload = {
      filter: {
        offer_id: chunk,
        visibility: "ALL"
      },
      limit: chunk.length
    };

    const options = {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    };

    const response = retryFetch(ozonPricesApiURL(), options);

    if (!response) {
      Logger.log("Не удалось получить индексы Ozon для батча " + (Math.floor(i / OZON_PRICE_INDEX_BATCH_SIZE) + 1));
      continue;
    }

    const responseCode = response.getResponseCode();
    const text = response.getContentText();

    if (responseCode < 200 || responseCode >= 300) {
      Logger.log("Ошибка Ozon product/info/prices: HTTP " + responseCode + " " + text);
      continue;
    }

    const data = JSON.parse(text);
    const items = data.items || (data.result && data.result.items) || [];

    items.forEach(function(item) {
      const offerId = String(item.offer_id || "").trim();
      if (!offerId) return;

      result[offerId] = normalizeOzonPriceIndex_(item);
    });

    Logger.log("Обработано " + Math.min(i + OZON_PRICE_INDEX_BATCH_SIZE, offerIds.length) + "/" + offerIds.length + " артикулов");
  }

  return result;
}

function normalizeOzonPriceIndex_(item) {
  const colorIndex = String(
    (item.price_indexes && item.price_indexes.color_index) ||
    item.price_index ||
    ""
  ).toUpperCase();

  const labels = {
    SUPER: "супервыгодный",
    SUPER_GREEN: "супервыгодный",
    GREEN: "выгодный",
    YELLOW: "умеренный",
    RED: "невыгодный",
    WITHOUT_INDEX: "без индекса",
    NO_INDEX: "без индекса"
  };

  return labels[colorIndex] || "без индекса";
}
