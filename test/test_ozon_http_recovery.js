'use strict';
const assert = require('assert');
const axios = require(require.resolve('axios', { paths: [require('path').resolve(__dirname, '..')] }));
const { mapDifferencesBySku, readSheetWithRetry, ozonPost } = require('../ozon_discount_auto_approve_local');
const { request } = require('../ozon_fbo_fbs_sales_local');
const { requestBuyouts } = require('../ozon_buyout_periods_local');

async function main() {
  const result = mapDifferencesBySku([['header', 'SKU'], ['a', '100'], ['b', '100'], ['a', '100'], ['c', '200']], 1,
    new Map([['a', 10], ['b', 20], ['c', 15]]));
  assert.deepStrictEqual(result.conflictingSkus, ['100']);
  assert.deepStrictEqual({ ...result.differenceBySku }, { 200: 15 });
  const originalPost = axios.post;
  const originalTimer = global.setTimeout;
  const waits = [];
  global.setTimeout = (callback, delay) => { waits.push(delay); callback(); };
  process.env.OZON_CLIENT_ID = 'test';
  process.env.OZON_API_KEY = 'test';
  try {
    let reads = 0;
    assert.equal(await readSheetWithRetry(async () => {
      if (++reads === 1) throw Object.assign(new Error('timeout'), { code: 'ETIMEDOUT' });
      return 'fresh';
    }), 'fresh');
    assert.equal(reads, 2);
    reads = 0;
    assert.equal(await readSheetWithRetry(async () => {
      if (++reads === 1) throw new Error('The operation was aborted.');
      return 'recovered';
    }), 'recovered');
    assert.equal(reads, 2, 'Gaxios timeout abort must retry');
    let calls = 0;
    axios.post = async () => { calls++; throw new Error('timeout'); };
    await assert.rejects(ozonPost('https://example.test/approve', {}, {}), /timeout/);
    assert.equal(calls, 1, 'approvals must not be replayed');
    calls = 0;
    axios.post = async () => ++calls === 1 ? { status: 429, headers: {}, data: {} } : { status: 200, data: { ok: true } };
    assert.deepStrictEqual(await request('https://example.test/read', {}, async () => {}), { ok: true });
    assert.equal(waits.at(-1), 30000);
    calls = 0;
    axios.post = async () => ++calls === 1 ? { status: 429, headers: {}, data: {} } : { status: 200, data: { products: [] } };
    assert.deepStrictEqual(await requestBuyouts('2026-01-01', '2026-01-31', {}, async () => {}), []);
    assert.equal(waits.at(-1), 60000);
    calls = 0;
    axios.post = async () => { calls++; return { status: 400, data: {} }; };
    await assert.rejects(requestBuyouts('2026-01-01', '2026-01-31', {}, async () => {}), /HTTP 400/);
    assert.equal(calls, 1);
  } finally {
    axios.post = originalPost;
    global.setTimeout = originalTimer;
  }
  console.log('PASS Ozon cooldowns, conflict quarantine and approval replay safety');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
