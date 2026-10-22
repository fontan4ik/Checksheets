"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { publishOnboarding, ETM_OZON_WAREHOUSE, fetchWbStocks } = require("../stream_onboarding_publish");

function setup() {
  const sent = [], states = new Map();
  const row = { offer_id: "NEW", sku: "123", chrt_id: "456", brand: "Feron", etm: 9, rs: 1,
    feron_msk: 4, feron_smr: 5, feron_nsb: 6, feron_ekb: 7, wb_stock: 12, wb_moscow: 4,
    snapshotReadAt: "2026-10-20T10:00:00Z" };
  const feronIds = { MSK: 11, SMR: 12, NSB: 13, EKB: 14 };
  const rs = {
    RS_OZON_WAREHOUSE_ID: 20, RS_WB_WAREHOUSE_ID: 798761,
    async updateRsStocksOzon(rows, { warehouseId, stockField }) {
      sent.push({ kind: "ozon", warehouseId, rows: rows.map((r) => ({ ...r })), stockField });
      states.set(warehouseId, new Map(rows.map((r) => [r.offer_id, { freeStock: r[stockField] }])));
      return {};
    },
    async fetchOzonStocksByOfferIds(ids, wh) { return states.get(wh) || new Map(); },
    async updateRsStocksWb(rows) {
      sent.push({ kind: "wb_ab", rows });
      states.set(798761, new Map(rows.map((r) => [r.chrt_id, r.wb_stock])));
    },
  };
  const feron = {
    readPausedFeronWarehouseKeys: () => new Set(["NSB", "EKB"]),
    FERON_TR_OZON_WAREHOUSES: feronIds,
    FERON_TR_WB_WAREHOUSE: { MSK: 1449484, SMR: 798761, NSB: 1724900, EKB: 1860503 },
    FORCE_ZERO_WB_EKB: true,
    async updateFeronStocksOzon(rows, paused) {
      sent.push({ kind: "feron_ozon", paused });
      for (const key of Object.keys(feronIds).filter((key) => !paused.has(key))) {
        states.set(feronIds[key], new Map(rows.map((r) => [r.offer_id, { freeStock: r[`stock_${key.toLowerCase()}`] }])));
      }
      return {};
    },
    async updateFeronStocksWB(rows, paused) {
      sent.push({ kind: "feron_wb", paused, rows });
      states.set(1449484, new Map(rows.map((r) => [r.chrt_id, r.stock_wb_feron_moscow])));
    },
  };
  const options = { marketplace: "ozon", rs, feron,
    ownership: { refreshNtcCloudWbOwnership: async () => {}, isNtcCloudWbOwned: () => false },
    fetchWbStocks: async (ids, wh) => states.get(wh) || new Map() };
  return { sent, states, row, options };
}

test("publishes new Ozon goods on active warehouses, verifies each and keeps Moscow off", async () => {
  const f = setup();
  const result = await publishOnboarding({}, [f.row], f.options);
  assert.deepEqual(result.verifiedOfferIds, ["NEW"]);
  assert.deepEqual(f.sent.filter((s) => s.kind === "ozon").map((s) => s.warehouseId), [ETM_OZON_WAREHOUSE, 20]);
  assert.equal(f.sent[0].rows[0].stock, 0);
  assert.deepEqual(result.warehouses.map((w) => w.warehouseId), [ETM_OZON_WAREHOUSE, 20, 11, 12]);
});

test("zero without an explicit readback row is pending", async () => {
  const f = setup(); f.row.rs = 0;
  f.options.rs.fetchOzonStocksByOfferIds = async () => new Map();
  const result = await publishOnboarding({}, [f.row], f.options);
  assert.deepEqual(result.verifiedOfferIds, []);
  assert.ok(result.pending[0].reasons.includes("readback:20:missing"));
});

