const { google } = require("googleapis");
const axios = require("axios");
const fs = require("fs");
const path = require("path");
const { sendTelegramAlert, sendFbsWarehouseReport, sendFbsMultiWarehouseReport, sendFbsBroadcastReport } = require("./telegram_notifier");
const { createWbStockAudit } = require("./wb_stock_audit");
const { buildStockReport, throwOnStockSyncFailures } = require("./stock_sync_report");
const {
  STREAM_SUPPS_HEADERS,
  resolveStreamSuppsColumns,
} = require("./stream_supps_schema");

const SHEET_NAME = "StreamSupps";
const SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI";

const FERON_TR_OZON_WAREHOUSES = {
  MSK: 1020005000217829,
  SMR: 1020005000234124,
  NSB: 1020005008262970,
  EKB: 1020005023877890,
};

const FERON_TR_WB_WAREHOUSE = {
  MSK: 1449484,
  SMR: 798761,
  NSB: 1724900,
  // МГТ / Екатеринбург ФБС, склад WB «Екатеринбург».
  EKB: 1860503,
};

const FERON_TR_SCHEMA = {
  vendor_code: STREAM_SUPPS_HEADERS.offerId,
  brand: STREAM_SUPPS_HEADERS.brand,
  ozon_sku: STREAM_SUPPS_HEADERS.ozonSku,
  marketplace_stock_msk: STREAM_SUPPS_HEADERS.podorozhnikFbs,
  marketplace_stock_smr: STREAM_SUPPS_HEADERS.feronFbs,
  marketplace_stock_nsb: STREAM_SUPPS_HEADERS.feronNsbFbs,
  marketplace_stock_ekb: STREAM_SUPPS_HEADERS.feronEkbFbs,
  wb_voltmir_stock: STREAM_SUPPS_HEADERS.wbVoltmirTotal,
  wb_feron_moscow_stock: STREAM_SUPPS_HEADERS.wbFeronMoscowTotal,
  chrt_id: "chrlid",
};

function normalizeMarketplaceStock(value, brand) {
  const stock = Math.trunc(Number(value));
  if (!Number.isFinite(stock) || stock < 0) return 0;
  const isArlight = String(brand || "").trim().toLowerCase() === "arlight";
  return stock === 1 && !isArlight ? 0 : stock;
}

// Скидка WB-остатка: когда true, склад Екатеринбург (EKB) записывает только 0.
// Установи false, чтобы вернуть обычный расчёт остатков.
const FORCE_ZERO_WB_EKB = true;

const configuredOzonStocksRps = Number(process.env.FERON_OZON_STOCKS_RPS || 1);
const OZON_STOCKS_RPS = Number.isFinite(configuredOzonStocksRps)
  ? Math.max(0.1, configuredOzonStocksRps)
  : 1;
const WB_RPS = 0.1;

const OZON_BASE_DELAY = 1000;
const WB_BASE_DELAY = 3000;
const OZON_MAX_RETRIES = 3;
const OZON_TERMINAL_PRODUCT_ERRORS = new Set([
  "NOT_FOUND_ERROR",
  "NOT_PASS_MODERATION",
  "PRODUCT_IS_NOT_CREATED",
]);
const WB_MAX_RETRIES = 3;
const OZON_POSTCHECK_DELAY_MS = 30000;
const OZON_POSTCHECK_RETRY_DELAY_MS = 60000;

let lastRequestTime = Date.now() - 1000 / OZON_STOCKS_RPS;

function rateLimitRPS(lastTime, rps) {
  const minInterval = 1000 / rps;
  const now = Date.now();
  const elapsed = now - lastTime;
  if (elapsed < minInterval) {
    return new Promise((resolve) =>
      setTimeout(resolve, minInterval - elapsed),
    ).then(() => Date.now());
  }
  return Promise.resolve(Date.now());
}

function retryAfterMs(headers) {
  const value = headers?.["retry-after"] ?? headers?.["Retry-After"];
  if (value === undefined || value === null) return 0;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds > 0) return seconds * 1000;
  const timestamp = Date.parse(String(value));
  return Number.isFinite(timestamp) ? Math.max(0, timestamp - Date.now()) : 0;
}

function wbRetryDelayMs(headers, fallbackMs) {
  const raw = headers?.["x-ratelimit-retry"] ?? headers?.["X-Ratelimit-Retry"];
  const seconds = Number(raw);
  return Number.isFinite(seconds) && seconds >= 0
    ? Math.max(fallbackMs, seconds * 1000)
    : fallbackMs;
}

function log(msg) {
  const localTime = new Date().toLocaleTimeString("ru-RU", { hour12: false });
  const ms = String(new Date().getMilliseconds()).padStart(3, "0");
  console.log(`${localTime}.${ms} ${msg}`);
}

function columnLetter(col) {
  let letter = "";
  while (col > 0) {
    const mod = (col - 1) % 26;
    letter = String.fromCharCode(65 + mod) + letter;
    col = Math.floor((col - mod) / 26);
  }
  return letter;
}

