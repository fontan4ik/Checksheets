"use strict";

// The caller holds the existing marketplace lock for the entire send/readback.
const ETM_OZON_WAREHOUSE = 1020005000689690;
const FERON_FIELDS = { MSK: "stock_msk", SMR: "stock_smr", NSB: "stock_nsb", EKB: "stock_ekb" };
const SOURCE_FIELDS = { stock_msk: "feron_msk", stock_smr: "feron_smr", stock_nsb: "feron_nsb", stock_ekb: "feron_ekb" };

function quantity(value, brand) {
  if (typeof value === "boolean" || String(value ?? "").trim() === "" || !Number.isFinite(Number(value)) || Number(value) < 0) {
    throw new Error("missing_or_invalid_stock");
  }
  const amount = Math.trunc(Number(value));
  return amount === 1 && String(brand || "").trim().toLowerCase() !== "arlight" ? 0 : amount;
}

async function fetchWbStocks(chrtIds, warehouseId, options) {
  const http = options.httpClient || require("axios");
  const limiter = options.wbLimiter || require("./wb_stock_rate_limiter").createWbStockRateLimiter();
  const result = new Map();
  for (let offset = 0; offset < chrtIds.length; offset += 1000) {
    const ids = chrtIds.slice(offset, offset + 1000);
    await limiter.waitTurn();
    const response = await http.post(`https://marketplace-api.wildberries.ru/api/v3/stocks/${warehouseId}`,
      { chrtIds: ids.map(Number) }, { headers: options.wbHeaders(), timeout: 30000 });
    if (!Array.isArray(response.data?.stocks)) throw new Error("invalid_wb_stock_readback");
    for (const row of response.data.stocks) {
      if (row.amount === null || row.amount === undefined || !Number.isFinite(Number(row.amount))) continue;
      result.set(String(row.chrtId), Number(row.amount));
    }
  }
  return result;
}

