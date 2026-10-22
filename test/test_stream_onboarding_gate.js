"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { gatePublication } = require("../stream_onboarding_gate");

function fixture(t, offers, extra = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "onboarding-gate-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, "state.json");
  fs.writeFileSync(file, JSON.stringify({ version: 1, enforcePublicationGate: true, offers, ...extra }));
  return { stateFile: file, logger: () => {} };
}
const ids = (rows) => rows.map((row) => row.offer_id);

test("allows historical baseline and excludes unknown/unverified new offers", (t) => {
  const options = fixture(t, { OLD: { baseline: true }, NEW: { baseline: false } });
  const rows = ["OLD", "NEW", "UNKNOWN"].map((offer_id) => ({ offer_id }));
  assert.deepEqual(ids(gatePublication(rows, "ozon", options)), ["OLD"]);
});

test("new offers require marketplace checkpoint and clear unit/quarantine state", (t) => {
  const options = fixture(t, {
    READY: { ozonFingerprint: "ok" }, UNIT: { ozonFingerprint: "ok", unitReview: true },
    RS: { ozonFingerprint: "ok", rsQuarantined: true }, WB: { wbFingerprint: "ok" },
  });
  const rows = ["READY", "UNIT", "RS", "WB"].map((offer_id) => ({ offer_id }));
  assert.deepEqual(ids(gatePublication(rows, "ozon", options)), ["READY"]);
  assert.deepEqual(ids(gatePublication(rows, "wb", options)), ["WB"]);
});

test("all requires WB checkpoint when a chrtId appears later", (t) => {
  const options = fixture(t, { NEW: { ozonFingerprint: "ok" } });
  assert.equal(gatePublication([{ offer_id: "NEW" }], "all", options).length, 1);
  assert.equal(gatePublication([{ offer_id: "NEW", chrt_id: 123 }], "all", options).length, 0);
  assert.equal(gatePublication([{ offer_id: "NEW", chrlid: 123 }], "all", options).length, 0);
  const state = JSON.parse(fs.readFileSync(options.stateFile)); state.offers.NEW.wbFingerprint = "verified";
  fs.writeFileSync(options.stateFile, JSON.stringify(state));
  assert.equal(gatePublication([{ offer_id: "NEW", chrt_id: 123 }], "all", options).length, 1);
});

test("filtered arrays retain original enumerable snapshot/source metadata", (t) => {
  const options = fixture(t, { OLD: { baseline: true } });
  const rows = [{ offer_id: "OLD" }, { offer_id: "UNKNOWN" }];
  rows.snapshotReadAt = "2026-10-20T12:00:00Z";
  rows.wbSourceColumns = { stock: "AB:WB ВОЛЬТМИР ИТОГ" };
  rows.wbSourceColumn = "AB";
  const filtered = gatePublication(rows, "wb", options);
  assert.equal(filtered.snapshotReadAt, rows.snapshotReadAt);
  assert.equal(filtered.wbSourceColumns, rows.wbSourceColumns);
  assert.equal(filtered.wbSourceColumn, rows.wbSourceColumn);
  assert.equal(rows.length, 2);
});

test("manual helper default and missing pre-install state retain legacy behavior", (t) => {
  const options = fixture(t, {}), rows = [{ offer_id: "NEW" }];
  assert.equal(gatePublication(rows, undefined, options), rows);
  fs.unlinkSync(options.stateFile);
  assert.equal(gatePublication(rows, "ozon", options), rows);
});

test("malformed state blocks instead of falling back to publication", (t) => {
  const options = fixture(t, {});
  for (const value of ["{", "null", JSON.stringify({ version: 1, offers: [], enforcePublicationGate: true }),
    JSON.stringify({ version: 1, offers: { NEW: { baseline: "true" } }, enforcePublicationGate: true })]) {
    fs.writeFileSync(options.stateFile, value);
    assert.throws(() => gatePublication([{ offer_id: "NEW" }], "ozon", options), /Invalid onboarding/);
  }
});

test("state file environment override and blocked-count logging work", (t) => {
  const options = fixture(t, { OLD: { baseline: true } }), previous = process.env.CHECKSHEETS_ONBOARDING_STATE_FILE;
  process.env.CHECKSHEETS_ONBOARDING_STATE_FILE = options.stateFile;
  try {
    const messages = [];
    const rows = gatePublication([{ offer_id: "OLD" }, { offer_id: "NEW" }], "ozon", { logger: (line) => messages.push(line) });
    assert.deepEqual(ids(rows), ["OLD"]);
    assert.match(messages[0], /allowed=1, blocked=1/);
  } finally {
    if (previous === undefined) delete process.env.CHECKSHEETS_ONBOARDING_STATE_FILE;
    else process.env.CHECKSHEETS_ONBOARDING_STATE_FILE = previous;
  }
});

test("all regular writer reads pass marketplace including refreshed WB snapshots", () => {
  const root = path.join(__dirname, "..");
  const rs = fs.readFileSync(path.join(root, "sync-rs-stocks.js"), "utf8");
  const etm = fs.readFileSync(path.join(root, "sync-etm-stocks.js"), "utf8");
  const feron = fs.readFileSync(path.join(root, "sync-feron-stocks.js"), "utf8");
  assert.match(rs, /stocks = await readRsStocksFromSheet\(sheets, marketplace\)/);
  assert.match(etm, /stocks = await readETMStocksFromSheet\(client, marketplace\)/);
  assert.match(etm, /wbStocks = await readETMStocksFromSheet\(client, "wb"\)/);
  assert.match(feron, /readFeronStocksWithRetries\(client, "исходный снимок", marketplace\)/);
  assert.match(feron, /readFeronStocksWithRetries\(client, "снимок перед WB", "wb"\)/);
});