async function readFeronStocksFromSheet(auth) {
  const sheets = google.sheets({ version: "v4", auth });

  const headersResp = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: `${SHEET_NAME}!1:1`,
    valueRenderOption: "UNFORMATTED_VALUE",
  });

  const headers = headersResp.data.values?.[0] || [];
  if (headers.length === 0) {
    log(`❌ Лист "${SHEET_NAME}" пуст или не найден!`);
    return [];
  }

  const columns = resolveStreamSuppsColumns(headers, FERON_TR_SCHEMA, SHEET_NAME);
  Object.entries(columns).forEach(([field, column]) => {
    log(`🔍 Схема: ${field} → '${headers[column - 1]}' → колонка ${column}`);
  });

  const colVendor = columns.vendor_code;
  const colBrand = columns.brand;
  const colOzonSku = columns.ozon_sku;
  const colStockMsk = columns.marketplace_stock_msk;
  const colStockSmr = columns.marketplace_stock_smr;
  const colStockNsb = columns.marketplace_stock_nsb;
  const colStockEkb = columns.marketplace_stock_ekb;
  const colWbVoltmirStock = columns.wb_voltmir_stock;
  const colWbFeronMoscowStock = columns.wb_feron_moscow_stock;
  const colChrtId = columns.chrt_id;

  log(
    `🔍 Колонки: offer_id=${colVendor}, sku_ozon=${colOzonSku}, MSK=${colStockMsk}, SMR=${colStockSmr}, NSB=${colStockNsb}, EKB=${colStockEkb}, WB ВольтМир итог=${colWbVoltmirStock}, WB ФБС ФЕРОН МОСКВА=${colWbFeronMoscowStock}, chrtId=${colChrtId}`,
  );

  const maxCol = Math.max(
    colVendor,
    colBrand,
    colOzonSku,
    colStockMsk,
    colStockSmr,
    colStockNsb,
    colStockEkb,
    colWbVoltmirStock,
    colWbFeronMoscowStock,
    colChrtId,
  );

  const dataResp = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: `${SHEET_NAME}!A:${columnLetter(maxCol)}`,
    majorDimension: "ROWS",
  });

  const allRows = dataResp.data.values || [];
  if (allRows.length < 2) {
    log(`❌ Нет данных на листе "${SHEET_NAME}"`);
    return [];
  }
  const data = allRows.slice(1);

  const stocks = [];

  for (let i = 0; i < data.length; i++) {
    const row = data[i];

    const vendorCode = row[colVendor - 1];
    const brand = String(row[colBrand - 1] || "").trim();
    const ozonSku = parseInt(row[colOzonSku - 1]) || 0;
    const originalStockMsk = parseInt(row[colStockMsk - 1]) || 0;
    const originalStockSmr = parseInt(row[colStockSmr - 1]) || 0;
    const originalStockNsb = parseInt(row[colStockNsb - 1]) || 0;
    const originalStockEkb = parseInt(row[colStockEkb - 1]) || 0;
    const wbVoltmirStock = Number(row[colWbVoltmirStock - 1]) || 0;
    const wbFeronMoscowStock = Number(row[colWbFeronMoscowStock - 1]) || 0;
    const chrtId = row[colChrtId - 1];

    if (!vendorCode) continue;

    const stockMsk = originalStockMsk;
    const stockSmr = originalStockSmr;
    const stockNsb = originalStockNsb;

    stocks.push({
      offer_id: vendorCode,
      brand: brand,
      ozon_sku: ozonSku,
      stock_msk: normalizeMarketplaceStock(originalStockMsk, brand),
      stock_smr: normalizeMarketplaceStock(originalStockSmr, brand),
      stock_nsb: normalizeMarketplaceStock(originalStockNsb, brand),
      stock_ekb: normalizeMarketplaceStock(originalStockEkb, brand),
      stock_wb_voltmir: normalizeMarketplaceStock(wbVoltmirStock, brand),
      stock_wb_feron_moscow: normalizeMarketplaceStock(wbFeronMoscowStock, brand),
      original_stock_msk: originalStockMsk,
      original_stock_smr: originalStockSmr,
      original_stock_nsb: originalStockNsb,
      original_stock_ekb: originalStockEkb,
      chrt_id: chrtId,
    });
  }

  log(`📊 Прочитано ${stocks.length} товаров из листа "${SHEET_NAME}"`);
  log(`   С chrtId: ${stocks.filter((s) => s.chrt_id).length}`);

  stocks.snapshotReadAt = new Date().toISOString();
  stocks.wbSourceColumns = {
    stock_wb_feron_moscow: `${columnLetter(colWbFeronMoscowStock)}:${headers[colWbFeronMoscowStock - 1]}`,
    stock_wb_voltmir: `${columnLetter(colWbVoltmirStock)}:${headers[colWbVoltmirStock - 1]}`,
    stock_nsb: `${columnLetter(colStockNsb)}:${headers[colStockNsb - 1]}`,
    stock_ekb: `${columnLetter(colStockEkb)}:${headers[colStockEkb - 1]}`,
  };
  log(`🧾 WB snapshot: readAt=${stocks.snapshotReadAt}, sources=${JSON.stringify(stocks.wbSourceColumns)}`);

  return stocks;
}

const WB_TOKEN_FILE =
  process.env.WB_API_TOKEN_FILE ||
  path.join(
    process.env.HOME || "/Users/vladimirgrebennikov",
    "AI agents",
    "secrets",
    "wb_api_token",
  );

const wbToken = (() => {
  const rawToken = fs.readFileSync(WB_TOKEN_FILE, "utf8").trim();
  if (!rawToken) throw new Error(`WB token file is empty: ${WB_TOKEN_FILE}`);
  return rawToken.toLowerCase().startsWith("bearer ")
    ? rawToken
    : `Bearer ${rawToken}`;
})();

const wbHeaders = () => ({
  Authorization: wbToken,
  "Content-Type": "application/json",
});

const ozonHeaders = () => ({
  "Content-Type": "application/json",
  "Client-Id": "142355",
  "Api-Key": "fe539630-170b-4b48-b222-8ba092907a63",
});

