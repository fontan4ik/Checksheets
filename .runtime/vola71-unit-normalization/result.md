# VOLA-71 isolated unit-normalization result — corrected real-fixture verification

## Provenance and candidate selection
- Frozen base worker SHA-256: `8e5a70b86edb1d6828b1aaa56c2cf23a9bc7ebb5e25b5e8f53096d34c86bb279`.
- My first candidate SHA-256 `694c12d87c1bd5ba7b52628c080fcf53e8b529d724953005a4715e8aae1cbc40` is superseded: independent testing found 9/76 failures, including all six real-source products. Its original flat `caseFor` records were synthetic controls, not actual IEK payload structure. Do not treat that candidate or its 1/1 test as real-product evidence.
- I isolated a corrected reference-derived candidate at `candidate-reference/worker/index.js`, SHA-256 `60d98ce1ecc99a6621bcc4523d10205f4c2eb57350aa4d9728ae20cfa8142129`. Its patch from frozen base is `candidate-reference.patch`, SHA-256 `ee7924f8ca71e0cf8e56b33fd7c9247f8bf5ab298925cd51a18a55e430e6f640`.
- The candidate only changes the normalization unit block and `normalizeSupplier` field wrappers; checked `validateDryRun` suffix is byte-identical to the frozen base. No shared/CEO checkout was modified.

## Real API-shaped fixture and downstream payload verification
The executable test `candidate-reference/test/unit-normalization.test.mjs` reads the immutable saved `mapping-input-safe.json` products (not synthetic flattened aliases), runs the candidate normalizer, then calls the frozen actual `ozonLocalPayload` implementation with candidate normalization bound into its execution harness.

All six saved source-product cases passed these normalized/payload expectations:
- `KKME11-012-230-10`: 77×48×88 mm, 360 g
- `KKME11-018-230-10`: 77×48×88 mm, 376 g
- `KKME11-009-230-10`: 77×48×88 mm, 360 g
- `KKME21-025-110-10`: 85×58×100 mm, 538 g
- `KKME31-040-230-11`: 128×81×120 mm, 1240 g
- `KKME41-095-230-11`: 130×90×131 mm, 1470 g

Actual saved fixture API shape includes `nameOrig: ВесБрутто` with display `name: Вес брутто, кг`, plus `l_см/b_см/h_см` and nested `value.individual`; test verifies those source rows directly. It also keeps synthetic typed-unit controls clearly separate: explicit Russian cm/mm/kg/g units, unknown-unit rejection, and package-only 121×62×45 mm + 230 g output.

## Verification performed in this run
- `node --check candidate-reference/worker/index.js`: PASS.
- `node --test candidate-reference/test/unit-normalization.test.mjs`: PASS, 1/1 suite; asserts six source-real payloads and synthetic controls.
- Confirmed candidate suffix from `function validateDryRun(` to file end is byte-identical to frozen base.
- Source fixture SHA-256: `bcea77669bee9265645726fff360e61e800eba3a99a0c722a7af3c31e2a286f5`.
- The separately supplied full harness evidence reports 76/76 PASS with no external network calls or production mutations; that full suite was not rerun by this agent. My direct run verified the six source fixtures and package/unit controls only.

## Integration boundary
Do not revert the whole worker. Reconcile only the bounded normalization patch and preserve concurrent dictionary, main-Ue, readback, claim, and UI changes. Preserve dimensions cm→mm `*10` and canonical weight kg→payload g `*1000` exactly once. Do not use `Math.round(cm)` or `Math.round(kg)` as unit conversion.

## Hash list
See `hashes.txt` for base, rejected first candidate, corrected candidate, patch, test, and fixture digests.
