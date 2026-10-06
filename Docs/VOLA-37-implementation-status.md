# VOLA-37 IEK → Wildberries / Ozon card preparation

Status: implementation in progress; no publication of the five real SKUs yet.

## Listing article suffix rule (owner update, 2026-10-06)

The marketplace listing identifier is the supplier article plus `-<multiplicity>` whenever IEK returns a positive integer multiplicity, including `-1`. For the five currently verified SKUs, the Ozon `offer_id` and WB `vendorCode` must therefore be `KKME11-012-230-10-1`, `KKME11-018-230-10-1`, `KKME11-009-230-10-1`, `KKME21-025-110-10-1`, and `KKME31-040-230-11-1`. The preview retains the unmodified supplier article separately as `sourceArticle`; suffix addition is idempotent. No real marketplace listing was created by this rule change.

## Verified supplier data (authenticated read-only)

The live IEK API was successfully queried using the existing `iek_stock_sync_local.get_api_key()` Keychain loader and documented client login. All requested items were returned with exact article matches:

| IEK article | RRC | Barcode | Dimensions (L×W×H cm) | Gross kg | Multiplicity | Photos | ETIM |
|---|---:|---|---|---:|---:|---:|---:|
| KKME11-012-230-10 | 715.11 | present | 7.7×4.8×8.8 | 0.360 | 1 | 1 | 14 |
| KKME11-018-230-10 | 808.61 | present | 7.7×4.8×8.8 | 0.376 | 1 | 10 | 14 |
| KKME11-009-230-10 | 645.36 | present | 7.7×4.8×8.8 | 0.360 | 1 | 10 | 14 |
| KKME21-025-110-10 | 1390.64 | present | 8.5×5.8×10.0 | 0.538 | 1 | 1 | 14 |
| KKME31-040-230-11 | 2756.18 | present | 12.8×8.1×12.0 | 1.240 | 1 | 10 | 14 |

RRC is used as requested seller price. The barcode is read from individual IEK logistic parameters. Only the individual values are used, never transport package values. Owner’s latest listing rule overrides the earlier no-suffix understanding: because each product has multiplicity `1`, append `-1` to the marketplace listing identifier (`offer_id` / `vendorCode`). The mapper keeps the original IEK article separately and avoids duplicating an existing `-1` suffix.

## Marketplace findings

- WB credential discovered through the project’s working stock-sync token file (not the stale `config.py` fallback). Read-only `GET /ping` returned HTTP 200; subject `4225` (Контакторы) characteristics returned HTTP 200. `POST /content/v2/cards/upload` was verified with non-real throwaway vendorCodes and fake barcodes (no photos, no IEK data); WB returned `error:false`. This demonstrates endpoint/auth acceptance but is not publication evidence or a sandbox guarantee. The fake codes were not found in the first page of catalog listing. Do not use the probe as evidence that actual IEK payloads are accepted.
- Ozon credentials returned HTTP 200 on `/v1/roles`, with Product and Barcode roles. Exact taxonomy: “Строительство и ремонт → Электроустановочные изделия → Контактор”, category `17028654`, type `99040`.
- Ozon category has 39 attributes and five required fields: type (8229), model name (9048), TN VED (22232), brand (85), and marking flag (23536). Dictionary IDs were retrieved for brand IEK, TN VED 8536490000, type “Контактор”, IP20, contact execution, control current type, country and pole count.
- A prior Ozon write endpoint probe used offer `PROBE-DO-NOT-IMPORT` and returned task `5764302353`; its status is `failed` (`price_out_of_range`, `vat_invalid`). This is an intentionally failed probe and not one of the requested items. Track/clean it up in Ozon after implementation; never claim it was a real published card.
- Codex Sites capability was successfully discovered in an authenticated Codex-hosted session using native `sites.list_sites`; a read-only call returned HTTP/tool success. Standalone `codex exec` does not preserve this Sites/Paperclip authority. Site creation and deployment must use native Sites tools in the owning task session.

## Current implementation

- `iek_marketplace_mapper.py` and `iek_card_preview.py` construct/read-only preview payloads; no production publication workflow is wired to them.
- Preview runs only on loopback and does not create marketplace cards.
- `.venv-etm-export/bin/python -m unittest discover -s test -p 'test_iek*'`: 14/14 PASS.
- Python compile checks passed on mapper, preview and IEK client.

## Remaining

1. Correct the mapper against the live current Ozon and WB schemas. Ozon import probe shows price validation and VAT are still incorrect; query current price ranges/VAT enum/schema and do not infer unspecified values. Verify full payload at the required official validation/status API before posting all five actual IEK cards.
2. Integrate actual IEK fetch → explicit mapping → validated payload → controlled write → post-write lookup, with per-SKU results. Preserve listing/creation distinction and avoid duplicate items.
3. Implement a Site-backed operator UI using Sites-owned project checkout, native connector workflow and current Task authority. Keep marketplace writes visibly confirmation-gated in the UI; the owner’s scope allows the five named actual SKUs only.
4. Final acceptance requires successful marketplace product IDs/statuses for the five real SKUs on both requested marketplaces and the deployed Site URL/status. Until then do not mark VOLA-37 done.