async function fetchOzonWarehouseStocksByOfferId(
  items,
  warehouseId,
  httpClient = axios,
) {
  const stockMap = new Map();
  const offerIds = [...new Set(
    items.map((item) => String(item.offer_id || "").trim()).filter(Boolean),
  )];
  // Ozon may return several warehouse rows per offer_id even if warehouse_id
  // is supplied. Keep chunks below the response limit to avoid silently
  // truncating rows and treating omitted products as zero stock.
  const chunkSize = 100;

  for (let i = 0; i < offerIds.length; i += chunkSize) {
    const chunk = offerIds.slice(i, i + chunkSize);
    const response = await httpClient.post(
      "https://api-seller.ozon.ru/v2/product/info/stocks-by-warehouse/fbs",
      {
        offer_id: chunk,
        warehouse_id: warehouseId,
        limit: 1000,
      },
      {
        headers: ozonHeaders(),
        timeout: 30000,
      },
    );

    const products = Array.isArray(response.data?.products)
      ? response.data.products
      : [];

    products.forEach((item) => {
      if (String(item.warehouse_id) !== String(warehouseId)) return;
      const offerId = String(item.offer_id || "").trim();
      if (!offerId) return;
      stockMap.set(offerId, {
        present: Number(item.present) || 0,
        reserved: Number(item.reserved) || 0,
        free_stock: Number(item.free_stock) || 0,
      });
    });
  }

  return stockMap;
}

async function verifyFeronOzonWarehouse(
  stocks,
  warehouse,
  { ignoredOfferIds = new Set(), httpClient = axios } = {},
) {
  const expected = stocks.filter(
    (item) => item.offer_id && !ignoredOfferIds.has(String(item.offer_id)),
  );
  if (expected.length === 0) return [];

  const actualMap = await fetchOzonWarehouseStocksByOfferId(
    expected,
    warehouse.id,
    httpClient,
  );

  const mismatches = [];
  const samples = [];
  let sheetPositiveCount = 0;
  let marketplacePositiveCount = 0;
  let marketplaceTotalPieces = 0;

  expected.forEach((item) => {
    const expectedStock = Number(item[warehouse.col]) || 0;
    const actual = actualMap.get(String(item.offer_id));
    const actualStock = actual?.free_stock ?? 0;
    const freeStock = actual?.free_stock ?? 0;

    if (expectedStock > 0) sheetPositiveCount++;
    if (actualStock > 0) {
      marketplacePositiveCount++;
      marketplaceTotalPieces += actualStock;
    }

    if (actualStock !== expectedStock) {
      mismatches.push({
        offer_id: item.offer_id,
        ozon_sku: item.ozon_sku,
        expected: expectedStock,
        actual: actualStock,
        free: freeStock,
      });
      if (samples.length < 10) {
        const skuLabel = item.ozon_sku ? ` [sku=${item.ozon_sku}]` : "";
        samples.push(
          `${item.offer_id}${skuLabel}: sheet=${expectedStock}, ozon=${actualStock}, free=${actual?.free_stock ?? 0}`,
        );
      }
    }
  });

  mismatches.stats = {
    warehouseName: warehouse.name,
    warehouseId: warehouse.id,
    sheetPositiveCount,
    marketplacePositiveCount,
    marketplaceTotalPieces,
  };

  if (mismatches.length === 0) {
    log(`✅ Ozon post-check ${warehouse.name}: расхождений не найдено (остаток Ozon: ${marketplacePositiveCount} SKU, ${marketplaceTotalPieces} шт.)`);
    return mismatches;
  }

  log(`⚠️ Ozon post-check ${warehouse.name}: найдено ${mismatches.length} расхождений (остаток Ozon: ${marketplacePositiveCount} SKU, ${marketplaceTotalPieces} шт.)`);
  samples.forEach((line) => log(`   - ${line}`));
  return mismatches;
}

async function updateFeronStocksOzonWithRetry(
  batch,
  warehouseId,
  colName,
  retryCount = 0,
) {
  const body = {
    stocks: batch.map((item) => ({
      offer_id: String(item.offer_id),
      stock: item[colName],
      warehouse_id: warehouseId,
    })),
  };

  try {
    const response = await axios.post(
      "https://api-seller.ozon.ru/v2/products/stocks",
      body,
      {
        headers: ozonHeaders(),
        timeout: 30000,
      },
    );

    return { ok: true, data: response.data };
  } catch (err) {
    const code = err.response?.status;
    const errorDetails = err.response?.data || err.message;

    if (code === 429 && retryCount < OZON_MAX_RETRIES) {
      const delay = Math.max(
        retryAfterMs(err.response?.headers),
        OZON_BASE_DELAY * Math.pow(2, retryCount),
      );
      log(
        "⏳ Ozon 429: ожидание " +
        delay / 1000 +
        " сек перед retry " +
        (retryCount + 1) +
        "/" +
        OZON_MAX_RETRIES +
        "...",
      );
      await new Promise((r) => setTimeout(r, delay));
      return updateFeronStocksOzonWithRetry(batch, warehouseId, colName, retryCount + 1);
    }

    if (code === 429) {
      log("⏭️ Ozon 429: пропуск после " + OZON_MAX_RETRIES + " попыток");
      return { ok: false, error: errorDetails, code };
    }

    return { ok: false, error: errorDetails, code };
  }
}

