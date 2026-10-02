"use strict";

const fs = require("fs");
const path = require("path");
const axios = require("axios");
const { google } = require("googleapis");
const { createWbStockRateLimiter } = require("../wb_stock_rate_limiter");
const { fetchOzonWarehouseStocksByOfferId } = require("../sync-feron-stocks");
const { STREAM_SUPPS_HEADERS, resolveStreamSuppsColumns } = require("../stream_supps_schema");

const SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI";
const SHEET_NAME = "StreamSupps";
const OUTPUT_PATH = path.join(__dirname, "..", "logs", "feron_zero_nsb_ekb_verification_20261002.json");
const OZON_WAREHOUSES = {
  NSB: 1020005008262970,
  EKB: 1020005023877890,
};
const WB_WAREHOUSES = {
  NSB: 1724900,
  EKB: 1860503,
};
const WB_STOCKS_URL = "https://marketplace-api.wildberries.ru/api/v3/stocks";
const WB_TOKEN_FILE = process.env.WB_API_TOKEN_FILE || path.join(
  process.env.HOME || "/Users/vladimirgrebennikov",
  "AI agents",
  "secrets",
  "wb_api_token",
);
const wbTokenText = fs.readFileSync(WB_TOKEN_FILE, "utf8").trim();
if (!wbTokenText) throw new Error("WB API token file is empty");
const wbToken = wbTokenText.toLowerCase().startsWith("bearer ") ? wbTokenText : `Bearer ${wbTokenText}`;
const wbLimiter = createWbStockRateLimiter({ requestsPerSecond: Number(process.env.WB_STOCKS_RPS || 5) });

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function readCurrentProductIds() {
  const auth = new google.auth.GoogleAuth({
    keyFile: path.join(__dirname, "..", "nomadic-bedrock-485314-b0-d7624dedd83c.json"),
    scopes: ["https://www.googleapis.com/auth/spreadsheets.readonly"],
  });
  const sheets = google.sheets({ version: "v4", auth: await auth.getClient() });
  const response = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: SHEET_NAME,
    majorDimension: "ROWS",
    valueRenderOption: "UNFORMATTED_VALUE",
  });
  const rows = response.data.values || [];
  if (!rows.length) throw new Error(`Sheet ${SHEET_NAME} is empty`);

  const columns = resolveStreamSuppsColumns(rows[0], {
    offerId: STREAM_SUPPS_HEADERS.offerId,
    chrtId: "chrlid",
  }, SHEET_NAME);
  const offerIds = new Set();
  const chrtIds = new Set();
  for (const row of rows.slice(1)) {
    const offerId = String(row[columns.offerId - 1] || "").trim();
    const chrtId = Number(row[columns.chrtId - 1]);
    if (offerId) offerIds.add(offerId);
    if (Number.isSafeInteger(chrtId) && chrtId > 0) chrtIds.add(chrtId);
  }
  return {
    readAt: new Date().toISOString(),
    rowCount: Math.max(0, rows.length - 1),
    offerIds: [...offerIds],
    chrtIds: [...chrtIds],
  };
}

function retryDelayMs(error, attempt) {
  const raw = error.response?.headers?.["retry-after"];
  const seconds = Number(raw);
  if (Number.isFinite(seconds) && seconds > 0) return seconds * 1000;
  return 1000 * 2 ** attempt;
}

async function queryOzonChunk(offerIds, warehouseId, result, attempt = 0) {
  try {
    const rows = offerIds.map((offer_id) => ({ offer_id }));
    const stocks = await fetchOzonWarehouseStocksByOfferId(rows, warehouseId);
    stocks.forEach((stock, offerId) => result.stockByOfferId.set(offerId, stock.free_stock));
    result.queried += offerIds.length;
  } catch (error) {
    const status = Number(error.response?.status || 0);
    if ((status === 429 || status >= 500) && attempt < 3) {
      await sleep(retryDelayMs(error, attempt));
      return queryOzonChunk(offerIds, warehouseId, result, attempt + 1);
    }
    if (offerIds.length > 1) {
      const midpoint = Math.ceil(offerIds.length / 2);
      await queryOzonChunk(offerIds.slice(0, midpoint), warehouseId, result);
      await queryOzonChunk(offerIds.slice(midpoint), warehouseId, result);
      return;
    }
    result.unqueryableOfferIds.push(offerIds[0]);
  }
}

