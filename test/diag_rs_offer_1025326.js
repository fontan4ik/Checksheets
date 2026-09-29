#!/usr/bin/env node

// Read-only live check for RS offers 1025326-8 and 1025326-25.
const path = require("path");
const { google } = require("googleapis");
const { fetchOzonStocksByOfferIds, RS_OZON_WAREHOUSE_ID, RS_OZON_MOSCOW_WAREHOUSE_ID } = require("../sync-rs-stocks");

const spreadsheetId = process.env.CHECKSHEETS_SPREADSHEET_ID || "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI";
const sheetName = "StreamSupps";
const offers = new Set(["1025326-8", "1025326-25"]);

async function main() {
  const auth = new google.auth.GoogleAuth({
    keyFile: process.env.GOOGLE_APPLICATION_CREDENTIALS || path.join(__dirname, "..", "nomadic-bedrock-485314-b0-d7624dedd83c.json"),
    scopes: ["https://www.googleapis.com/auth/spreadsheets.readonly"],
  });
  const sheets = google.sheets({ version: "v4", auth: await auth.getClient() });
  const response = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${sheetName}!A:AZ`,
    valueRenderOption: "UNFORMATTED_VALUE",
  });
  const rows = response.data.values || [];
  const headers = rows[0] || [];
  const col = (header, occurrence = 1) => {
    const matches = headers.flatMap((value, index) => String(value || "").trim().toLowerCase() === header.toLowerCase() ? [index] : []);
    if (matches.length < occurrence) throw new Error(`Missing header ${header} occurrence ${occurrence}`);
    return matches[occurrence - 1];
  };
  const columns = {
    offer: col("Артикул продавца"),
    model: col("Артикул производителя"),
    brand: col("brand"),
    smr: col("RS SMR"),
    reserve: col("РЕЗЕРВ"),
    msk: col("RS MSK"),
    moscow: col("РУССКИЙ СВЕТ МОСКВА"),
  };
  const records = rows.slice(1).flatMap((row, index) => {
    if (!offers.has(String(row[columns.offer] || "").trim())) return [];
    return [{
      row: index + 2,
      offer: row[columns.offer],
      model: row[columns.model],
      brand: row[columns.brand],
      rsSmr: row[columns.smr],
      reserve: row[columns.reserve],
      rsMsk: row[columns.msk],
      moscow: row[columns.moscow],
    }];
  });
  console.log("SHEET", JSON.stringify(records));
  for (const warehouseId of [RS_OZON_WAREHOUSE_ID, RS_OZON_MOSCOW_WAREHOUSE_ID]) {
    const stocks = await fetchOzonStocksByOfferIds([...offers], warehouseId);
    console.log("OZON", JSON.stringify({ warehouseId, stocks: Object.fromEntries(stocks) }));
  }
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exit(1);
});