async function updateFeronStocksOzon(stocks) {
  log(`🟠 Обновление остатков Ozon (4 склада)...`);

  const validStocks = stocks.filter((s) => s.offer_id);
  if (validStocks.length === 0) {
    log(`⚠️ Нет товаров с offer_id`);
    return;
  }

  const warehouses = [
    {
      key: "MSK",
      name: "ПОДОРОЖНИК ФБС (МСК)",
      id: FERON_TR_OZON_WAREHOUSES.MSK,
      col: "stock_msk",
    },
    {
      key: "SMR",
      name: "ФЕРОН ФБС (Самара)",
      id: FERON_TR_OZON_WAREHOUSES.SMR,
      col: "stock_smr",
    },
    {
      key: "NSB",
      name: "НОВОСИБИРСК ФЕРОН",
      id: FERON_TR_OZON_WAREHOUSES.NSB,
      col: "stock_nsb",
    },
    {
      key: "EKB",
      name: "ЕКБ Ферон",
      id: FERON_TR_OZON_WAREHOUSES.EKB,
      col: "stock_ekb",
    },
  ];

  let totalSuccess = 0;
  let totalSkipped = 0;
  let totalError = 0;
  const pendingChecks = [];
  const ozonWarehouseStats = [];

  for (const wh of warehouses) {
    log(`\n📦 Обработка склада: ${wh.name} (ID: ${wh.id})...`);

    const batchSize = 100;
    const batches = Math.ceil(validStocks.length / batchSize);

    let warehouseSuccess = 0;
    let warehouseSkipped = 0;
    let warehouseError = 0;
    const skippedOfferIds = new Set();

    for (let i = 0; i < batches; i++) {
      lastRequestTime = await rateLimitRPS(lastRequestTime, OZON_STOCKS_RPS);

      const batch = validStocks.slice(i * batchSize, (i + 1) * batchSize);

      log(`📤 Отправка на Ozon ${wh.name}: ${batch.length} товаров, первый: offer_id=${batch[0]?.offer_id}, ${wh.col}=${batch[0]?.[wh.col]}`);

      const result = await updateFeronStocksOzonWithRetry(batch, wh.id, wh.col);

      if (result.ok && result.data?.result) {
        const itemResults = result.data.result;
        itemResults.forEach((r) => {
          if (r.updated) {
            warehouseSuccess++;
          } else if (r.errors && r.errors.length > 0) {
            const terminal = r.errors.every((e) => OZON_TERMINAL_PRODUCT_ERRORS.has(e.code));
            if (terminal) {
              warehouseSkipped++;
              if (r.offer_id) skippedOfferIds.add(String(r.offer_id));
            } else {
              warehouseError++;
              log(
                `❌ Ozon ${wh.name}: ${r.offer_id || "(без offer_id)"}: ${JSON.stringify(r.errors).slice(0, 1000)}`,
              );
            }
          } else {
            warehouseError++;
            log(`❌ Ozon ${wh.name}: ${r.offer_id || "(без offer_id)"} без updated и без terminal-ошибки`);
          }
        });
        if (itemResults.length < batch.length) {
          const missing = batch.length - itemResults.length;
          warehouseError += missing;
          log(`❌ Ozon ${wh.name}: неполный результат пачки ${i + 1}/${batches}, без статуса ${missing} SKU`);
        }
        log(`✅ Пачка ${i + 1}/${batches} обработана`);
      } else {
        log(
          `❌ Ошибка API (пачка ${i + 1}/${batches}): ${JSON.stringify(result.error || result.code).slice(0, 1000)}`,
        );
        warehouseError += batch.length;
      }
    }

    log(
      `🟠 ${wh.name}: ✅ ${warehouseSuccess} обновлено, ❌ ${warehouseError} ошибок`,
    );
    log(
      `⏳ Ожидание ${OZON_POSTCHECK_DELAY_MS / 1000} сек перед промежуточным Ozon post-check ${wh.name}...`,
    );
    await new Promise((resolve) => setTimeout(resolve, OZON_POSTCHECK_DELAY_MS));
    const mismatches = await verifyFeronOzonWarehouse(validStocks, wh, { ignoredOfferIds: skippedOfferIds });
    ozonWarehouseStats.push({
      ...(mismatches.stats || {
        warehouseName: wh.name,
        warehouseId: wh.id,
        sheetPositiveCount: validStocks.filter((s) => s[wh.col] > 0).length,
        marketplacePositiveCount: null,
        marketplaceTotalPieces: null,
      }),
      sourcePositiveSku: validStocks.filter((item) => Number(item[wh.col]) > 0).length,
      attemptedSku: validStocks.length,
      acceptedSku: warehouseSuccess,
      skippedSku: warehouseSkipped,
      errorSku: warehouseError,
      skippedOfferIds,
      mismatchSku: mismatches.length,
      verificationStatus: mismatches.length ? "pending" : "verified",
      snapshotReadAt: stocks.snapshotReadAt || null,
    });
    if (mismatches.length > 0) {
      log(
        `ℹ️ Промежуточные расхождения Ozon ${wh.name} будут перепроверены в конце скрипта после WB: ${mismatches.length}`,
      );
      pendingChecks.push({ warehouse: wh, mismatches, skippedOfferIds });
    }
    totalSuccess += warehouseSuccess;
    totalSkipped += warehouseSkipped;
    totalError += warehouseError;
  }

  log(`\n🟠 Ozon Всего: ✅ ${totalSuccess} обновлено, ⏸️ ${totalSkipped} terminal-пропусков, ❌ ${totalError} ошибок`);
  return { pendingChecks, ozonWarehouseStats };
}

