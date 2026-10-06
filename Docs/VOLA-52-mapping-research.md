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
- WB live subject `4225` (Контакторы). Prior fresh live characteristic lookup corrected physical attribute semantics: 88953 is weight in kg; 90630/90652/90673 are dimensions in cm. Current-schema full characteristic mapping is being handled in parallel issue VOLA-57; use its reviewed output rather than reintroducing legacy static IDs.
- IEK data provides real photo URLs, individual dimensions/weight, barcode and ETIM. Mapping must use each individual package value, not transport values.

## Code state and validation

- The current mapper requires explicit seller_price and Ozon VAT and omits WB price if seller_price is absent. It does not infer VAT from an unrelated cabinet sample. It builds Ozon `images`/attributes and WB `photos`, dimensions, barcode SKU and size price.
- Focused mapper tests: `python3 -m unittest discover -s test -p 'test_iek_marketplace_mapper.py' -v` — 14/14 passed on 2026-10-06. One incorrect module-style invocation failed because `test/` is not a package; discovery invocation passed.
- Five live payloads were not built in this run because the authenticated IEK read loader was not re-executed and VAT remains unresolved. No marketplace writes were sent. Prior live post-check found no listings for the five suffixed articles.

## Next action

After the pending exact VAT answer, fetch the five current IEK products through the supported loader, assemble each payload with RRC seller price, confirmed VAT, and the VOLA-57 reviewed WB characteristic schema, validate all five payloads, then continue authorized real writes and live ID/status post-check. Never use the failed synthetic Ozon task 5764302353 or WB throwaway upload as product evidence.
