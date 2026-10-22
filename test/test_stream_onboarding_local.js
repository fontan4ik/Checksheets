"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { runPipeline } = require("../stream_onboarding_local");

test("future offers inserted above the historical row boundary are still new", async t => {
  const f=fixture(t);
  await f.run();
  f.calls.publish.length=0;
  f.rows.unshift({...f.rows[0],row:100,offer_id:'INSERTED'});
  await f.run();
  assert.equal(f.state().offers.INSERTED.baseline,false);
  assert.ok(f.calls.publish.some(p=>p.rows.some(r=>r.offer_id==='INSERTED')));
});

test("masked RS rows retain numeric cells but never earn a freshness checkpoint", async t => {
  const f=fixture(t);
  f.deps.runSourceJob=async job=>({job,finishedAt:new Date().toISOString(),...(job==='rs_sync'?{quarantinedModels:['MODEL']}:{})});
  await f.run();
  assert.equal(f.state().offers.NEW.rsQuarantined,true);
  assert.equal(f.state().offers.NEW.sourcesFingerprint,undefined);
  assert.equal(f.calls.publish.length,0);
});

test("supplier age uses the oldest completion, not the end of the combined run", async t => {
  const f=fixture(t),now=Date.now;
  f.deps.runSourceJob=async job=>{
    const result={job,finishedAt:new Date().toISOString()};
    if(job==='feron_sync')Date.now=()=>now()+16*60000;
    return result;
  };
  try {await assert.rejects(f.run(),/older than 15 minutes/);}finally{Date.now=now;}
  assert.equal(f.calls.publish.length,0);
  assert.equal(f.state().offers.NEW.sourcesFingerprint,undefined);
});

function fixture(t, overrides = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "checksheets-onboarding-test-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const stateFile = path.join(dir, "state.json");
  const rows = [{ row: 22488, offer_id: "NEW", model: "MODEL", brand: "Brand", sku: "123", pack: 1,
    code: "ETM-123", chrt: "456", etmRaw: 4, rsRaw: 3,
    feronRawMsk: 2, feronRawSmr: 1, feronRawNsb: 0, feronRawEkb: 0,
    etm: 4, rs: 3, feron_msk: 2, feron_smr: 1, feron_nsb: 0, feron_ekb: 0,
    wb_stock: 8, wb_moscow: 2, rsMoscow: 0, snapshotReadAt: new Date().toISOString() }];
  const calls = { sources: [], publish: [], prepare: [], resolve: [], leases: [], releases: [] };
  const deps = {
    async enrichTestCatalog() {return{added:0,enriched:0,pending:[]};},
    async prepareWbArticleIds() {return{written:0};},
    async prepareOborFormulas() {return{written:0,effectiveErrors:0};},
    async readIndex() { return { headers: [], columns: {}, index: rows.map(({ row, offer_id }) => ({ row, offer_id })) }; },
    async readRecords(_sheets, _index, offers) { return rows.filter(r => offers.has(r.offer_id)).map(r => ({ ...r })); },
    async resolveCatalog(_sheets, offers) {
      calls.resolve.push([...offers]);
      return { identities: new Map(offers.map(offer_id => [offer_id, { offer_id, unitReview: false }])), pending: [], packMap: {} };
    },
    async prepare(_sheets, options) {
      calls.prepare.push([...options.targetOffers]);
      return { changed: 0, offers: [], pending: [], report: { counts: {} } };
    },
    async prepareCatalogFormulas(_sheets, options) {
      return {changed:0,sheets:{},pending:[],errors:[]};
    },
    async runSourceJob(job, args) { calls.sources.push({ job, args }); return { job, finishedAt: new Date().toISOString() }; },
    async publish(_sheets, batch, { marketplace }) {
      calls.publish.push({ marketplace, rows: batch.map(r => ({ ...r })) });
      return { marketplace, verifiedOfferIds: batch.map(r => r.offer_id), pending: [] };
    },
    acquireLease(name) { calls.leases.push(name); return () => calls.releases.push(name); },
  };
  Object.assign(deps, overrides);
  return { rows, calls, deps, stateFile,
    run: () => runPipeline({ sheets: {}, stateFile, bootstrapThrough: 22487, deps }),
    state: () => JSON.parse(fs.readFileSync(stateFile, "utf8")) };
}