function isWBCargoRestrictionError(responseText) {
  try {
    const errorData = JSON.parse(responseText);
    const errorItems = Array.isArray(errorData)
      ? errorData
      : errorData?.errors || errorData?.error || [];

    if (!errorItems || errorItems.length === 0) return false;

    return errorItems.some((err) => {
      const code = String(err.code || err.error || "");
      const message = String(err.message || err.detail || "");
      return (
        code.includes("CargoWarehouseRestriction") ||
        message.includes("CargoWarehouseRestriction") ||
        code.includes("SGTKGTPlus") ||
        message.includes("SGTKGTPlus") ||
        message.includes("ODC") ||
        message.includes("CD+")
      );
    });
  } catch (e) {
    return (
      responseText.includes("CargoWarehouseRestriction") ||
      responseText.includes("SGTKGTPlus") ||
      responseText.includes("ODC") ||
      responseText.includes("CD+")
    );
  }
}

async function sendFeronWBStocksBatch(batch, warehouseId, retryCount = 0) {
  const body = { stocks: batch };
  const url = `https://marketplace-api.wildberries.ru/api/v3/stocks/${warehouseId}`;

  try {
    const response = await axios.put(url, body, {
      headers: wbHeaders(),
      timeout: 30000,
    });

    const code = response.status;
    const text = JSON.stringify(response.data || {});

    if (code === 429 && retryCount < WB_MAX_RETRIES) {
      const delay = wbRetryDelayMs(response.headers, WB_BASE_DELAY * Math.pow(2, retryCount));
      log(
        "⏳ WB 429: ожидание " +
        delay / 1000 +
        " сек перед retry " +
        (retryCount + 1) +
        "/" +
        WB_MAX_RETRIES +
        "...",
      );
      await new Promise((r) => setTimeout(r, delay));
      return sendFeronWBStocksBatch(batch, warehouseId, retryCount + 1);
    }

    if (code === 429) {
      log("⏭️ WB 429: пропуск после " + WB_MAX_RETRIES + " попыток");
      return { ok: false, code, text: "MAX_RETRIES_EXCEEDED" };
    }

    return {
      ok: code === 200 || code === 204,
      code,
      text,
      cargoRestriction: code === 409 && isWBCargoRestrictionError(text),
    };
  } catch (err) {
    const code = err.response?.status || 0;
    const text = err.response?.data
      ? JSON.stringify(err.response.data)
      : err.message;

    if (code === 429 && retryCount < WB_MAX_RETRIES) {
      const delay = wbRetryDelayMs(err.response?.headers, WB_BASE_DELAY * Math.pow(2, retryCount));
      log(
        "⏳ WB 429: ожидание " +
        delay / 1000 +
        " сек перед retry " +
        (retryCount + 1) +
        "/" +
        WB_MAX_RETRIES +
        "...",
      );
      await new Promise((r) => setTimeout(r, delay));
      return sendFeronWBStocksBatch(batch, warehouseId, retryCount + 1);
    }

    if (code === 429) {
      log("⏭️ WB 429: пропуск после " + WB_MAX_RETRIES + " попыток");
      return { ok: false, code, text: "MAX_RETRIES_EXCEEDED" };
    }

    return {
      ok: false,
      code,
      text,
      cargoRestriction: code === 409 && isWBCargoRestrictionError(text),
    };
  }
}

async function processFeronWBConflictIndividually(
  validBatch,
  warehouseId,
  batchLabel,
  auditContext = null,
) {
  let successCount = 0;
  let skippedCount = 0;
  let errorCount = 0;

  log(
    `🔍 ${batchLabel}: дробление до отдельных товаров (${validBatch.length} шт)...`,
  );

  for (let j = 0; j < validBatch.length; j++) {
    if (j > 0 && j % 5 === 0) {
      await new Promise((r) => setTimeout(r, 3000));
    }

    const item = validBatch[j];
    const result = await sendFeronWBStocksBatch([item], warehouseId);
    const auditItem = auditContext?.itemsByChrtId.get(Number(item.chrtId));

    if (result.ok) {
      successCount++;
      auditContext?.audit.recordItemResult({
        warehouseId,
        batchIndex: auditContext.batchIndex,
        offerId: auditItem?.offerId,
        chrtId: item.chrtId,
        amount: item.amount,
        status: "success",
        code: result.code,
      });
      continue;
    }

    if (result.cargoRestriction) {
      log(
        `⏸️ ${batchLabel}: пропущен ODC/CD+ chrtId=${item.chrtId}, amount=${item.amount}`,
      );
      skippedCount++;
      auditContext?.audit.recordItemResult({
        warehouseId,
        batchIndex: auditContext.batchIndex,
        offerId: auditItem?.offerId,
        chrtId: item.chrtId,
        amount: item.amount,
        status: "cargo_restriction",
        code: result.code,
      });
      continue;
    }

    if (result.text === "MAX_RETRIES_EXCEEDED") {
      log(
        `⏭️ ${batchLabel}: chrtId=${item.chrtId} - 429 превышен лимит, пропущен`,
      );
      skippedCount++;
      auditContext?.audit.recordItemResult({
        warehouseId,
        batchIndex: auditContext.batchIndex,
        offerId: auditItem?.offerId,
        chrtId: item.chrtId,
        amount: item.amount,
        status: "rate_limited",
        code: result.code,
      });
      continue;
    }

    log(
      `❌ ${batchLabel}: ошибка для chrtId=${item.chrtId}, code=${result.code}`,
    );
    errorCount++;
    auditContext?.audit.recordItemResult({
      warehouseId,
      batchIndex: auditContext.batchIndex,
      offerId: auditItem?.offerId,
      chrtId: item.chrtId,
      amount: item.amount,
      status: "error",
      code: result.code,
    });
  }

  log(
    `📊 ${batchLabel}: поштучно ✅ ${successCount}, ⏸️ ${skippedCount}, ❌ ${errorCount}`,
  );

  return { successCount, skippedCount, errorCount };
}

