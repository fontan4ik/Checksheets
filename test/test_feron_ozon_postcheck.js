#!/usr/bin/env node

const assert = require("assert");
const {
  fetchOzonWarehouseStocksByOfferId,
  verifyFeronOzonWarehouse,
} = require("../sync-feron-stocks");

async function run() {
  const calls = [];
  const warehouseId = 123;
  const items = Array.from({ length: 101 }, (_, index) => ({
    offer_id: `FERON-${String(index + 1).padStart(3, "0")}`,
    stock_msk: (index % 9) + 1,
  }));
  const httpClient = {
    post: async (_url, body) => {
      calls.push(body);
      const products = body.offer_id.flatMap((offerId) => {
        const item = items.find((candidate) => candidate.offer_id === offerId);
        const rows = [{
          offer_id: offerId,
          warehouse_id: warehouseId,
          free_stock: item.stock_msk,
          reserved: 2,
          present: item.stock_msk + 2,
        }];
        // The endpoint can return other warehouse rows even when a warehouse
        // filter was supplied; they must not override the requested warehouse.
        rows.push({
          offer_id: offerId,
          warehouse_id: 999,
          free_stock: 500,
          reserved: 0,
          present: 500,
        });
        return offerId === "FERON-101" ? rows.slice(1) : rows;
      });
      return { data: { products } };
    },
  };

  const actual = await fetchOzonWarehouseStocksByOfferId(items, warehouseId, httpClient);
  assert.strictEqual(calls.length, 2, "post-check requests are limited to 100 offers");
  assert.strictEqual(calls[0].offer_id.length, 100);
  assert.strictEqual(calls[1].offer_id.length, 1);
  assert.strictEqual(calls[0].limit, 1000);
  assert.strictEqual(calls[0].sku, undefined, "requests should use offer_id consistently");
  assert.strictEqual(actual.get("FERON-001").free_stock, items[0].stock_msk);
  assert.strictEqual(actual.has("FERON-101"), false, "foreign warehouse rows are ignored");

  calls.length = 0;
  const mismatches = await verifyFeronOzonWarehouse(
    items,
    { id: warehouseId, name: "Feron test", col: "stock_msk" },
    { httpClient },
  );
  assert.strictEqual(calls.length, 2);
  assert.deepStrictEqual(
    mismatches.map((item) => item.offer_id),
    ["FERON-101"],
    "verification compares free_stock and flags only the missing target-warehouse row",
  );
  assert.strictEqual(mismatches[0].actual, 0);

  console.log("Feron Ozon post-check regression test: OK");
}

run().catch((error) => {
  console.error(error.stack || error);
  process.exit(1);
});