test("dry-run and duplicate offers never send or complete", async () => {
  const f = setup();
  assert.deepEqual((await publishOnboarding({}, [f.row], { ...f.options, dryRun: true })).verifiedOfferIds, []);
  const result = await publishOnboarding({}, [f.row, { ...f.row }], f.options);
  assert.deepEqual(result.verifiedOfferIds, []);
  assert.equal(f.sent.length, 0);
});

test("missing quantities cannot become successful zero writes", async () => {
  const f = setup(); delete f.row.feron_msk;
  const result = await publishOnboarding({}, [f.row], f.options);
  assert.equal(f.sent.length, 0);
  assert.deepEqual(result.pending[0].reasons, ["missing_or_invalid_stock"]);
});

test("WB uses audited AB and AC senders once and preserves paused warehouses", async () => {
  const f = setup(); f.options.marketplace = "wb";
  const result = await publishOnboarding({}, [f.row], f.options);
  assert.deepEqual(result.verifiedOfferIds, ["NEW"]);
  assert.deepEqual(f.sent.map((s) => s.kind), ["wb_ab", "feron_wb"]);
  assert.deepEqual([...f.sent[1].paused].sort(), ["EKB", "NSB", "SMR"]);
  assert.deepEqual(result.warehouses.map((w) => w.warehouseId), [798761, 1449484]);
  assert.equal(Date.parse(f.sent[0].rows.snapshotReadAt), Date.parse(f.row.snapshotReadAt));
});

test("missing or ambiguous WB chrtId never sends", async () => {
  const f = setup(); f.options.marketplace = "wb";
  const rows = [f.row, { ...f.row, offer_id: "OTHER" }];
  const result = await publishOnboarding({}, rows, f.options);
  assert.equal(f.sent.length, 0);
  assert.equal(result.pending.length, 2);
});

test("WB cloud ownership cannot be checkpointed as local success", async () => {
  const f = setup(); f.options.marketplace = "wb";
  f.options.ownership.isNtcCloudWbOwned = () => true;
  const result = await publishOnboarding({}, [f.row], f.options);
  assert.deepEqual(result.verifiedOfferIds, []);
  assert.ok(result.pending[0].reasons.includes("wb_cloud_owned"));
});

test("WB readback uses the shared limiter and does not invent missing zeros", async () => {
  let turns = 0;
  const actual = await fetchWbStocks([456, 457], 798761, {
    wbLimiter: { waitTurn: async () => { turns++; } }, wbHeaders: () => ({}),
    httpClient: { post: async () => ({ data: { stocks: [{ chrtId: 456, amount: 0 }] } }) },
  });
  assert.equal(turns, 1);
  assert.equal(actual.get("456"), 0);
  assert.equal(actual.has("457"), false);
});

test("terminal sender skip stays pending even if a zero readback happens to match", async () => {
  const f = setup();
  const sender = f.options.rs.updateRsStocksOzon;
  f.options.rs.updateRsStocksOzon = async (...args) => {
    await sender(...args);
    return { skippedOfferIds: new Set(["NEW"]) };
  };
  const result = await publishOnboarding({}, [f.row], f.options);
  assert.deepEqual(result.verifiedOfferIds, []);
  assert.ok(result.pending[0].reasons.some((r) => r.startsWith("unavailable:")));
});

test("Arlight preserves a single unit while other brands suppress it", async () => {
  const f = setup(); f.row.brand = "Arlight";
  await publishOnboarding({}, [f.row], f.options);
  assert.equal(f.sent[0].rows[0].stock, 1);
});

test("a failed send leaves the record pending even when readback already matches", async () => {
  const f = setup();
  const sender = f.options.rs.updateRsStocksOzon;
  f.options.rs.updateRsStocksOzon = async (...args) => {
    await sender(...args);
    throw new Error("transport_error");
  };
  const result = await publishOnboarding({}, [f.row], f.options);
  assert.deepEqual(result.verifiedOfferIds, []);
  assert.ok(result.pending[0].reasons.some((reason) => reason.includes("transport_error")));
});

