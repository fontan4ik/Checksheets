# Current change chunk: supplier capability handoff and bootstrap visibility

Scope: VOLA-101 frontend changes only; do not edit Worker/backend/runtime. Current local tests, public browser readback, and QA findings are authoritative evidence for this chunk.

## Changed files to review

- `sites/iek-operator-correction-20261009/src/article-import.js`
- `sites/iek-operator-correction-20261009/src/supplier-selection.js`
- `sites/iek-operator-correction-20261009/test/supplier-selection.test.mjs`
- Existing candidate artifacts in Paperclip work products; update hashes after verification.

## Findings

- QA179 asked for a truthful actual supplier capability boundary, not fake Feron/Arlight support. Current Worker supports the IEK-specific route only; those other suppliers must remain explicitly unavailable and Start-disabled until an actual integrated contract exists.
- The public anonymous/authenticated browser path recently succeeded; exact deployed bytes remain ambiguous because QA observed intro-only. Do not claim publication/identity.
- Attempted to wire a supplier-change custom event so Start validation can update immediately; isolated test doubles do not implement EventTarget. Reconcile by using a simple safe refresh/availability strategy that does not introduce an event dependency into tests, and add a regression that proves Start cannot remain enabled after selecting unsupported supplier.
- Preserve server-side source/catalog/auth guards and avoid marketplace writes during verification.

## Acceptance for this chunk

- Selecting Feron or Arlight updates the status truthfully and disables Start; switching back to IEK recomputes Start availability from the current parsed workbook and errors.
- Public login/Excel UI remains behind server-authenticated state.
- Targeted tests, full suite, build/check pass.
- Do not modify shared backend or deploy. Register actual source/test refs before updating result.
- If a real executable item remains after this chunk, schedule the native bounded continuation with a specific nextAction and verify receipt. Otherwise keep waiting on the existing addressed publisher interaction without duplicates.