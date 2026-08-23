const assert = require("assert");
const {
  normalizeSku,
  skuFingerprint,
  quoteSheetName,
  isRetryable,
} = require("../ozon_reviews_local");

assert.strictEqual(normalizeSku(" 12345 "), "12345");
assert.strictEqual(normalizeSku(12345), "12345");
assert.strictEqual(normalizeSku("0"), "");
assert.strictEqual(normalizeSku(""), "");
assert.strictEqual(normalizeSku("not-a-sku"), "");
assert.strictEqual(quoteSheetName("ТЕСТ"), "'ТЕСТ'");
assert.strictEqual(quoteSheetName("A'B"), "'A''B'");
assert.strictEqual(skuFingerprint(["1", "2"]), skuFingerprint(["1", "2"]));
assert.notStrictEqual(skuFingerprint(["1", "2"]), skuFingerprint(["2", "1"]));
assert.strictEqual(isRetryable({ response: { status: 429 } }), true);
assert.strictEqual(isRetryable({ response: { status: 503 } }), true);
assert.strictEqual(isRetryable({ response: { status: 400 } }), false);
assert.strictEqual(isRetryable(new Error("network")), true);

console.log("ozon_reviews_local focused tests: OK");
