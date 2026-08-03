const assert = require("assert");

const cdek = require("../sync-cdek-stocks");
const ozon = require("../sync-cdek-ozon-stocks");

async function testCdekStockCalculation() {
  const calls = [];
  const httpClient = { get: async (url) => {
    const model = new URL(url).searchParams.get("filter[0][value]");
    calls.push(model);
    const product_offer = model === "100"
      ? [
        { article: "100", items: [{ state: "normal", count: 3 }, { state: "booked", count: 9 }, { state: "normal", count: "2" }] },
        { article: "other", items: [{ state: "normal", count: 100 }] },
      ]
      : [];
    return {
      status: 200,
      headers: { "content-type": "application/json" },
      data: { _embedded: { product_offer }, _links: {} },
    };
  }};
  const stocks = await cdek.loadStocks(["100", "200"], { Accept: "application/json" }, httpClient);
  assert.deepStrictEqual(calls, ["100", "200"]);
  assert.strictEqual(stocks.get("100"), 5);
  assert.strictEqual(stocks.get("200"), 0);
}

function testCdekBypassInterface() {
  assert.deepStrictEqual(cdek.getCdekBypassInterface({
    en0: [{ family: "IPv4", internal: false, address: "192.168.1.5" }],
  }, ""), { interfaceName: "en0", sourceIp: "192.168.1.5" });
}

async function testOzonUploadAndVerification() {
  const calls = [];
  const httpClient = { post: async (url, body) => {
    calls.push({ url, body });
    if (url.endsWith("/v2/products/stocks")) {
      return { data: { result: body.stocks.map((stock) => ({ offer_id: stock.offer_id, updated: true, errors: [] })) } };
    }
    return { data: { products: body.offer_id.map((offer_id) => ({ offer_id, warehouse_id: 1020002321437000, free_stock: offer_id === "a" ? 7 : 0 })) } };
  }};
  const stocks = [{ offer_id: "a", stock: 7 }, { offer_id: "b", stock: 0 }];
  assert.strictEqual(await ozon.uploadStocks(stocks, {}, httpClient), 2);
  const actual = await ozon.fetchOzonStocks(stocks, {}, httpClient);
  assert.strictEqual(actual.get("a"), 7);
  assert.strictEqual(actual.get("b"), 0);
  assert.strictEqual(calls.length, 2);
}

async function testSheetInputValidation() {
  const sheets = {
    spreadsheets: {
      values: {
        get: async () => ({ data: { values: [["art", "tr"], ["a", "5"], ["b", "-1"], ["c", "not-a-number"]] } }),
      },
    },
  };
  assert.deepStrictEqual(await ozon.readCdekStocks(sheets), [
    { offer_id: "a", stock: 5 },
    { offer_id: "b", stock: 0 },
    { offer_id: "c", stock: 0 },
  ]);
}

function testLegacyOzonCredentials() {
  const credentials = ozon.parseLegacyOzonCredentials(
    'const clientId = process.env.OZON_CLIENT_ID || "test-client";\n' +
    'const apiKey =\n  process.env.OZON_API_KEY || "test-key";',
  );
  assert.deepStrictEqual(credentials, { clientId: "test-client", apiKey: "test-key" });
}

async function testOzonRetry() {
  let attempts = 0;
  const httpClient = { post: async () => {
    attempts += 1;
    if (attempts === 1) {
      const error = new Error("temporary Ozon error");
      error.response = { status: 500 };
      throw error;
    }
    return { data: { result: [{ offer_id: "retry", updated: true, errors: [] }] } };
  }};
  assert.strictEqual(await ozon.uploadBatch([{ offer_id: "retry", stock: 1 }], {}, httpClient), 1);
  assert.strictEqual(attempts, 2);
}

(async () => {
  await testCdekStockCalculation();
  testCdekBypassInterface();
  await testOzonUploadAndVerification();
  await testSheetInputValidation();
  testLegacyOzonCredentials();
  await testOzonRetry();
  console.log("PASS test_cdek_node_sync");
})().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
