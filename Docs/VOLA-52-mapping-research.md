# VOLA-52 — IEK marketplace mapping research (2026-10-06)

## Scope and result

This artifact records verified facts and current limits. It does not claim marketplace writes or new live product IDs.

## Confirmed commercial/source data

- Supported IEK read-only loader: `iek_stock_sync_local.get_api_key()` via macOS Keychain, with `create_session()`, `login()`, and GET `/api/catalog/v1/client/products/{article}`. The live read returned all five exact supplier articles; every item has multiplicity 1, RRC/seller price per the project status document, barcode, photos, 14 ETIM features, and individual package measurements.
- Listing IDs are exact article plus `-1`: `KKME11-012-230-10-1`, `KKME11-018-230-10-1`, `KKME11-009-230-10-1`, `KKME21-025-110-10-1`, `KKME31-040-230-11-1`.
- Owner authorized VAT selection from same-category IEK-contactors in the Ozon cabinet. Read-only product records in category `17028654` agreed on `vat="0.22"`; same-category analogs included product IDs `2948157443` (`KKM11-012-230-10-1`), `2948157630` (`KKM11-018-230-10-1`), `2948157414` (`KKM11-009-230-10-1`), `2948157655` (`KKM21-025-230-10-1`), `2948159059` (`KKM31-040-230-11-1`). No disagreement found. VAT is resolved; do not request it again.
- Credentials are loaded only through existing protected runtime sources and must not be printed or saved.

## Current schema evidence

### Ozon

- Current taxonomy/category/type confirmed in prior live read: description category `17028654`, type `99040`.
- Required attribute IDs: type `8229`, model `9048`, TN VED `22232`, brand `85`, marking flag `23536`. Confirmed dictionary values include `Контактор`, IEK, TN VED `8536490000`; marking flag must be supplied from actual product/commercial evidence rather than invented.
- 2026-10-07 follow-up: the exact IEK `shortName`/`name` values establish source-backed model text for 9048 (KMIe series); mapper now derives this field from supplier data. Ozon cabinet comparison for five corresponding IEK analogs yielded price 1,526–4,683 RUB and VAT 0.22. This is a comparison, not an API-stated allowable min/max for new offers. Exact target offer IDs remain absent from catalog reads.
- Existing Ozon seller catalog documented VAT `0.22` for matching same-category IEK contactors.

### Wildberries

- Subject `4225` is Контакторы. Reviewed VOLA-57 read of `GET /content/v2/object/charcs/4225` returned 34 characteristics, all `required:false`.
- Confirmed IDs: `81589` nominal current (A); `88953` packaged weight (kg); `90630/90652/90673` item height/depth/width (cm); `90745/90846/90849` package width/height/length (cm).
- The response and report do NOT contain all 34 characteristic names/units/enum dictionaries in this checkout. Never infer a WB characteristic ID from a Russian ETIM name without matching the actual live descriptor. Dimensions in `dimensions` are the WB item dimensions; package size characteristic IDs must not be populated with guessed item or transport sizes. WB API docs/current field requirements and actual enums remain to be checked before treating payloads as publishable.
- WB card payload requires schema-derived characteristics in `variants[].characteristics` and item measurements in `dimensions`; media constraints also require live/docs validation.

## Implementation checkpoint

- Mapper now fails closed unless each marketplace schema is explicitly marked verified. For WB subject `4225`, automatic mappings are restricted to the verified numeric descriptors: current `81589`, packaged weight `88953`, item dimensions `90630/90652/90673`, and package dimensions `90745/90846/90849`. Unverified text/enum mappings are deliberately omitted.
- The former three stale WB fixture failures were corrected. Current focused suite: `./.venv-etm-export/bin/python -m unittest discover -s test -p 'test_iek_marketplace_mapper.py' -v` — 15/15 PASS. Mapper/test compilation and `git diff --check` pass.
- Current read-only marketplace reconciliation returned zero records for all five exact suffixed Ozon offer IDs (`/v3/product/info/list`, HTTP 200) and all five exact WB vendor codes (`/content/v2/get/cards/list`). This confirms targets remain absent at check time, not that writes are ready.
- The current WB subject endpoint returned HTTP 200 with 33 descriptors (VOLA-57's saved report had 34 on its earlier fetch). Required flags were false for checked descriptors. This response still does not supply dictionary values or media upload constraints.
- 2026-10-07 follow-up: mapper was hardened to fail closed for WB photos unless `photo_contract_verified=true`. WB `OPTIONS /content/v3/media/save` returns 405 `Allow: POST`; the available authenticated read-only WB endpoint could not be reached during this run (`fetch failed`), and the local OpenAPI copy did not contain media endpoints. This does not establish a successful photo submission contract.
- Explicit project status identifies IEK RRC as the requested seller price. The mapper accepts `priceRrc` only when configuration explicitly sets `seller_price_source="iek_priceRrc"`; without that policy, tests confirm it remains unset.
- Focused mapper tests after these changes: 18/18 pass; `git diff --check` passed. No marketplace writes were sent.
- The unit tests validate mapper mechanics, not five real payloads. Ozon price-range constraints, payload-specific category dictionary values/marking, and verified photo/card submission contracts remain unvalidated. No marketplace write was sent.

## Not yet done / next exact steps

1. Read current task workspace’s latest WB subject descriptor source/report (VOLA-57 linked evidence) and Ozon schema/dictionaries; derive full IEK-to-WB mapping without guessing, including item/package dimension semantics and valid enums.
2. Re-read the five exact IEK products through the supported loader; validate payload-specific required Ozon attribute values, all photo URLs, barcode, seller price and VAT.
3. Generate and save five concrete WB and five Ozon payloads in a controlled, non-secret artifact; validate the actual request bodies against current endpoint schemas. Do not create another synthetic listing/probe.
4. Reconcile exact suffixed offer/vendor codes read-only once more; then publish only missing authorized five products and post-check returned marketplace IDs/status/availability. Never repeat Ozon task `5764302353` or treat the old WB throwaway upload as a real card.
