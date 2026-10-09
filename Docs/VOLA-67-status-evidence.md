# Issue Status Evidence — VOLA-67

## Latest owner direction incorporated

- The current independent Ozon info/list snapshot at 2026-10-09 10:02:57 UTC is authoritative for the reported latest price values: 340 / 340 / 340 / 377 / 433 RUB (9A / 12A / 18A / 25A / 40A). Do not use older saved values 1432 / 1618 / 1292 / 2782 / 5514 as current.
- The approved seller-price rule is the exact owner statement from 2026-10-06: seller price comes from IEK API RRC. Fresh IEK RRCs are 715.11 / 808.61 / 645.36 / 1390.64 / 2756.18. This records intended policy, not a claim that those values have been written to Ozon.
- Fresh independent IEK facts identify `tm=GENERICA` for all five SKUs. Existing Ozon brand `IEK` is therefore a confirmed field discrepancy; corrections must preserve the five product IDs.
- The source IEK ETIM fields report auxiliary NO=1, while power NO and NC are both 0. Do not infer Ozon poles from those contradictory zeros. Physical pole count remains unverified until exact product/catalog evidence establishes it.
- Supplier individual dimensions (cm) and gross weight (kg) are distinguishable from transport values. Current Ozon dimensions for the five are already 77×48×88 mm and match 7.7×4.8×8.8 cm for the 12A model; the earlier demonstrated ×10 regression applies to other unit cases, not these current five rows.
- Live UI visual verification was declined by the browser security policy; do not retry by another browser, CDP, CLI, or HTTP screenshot route. Mark live visual UI unverified. This does not block source/API work or publication via official Sites connector.
- Product certificates and documents are out of scope.

## Current objective / disposition

VOLA-67 is not complete. Correct the existing Site and the five existing Ozon cards only within the authorized scope: no duplicate products, preserved product IDs, no sales activation, no stock management, no certificate edits, no WB expansion, and no public-access/settings changes.

## Verified evidence to date

- Published Site v14 source had independently reproduced logic/concurrency/UI/data defects documented in the task's `verification-inputs` document.
- The site's current working tree includes uncommitted implementation edits. `npm test` previously passed 4/4, but this alone does not establish that the independently reproduced defects are fixed.
- Latest source review showed that current changes still have material gaps: the payload falls back to `IEK` if supplier brand is absent; it sends only a few metadata attributes and omits technical mappings; dimensional normalization uses key aliases without robust source-unit provenance; current required-attribute validation checks attribute presence rather than actual typed/dictionary values; existing product readback short-circuits to complete without comparing fields; imported task completion is accepted without product/picture/validation readback; `/api/import/process` loads queued rows without a durable atomic claim; browser start still allows double-click, queued-run reload only renders instead of resuming, and `driveRun` stops after 30 polls without durable continuation. See `sites/iek-operator/worker/index.js` and `sites/iek-operator/src/article-import.js`.
- No authoritative proof has been gathered here for the provenance of the latest Ozon prices. Do not attribute the changes to this agent or any other actor without verified action logs. This run did not modify Ozon or publish the Site.
- The previous native Sites source workflow could not receive its credential through stdin because the isolated CLI approval policy rejected the write. Thus no fresh current source/deployment result is claimed.
- A diagnostic readback script exists at `test/iek-card-correction-20261009-live-readback.cjs` and executed successfully on 2026-10-09 10:05:47 UTC: Ozon info/attributes, pictures/info, schema, and dictionaries all returned HTTP 200; five products were returned. This run only reported request status/counts; detailed read-only response is stored locally by the script, not yet attached as a task artifact.
- Independent offline reviewer follow-up [VOLA-68](/VOLA/issues/VOLA-68) is assigned to Founding Engineer and remains `in_review`; no review verdict was available in this run.

## Remaining required work

1. Establish action-log/provider-response provenance for the latest five Ozon seller prices without speculation.
2. Obtain current Site source through supported native Sites workflow; reconcile, do not overwrite shared edits.
3. Fix and test the Site defects above, including real field-level readback and safe price/brand semantics, while retaining no-submit safety except for specifically authorized existing-card updates.
4. Obtain exact official/catalog pole semantics before sending Ozon `10818`; map supported other technical fields using fresh schema and dictionaries, with real values/units/cardinality.
5. Fresh-preview and carefully correct only the allowed ordinary fields on the same five existing Ozon product IDs, then read back each provider result.
6. Build and publish via official Sites tools; verify exact source commit/archive/deployment ID and success.
7. Record matrix `IEK source → expected → submitted → persisted` with provenance and gaps. Live visual UI remains unverified under the owner's browser boundary.
8. Independent code/regression review and human-only acceptance of the current revision remain required.