async function publishOnboarding(sheets, records, options = {}) {
  const { marketplace, dryRun = false } = options;
  if (!["ozon", "wb"].includes(marketplace)) throw new Error("marketplace must be ozon or wb");
  const pending = new Map();
  const warehouses = [];
  const fail = (id, reason) => {
    if (!pending.has(id)) pending.set(id, new Set());
    pending.get(id).add(reason);
  };
  const count = (field) => records.reduce((map, row) => {
    const id = String(row[field] ?? "").trim();
    if (id) map.set(id, (map.get(id) || 0) + 1);
    return map;
  }, new Map());
  const offers = count("offer_id"), chrts = count("chrt_id");
  const rs = options.rs || require("./sync-rs-stocks");
  const feron = options.feron || require("./sync-feron-stocks");
  const paused = new Set(feron.readPausedFeronWarehouseKeys());
  const activeKeys = Object.keys(FERON_FIELDS).filter((key) => !paused.has(key));
  const rows = [];
  for (const record of records) {
    const id = String(record.offer_id ?? "").trim();
    if (!id || offers.get(id) !== 1) { fail(id, "missing_or_duplicate_offer_id"); continue; }
    if (marketplace === "wb" && (!/^[1-9]\d*$/.test(String(record.chrt_id)) ||
        !Number.isSafeInteger(Number(record.chrt_id)) || chrts.get(String(record.chrt_id)) !== 1)) {
      fail(id, "missing_or_ambiguous_chrt_id"); continue;
    }
    try {
      const row = { ...record, offer_id: id, chrt_id: String(record.chrt_id ?? "") };
      if (marketplace === "ozon") {
        row.etm = quantity(record.etm, record.brand);
        row.stock = quantity(record.rs, record.brand);
      } else {
        row.wb_stock = quantity(record.wb_stock, record.brand);
        row.stock_wb_feron_moscow = quantity(record.wb_moscow, record.brand);
        row.stock_wb_voltmir = row.wb_stock;
      }
      for (const key of activeKeys) {
        if (marketplace === "wb" && ["MSK", "SMR"].includes(key)) continue;
        row[FERON_FIELDS[key]] = quantity(record[SOURCE_FIELDS[FERON_FIELDS[key]]], record.brand);
      }
      if (!Number.isFinite(Date.parse(record.snapshotReadAt))) throw new Error("missing_snapshot_timestamp");
      rows.push(row);
    } catch (error) { fail(id, error.message); }
  }
  rows.snapshotReadAt = rows.length ? new Date(Math.min(...rows.map((row) => Date.parse(row.snapshotReadAt)))).toISOString() : null;
  rows.wbSourceColumns = {
    wb_stock: "AB:WB ВОЛЬТМИР ИТОГ",
    stock_wb_feron_moscow: "AC:WB ФЕРОН МОСКВА ИТОГ",
    stock_nsb: "НОВОСИБИРСК ФЕРОН", stock_ekb: "ЕКБ Ферон",
  };
  const finish = () => ({ marketplace, dryRun,
    verifiedOfferIds: rows.filter((row) => !pending.has(row.offer_id)).map((row) => row.offer_id),
    pending: [...pending].map(([offer_id, reasons]) => ({ offer_id, reasons: [...reasons] })), warehouses });
  if (!rows.length) return finish();
  if (dryRun) { for (const row of rows) fail(row.offer_id, "dry_run"); return finish(); }

  async function send(label, callback) {
    try { return await callback(); }
    catch (error) { for (const row of rows) fail(row.offer_id, `${label}: ${error.message}`); return null; }
  }
  async function verify(warehouseId, field, fetcher, idField, valueField) {
    try {
      const actual = await fetcher(rows.map((row) => row[idField]), warehouseId);
      let verified = 0;
      for (const row of rows) {
        const value = actual.get(String(row[idField]));
        const amount = valueField ? value?.[valueField] : value;
        if (amount !== undefined && amount !== null && Number(amount) === row[field]) verified += 1;
        else fail(row.offer_id, `readback:${warehouseId}:${amount === undefined ? "missing" : "mismatch"}`);
      }
      warehouses.push({ warehouseId, verified, attempted: rows.length });
    } catch (error) { for (const row of rows) fail(row.offer_id, `readback:${warehouseId}: ${error.message}`); }
  }
  function markUnaccepted(stats, warehouseId) {
    const skippedIds = new Set([...(stats?.skippedOfferIds || [])].map(String));
    for (const id of skippedIds) fail(id, `unavailable:${warehouseId}`);
    const errors = Math.max(Number(stats?.errorSku) || 0, Number(stats?.errorCount) || 0);
    const skipped = Math.max(Number(stats?.skippedSku) || 0, Number(stats?.skippedCount) || 0);
    if (stats?.acceptedOfferIds instanceof Set || Array.isArray(stats?.acceptedOfferIds)) {
      const acceptedIds = new Set([...stats.acceptedOfferIds].map(String));
      for (const row of rows) {
        if (!acceptedIds.has(row.offer_id)) fail(row.offer_id, `unaccepted:${warehouseId}`);
      }
      return;
    }
    // Existing senders do not identify every rejected item. Keep the entire
    // attempted set pending when acceptance cannot be attributed safely.
    if (errors > 0 || skipped > skippedIds.size) {
      for (const row of rows) fail(row.offer_id, `unaccepted:${warehouseId}`);
    }
  }
  if (marketplace === "ozon") {
    const targets = [
      { id: ETM_OZON_WAREHOUSE, field: "etm" },
      { id: rs.RS_OZON_WAREHOUSE_ID, field: "stock" },
    ];
    for (const target of targets) {
      const stats = await send(`send:${target.id}`, () => rs.updateRsStocksOzon(rows,
        { warehouseId: target.id, stockField: target.field, httpClient: options.httpClient }));
      markUnaccepted(stats, target.id);
    }
    const stats = await send("send:feron", () => feron.updateFeronStocksOzon(rows, paused));
    for (const warehouse of stats?.ozonWarehouseStats || []) markUnaccepted(warehouse, warehouse.warehouseId);
    targets.push(...activeKeys.map((key) => ({ id: feron.FERON_TR_OZON_WAREHOUSES[key], field: FERON_FIELDS[key] })));
    const fetcher = (ids, wh) => rs.fetchOzonStocksByOfferIds(ids, wh, 0, options.httpClient);
    for (const target of targets) await verify(target.id, target.field, fetcher, "offer_id", "freeStock");
  } else {
    const ownership = options.ownership || require("./ntc_wb_ownership");
    await ownership.refreshNtcCloudWbOwnership(sheets);
    for (const row of rows) {
      if (ownership.isNtcCloudWbOwned(rs.RS_WB_WAREHOUSE_ID, row.offer_id, row.chrt_id)) fail(row.offer_id, "wb_cloud_owned");
    }
    const abStats = await send("send:wb_voltmir", () => rs.updateRsStocksWb(rows, sheets));
    markUnaccepted(abStats, rs.RS_WB_WAREHOUSE_ID);
    // AB is sent exactly once above; AC stays with its regular audited writer.
    const feronStats = await send("send:wb_feron", () => feron.updateFeronStocksWB(rows, new Set([...paused, "SMR"])));
    for (const warehouse of feronStats || []) markUnaccepted(warehouse, warehouse.warehouseId);
    const fetcher = options.fetchWbStocks || ((ids, wh) => fetchWbStocks(ids, wh,
      { ...options, wbHeaders: options.wbHeaders || feron.wbHeaders }));
    const targets = [{ id: rs.RS_WB_WAREHOUSE_ID, field: "wb_stock" }];
    for (const key of activeKeys.filter((key) => key !== "SMR")) {
      const field = key === "MSK" ? "stock_wb_feron_moscow" : FERON_FIELDS[key];
      if (key === "EKB" && feron.FORCE_ZERO_WB_EKB) for (const row of rows) row[field] = 0;
      targets.push({ id: feron.FERON_TR_WB_WAREHOUSE[key], field });
    }
    for (const target of targets) await verify(target.id, target.field, fetcher, "chrt_id");
  }
  return finish();
}

module.exports = { publishOnboarding, fetchWbStocks, quantity, ETM_OZON_WAREHOUSE };