async function verifyOzon(offerIds, key, warehouseId) {
  const result = { stockByOfferId: new Map(), queried: 0, unqueryableOfferIds: [] };
  const chunkSize = 100;
  for (let offset = 0; offset < offerIds.length; offset += chunkSize) {
    await queryOzonChunk(offerIds.slice(offset, offset + chunkSize), warehouseId, result);
    if ((offset / chunkSize + 1) % 25 === 0) {
      console.log(`Ozon ${key}: checked ${Math.min(offset + chunkSize, offerIds.length)}/${offerIds.length}`);
    }
  }
  const nonzero = [...result.stockByOfferId.entries()]
    .filter(([, amount]) => Number(amount) > 0)
    .map(([offerId, amount]) => ({ offerId, amount }));
  return {
    warehouseKey: key,
    warehouseId,
    queried: result.queried,
    unqueryableCount: result.unqueryableOfferIds.length,
    unqueryableSample: result.unqueryableOfferIds.slice(0, 20),
    nonzeroCount: nonzero.length,
    nonzeroPieces: nonzero.reduce((sum, item) => sum + Number(item.amount || 0), 0),
    nonzeroSample: nonzero.slice(0, 20),
  };
}

async function queryWbChunk(warehouseId, chrtIds, attempt = 0) {
  await wbLimiter.waitTurn();
  try {
    const response = await axios.post(
      `${WB_STOCKS_URL}/${warehouseId}`,
      { chrtIds },
      {
        headers: { Authorization: wbToken, "Content-Type": "application/json" },
        timeout: 30000,
      },
    );
    return (response.data?.stocks || []).map((item) => ({
      chrtId: Number(item.chrtId),
      amount: Number(item.amount) || 0,
    }));
  } catch (error) {
    const status = Number(error.response?.status || 0);
    if (status === 429) {
      const delay = await wbLimiter.deferForRateLimit(error.response?.headers, 3000 * 2 ** attempt);
      if (attempt < 3) {
        await sleep(delay);
        return queryWbChunk(warehouseId, chrtIds, attempt + 1);
      }
    }
    if ((status >= 500 || !status) && attempt < 3) {
      await sleep(1000 * 2 ** attempt);
      return queryWbChunk(warehouseId, chrtIds, attempt + 1);
    }
    throw error;
  }
}

async function verifyWb(chrtIds, key, warehouseId) {
  const stockByChrtId = new Map();
  const failed = [];
  const chunkSize = 250;
  for (let offset = 0; offset < chrtIds.length; offset += chunkSize) {
    const chunk = chrtIds.slice(offset, offset + chunkSize);
    try {
      const stocks = await queryWbChunk(warehouseId, chunk);
      stocks.forEach((item) => stockByChrtId.set(item.chrtId, item.amount));
    } catch (error) {
      failed.push({ status: error.response?.status || 0, chrtIds: chunk });
    }
    if ((offset / chunkSize + 1) % 15 === 0) {
      console.log(`WB ${key}: checked ${Math.min(offset + chunkSize, chrtIds.length)}/${chrtIds.length}`);
    }
  }
  const nonzero = [...stockByChrtId.entries()]
    .filter(([, amount]) => Number(amount) > 0)
    .map(([chrtId, amount]) => ({ chrtId, amount }));
  const returnedIds = new Set(stockByChrtId.keys());
  return {
    warehouseKey: key,
    warehouseId,
    queried: chrtIds.length,
    returned: returnedIds.size,
    failedChunkCount: failed.length,
    failedSample: failed.slice(0, 10).map(({ status, chrtIds: ids }) => ({ status, firstChrtId: ids[0], count: ids.length })),
    nonzeroCount: nonzero.length,
    nonzeroPieces: nonzero.reduce((sum, item) => sum + Number(item.amount || 0), 0),
    nonzeroSample: nonzero.slice(0, 20),
  };
}

async function main() {
  const ids = await readCurrentProductIds();
  console.log(`Fresh sheet snapshot: ${ids.rowCount} rows, ${ids.offerIds.length} offerIds, ${ids.chrtIds.length} chrtIds at ${ids.readAt}`);

  const results = { snapshotReadAt: ids.readAt, rowCount: ids.rowCount, offerCount: ids.offerIds.length, chrtIdCount: ids.chrtIds.length, ozon: [], wb: [] };
  for (const [key, warehouseId] of Object.entries(OZON_WAREHOUSES)) {
    results.ozon.push(await verifyOzon(ids.offerIds, key, warehouseId));
  }
  for (const [key, warehouseId] of Object.entries(WB_WAREHOUSES)) {
    results.wb.push(await verifyWb(ids.chrtIds, key, warehouseId));
  }

  fs.writeFileSync(OUTPUT_PATH, JSON.stringify(results, null, 2));
  for (const marketplace of ["ozon", "wb"]) {
    for (const result of results[marketplace]) {
      console.log(`${marketplace.toUpperCase()} ${result.warehouseKey}: nonzero=${result.nonzeroCount}, pieces=${result.nonzeroPieces}, unavailable=${result.unqueryableCount ?? result.failedChunkCount ?? 0}`);
    }
  }
  console.log(`Verification details: ${OUTPUT_PATH}`);
  if (results.ozon.some((result) => result.nonzeroCount || result.unqueryableCount) ||
      results.wb.some((result) => result.nonzeroCount || result.failedChunkCount)) {
    process.exitCode = 2;
  }
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exitCode = 1;
});
