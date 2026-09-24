#!/usr/bin/env node

const assert = require("assert");
const {
  fetchOzonStocksByOfferIds,
  verifyRsOzonStocks,
  updateRsStocksOzon,
  wbRetryDelayMs,
} = require("../sync-rs-stocks");

async function run() {
  assert.strictEqual(wbRetryDelayMs({ "x-ratelimit-retry": "7" }, 3000), 7000,
    "WB 429 retry must respect the official retry header");
  assert.strictEqual(wbRetryDelayMs({}, 3000), 3000,
    "WB retry uses exponential fallback when no retry header is present");
  const calls = [];
  const httpClient = { post: async (_url, body) => {
    calls.push(body.offer_id);
    return {
      data: {
        products: body.offer_id.flatMap((offerId) => [
          {
            offer_id: offerId,
            warehouse_id: 10,
            free_stock: offerId === "A" ? 7 : 0,
            present: 99,
            reserved: 4,
          },
          { offer_id: offerId, warehouse_id: 999, free_stock: 123 },
        ]),
      },
    };
  }};

  const ids = Array.from({ length: 101 }, (_, index) => index === 0 ? "A" : `SKU-${index}`);
  const stocks = await fetchOzonStocksByOfferIds(ids, 10, 0, httpClient);
    assert.strictEqual(calls.length, 2, "post-check must request no more than 100 offers per call");
    assert.strictEqual(calls[0].length, 100);
    assert.strictEqual(calls[1].length, 1);
    assert.deepStrictEqual(stocks.get("A"), { freeStock: 7, present: 99, reserved: 4 });

    calls.length = 0;
    const result = await verifyRsOzonStocks([
      { offer_id: "A", stock: 7 },
      { offer_id: "B", stock: 3 },
    ], {
      warehouseId: 10,
      label: "test",
      httpClient,
      ignoredOfferIds: new Set(["B"]),
    });
    assert.strictEqual(result.mismatches.length, 0, "free_stock must be compared with the sent stock");

    const rejectedMissingResult = await updateRsStocksOzon(
      [{ offer_id: "MISSING-RESULT", stock: 4 }],
      {
        warehouseId: 10,
        label: "test missing result",
        httpClient: { post: async () => ({ status: 200, data: { result: [] } }) },
      },
    );
    assert.strictEqual(rejectedMissingResult.acceptedSku, 0, "an empty item result must not count as accepted");
    assert.strictEqual(rejectedMissingResult.errorSku, 1, "a missing item result is a write error");

    console.log("RS Ozon post-check regression test: OK");
}

run().catch((error) => {
  console.error(error.stack || error);
  process.exit(1);
});