async function updateFeronStocksWB(stocks) {
  log(`🟣 Обновление остатков WB FBS (4 склада)...`);

  const validStocks = stocks.filter((s) => s.chrt_id);
  if (validStocks.length === 0) {
    log(`⚠️ Нет товаров с chrtId`);
    return;
  }

  log(`📦 Товаров для обработки: ${validStocks.length}`);
  const audit = createWbStockAudit({
    scriptName: "sync-feron-stocks",
    sheetName: SHEET_NAME,
    sourceReadAt: stocks.snapshotReadAt,
  });
  log(`🧾 WB payload audit: ${audit.filePath} (runId=${audit.runId})`);

  const warehouses = [
    {
      key: "MSK",
      name: "ФБС ФЕРОН МОСКВА",
      id: FERON_TR_WB_WAREHOUSE.MSK,
      col: "stock_wb_feron_moscow",
    },
    {
      key: "SMR",
      name: "ВольтМир (Самара)",
      id: FERON_TR_WB_WAREHOUSE.SMR,
      col: "stock_wb_voltmir",
    },
    {
      key: "NSB",
      name: "Новосибирск",
      id: FERON_TR_WB_WAREHOUSE.NSB,
      col: "stock_nsb",
    },
    {
      key: "EKB",
      name: "Екатеринбург",
      id: FERON_TR_WB_WAREHOUSE.EKB,
      col: "stock_ekb",
    },
  ];

  lastRequestTime = Date.now() - 1000 / WB_RPS;
  let totalSuccess = 0;
  let totalSkipped = 0;
  let totalError = 0;
  const wbWarehouseStats = [];

  for (const wh of warehouses) {
    log(`\n📦 Обработка склада: ${wh.name} (ID: ${wh.id})...`);

    if (FORCE_ZERO_WB_EKB && wh.key === "EKB") {
      log(`⏸️ FORCE_ZERO_WB_EKB: склад EKB будет записан нулями`);
    }

    const activeCount = validStocks.filter((s) => {
      const amt = FORCE_ZERO_WB_EKB && wh.key === "EKB" ? 0 : s[wh.col];
      return amt > 0;
    }).length;
    wbWarehouseStats.push({
      warehouseName: wh.name,
      warehouseId: wh.id,
      activeSku: activeCount,
      marketplaceStockSku: null,
      marketplaceTotalPieces: null,
      sourcePositiveSku: activeCount,
      attemptedSku: validStocks.length,
      acceptedSku: 0,
      skippedSku: 0,
      errorSku: 0,
      verificationStatus: "not_run",
      runId: audit.runId,
      snapshotReadAt: stocks.snapshotReadAt || null,
      snapshotSources: stocks.wbSourceColumns || null,
    });

    const batchSize = 200;
    const batches = Math.ceil(validStocks.length / batchSize);

    let warehouseSuccess = 0;
    let warehouseSkipped = 0;
    let warehouseError = 0;

    for (let i = 0; i < batches; i++) {
      lastRequestTime = rateLimitRPS(lastRequestTime, WB_RPS);

      const batch = validStocks.slice(i * batchSize, (i + 1) * batchSize);

      const validBatch = [];
      const auditItems = [];

      for (const item of batch) {
        const idNum = Number(item.chrt_id);
        if (isNaN(idNum) || !item.chrt_id) {
          warehouseError++;
          continue;
        }
        const amount = FORCE_ZERO_WB_EKB && wh.key === "EKB" ? 0 : item[wh.col];
        validBatch.push({ chrtId: idNum, amount });
        auditItems.push({ offerId: item.offer_id, chrtId: idNum, amount });
      }

      if (validBatch.length === 0) continue;

      const auditPayload = audit.recordPayload({
        warehouseId: wh.id,
        warehouseName: wh.name,
        sourceColumn: stocks.wbSourceColumns?.[wh.col] || wh.col,
        batchIndex: i + 1,
        totalBatches: batches,
        items: auditItems,
      });
      if (auditPayload.shouldWarn) {
        log(`⚠️ WB STALE SNAPSHOT: снимку уже ${auditPayload.ageSeconds} сек; warehouse=${wh.name}, batch=${i + 1}/${batches}, source=${stocks.wbSourceColumns?.[wh.col] || wh.col}`);
      }

      log(`📤 Отправка на WB ${wh.name}: ${validBatch.length} товаров, первый: chrtId=${validBatch[0]?.chrtId}, amount=${validBatch[0]?.amount}`);

      const result = await sendFeronWBStocksBatch(validBatch, wh.id);

      if (result.ok) {
        warehouseSuccess += validBatch.length;
        audit.recordBatchResult({
          warehouseId: wh.id,
          batchIndex: i + 1,
          checksum: auditPayload.checksum,
          status: "success",
          code: result.code,
          successCount: validBatch.length,
        });
        log(
          `✅ Пачка ${i + 1}/${batches} обработана (${validBatch.length} товаров)`,
        );
        continue;
      }

      if (result.cargoRestriction) {
        log(`⚠️ WB 409 ODC/CD+ (пачка ${i + 1}/${batches}): дробление...`);
        const fallback = await processFeronWBConflictIndividually(
          validBatch,
          wh.id,
          `Пачка ${i + 1}/${batches}`,
          {
            audit,
            batchIndex: i + 1,
            itemsByChrtId: new Map(auditItems.map((item) => [item.chrtId, item])),
          },
        );
        audit.recordBatchResult({
          warehouseId: wh.id,
          batchIndex: i + 1,
          checksum: auditPayload.checksum,
          status: "individual_fallback",
          code: result.code,
          successCount: fallback.successCount,
          skippedCount: fallback.skippedCount,
          errorCount: fallback.errorCount,
        });
        warehouseSuccess += fallback.successCount;
        warehouseSkipped += fallback.skippedCount;
        warehouseError += fallback.errorCount;
        continue;
      }

      if (result.text === "MAX_RETRIES_EXCEEDED") {
        log(
          `⏭️ WB 429 (пачка ${i + 1}/${batches}): превышен лимит, пропущено ${validBatch.length} товаров`,
        );
        warehouseSkipped += validBatch.length;
        audit.recordBatchResult({
          warehouseId: wh.id,
          batchIndex: i + 1,
          checksum: auditPayload.checksum,
          status: "rate_limited",
          code: result.code,
          skippedCount: validBatch.length,
        });
        continue;
      }

      log(`❌ Ошибка API (пачка ${i + 1}/${batches}): ${result.code}`);
      warehouseError += validBatch.length;
      audit.recordBatchResult({
        warehouseId: wh.id,
        batchIndex: i + 1,
        checksum: auditPayload.checksum,
        status: "error",
        code: result.code,
        errorCount: validBatch.length,
      });
    }

    log(
      `🟣 ${wh.name}: ✅ ${warehouseSuccess} обновлено, ⏸️ ${warehouseSkipped} пропущено ODC/CD+, ❌ ${warehouseError} ошибок`,
    );
    const warehouseStats = wbWarehouseStats[wbWarehouseStats.length - 1];
    warehouseStats.acceptedSku = warehouseSuccess;
    warehouseStats.skippedSku = warehouseSkipped;
    warehouseStats.errorSku = warehouseError;
    totalSuccess += warehouseSuccess;
    totalSkipped += warehouseSkipped;
    totalError += warehouseError;
  }

  log(
    `\n🟣 WB Всего: ✅ ${totalSuccess} обновлено, ⏸️ ${totalSkipped} пропущено ODC/CD+, ❌ ${totalError} ошибок`,
  );
  return wbWarehouseStats;
}

