"use strict";
// Seed ownership is retained even when a migrated offer is removed from the catalog.
// Every local WB writer initializes ownership before targeting ВольтМир.
// While disconnected, initialization uses only the frozen verified catalog.
// Other offers and warehouses retain their existing writers, including zero modes.
const NTC_WB_WAREHOUSE_ID = 798761;
const NTC_CLOUD_OFFERS = Object.freeze(["1029089-10", "1029089-3", "1029089-5", "1029096-10", "1029096-3", "1029096-5", "2851987-10", "2851987-3", "2851987-5", "2852007-10", "2852007-3", "2852007-5", "5006065-10", "5006065-3", "5006065-5", "5032873-10", "5032873-3", "5032873-5", "5032903-10", "5032903-3", "5032903-5"]);
const NTC_SPREADSHEET_ID = "1i35SfWZljNR63GEkPuwgU2zVSU_Y2CWoxcRK-LcpjUo";
// User-requested disconnect, 2026-10-19: StreamSupps must not read the NTC book.
// Keep the last verified ownership so disconnecting cannot start overwriting NTC stocks.
// Resume live catalog synchronization only on an explicit user request.
const NTC_LIVE_CATALOG_SYNC_ENABLED = false;
const NTC_FROZEN_OWNERSHIP = Object.freeze([["2851987-3", "348088373"], ["2851987-5", "348088348"], ["2851987-10", "348088288"], ["2852007-3", "348088290"], ["2852007-5", "348088384"], ["2852007-10", "348088383"], ["5006065-3", "348088410"], ["5006065-10", "348088475"], ["5006065-5", "348088415"], ["5032873-3", "348088356"], ["5032873-5", "348088243"], ["5032873-10", "348088404"], ["1029089-10", "348088335"], ["1029089-3", "348088279"], ["1029089-5", "348088425"], ["5032903-5", "348088258"], ["5032903-3", "348088392"], ["5032903-10", "348088371"], ["1029096-3", "348088292"], ["1029096-5", "348088284"], ["1029096-10", "348088464"], ["55189-20", "690079098"], ["55189-10", "292073381"], ["55189-5", "292073478"]]);
let owned = new Set(NTC_CLOUD_OFFERS);
let ownedChrtIds = new Set();
let liveVerified = false;

async function refreshNtcCloudWbOwnership(sheets) {
  if (!NTC_LIVE_CATALOG_SYNC_ENABLED) {
    owned = new Set([...NTC_CLOUD_OFFERS, ...NTC_FROZEN_OWNERSHIP.map(item => item[0])]);
    ownedChrtIds = new Set(NTC_FROZEN_OWNERSHIP.map(item => item[1]));
    liveVerified = true;
    return { offers: owned.size, chrtIds: ownedChrtIds.size, liveSyncEnabled: false };
  }
  liveVerified = false;
  if (!sheets?.spreadsheets?.values?.get) throw new Error("NTC ownership: Sheets client required; WB 798761 writes blocked");
  try {
    const response = await sheets.spreadsheets.values.get({
      spreadsheetId: NTC_SPREADSHEET_ID,
      range: "'НТЦ списания'!A:ZZ",
      valueRenderOption: "UNFORMATTED_VALUE",
    });
    const rows = response.data?.values;
    if (!Array.isArray(rows) || rows.length < 2) throw new Error("empty NTC catalog");
    const headers = rows[0].map(value => String(value || "").trim());
    function column(header) {
      const matches = headers.flatMap((value, index) => value === header ? [index] : []);
      if (matches.length !== 1) throw new Error("missing or duplicate header: " + header);
      return matches[0];
    }
    const offerColumn = column("Артикул продавца"), chrtColumn = column("chrlid");
    const liveOffers = new Set(), liveChrtIds = new Set();
    for (const row of rows.slice(1)) {
      const offer = String(row[offerColumn] || "").trim();
      if (!offer) continue;
      liveOffers.add(offer);
      const chrt = String(row[chrtColumn] || "").trim();
      if (chrt) {
        if (!/^[1-9]\d*$/.test(chrt)) throw new Error("invalid NTC chrlid");
        liveChrtIds.add(chrt);
      }
    }
    if (!liveOffers.size) throw new Error("no NTC offers");
    // Union protects deleted offers during the current run as well as the migration seed.
    owned = new Set([...owned, ...liveOffers]);
    ownedChrtIds = new Set([...ownedChrtIds, ...liveChrtIds]);
    liveVerified = true;
    return { offers: owned.size, chrtIds: ownedChrtIds.size };
  } catch (error) {
    throw new Error("NTC ownership refresh failed; WB 798761 writes blocked: " + error.message);
  }
}
function requireLiveOwnership(warehouseId) {
  if (Number(warehouseId) === NTC_WB_WAREHOUSE_ID && !liveVerified) {
    throw new Error("NTC ownership has not been verified; WB 798761 writes blocked");
  }
}
function isNtcCloudWbOwned(warehouseId, offerId, chrtId) {
  requireLiveOwnership(warehouseId);
  return Number(warehouseId) === NTC_WB_WAREHOUSE_ID && (
    owned.has(String(offerId || "").trim()) || ownedChrtIds.has(String(chrtId || "").trim())
  );
}
function filterLocalWbOwned(stocks, warehouseId) {
  requireLiveOwnership(warehouseId);
  return stocks.filter(item => !isNtcCloudWbOwned(warehouseId,
    item.offer_id || item.offerId, item.chrlid || item.chrt_id || item.chrtId));
}
module.exports = {NTC_WB_WAREHOUSE_ID, NTC_CLOUD_OFFERS, refreshNtcCloudWbOwnership, isNtcCloudWbOwned, filterLocalWbOwned};
