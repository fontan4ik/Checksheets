# VOLA-52 — IEK marketplace mapping research (2026-10-06)

## Scope and result

The latest board instruction was followed: continue schema and payload implementation independently; ask only for a commercial fact that cannot be established from permitted sources. This artifact records verified facts and limits. It does not claim any marketplace writes or live product IDs.

## Source and seller-price/VAT research

- The project IEK integration has a supported authenticated read-only loader: `iek_stock_sync_local.get_api_key()` (Keychain service `checksheets-iek-api`, account `ticket`), `create_session()`, `login()`, and GET `/api/catalog/v1/client/products/{article}`. The status report documents per-SKU RRC values, barcode, individual package measurements, photos and ETIM.
- `Docs/VOLA-37-implementation-status.md` explicitly says RRC is the requested seller price (line 21) and lists the five current source articles and priceRrc values (lines 15–19). The board's latest direction authorizes the five real SKUs and directs resolving price/VAT from project/current account sources before asking. Accordingly, seller price for this scope is sourced from the documented RRC value; do not change it to a different number without specific contradictory seller data.
- `config.py` and `config_backup.py` contain no IEK seller-price or marketplace VAT setting. They contain unrelated API configuration; credential values are intentionally not copied or disclosed.
- IEK product source does not provide VAT. Ozon's current product-info pricing API returns VAT only for existing listings; target SKUs have no current listings, per the preceding live reconciliation. A 0.22 sample from unrelated existing listings is not a valid per-product/account selection. Therefore the exact Ozon `vat` for these new product cards remains a required commercial/tax choice.
- Created one native human-only input card on VOLA-52 asking for the precise `vat` field/value and noting the checked sources. Interaction ID: `747aa3d1-af96-4681-81ed-8c427f20578d` (pending, wake assignee).

## Schema evidence already established

- Ozon live category/type: category `17028654`, type `99040`; required attribute IDs: 8229 (type), 9048 (model name), 22232 (TN VED), 85 (brand), 23536 (marking flag). Verified dictionary values from the prior live schema read include Контактор, IEK and TN VED 8536490000. The local Ozon API documentation describes import field `vat` as a string (`Docs/Ozon api documentation.md`, around line 1878).
- WB live subject `4225` (Контакторы). Reviewed VOLA-57 evidence is attached to [VOLA-57](/VOLA/issues/VOLA-57#comment-b758f1d8-289c-4f4c-a20d-41882ee06d33): live `GET /content/v2/object/charcs/4225` returned HTTP 200 and 34 characteristics; all are `required:false`. Current useful IDs: 81589 current (A), 88953 packaged weight (kg), 90630/90652/90673 item height/depth/width (cm), and 90745/90846/90849 package width/height/length (cm). Use exact IEK individual package measurements for package dimensions and do not conflate them with item dimensions. The response does not verify dictionaries or upload/photo constraints.
- IEK data provides real photo URLs, individual dimensions/weight, barcode and ETIM. Mapping must use each individual package value, not transport values.

## Code state and validation

- The current mapper requires explicit seller_price and Ozon VAT and omits WB price if seller_price is absent. It does not infer VAT from an unrelated cabinet sample. It builds Ozon `images`/attributes and WB `photos`, dimensions, barcode SKU and size price.
- Focused mapper tests: `python3 -m unittest discover -s test -p 'test_iek_marketplace_mapper.py' -v` — 14/14 passed on 2026-10-06. One incorrect module-style invocation failed because `test/` is not a package; discovery invocation passed.
- Five live payloads were not built in this run because the authenticated IEK read loader was not re-executed and VAT remains unresolved. No marketplace writes were sent. Prior live post-check found no listings for the five suffixed articles.

## Next action

VAT is resolved. Remaining work is to complete current Ozon/WB value and media validation, build and validate all five payloads from the supported IEK loader, then continue authorized real writes and live ID/status post-check. Never use the failed synthetic Ozon task 5764302353 or WB throwaway upload as product evidence.

## Owner VAT decision and live cabinet evidence (2026-10-06)

The owner superseded the exact-rate question and authorized selecting VAT from similar IEK contactors in the same Ozon category. I loaded Ozon credentials only in process using the existing `ozon_report65_local.js` dotenv order (protected secrets file first, project `.env` second); no credential value was displayed or persisted. Read-only `POST /v1/roles` returned HTTP 200. A complete pagination of `/v3/product/list` followed by `/v3/product/info/list` over the account catalog found exact same-category (`17028654`) IEK contactors; target suffixed offer IDs were absent from the catalog snapshot.

Every matched same-category IEK contactor returned `vat="0.22"`. This selection is supported by actual product VAT from the cabinet, not by the unrelated general-catalog sample. Closest KMIe series analogs (Ozon product ID — offer ID) include:

- `2948157443` — `KKM11-012-230-10-1`
- `2948157630` — `KKM11-018-230-10-1`
- `2948157414` — `KKM11-009-230-10-1`
- `2948157655` — `KKM21-025-230-10-1`
- `2948159059` — `KKM31-040-230-11-1`

These KMI/IEK offers are related catalog analogs, not duplicates of the five KMIe supplier products. Additional IEK contactors in the same category also showed `0.22`; no rate disagreement was observed. Use Ozon `vat="0.22"` for the five authorized cards, grounded in these actual product IDs, not the unrelated general-catalog sample.

This supersedes the earlier request for a manually supplied VAT value in lines 12–13: the owner directed selecting the rate from same-category IEK cabinet analogs, and the read-only cabinet inspection above fulfilled that request. VAT is therefore resolved to `0.22` for this five-SKU scope; no new owner input is required.

The live IEK detail loader was exercised read-only for all five exact supplier articles. Each article matched; each has multiplicity 1, so listing IDs must end in exactly `-1`. Photos, 14 ETIM features, individual barcode, package dimensions/weight, and RRC were present. No credential or raw product response was saved as an artifact.

This resolves VAT and authenticated source-data access. It does not by itself establish that the current WB mapper characteristics or all required Ozon attribute values are valid for live writes; do not publish until both actual endpoint payloads are assembled and schema-validated. No marketplace writes were sent in this continuation.
