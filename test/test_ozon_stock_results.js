"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const { reconcileOzonStockResults, isOzonWarehouseRestriction } = require("../ozon_stock_results");

const batch = [{ offer_id: "A" }, { offer_id: "B" }];
const results = reconcileOzonStockResults(batch, { result: [
  { offer_id: "A", updated: true, warehouse_id: 42 },
  { offer_id: "A", updated: true, warehouse_id: 42 },
  { offer_id: "B", updated: true, warehouse_id: 99 },
  { offer_id: "UNREQUESTED", updated: true },
] }, 42);
assert.strictEqual(results.length, 2);
assert.strictEqual(results[0].errors[0].code, "AMBIGUOUS_RESULT");
assert.strictEqual(results[1].errors[0].code, "MISSING_RESULT");
assert.strictEqual(reconcileOzonStockResults(batch, null, 42).length, 2);
assert.strictEqual(reconcileOzonStockResults(batch, { result: [{ offer_id: "A", updated: true }] }, 42)[0].updated, true);
assert(isOzonWarehouseRestriction({ errors: [{ code: "OVER_MAX_OVH_NON_KGT" }] }));
assert(!isOzonWarehouseRestriction({ errors: [{ code: "OVER_MAX_OVH_NON_KGT" }, { code: "UNKNOWN" }] }));
assert(!isOzonWarehouseRestriction({ errors: [] }));

// Exercise the actual ETM repair function without initializing live API clients.
const source = fs.readFileSync(path.join(__dirname, "../sync-etm-stocks.js"), "utf8");
const start = source.indexOf("async function repairETMOzonMismatches(");
const end = source.indexOf("async function updateETMStocksOzonWithRetry(", start);
let writes = 0;
const logs = [];
const mismatch = [{ offer_id: "A", sheet: 3, free: 0 }];
const context = {
  STOCK_REPAIR_ATTEMPTS: 2, STOCK_REPAIR_DELAY_MS: 0, OZON_STOCKS_RPS: 1,
  ETM_TR_OZON_WAREHOUSE: 42, lastRequestTime: 0,
  rateLimitRPS: async () => 0, sleep: async () => {},
  log: (message) => logs.push(message), reconcileOzonStockResults,
  verifyETMOzonStocks: async () => [],
  updateETMStocksOzonWithRetry: async () => {
    writes++;
    return { ok: true, data: { result: [{ offer_id: "A", updated: false, errors: [{ code: "TOO_MANY_REQUESTS" }] }] } };
  },
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
(async () => {
  const blocked = await context.repairETMOzonMismatches([], mismatch, { restrictedOfferIds: new Set(["A"]) });
  assert.strictEqual(writes, 0, "persistent size restrictions must not be resent during repair");
  assert.strictEqual(blocked.length, 1, "the failed product must remain visible in verification");
  await context.repairETMOzonMismatches([], mismatch);
  assert.strictEqual(writes, 1);
  assert(logs.some((message) => message.includes("✅ 0, ❌ 1")), "TOO_MANY_REQUESTS is not an accepted update");
  console.log("Ozon stock result and ETM repair regression checks passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
