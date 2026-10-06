# VOLA-37 IEK → Wildberries / Ozon card preparation

This prototype fetches supplier product data from IEK and renders a local review page. It constructs candidate marketplace payloads but does not publish them.

## Current verified source data

Read-only IEK checks on 2026-10-06 found all five SKUs. Each has 14 ETIM features. Photo counts in the supplied order are 1, 10, 10, 1, 10. IEK top-level `multiplicity=1` on every item; do not append `-5`.

The supplier details expose an RRC/list price, but this is not an owner-approved seller price. The detail payloads do not contain a barcode or physical dimensions/weight. The mapper intentionally rejects payload readiness instead of inventing any of these fields.

## API contract checks

- The attached IEK OpenAPI describes read-only product detail at `/api/catalog/v1/client/products/{article}` and does not specify marketplace publishing.
- Authenticated Ozon `POST /v1/description-category/tree` returned HTTP 200. The returned full tree contains no matching «контактор», «магнитный пускатель», or «электромагнитный пускатель» branch; do not guess a category. The read-only call to Ozon `/v4/product/info/attributes` without auth returned HTTP 401 with `Client-Id and Api-Key headers are required` (not a 404). It was only a no-credential endpoint check; no catalog data was sent.
- WB official endpoint path information is present in the repository's bundled WB docs: `GET /content/v2/object/parent/all`, `GET /content/v2/object/all`, `GET /content/v2/object/charcs/{subjectId}`, and `POST /content/v2/cards/upload`. Authenticated `GET /content/v2/object/parent/all` returned HTTP 200, but the downloaded parent list did not surface a clear electrical contactor branch. A request with a placeholder token returned HTTP 401 as expected; no actual token was sent in that unauthenticated probe.
- These checks are not a sandbox/publish dry-run. No marketplace write endpoint was called.

## Implemented

- `iek_marketplace_mapper.py` maps IEK photos, text, ETIM characteristics, and multiplicity to candidate Ozon and WB payload structures.
- Category/type/attribute IDs are explicit mapping inputs; no guessed mapping is applied.
- Missing seller-approved price, barcode, category mappings, characteristics, or WB dimensions/weight block readiness.
- `iek_card_preview.py` is a loopback-bound local UI/API with per-marketplace readiness errors and source multiplicity.

## Validation

- Mapper unit tests: 4/4 PASS.
- Preview UI/API unit tests: 3/3 PASS.
- `py_compile` and `git diff --check`: PASS.
- Preview is local only. No public URL or deployment exists yet.

## Remaining owner input and execution

For each SKU, provide/approve the seller price, barcode, and physical dimensions/weight (with units), or identify an authoritative approved source for those fields. Once those data and exact WB/Ozon mappings are available, run marketplace-side validation and follow the server's approval gates before any publication. Then deploy the operator site and record its URL and health check.

No public cards or website have been published by this prototype.