test("unsuccessful Ozon per-item stats prevent checkpoints despite matching old stocks", async () => {
  for (const failureStats of [{ errorSku: 1 }, { errorCount: 1 }, { skippedSku: 1 }, { skippedCount: 1 }]) {
    const f = setup(), sender = f.options.rs.updateRsStocksOzon;
    f.options.rs.updateRsStocksOzon = async (...args) => { await sender(...args); return failureStats; };
    const result = await publishOnboarding({}, [f.row], f.options);
    assert.deepEqual(result.verifiedOfferIds, []);
    assert.ok(result.pending[0].reasons.some((reason) => reason.startsWith("unaccepted:")));
  }
});

test("Feron per-warehouse rejection stats prevent Ozon and WB checkpoints", async () => {
  for (const marketplace of ["ozon", "wb"]) {
    const f = setup(); f.options.marketplace = marketplace;
    const method = marketplace === "ozon" ? "updateFeronStocksOzon" : "updateFeronStocksWB";
    const sender = f.options.feron[method];
    f.options.feron[method] = async (...args) => {
      await sender(...args);
      const warehouses = [{ warehouseId: marketplace === "ozon" ? 11 : 1449484, errorSku: 1 }];
      return marketplace === "ozon" ? { ozonWarehouseStats: warehouses } : warehouses;
    };
    const result = await publishOnboarding({}, [f.row], f.options);
    assert.deepEqual(result.verifiedOfferIds, []);
    assert.ok(result.pending[0].reasons.some((reason) => reason.startsWith("unaccepted:")));
  }
});

test("WB aggregate skipped results cannot be mistaken for accepted zero stocks", async () => {
  const f = setup(); f.options.marketplace = "wb";
  const sender = f.options.rs.updateRsStocksWb;
  f.options.rs.updateRsStocksWb = async (...args) => { await sender(...args); return { skippedCount: 1 }; };
  const result = await publishOnboarding({}, [f.row], f.options);
  assert.deepEqual(result.verifiedOfferIds, []);
  assert.ok(result.pending[0].reasons.includes("unaccepted:798761"));
});

test("explicit accepted IDs checkpoint verified rows independently of rejected matching old stock", async () => {
  const f = setup(), sender = f.options.rs.updateRsStocksOzon;
  f.options.rs.updateRsStocksOzon = async (...args) => {
    await sender(...args);
    return { acceptedOfferIds: new Set(["NEW"]), errorSku: 1, errorCount: 1 };
  };
  const result = await publishOnboarding({}, [f.row, { ...f.row, offer_id: "REJECTED", chrt_id: "457" }], f.options);
  assert.deepEqual(result.verifiedOfferIds, ["NEW"]);
  assert.deepEqual(result.pending.map((entry) => entry.offer_id), ["REJECTED"]);
  assert.ok(result.pending[0].reasons.some((reason) => reason.startsWith("unaccepted:")));
});

test("RS sender attributes accepted IDs only to updated true results", async () => {
  const { updateRsStocksOzon } = require("../sync-rs-stocks");
  const rows = ["ACCEPTED", "REJECTED", "MISSING"].map((offer_id) => ({ offer_id, stock: 4 }));
  const stats = await updateRsStocksOzon(rows, { warehouseId: 10,
    httpClient: { post: async () => ({ status: 200, data: { result: [
      { offer_id: "ACCEPTED", warehouse_id: 10, updated: true, errors: [] },
      { offer_id: "REJECTED", warehouse_id: 10, updated: false, errors: [{ code: "OVER_MAX_OVH_NON_KGT", message: "warehouse restriction" }] },
    ] } }) } });
  assert.deepEqual([...stats.acceptedOfferIds], ["ACCEPTED"]);
  assert.equal(stats.acceptedSku, 1);
  assert.equal(stats.errorSku, 2);
});
