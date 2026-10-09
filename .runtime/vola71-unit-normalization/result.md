# VOLA-71 isolated candidate result

## Provenance
- Exact frozen base `worker/index.js` SHA-256: `8e5a70b86edb1d6828b1aaa56c2cf23a9bc7ebb5e25b5e8f53096d34c86bb279`.
- SHA confirmed against immutable source snapshot under `MultiAI/.runtime/evaluations/iek-card-correction-20261009/independent-fixtures-after/runs/20261009T124001142185Z/examined/worker/index.js`.
- This is a content hash, not a Git commit. No CEO checkout / shared worker was changed.

## Candidate scope
- `candidate/worker/index.js`: unit-aware `normalizedDimension` and `normalizeSupplier` only. Internal dimensions are mm and mass is kg; declared cm/mm and field-name units convert once; g -> kg once. Unknown units do not supply physical values.
- Nested logistics considers both `nameOrig` and display `name`, prefers `value.individual`, and uses nested explicit unit before metadata. Package typed values are fallback; multiplicity/unit-only metadata does not mask per-product logistics dimensions. Package `weightGrams` is converted to kg.
- `candidate/test/unit-normalization.test.mjs`: real six-product downstream payload checks plus cm/mm/g/kg, unknown units, individual-vs-transport, and package-only payload checks.

## Independent 76-case reference
- Compared the supplied independent reference candidate at `.runtime/vola71-unit-reference-root/candidate/worker/index.js`: SHA-256 `60d98ce1ecc99a6621bcc4523d10205f4c2eb57350aa4d9728ae20cfa8142129`; patch at `.runtime/vola71-unit-reference-root/reference.patch`.
- Its saved harness evidence reports 76/76 pass, 0 external network calls, and 0 production mutations. This is evidence from the supplied snapshot, not a rerun by this agent.
- Its patch changes only normalization and supplier field wrappers; suffix after `validateDryRun` matches the frozen source. The reference rejects unknown units, parses units from logistics names/nested values/field wrappers, and preserves canonical kg/mm with payload kg-to-g *1000 and cm-to-mm *10.
- Keep this separate from my independently implemented candidate; integrate/reconcile only the bounded normalization changes, preserving concurrent non-unit code.

## Verification
- `node --check candidate/worker/index.js`: PASS.
- `node --test candidate/test/unit-normalization.test.mjs`: PASS, 1/1.
- Payload assertions cover six controls and output dimensions in mm / mass in g; frozen payload contract multiplies canonical kg by 1000.
- Independent evidence fixtures were not edited.

## Integration warning
Current integration worker may have diverged. Do not revert the whole worker. Reconcile only unit normalization, preserve dictionary/readback/claim/UI work, and verify cm-to-mm `*10` and kg-to-g `*1000` exactly once; never substitute `Math.round(cm)` or `Math.round(kg)`.

## Hashes
- Base worker: `8e5a70b86edb1d6828b1aaa56c2cf23a9bc7ebb5e25b5e8f53096d34c86bb279`.
- My candidate worker: `694c12d87c1bd5ba7b52628c080fcf53e8b529d724953005a4715e8aae1cbc40`.
- Independent reference worker: `60d98ce1ecc99a6621bcc4523d10205f4c2eb57350aa4d9728ae20cfa8142129`.
- Generated focused reference patch: `.runtime/vola71-unit-normalization/reference.patch`, SHA-256 `e012845673edaaaceb015bc0cf68c792b854b89b36d619a9852e2e28c8252088`.
- Other artifact hashes: `.runtime/vola71-unit-normalization/hashes.txt`.