test("all source jobs must finish before any marketplace publication", async t => {
  const f = fixture(t);
  const run = f.deps.runSourceJob;
  f.deps.runSourceJob = async (job, args) => {
    await run(job, args);
    if (job === "rs_sync") throw Error("RS download failed");
    return { job, finishedAt: new Date().toISOString() };
  };
  await assert.rejects(f.run(), /RS download failed/);
  assert.deepEqual(f.calls.sources.map(c => c.job).sort(), ["etm_sync", "feron_sync", "rs_sync"]);
  assert.equal(f.calls.publish.length, 0);
  assert.equal(f.state().offers.NEW.sourcesFingerprint, undefined);
  assert.equal(f.state().offers.NEW.ozonFingerprint, undefined);
});

test("verified offers survive restart without repeating source jobs or publications", async t => {
  const f = fixture(t);
  await f.run();
  assert.deepEqual(f.calls.publish.map(c => c.marketplace), ["ozon", "wb"]);
  const state = f.state().offers.NEW;
  assert.ok(state.sourcesFingerprint);
  assert.equal(state.ozonFingerprint, state.sourcesFingerprint);
  assert.equal(state.wbFingerprint, state.sourcesFingerprint);
  f.calls.sources.length = 0; f.calls.publish.length = 0;
  f.calls.resolve.length = 0;
  await f.run();
  assert.equal(f.calls.sources.length, 0);
  assert.equal(f.calls.publish.length, 0);
  assert.equal(f.calls.resolve.length, 0, "Map catalog identities must persist their checked marker");
  assert.deepEqual(f.calls.releases, ["marketplace_ozon", "marketplace_wb"]);
});

test("late WB card discovery refreshes sources and earns its own verified checkpoint", async t => {
  const f = fixture(t); f.rows[0].chrt = "";
  await f.run();
  assert.deepEqual(f.calls.publish.map(c => c.marketplace), ["ozon"]);
  assert.equal(f.state().offers.NEW.wbFingerprint, undefined);
  f.rows[0].chrt = "987";
  f.calls.sources.length = 0; f.calls.publish.length = 0;
  await f.run();
  assert.equal(f.calls.sources.length, 3);
  const wb = f.calls.publish.find(c => c.marketplace === "wb");
  assert.equal(wb.rows[0].chrt_id, "987");
  assert.equal(f.state().offers.NEW.wbFingerprint, f.state().offers.NEW.sourcesFingerprint);
});

test("busy marketplace defers publication without claiming its checkpoint", async t => {
  const f = fixture(t);
  f.deps.acquireLease = name => name === "marketplace_wb" ? null : () => {};
  const report = await f.run();
  assert.deepEqual(f.calls.publish.map(c => c.marketplace), ["ozon"]);
  assert.ok(f.state().offers.NEW.ozonFingerprint);
  assert.equal(f.state().offers.NEW.wbFingerprint, undefined);
  assert.ok(report.publications.some(p => p.marketplace === "wb" && p.deferred === "marketplace_busy"));
});

for (const field of ["sku", "pack"]) {
  test(`unresolved ${field} prevents source runs and all publications`, async t => {
    const f = fixture(t); f.rows[0][field] = "";
    await f.run();
    assert.equal(f.calls.resolve.length, 1);
    assert.equal(f.calls.sources.length, 0);
    assert.equal(f.calls.publish.length, 0);
    assert.equal(f.state().offers.NEW.sourcesFingerprint, undefined);
  });
}

test("historical baseline through row 22487 is never repaired or republished", async t => {
  const f = fixture(t);
  f.rows.unshift({ row: 22487, offer_id: "OLD", sku: "", model: "", pack: "" });
  await f.run();
  assert.equal(f.state().offers.OLD.baseline, true);
  assert.deepEqual(f.calls.prepare, [["NEW"]]);
  assert.deepEqual(f.calls.resolve, [["NEW"]]);
  assert.ok(f.calls.publish.every(c => c.rows.every(r => r.offer_id === "NEW")));
});

test("duplicate offers are excluded before preparation and publication", async t => {
  const f = fixture(t); f.rows.push({ ...f.rows[0], row: 22489 });
  const report = await f.run();
  assert.deepEqual(report.duplicates, ["NEW"]);
  assert.equal(f.calls.prepare.length, 0);
  assert.equal(f.calls.sources.length, 0);
  assert.equal(f.calls.publish.length, 0);
  assert.equal(f.state().offers.NEW.ozonFingerprint, undefined);
});

test("identity changed during supplier downloads cannot acquire a source checkpoint", async t => {
  const f = fixture(t); const run = f.deps.runSourceJob;
  f.deps.runSourceJob = async (job, args) => {
    const result = await run(job, args);
    if (job === "rs_sync") f.rows[0].model = "CHANGED-MODEL";
    return result;
  };
  await f.run().catch(() => {});
  assert.equal(f.calls.publish.length, 0);
  assert.equal(f.state().offers.NEW.sourcesFingerprint, undefined);
});

