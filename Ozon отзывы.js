/**
 * Считает количество отзывов Ozon по каждому SKU и записывает в колонку BL.
 *
 * API: /v2/review/list
 * Вход: SKU Ozon из колонки V.
 * Выход: количество отзывов по SKU.
 * Запись: BL (64) — "Отзывы".
 *
 * Скрипт читает общий список отзывов один раз и считает только SKU из таблицы.
 * Если не успевает за один запуск, сохраняет прогресс в Script Properties
 * чанками и автоматически продолжает через time-based trigger.
 */

const OZON_REVIEW_COUNT_SKU_COLUMN = 22; // V
const OZON_REVIEW_COUNT_COLUMN = 64; // BL
const OZON_REVIEW_LIST_LIMIT = 100;
const OZON_REVIEW_COUNT_MAX_RUN_MS = 5 * 60 * 1000;
const OZON_REVIEW_COUNT_TRIGGER_DELAY_MS = 60 * 1000;
const OZON_REVIEW_COUNT_STATE_KEY = "OZON_REVIEW_COUNT_STATE";
const OZON_REVIEW_COUNT_MAP_CHUNK_PREFIX = "OZON_REVIEW_COUNT_MAP_CHUNK_";
const OZON_REVIEW_COUNT_MAP_CHUNK_COUNT_KEY = "OZON_REVIEW_COUNT_MAP_CHUNK_COUNT";
const OZON_REVIEW_COUNT_MAP_CHUNK_SIZE = 8000;
const OZON_REVIEW_COUNT_TRIGGER_HANDLER = "resumeOzonReviewCountBL";
const OZON_REVIEW_COUNT_OLD_TEMP_SHEET = "_ozon_review_counts_tmp";

function ozonReviewListURL() {
  return "https://api-seller.ozon.ru/v2/review/list";
}

function updateOzonReviewCountBL() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();

  deleteOzonReviewCountTriggers_();
  deleteOzonReviewCountState_();
  cleanupOzonReviewCountOldTempSheet_();

  if (lastRow < 2) {
    Logger.log("Нет строк для записи количества отзывов Ozon");
    return;
  }

  const skuValues = getOzonReviewSheetSkus_(sheet, lastRow);
  const uniqueSkus = getUniqueOzonReviewSkus_(skuValues);

  sheet.getRange(1, OZON_REVIEW_COUNT_COLUMN).setValue("Отзывы");

  if (!uniqueSkus.length) {
    sheet.getRange(2, OZON_REVIEW_COUNT_COLUMN, skuValues.length, 1).setValue(0);
    Logger.log("В колонке V нет SKU Ozon");
    return;
  }

  const countMap = {};
  uniqueSkus.forEach(function(sku) {
    countMap[sku] = 0;
  });

  saveOzonReviewCountMap_(countMap);
  saveOzonReviewCountState_({
    last_id: "",
    pages: 0,
    reviews: 0
  });

  Logger.log("=== Ozon количество отзывов по SKU ===");
  Logger.log("SKU в таблице: " + uniqueSkus.length);
  Logger.log("Старт общего прохода по отзывам");

  processOzonReviewCountPages_();
}

function resumeOzonReviewCountBL() {
  processOzonReviewCountPages_();
}

function processOzonReviewCountPages_() {
  const startedAt = Date.now();
  const state = getOzonReviewCountState_();

  if (!state) {
    Logger.log("Нет сохраненного состояния подсчета отзывов. Запустите updateOzonReviewCountBL()");
    return;
  }

  const countMap = loadOzonReviewCountMap_();
  let lastRequestTime = Date.now() - 1000 / RPS();

  while (Date.now() - startedAt < OZON_REVIEW_COUNT_MAX_RUN_MS) {
    lastRequestTime = rateLimitRPS(lastRequestTime, RPS());

    const payload = {
      filters: {},
      last_id: state.last_id || "",
      limit: OZON_REVIEW_LIST_LIMIT,
      sort_dir: "ASC"
    };

    const options = {
      method: "post",
      contentType: "application/json",
      headers: ozonHeaders(),
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    };

    const response = retryFetch(ozonReviewListURL(), options);

    if (!response) {
      saveOzonReviewCountMap_(countMap);
      saveOzonReviewCountState_(state);
      scheduleOzonReviewCountResume_();
      Logger.log("Ozon review/list не ответил. Прогресс сохранен, продолжение запланировано");
      return;
    }

    const responseCode = response.getResponseCode();
    const text = response.getContentText();

    if (responseCode < 200 || responseCode >= 300) {
      saveOzonReviewCountMap_(countMap);
      saveOzonReviewCountState_(state);
      Logger.log("Ошибка Ozon review/list: HTTP " + responseCode + " " + text);
      return;
    }

    const data = JSON.parse(text);
    const reviews = data.reviews || [];

    reviews.forEach(function(review) {
      const sku = normalizeOzonReviewSku_(review.sku);
      if (sku && countMap[sku] !== undefined) {
        countMap[sku]++;
      }
    });

    state.pages++;
    state.reviews += reviews.length;
    state.last_id = data.last_id || "";

    if (!data.has_next || !state.last_id || !reviews.length) {
      saveOzonReviewCountMap_(countMap);
      finishOzonReviewCount_();
      return;
    }

    if (state.pages % 50 === 0) {
      Logger.log("Страниц отзывов обработано: " + state.pages + ", отзывов просмотрено: " + state.reviews);
    }
  }

  saveOzonReviewCountMap_(countMap);
  saveOzonReviewCountState_(state);
  scheduleOzonReviewCountResume_();

  Logger.log("Достигнут лимит времени. Прогресс сохранен: страниц " + state.pages + ", отзывов " + state.reviews);
}

