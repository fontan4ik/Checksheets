"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const {
  buildStockReport,
  stockSyncFailure,
  throwOnStockSyncFailures,
} = require("../stock_sync_report");

const clean = buildStockReport({
  marketplace: "ВБ",
  warehouseName: "ВольтМир",
  sourcePositiveSku: 8,
  attemptedSku: 10,
  acceptedSku: 8,
  skippedSku: 2,
  verification: { status: "verified", positiveSku: 8, pieces: 22, mismatchSku: 0 },
  runId: "audit-run",
  snapshotReadAt: "2026-09-22T00:00:00.000Z",
  snapshotSources: { wb_stock: "AB:WB ВОЛЬТМИР ИТОГ" },
});
assert.deepStrictEqual(
  {
    sourcePositiveSku: clean.sourcePositiveSku,
    attemptedSku: clean.attemptedSku,
    acceptedSku: clean.acceptedSku,
    skippedSku: clean.skippedSku,
    errorSku: clean.errorSku,
    verifiedPositiveSku: clean.verifiedPositiveSku,
    verifiedPieces: clean.verifiedPieces,
    mismatchSku: clean.mismatchSku,
    verificationStatus: clean.verificationStatus,
  },
  { sourcePositiveSku: 8, attemptedSku: 10, acceptedSku: 8, skippedSku: 2, errorSku: 0, verifiedPositiveSku: 8, verifiedPieces: 22, mismatchSku: 0, verificationStatus: "verified" },
);
assert.strictEqual(stockSyncFailure(clean), null);
assert.strictEqual(
  stockSyncFailure(buildStockReport({ marketplace: "Ozon", skippedSku: 3, verification: { status: "verified" } })),
  null,
  "terminal Ozon product errors are expected skips, not a failed run",
);

const transportFailure = buildStockReport({ marketplace: "ВБ", warehouseName: "ВольтМир", errorSku: 10 });
assert.match(stockSyncFailure(transportFailure), /10/);
assert.throws(() => throwOnStockSyncFailures([transportFailure]), /необработанных ошибок/);

const mismatchFailure = buildStockReport({ marketplace: "ВБ", warehouseName: "ВольтМир", verification: { status: "mismatch", mismatchSku: 21 } });
assert.match(stockSyncFailure(mismatchFailure), /21/);
assert.throws(() => throwOnStockSyncFailures([mismatchFailure]), /расхождения/);

assert.throws(
  () => throwOnStockSyncFailures([buildStockReport({ marketplace: "ВБ", verification: { status: "incomplete" } })]),
  /неполностью/,
);

for (const scriptName of ["sync-etm-stocks.js", "sync-feron-stocks.js"]) {
  const source = fs.readFileSync(path.join(__dirname, "..", scriptName), "utf8");
  assert.match(source, /ignoredOfferIds/, `${scriptName} must exclude terminal Ozon SKU from post-check`);
  assert.match(source, /if \(r\.updated\)[\s\S]{0,240}else if \(r\.errors/, `${scriptName} must prefer updated over a co-reported error`);
}
console.log("stock sync report metrics/exit policy: OK");
