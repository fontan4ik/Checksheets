import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";
import { normalizeSupplier } from "../worker/index.js";

const fixturePath = "/Users/vladimirgrebennikov/MultiAI/.runtime/evaluations/iek-card-correction-20261009/independent-fixtures-after/mapping-input-safe.json";
const fixtures = JSON.parse(readFileSync(fixturePath, "utf8")).products;
const expectedByArticle = new Map([
  ["KKME11-012-230-10", [77, 48, 88, 360]],
  ["KKME11-018-230-10", [77, 48, 88, 376]],
  ["KKME11-009-230-10", [77, 48, 88, 360]],
  ["KKME21-025-110-10", [85, 58, 100, 538]],
  ["KKME31-040-230-11", [128, 81, 120, 1240]],
  ["KKME41-095-230-11", [130, 90, 131, 1470]],
]);

// Execute the frozen ozonLocalPayload implementation with the candidate normalizer bound in.
const baseHarness = "/Users/vladimirgrebennikov/MultiAI/.runtime/evaluations/iek-card-correction-20261009/independent-fixtures-after/runs/20261009T124001142185Z/examined/worker-under-test.mjs";
const harnessSource = readFileSync(baseHarness, "utf8");
const boundSource = harnessSource
  .replace('"./worker/article-id.js"', '"../worker/article-id.js"')
  .replace('"./articles.mjs"', '"../articles.mjs"')
  .replace(/^function normalizeSupplier\(p\) \{/m,
    `function normalizeSupplier(p) { return globalThis.__candidateNormalizeSupplier(p); }\nfunction normalizeSupplierOriginal(p) {`);
const boundPath = resolve(new URL("../worker/worker-under-test-bound.mjs", import.meta.url).pathname);
await import("node:fs").then(({ writeFileSync }) => writeFileSync(boundPath, boundSource));
globalThis.__candidateNormalizeSupplier = normalizeSupplier;
const payloadWorker = await import(pathToFileURL(boundPath).href);

assert.equal(fixtures.length, 6, "use the six saved source product fixtures, not synthetic flat aliases");
for (const sourceProduct of fixtures) {
  const normalized = normalizeSupplier(sourceProduct);
  const expected = expectedByArticle.get(sourceProduct.article);
  assert.ok(expected, `unexpected source fixture ${sourceProduct.article}`);
  assert.deepEqual([normalized.length, normalized.width, normalized.height, normalized.weight],
    [expected[0], expected[1], expected[2], expected[3] / 1000], `${sourceProduct.article} normalized canonical mm/kg`);
  const payload = payloadWorker.ozonLocalPayload({ article: sourceProduct.article }, normalized, `${sourceProduct.article}-1`).items[0];
  assert.deepEqual([payload.depth, payload.width, payload.height, payload.weight, payload.dimension_unit, payload.weight_unit],
    [expected[0], expected[1], expected[2], expected[3], "mm", "g"], `${sourceProduct.article} actual Ozon payload`);
}

// Explicit synthetic controls are deliberately separate from the real API-shaped fixtures above.
assert.equal(normalizeSupplier({ length: 7.7, lengthUnit: "см" }).length, 77, "synthetic declared cm");
assert.equal(normalizeSupplier({ length: 77, lengthUnit: "мм" }).length, 77, "synthetic declared mm");
assert.equal(normalizeSupplier({ weight: 0.36, weightUnit: "кг" }).weight, 0.36, "synthetic declared kg");
assert.equal(normalizeSupplier({ weight: 360, weightUnit: "г" }).weight, 0.36, "synthetic declared g");
assert.equal(normalizeSupplier({ length: 7.7 }).length, null, "unknown dimension unit is not guessed");
assert.equal(normalizeSupplier({ weight: 0.36 }).weight, null, "unknown weight unit is not guessed");

const packageOnly = normalizeSupplier({ article: "SYNTHETIC-PACKAGE", logisticParamsData: { singlePackage: {
  multiplicity: 1, unit: "шт", lengthMm: 121, widthMm: 62, heightMm: 45, weightGrams: 230,
} } });
assert.deepEqual([packageOnly.length, packageOnly.width, packageOnly.height, packageOnly.weight], [121, 62, 45, 0.23]);
const packagePayload = payloadWorker.ozonLocalPayload({ article: "SYNTHETIC-PACKAGE" }, packageOnly, "SYNTHETIC-PACKAGE-1").items[0];
assert.deepEqual([packagePayload.depth, packagePayload.width, packagePayload.height, packagePayload.weight, packagePayload.dimension_unit, packagePayload.weight_unit],
  [121, 62, 45, 230, "mm", "g"]);
console.log("six real API-shaped source fixtures and downstream Ozon payload assertions passed; synthetic controls passed");