function finishOzonReviewCount_() {
  const sheet = mainSheet();
  const lastRow = sheet.getLastRow();
  const skuValues = getOzonReviewSheetSkus_(sheet, lastRow);
  const countMap = loadOzonReviewCountMap_();

  const valuesToWrite = skuValues.map(function(sku) {
    return [sku ? (countMap[sku] || 0) : ""];
  });

  sheet.getRange(1, OZON_REVIEW_COUNT_COLUMN).setValue("Отзывы");
  sheet.getRange(2, OZON_REVIEW_COUNT_COLUMN, valuesToWrite.length, 1).setValues(valuesToWrite);

  const totalReviews = valuesToWrite.reduce(function(sum, row) {
    return sum + (Number(row[0]) || 0);
  }, 0);

  deleteOzonReviewCountTriggers_();
  deleteOzonReviewCountState_();

  Logger.log("Отзывы Ozon записаны в BL. Всего по строкам: " + totalReviews);
}

function getOzonReviewSheetSkus_(sheet, lastRow) {
  return sheet
    .getRange(2, OZON_REVIEW_COUNT_SKU_COLUMN, lastRow - 1, 1)
    .getValues()
    .map(function(row) {
      return normalizeOzonReviewSku_(row[0]);
    });
}

function getUniqueOzonReviewSkus_(skuValues) {
  const skus = [];
  const seen = {};

  skuValues.forEach(function(sku) {
    if (sku && !seen[sku]) {
      seen[sku] = true;
      skus.push(sku);
    }
  });

  return skus;
}

function saveOzonReviewCountMap_(countMap) {
  clearOzonReviewCountMap_();

  const props = PropertiesService.getScriptProperties();
  const raw = JSON.stringify(countMap || {});
  const chunks = [];

  for (let offset = 0; offset < raw.length; offset += OZON_REVIEW_COUNT_MAP_CHUNK_SIZE) {
    chunks.push(raw.slice(offset, offset + OZON_REVIEW_COUNT_MAP_CHUNK_SIZE));
  }

  chunks.forEach(function(chunk, index) {
    props.setProperty(OZON_REVIEW_COUNT_MAP_CHUNK_PREFIX + index, chunk);
  });

  props.setProperty(OZON_REVIEW_COUNT_MAP_CHUNK_COUNT_KEY, String(chunks.length));
  Logger.log("Карта отзывов сохранена в свойства: chunks " + chunks.length + ", chars " + raw.length);
}

function loadOzonReviewCountMap_() {
  const props = PropertiesService.getScriptProperties();
  const count = Number(props.getProperty(OZON_REVIEW_COUNT_MAP_CHUNK_COUNT_KEY)) || 0;
  let raw = "";

  for (let i = 0; i < count; i++) {
    raw += props.getProperty(OZON_REVIEW_COUNT_MAP_CHUNK_PREFIX + i) || "";
  }

  return raw ? JSON.parse(raw) : {};
}

function clearOzonReviewCountMap_() {
  const props = PropertiesService.getScriptProperties();
  const count = Number(props.getProperty(OZON_REVIEW_COUNT_MAP_CHUNK_COUNT_KEY)) || 0;

  for (let i = 0; i < count; i++) {
    props.deleteProperty(OZON_REVIEW_COUNT_MAP_CHUNK_PREFIX + i);
  }

  props.deleteProperty(OZON_REVIEW_COUNT_MAP_CHUNK_COUNT_KEY);
}

function saveOzonReviewCountState_(state) {
  PropertiesService
    .getScriptProperties()
    .setProperty(OZON_REVIEW_COUNT_STATE_KEY, JSON.stringify(state));
}

function getOzonReviewCountState_() {
  const raw = PropertiesService.getScriptProperties().getProperty(OZON_REVIEW_COUNT_STATE_KEY);
  return raw ? JSON.parse(raw) : null;
}

function deleteOzonReviewCountState_() {
  PropertiesService.getScriptProperties().deleteProperty(OZON_REVIEW_COUNT_STATE_KEY);
  clearOzonReviewCountMap_();
}

function scheduleOzonReviewCountResume_() {
  deleteOzonReviewCountTriggers_();

  ScriptApp
    .newTrigger(OZON_REVIEW_COUNT_TRIGGER_HANDLER)
    .timeBased()
    .after(OZON_REVIEW_COUNT_TRIGGER_DELAY_MS)
    .create();
}

function deleteOzonReviewCountTriggers_() {
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (trigger.getHandlerFunction() === OZON_REVIEW_COUNT_TRIGGER_HANDLER) {
      ScriptApp.deleteTrigger(trigger);
    }
  });
}

function cleanupOzonReviewCountOldTempSheet_() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const tempSheet = spreadsheet.getSheetByName(OZON_REVIEW_COUNT_OLD_TEMP_SHEET);

  if (tempSheet && spreadsheet.getSheets().length > 1) {
    spreadsheet.deleteSheet(tempSheet);
    Logger.log("Удален старый временный лист " + OZON_REVIEW_COUNT_OLD_TEMP_SHEET);
  }
}

function normalizeOzonReviewSku_(value) {
  const sku = String(value || "").trim();
  if (!sku || sku === "0" || isNaN(Number(sku))) {
    return "";
  }

  return sku;
}