for (const result of [false, undefined, { job: "rs_sync", success: false }]) {
  test(`fulfilled source result ${JSON.stringify(result)} is not proof of a source refresh`, async t => {
    const f = fixture(t); const run = f.deps.runSourceJob;
    f.deps.runSourceJob = async (job, args) => job === "rs_sync" ? result : run(job, args);
    await f.run().catch(() => {});
    assert.equal(f.calls.publish.length, 0);
    assert.equal(f.state().offers.NEW.sourcesFingerprint, undefined);
  });
}

test("catalog Map unit review survives restart and blocks publication", async t => {
  const f = fixture(t);
  f.deps.resolveCatalog = async () => ({ identities: new Map([["NEW", { offer_id: "NEW", unitReview: true }]]), packMap: {}, pending: [] });
  const report = await f.run();
  assert.equal(report.catalog.identities, 1);
  assert.equal(f.state().offers.NEW.unitReview, true);
  assert.ok(f.state().offers.NEW.catalogCheckedAt);
  assert.equal(f.calls.publish.length, 0);
  assert.equal(f.state().offers.NEW.sourcesFingerprint, undefined);
  await f.run();
  assert.equal(f.calls.publish.length, 0);
  assert.equal(f.state().offers.NEW.unitReview, true);
});

test("only API-verified offers earn publication checkpoints", async t => {
  const f = fixture(t);
  f.deps.publish = async (_sheets, batch, { marketplace }) => ({ marketplace, verifiedOfferIds: [],
    pending: batch.map(r => ({ offer_id: r.offer_id, reasons: ["readback_missing"] })) });
  await f.run();
  assert.ok(f.state().offers.NEW.sourcesFingerprint);
  assert.equal(f.state().offers.NEW.ozonFingerprint, undefined);
  assert.equal(f.state().offers.NEW.wbFingerprint, undefined);
});

test("identity changed after source refresh is rechecked under the marketplace lease", async t => {
  const f = fixture(t);
  f.deps.acquireLease = () => {
    f.rows[0].code = "REPLACED-CODE";
    return () => {};
  };
  await f.run();
  assert.ok(f.calls.publish.every(p => p.rows.length === 0));
  assert.equal(f.state().offers.NEW.ozonFingerprint, undefined);
  assert.equal(f.state().offers.NEW.wbFingerprint, undefined);
});

test('catalog formula preparation receives only managed offers before stock publication',async t=>{
  const f=fixture(t);let prepared=false;
  f.deps.prepareCatalogFormulas=async(_sheets,{targetOffers})=>{
    assert.deepEqual([...targetOffers],['NEW']);prepared=true;
    return{changed:12,sheets:{},pending:[{field:'AO'}],errors:[]};
  };
  const publish=f.deps.publish;
  f.deps.publish=async(...args)=>{assert.equal(prepared,true);return publish(...args);};
  const result=await f.run();assert.equal(result.catalogFormulas.changed,12);assert.equal(result.catalogFormulas.pendingInputs,1);
});

test('unsafe catalog formula layout blocks source and marketplace writes',async t=>{
  const f=fixture(t);f.deps.prepareCatalogFormulas=async()=>{throw Error('UNIT API: key moved from A');};
  await assert.rejects(f.run(),/key moved/);assert.equal(f.calls.sources.length,0);assert.equal(f.calls.publish.length,0);
});

test('TEST enrichment precedes dependent reads, OBOR, UNIT and stock work',async t=>{
 const f=fixture(t);let enriched=false,wb=false,obor=false;
 f.deps.enrichTestCatalog=async(_sheets,offers)=>{assert.deepEqual(offers,['NEW']);enriched=true;return{added:1,enriched:8,pending:[]};};
 f.deps.prepareWbArticleIds=async()=>{assert.equal(enriched,true);wb=true;return{written:1};};
 const read=f.deps.readRecords;f.deps.readRecords=async(...args)=>{assert.equal(enriched,true);assert.equal(wb,true);return read(...args);};
 f.deps.prepareOborFormulas=async(_sheets,offers)=>{assert.equal(enriched,true);assert.deepEqual(offers,['NEW']);obor=true;return{written:24};};
 f.deps.prepareCatalogFormulas=async()=>{assert.equal(obor,true);return{changed:0,pending:[],errors:[]};};
 const r=await f.run();assert.equal(r.testCatalog.added,1);assert.equal(r.oborFormulas.written,24);
});
