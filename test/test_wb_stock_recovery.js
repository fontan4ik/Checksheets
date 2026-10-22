"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");
const { createWbStockAudit } = require("../wb_stock_audit");

function loadFunction(filename, name, nextName, overrides = {}) {
  const source = fs.readFileSync(path.join(__dirname, "..", filename), "utf8");
  const start = source.indexOf(`async function ${name}(`);
  const end = source.indexOf(`async function ${nextName}(`, start);
  const context = vm.createContext({
    log() {}, wbHeaders: () => ({}), WB_BASE_DELAY: 1, WB_MAX_RETRIES: 3,
    // Ownership behavior is covered by test_ntc_wb_ownership; isolate HTTP recovery here.
    isNtcCloudWbOwned: () => false, refreshNtcCloudWbOwnership: async () => {},
    google: { sheets: () => ({}) }, ETM_TR_WB_WAREHOUSE: 798761,
    setTimeout: (callback) => callback(),
    wbRequestLimiter: { waitTurn: async () => {}, chargeResponse: async () => {} },
    isTransportError: (code) => code === 0, isWBCargoRestrictionError: () => true,
    ...overrides,
  });
  vm.runInContext(source.slice(start, end), context);
  return context[name];
}

for (const [filename, name, nextName] of [
  ["sync-feron-stocks.js", "sendFeronWBStocksBatch", "processFeronWBConflictIndividually"],
  ["sync-etm-stocks.js", "sendETMStocksBatch", "processETMConflictIndividually"],
]) {
  for (const code of [0, 500, 503]) {
    test(`${filename} retries transient WB ${code} and accepts recovery`, async () => {
      let calls = 0;
      const fn = loadFunction(filename, name, nextName, {
        axios: { put: async () => {
          if (++calls === 1) throw { message: "temporary", response: code ? { status: code, data: {} } : undefined };
          return { status: 204 };
        } },
      });
      const result = await fn([{ chrtId: 1, amount: 4 }], 798761);
      assert.equal(calls, 2);
      assert.equal(result.ok, true);
    });
  }
  test(`${filename} does not retry permanent 409 cargo restrictions`, async () => {
    let calls = 0;
    const fn = loadFunction(filename, name, nextName, {
      axios: { put: async () => { calls++; throw { response: { status: 409, data: {} } }; } },
    });
    assert.equal((await fn([], 798761)).cargoRestriction, true);
    assert.equal(calls, 1);
  });
}

test("WB repair preserves confirmed cargo mismatch without sending an impossible repair", async () => {
  const fn = loadFunction("sync-etm-stocks.js", "repairETMWBMismatches", "main", {
    STOCK_REPAIR_ATTEMPTS: 2,
    createWbStockAudit: () => { throw new Error("must not write"); },
  });
  const mismatches = [{ chrtId: 1, sheet: 4, wb: 0 }];
  const result = await fn([{ chrlid: 1, offer_id: "ART" }], mismatches, new Set([1]));
  assert.equal(result.length, 1);
  assert.equal(result.cargoRestrictedSku, 1);
});

test("WB repair records payload, checksum and batch outcome", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "wb-repair-test-"));
  try {
    const fn = loadFunction("sync-etm-stocks.js", "repairETMWBMismatches", "main", {
      STOCK_REPAIR_ATTEMPTS: 1, STOCK_REPAIR_DELAY_MS: 0,
      ETM_TR_WB_WAREHOUSE: 798761, SHEET_NAME: "StreamSupps", sleep: async () => {},
      createWbStockAudit: (options) => createWbStockAudit({ ...options, logDirectory: directory }),
      sendETMStocksBatch: async () => ({ ok: true, code: 204 }),
      verifyETMWBStocks: async () => [],
    });
    const stocks = [{ chrlid: 1, offer_id: "ART" }];
    stocks.snapshotReadAt = new Date().toISOString();
    stocks.wbSourceColumn = "AB:WB ВОЛЬТМИР ИТОГ";
    await fn(stocks, [{ chrtId: 1, sheet: 4, wb: 0 }]);
    const events = fs.readFileSync(path.join(directory, fs.readdirSync(directory)[0]), "utf8").trim().split("\n").map(JSON.parse);
    const payload = events.find((event) => event.event === "payload_prepared");
    const result = events.find((event) => event.event === "batch_result");
    assert.equal(payload.items[0].offerId, "ART");
    assert.equal(payload.sourceColumn, stocks.wbSourceColumn);
    assert.equal(result.checksum, payload.checksum);
    assert.equal(result.successCount, 1);
  } finally { fs.rmSync(directory, { recursive: true, force: true }); }
});

for (const [filename, name, nextName, sender] of [
  ["sync-etm-stocks.js", "processETMConflictIndividually", "updateETMStocksWB", "sendETMStocksBatch"],
  ["sync-feron-stocks.js", "processFeronWBConflictIndividually", "updateFeronStocksWB", "sendFeronWBStocksBatch"],
]) {
  test(`${filename} records exhausted 429 as an alerted error with checksum`, async () => {
    const records = [];
    const fn = loadFunction(filename, name, nextName, {
      [sender]: async () => ({ ok: false, code: 429, text: "MAX_RETRIES_EXCEEDED" }),
    });
    const result = await fn([{ chrtId: 1, amount: 4 }], 798761, "test", {
      audit: { recordItemResult: (record) => records.push(record) },
      itemsByChrtId: new Map([[1, { offerId: "ART" }]]), batchIndex: 1, checksum: "prepared-checksum",
    });
    assert.equal(result.errorCount, 1);
    assert.equal(result.skippedCount, 0);
    assert.equal(records[0].checksum, "prepared-checksum");
    assert.equal(records[0].status, "rate_limited");
  });
}

test("confirmed cargo mismatch remains an actionable failure", () => {
  const { buildStockReport, stockSyncFailure } = require("../stock_sync_report");
  const report = buildStockReport({ marketplace: "ВБ", warehouseName: "ВольтМир", cargoRestrictedSku: 55,
    verification: { status: "mismatch", mismatchSku: 55 } });
  assert.match(stockSyncFailure(report), /ODC\/CD\+: 55/);
  assert.match(stockSyncFailure(report), /запрещает/);
});
