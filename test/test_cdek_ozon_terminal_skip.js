const assert = require("assert");
const ozon = require("../sync-cdek-ozon-stocks");

async function main() {
  const skipped = new Set();
  const stocks = [
    { offer_id: "known", stock: 7 },
    { offer_id: "not-in-ozon", stock: 5 },
    { offer_id: "archived", stock: 2 },
  ];
  const httpClient = { post: async () => ({ data: { result: [
    { offer_id: "known", updated: true, errors: [] },
    { offer_id: "not-in-ozon", updated: false, errors: [{ code: "NOT_FOUND_ERROR", message: "Product not found" }] },
    { offer_id: "archived", updated: false, errors: [{ code: "PRODUCT_IS_ARCHIVED", message: "Can't set positive stock to archived product" }] },
  ] } }) };
  assert.strictEqual(await ozon.uploadStocks(stocks, {}, httpClient, skipped), 1);
  assert.deepStrictEqual([...skipped], ["not-in-ozon", "archived"]);

  await assert.rejects(
    ozon.uploadBatch([{ offer_id: "real-failure", stock: 5 }], {}, {
      post: async () => ({ data: { result: [{
        offer_id: "real-failure", updated: false,
        errors: [{ code: "VALIDATION_ERROR", message: "Invalid stock" }],
      }] } }),
    }),
    /real-failure: VALIDATION_ERROR/,
  );
  console.log("PASS test_cdek_ozon_terminal_skip");
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
