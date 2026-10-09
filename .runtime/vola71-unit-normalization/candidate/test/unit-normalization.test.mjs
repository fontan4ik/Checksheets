import assert from "node:assert/strict";
import { normalizeSupplier } from "../worker/index.js";
import { pathToFileURL } from "node:url";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

// Isolated executable harness copy binds its existing payload implementation to the candidate normalizer.
const harnessPath = resolve(new URL("../../worker-under-test.mjs", import.meta.url).pathname);
const source = readFileSync(harnessPath, "utf8");
const bound = source.replace('"./worker/article-id.js"', '"../worker/article-id.js"').replace('"./articles.mjs"', '"../articles.mjs"').replace(/^function normalizeSupplier\(p\) \{/m,
  `function normalizeSupplier(p) { return globalThis.__candidateNormalizeSupplier(p); }\nfunction normalizeSupplierOriginal(p) {`);
const boundPath = resolve(new URL("../worker-under-test-bound.mjs", import.meta.url).pathname);
writeFileSync(boundPath, bound);
globalThis.__candidateNormalizeSupplier = normalizeSupplier;
const worker = await import(pathToFileURL(boundPath).href);

const payload = (supplier, article = "KKME11-012-230-10") => worker.ozonLocalPayload(
  { article }, { ...supplier, article, multiplicity: 1 }, `${article}-1`,
).items[0];
const caseFor = (article, l, w, h, g) => {
  const supplier = normalizeSupplier({ article, lengthCm: l / 10, widthCm: w / 10, heightCm: h / 10,
    weightBrutto: g / 1000, weightBruttoUnit: "kg" });
  const item = payload(supplier, article);
  assert.deepEqual([item.depth, item.width, item.height, item.weight, item.dimension_unit, item.weight_unit], [l, w, h, g, "mm", "g"]);
};
caseFor("KKME11-012-230-10", 77, 48, 88, 360);
caseFor("KKME11-018-230-10", 77, 48, 88, 376);
caseFor("KKME11-009-230-10", 77, 48, 88, 360);
caseFor("KKME21-025-110-10", 85, 58, 100, 538);
caseFor("KKME31-040-230-11", 128, 81, 120, 1240);
caseFor("KKME41-095-230-11", 130, 90, 131, 1470);
assert.equal(normalizeSupplier({ length: 7.7, lengthUnit: "cm" }).length, 77);
assert.equal(normalizeSupplier({ lengthCm: 7.7 }).length, 77);
assert.equal(normalizeSupplier({ lengthMm: 77 }).length, 77);
assert.equal(normalizeSupplier({ length: 7.7 }).length, null, "unknown unit is not guessed");
assert.equal(normalizeSupplier({ weightBrutto: 0.36, weightBruttoUnit: "kg" }).weight, 0.36);
assert.equal(normalizeSupplier({ weightGrams: 230 }).weight, 0.23);
assert.equal(normalizeSupplier({ weight: 230, weightUnit: "g" }).weight, 0.23);
assert.equal(normalizeSupplier({ weight: 0.36 }).weight, null, "unknown unit is not guessed");
const individual = normalizeSupplier({ article: "X", logisticParams: [
  { nameOrig: "ВесБрутто", name: "Вес брутто, кг", unit: "кг", value: { individual: 0.376, transport: 99 } },
  { nameOrig: "Длина", unit: "см", value: { individual: 7.7, transport: 700 } },
], logisticParamsData: { singlePackage: { multiplicity: 1, unit: "шт" } } });
assert.deepEqual([individual.length, individual.weight], [77, 0.376]);
const individualPayload = payload({ ...individual, width: 48, height: 88 });
assert.deepEqual([individualPayload.depth, individualPayload.width, individualPayload.height, individualPayload.weight, individualPayload.dimension_unit, individualPayload.weight_unit], [77, 48, 88, 376, "mm", "g"]);
const packageOnly = normalizeSupplier({ article: "X", logisticParamsData: { singlePackage: {
  multiplicity: 1, unit: "шт", lengthMm: 121, widthMm: 62, heightMm: 45, weightGrams: 230,
} } });
assert.deepEqual([packageOnly.length, packageOnly.width, packageOnly.height, packageOnly.weight], [121, 62, 45, 0.23]);
const packagePayload = payload(packageOnly);
assert.deepEqual([packagePayload.depth, packagePayload.width, packagePayload.height, packagePayload.weight, packagePayload.dimension_unit, packagePayload.weight_unit], [121, 62, 45, 230, "mm", "g"]);
console.log("unit normalization and Ozon downstream payload assertions passed");