async function main() {
  const marketplace = process.argv.find((arg) => arg.startsWith("--marketplace="))?.split("=")[1] || "all";
  if (!["all", "ozon", "wb"].includes(marketplace)) throw new Error(`Unknown marketplace: ${marketplace}`);
  console.log("============================================");
  console.log("🔄 СИНХРОНИЗАЦИЯ ОСТАТКОВ FERON (LOCAL)");
  console.log("============================================");

  const startTime = new Date();

  const auth = new google.auth.GoogleAuth({
    keyFile: path.join(
      __dirname,
      "nomadic-bedrock-485314-b0-d7624dedd83c.json",
    ),
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });

  const client = await auth.getClient();
  google.options({ auth: client });

  let stocks = [];
  const maxReadRetries = 5;
  for (let attempt = 1; attempt <= maxReadRetries; attempt++) {
    try {
      log(`📊 Шаг 1: Чтение данных из листа "${SHEET_NAME}" (попытка ${attempt}/${maxReadRetries})...`);
      stocks = await readFeronStocksFromSheet(client);
      break;
    } catch (err) {
      log(`⚠️ Ошибка чтения листа (попытка ${attempt}/${maxReadRetries}): ${err.message || err}`);
      if (attempt === maxReadRetries) throw err;
      const errMsg = String(err.message || err).toLowerCase();
      const isQuotaOrLock =
        errMsg.includes("exhausted") ||
        errMsg.includes("429") ||
        errMsg.includes("socket hang up") ||
        errMsg.includes("etimedout") ||
        errMsg.includes("timeout") ||
        errMsg.includes("500") ||
        errMsg.includes("503");

      const delay = isQuotaOrLock ? 30000 * attempt : 5000 * attempt;
      log(`⏳ Ожидание ${delay / 1000} сек перед повтором (тип ошибки: ${isQuotaOrLock ? "квота/перегрузка Google" : "стандартная"})...`);
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }

  if (stocks.length === 0) {
    log("❌ Нет данных для синхронизации");
    await sendTelegramAlert("sync_feron_stocks", "В листе StreamSupps не найдено строк с offer_id для синхронизации");
    return;
  }

  log(`📋 Примеры данных (первые 5):`);
  stocks.slice(0, 5).forEach((s) => {
    log(
      `  - ${s.offer_id} | Ozon MSK: ${s.stock_msk} | WB Москва итог: ${s.stock_wb_feron_moscow} | SMR: ${s.stock_smr} | NSB: ${s.stock_nsb} | chrtId: ${s.chrt_id || "(нет)"}`,
    );
  });

  log(``);
  log(`🟠 Шаг 2: Обновление остатков Ozon...`);
  const { pendingChecks: ozonPendingChecks, ozonWarehouseStats } = marketplace !== "wb"
    ? await updateFeronStocksOzon(stocks)
    : { pendingChecks: [], ozonWarehouseStats: [] };

  log(``);
  log(`🟣 Шаг 3: Обновление остатков WB...`);
  const wbWarehouseStats = marketplace !== "ozon" ? await updateFeronStocksWB(stocks) : [];

  if (ozonPendingChecks.length > 0) {
    log(``);
    log(`🟠 Шаг 4: Финальная перепроверка расхождений Ozon после завершения WB...`);
    log(
      `⏳ Дополнительное ожидание ${OZON_POSTCHECK_RETRY_DELAY_MS / 1000} сек перед финальным Ozon post-check...`,
    );
    await new Promise((resolve) =>
      setTimeout(resolve, OZON_POSTCHECK_RETRY_DELAY_MS),
    );

    for (const pending of ozonPendingChecks) {
      const pendingOfferIds = new Set(pending.mismatches.map((item) => String(item.offer_id)));
      const rechecked = await verifyFeronOzonWarehouse(
        stocks.filter((item) => pendingOfferIds.has(String(item.offer_id))),
        pending.warehouse,
        { ignoredOfferIds: pending.skippedOfferIds },
      );
      if (rechecked?.stats) {
        const idx = ozonWarehouseStats.findIndex(
          (s) => s.warehouseId === pending.warehouse.id,
        );
        if (idx >= 0) ozonWarehouseStats[idx] = {
          ...ozonWarehouseStats[idx],
          ...rechecked.stats,
          mismatchSku: rechecked.length,
          verificationStatus: rechecked.length ? "mismatch" : "verified",
        };
      }
    }
  }

  const endTime = new Date();
  const duration = Math.round((endTime - startTime) / 1000);

  log(``);
  console.log("============================================");
  log(`✅ Синхронизация завершена за ${duration} сек.`);
  console.log("============================================");

  // Отправка итоговой сводки трансляции ФБС в Telegram (Ozon и WB)
  const reports = [];
  try {
    const totalSku = stocks.length;

    // 1. Отчет по Ozon (Ферон)
    if (marketplace !== "wb") await sendFbsMultiWarehouseReport({
      supplier: "Ферон",
      marketplace: "Ozon",
      totalSku,
      warehouses: ozonWarehouseStats.map((st) => ({
        warehouseName: st.warehouseName,
        activeSku: st.sheetPositiveCount,
        marketplaceStockSku: st.marketplacePositiveCount,
        marketplaceTotalPieces: st.marketplaceTotalPieces,
        ...buildStockReport({
          sourcePositiveSku: st.sourcePositiveSku,
          attemptedSku: st.attemptedSku,
          acceptedSku: st.acceptedSku,
          skippedSku: st.skippedSku,
          errorSku: st.errorSku,
          verification: { status: st.verificationStatus === "pending" ? "mismatch" : st.verificationStatus, positiveSku: st.marketplacePositiveCount, pieces: st.marketplaceTotalPieces, mismatchSku: st.mismatchSku },
          snapshotReadAt: st.snapshotReadAt,
        }),
      })),
      durationSec: duration,
    });

    await new Promise((resolve) => setTimeout(resolve, 600));

    // 2. Отчет по WB (Ферон)
    if (marketplace !== "ozon") await sendFbsMultiWarehouseReport({
      supplier: "Ферон",
      marketplace: "ВБ",
      totalSku,
      warehouses: wbWarehouseStats.map((st) => ({
        warehouseName: st.warehouseName,
        activeSku: st.activeSku,
        marketplaceStockSku: null,
        marketplaceTotalPieces: null,
        ...buildStockReport({
          sourcePositiveSku: st.sourcePositiveSku,
          attemptedSku: st.attemptedSku,
          acceptedSku: st.acceptedSku,
          skippedSku: st.skippedSku,
          errorSku: st.errorSku,
          verification: { status: st.verificationStatus },
          runId: st.runId,
          snapshotReadAt: st.snapshotReadAt,
          snapshotSources: st.snapshotSources,
        }),
      })),
      durationSec: duration,
    });
  } catch (repErr) {
    console.error("Не удалось отправить сводку в Telegram:", repErr);
  }
  if (marketplace !== "wb") reports.push(...ozonWarehouseStats.map((st) => buildStockReport({
    marketplace: "Ozon", warehouseName: st.warehouseName,
    sourcePositiveSku: st.sourcePositiveSku, attemptedSku: st.attemptedSku,
    acceptedSku: st.acceptedSku, skippedSku: st.skippedSku, errorSku: st.errorSku,
    verification: { status: st.verificationStatus === "pending" ? "mismatch" : st.verificationStatus, mismatchSku: st.mismatchSku },
    snapshotReadAt: st.snapshotReadAt,
  })));
  if (marketplace !== "ozon") reports.push(...wbWarehouseStats.map((st) => buildStockReport({
    marketplace: "ВБ", warehouseName: st.warehouseName,
    sourcePositiveSku: st.sourcePositiveSku, attemptedSku: st.attemptedSku,
    acceptedSku: st.acceptedSku, skippedSku: st.skippedSku, errorSku: st.errorSku,
    verification: { status: st.verificationStatus }, runId: st.runId,
    snapshotReadAt: st.snapshotReadAt, snapshotSources: st.snapshotSources,
  })));
  throwOnStockSyncFailures(reports);
}

if (require.main === module) {
  main().catch(async (err) => {
    console.error("❌ Ошибка:", err);
    try {
      await sendTelegramAlert(
        "sync_feron_stocks",
        err.message || String(err),
        err.stack || null,
      );
    } catch (tgErr) {
      console.error("Не удалось отправить Telegram алерт:", tgErr);
    }
    process.exit(1);
  });
}

module.exports = {
  fetchOzonWarehouseStocksByOfferId,
  verifyFeronOzonWarehouse,
};
