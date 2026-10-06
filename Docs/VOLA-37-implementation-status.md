# VOLA-37 IEK → Wildberries / Ozon card preparation

This prototype fetches supplier product data from IEK and renders a local review page. It constructs candidate marketplace payloads but does not publish them.

## Current verified source data

On 2026-10-06, the IEK client was used to read the following five SKUs. Every SKU was found, each has 14 ETIM characteristics, and photo counts were 1, 10, 10, 1, and 10 in the given order. IEK returns `multiplicity=1` for all five, so no `-5` suffix should be added.

IEK supplies an RRC/list price field. That value is not automatically used as the seller-approved marketplace price. The returned product detail did not contain barcode or dimensions/weight fields needed by marketplace payloads. Do not invent these fields.

## Implemented

- `iek_marketplace_mapper.py` maps IEK photos, text, ETIM characteristics, and multiplicity to draft Ozon and WB payload structures.
- Category IDs and attribute IDs are explicit mapping inputs; no automatic guessed category mapping is applied.
- Missing seller price, barcode, category mappings, attributes, or WB dimensions/weight keep the draft not ready.
- `iek_card_preview.py` provides a local UI/API, loopback-bound by default, and displays the IEK data and per-marketplace readiness errors.
- No marketplace write endpoint is called by the preview or mapper.

## Validation

- Focused unit tests are run with `.venv-etm-export/bin/python -m unittest discover -s test -p 'test_iek_marketplace_mapper.py' -v`.
- Python compilation: `python3 -m py_compile iek_marketplace_mapper.py iek_card_preview.py`.
- Embedded UI JavaScript syntax is checked with `node --check` after extracting it to a temporary file under the run scratch directory.

## Remaining

1. Provide verified seller price, barcode, and physical dimensions/weight for each SKU, or an explicitly approved authoritative source for each field.
2. Retrieve authoritative current Ozon category/type/attribute mappings and WB subject/characteristic mappings for these products.
3. Complete marketplace-side dry-run/validation in the existing VOLA-40 child task, recording exact endpoints/statuses.
4. Only after payload and policy approval, publish cards to WB/Ozon and verify card/task IDs and final statuses.
5. Deploy the operator-facing site through the approved publishing path and record a working URL and health verification.

No public cards or website have been published by this prototype.
