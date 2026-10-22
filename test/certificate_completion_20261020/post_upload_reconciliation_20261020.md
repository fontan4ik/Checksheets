# Certificate reconciliation — 2026-10-20

Fresh Ozon API readback at 2026-10-20T08:25:50.177764+00:00. Full catalog snapshot at 2026-10-20T07:54:42.020692+00:00.

## Ozon

- 22,468 active products; 14,925 have at least one current approved document and 7,543 do not.
- 10 newly uploaded document records; target-link states: {'approved': 30, 'declined': 13}. Five ambiguous sample-date bindings were unbound and verified absent.
- Current Ozon certificate records: {'approved': 627, 'declined': 14, 'awaiting_verification': 1}; reported binding count: 28,238.

## Wildberries

- 19,962 cards; 13,799 have a valid document, 259 are pending only, 377 rejected only, and 6,163 have no valid document.
- Live WB search found no matching cards for 49 recently checked offer entries covering the confirmed documents. No WB writes were needed.

## Local PDF cleanup

- Cumulative confirmed cleanup: 150 local PDF copies across 22 documents; 211,531,453 bytes reclaimed (201.8 MiB). Every deletion followed Ozon approval and WB target-card readback, or a verified no-card result.
- One otherwise verified Ozon document with a declined binding remains local. Unresolved and declined document PDFs also remain available.
- Full cleanup evidence: `local_pdf_cleanup_receipt_20261020.json` and `existing_iek_local_cleanup_receipt_20261020.json`.

## Ozon documents handled

- `ЕАЭС N RU Д-CN.РА02.В.66453/26` — Ozon ID 5905049; record `approved`; 7/7 target bindings visible; links {'approved': 6, 'declined': 1}.
- `ЕАЭС N RU Д-CN.РА02.В.66507/26` — Ozon ID 5905053; record `approved`; 1/1 target bindings visible; links {'approved': 1}.
- `ЕАЭС N RU Д-CN.РА02.В.68171/26` — Ozon ID 5905057; record `approved`; 12/12 target bindings visible; links {'declined': 12}.
- `ЕАЭС N RU Д-CN.РА02.В.68364/26` — Ozon ID 5905065; record `approved`; 4/4 target bindings visible; links {'approved': 4}.
- `ЕАЭС N RU Д-CN.РА02.В.71161/26` — Ozon ID 5905072; record `approved`; 5/5 target bindings visible; links {'approved': 5}.
- `ЕАЭС N RU Д-RU.РА04.В.27073/26` — Ozon ID 5905082; record `approved`; 2/2 target bindings visible; links {'approved': 2}.
- `ЕАЭС RU С-CN.АЯ46.В.47749/26` — Ozon ID 5905088; record `approved`; latest readback: 3/3 target bindings approved.
- `ЕАЭС RU С-CN.АЯ46.В.48571/26` — Ozon ID 5905093; record `approved`; latest readback: 2/2 target bindings approved.
- `RU С-RU.АЮ64.В.00560/25` — Ozon ID 5905506; record `approved`; 6/6 target bindings visible; links {'approved': 6}.
- `RU С-RU.АЮ64.В.00631/26` — Ozon ID 5905380; record `approved`; 6/6 target bindings visible; links {'approved': 6}.

The twelve DVO links for declaration 68171/26 remain declined because its PDF lists different DVO models. One PDU link is declined. Other uncertain candidates are retained for follow-up.

Overall coverage remains incomplete. WB review stays pending wherever a matching card is found.

## Previously processed cross-brand groups

- Fresh Ozon readback at `2026-10-20T08:53:21.376493+00:00` and complete WB snapshot at `2026-10-20T07:50:12.324035+00:00` confirmed 13 older source groups across Arlight, Feron, KVT, TDM and IEK. Their exact Ozon targets are approved; WB has the matching document on every existing target card (some remain pending review), and offers without a WB card were left as no-card cases.
- Deleted 139 local copies across 13 documents and reclaimed 171,410,422 bytes. Two groups remain local because their source hash is also assigned to extra offers outside the verified target manifest.
- Detailed evidence and per-file checks: `previously_processed_groups_local_cleanup_receipt_20261020.json`; deletion journal: `previously_processed_groups_local_cleanup_journal_20261020.jsonl`.

## Older Ozon certificates — fresh cross-platform check

- Fresh complete WB catalog read at `2026-10-20T09:09:36Z` covered 19,962 unique cards over 200 pages. Fresh Ozon bindings were re-read through `2026-10-20T09:11:39Z`.
- `ЕАЭС RU С-CN.СП28.В.04871/26` (Ozon 5448220): 17/18 Ozon product links approved, 1 awaiting verification; exact certificate metadata already appears on all 18 WB cards.
- `ЕАЭС RU С-CN.НА75.В.02046/22` (Ozon 5448281): 37/39 approved, 2 awaiting; exact metadata already appears on all 39 WB cards.
- `ЕАЭС RU С-CN.НА75.В.02041/22` (Ozon 5448284): 367/368 approved, 1 awaiting; exact metadata appears on all 366 matching WB cards. Two assigned Ozon offers (`55058-4`, `55059-4`) have no WB card in the complete catalog. Thirteen cards that had blank or different WB brand fields were checked individually; each already had the exact certificate metadata and a valid WB verdict. No card updates were needed.
- The three local source files remain in place: each Ozon record still has awaiting-verification links. Nothing in this check qualified for local deletion.
- The four awaiting Ozon links are `SK-V12-0-10-K03-2`, `55071-5`, `55065-5`, and `55280-3`. WB already shows the matching documents on all four cards; three WB verdicts are valid and the IEK card has no verdict yet.
- Detailed evidence: `older_pending_certificates_crossplatform_reconciliation_20261020.json`, `older_pending_certificates_wb_plan_20261020.json`, and `older_pending_certificates_wb_targeted_readback_20261020.json`.


## Latest continuation — 2026-10-20 12:37 UTC

- IEK official-document batches were processed on Ozon: the 19-document manifest produced 19/19 visible documents and 134/134 exact target bindings approved. A separate eight-document batch had 36 current target bindings: the latest recheck shows 23 approved and 13 declined. The 134 targets in the 19-document manifest and all 36 targets in the later batch had no exact WB seller cards, so no WB writes were made for those groups and their local source files remain.
- Arlight voluntary fire certificate `РОСС RU.32001.04ИБФ1.ОСП32.90090` was written to 591 exact-scope WB cards. Full catalog readback confirmed the number/dates on all 591 and preservation of prior documents and unrelated card fields. WB returned `verified=false`, `reason=document_not_found` on all 591, so this is not counted as a confirmed/valid certificate. Ozon rejected the official number format (`NUMBER INVALID`); no Ozon record or binding was created. Keep the local PDF because both-platform confirmation is absent.
- Five remaining Feron documents (94 planned target edges) were skipped at live preflight because current Ozon TN VED codes fell outside the official PDF scope; WB codes were missing or out of scope. No upload was made for those candidates.
- Latest WB full-catalog counts: 19,962 unique cards; 13,799 with a current valid document, 259 pending-only, 698 rejected-only, and 6,163 without a current valid document. Readback: `arlight_0333370_wb_full_live_reconciliation_20261020.json` at 12:37:55 UTC.
- Latest Ozon coverage remains the earlier 11:10–11:13 UTC read: 22,579 active products; 15,141 with at least one current approved document and 7,438 without. The Arlight attempt did not change Ozon. Counts describe approved coverage, not all pending links.
- No newly uploaded source file qualified for local deletion in this continuation: Arlight lacks an Ozon record and WB validation, while the 134 IEK targets lack exact WB cards. Prior cleanup receipts remain the evidence for local deletions already completed.

Overall coverage remains incomplete; the remaining candidate pool is gated by missing/ambiguous PDFs, restricted production-lot/sample scope, unsupported or conflicting document metadata, and live product-code mismatches.

- Follow-up to the duplicate-record warning: `ЕАЭС N RU Д-RU.РА04.В.27570/26` is already approved and exactly linked on Ozon to all 22 target products; the 11:24 UTC full WB snapshot shows valid records on all 22 matching cards. `ЕАЭС N RU Д-CN.РА02.В.66430/26` is already approved and linked to its one exact Ozon product, with a valid document on its matching WB card. Neither needs another upload.


## Continued marketplace loading — 2026-10-20 20:01 UTC (21 Oct, Dubai)

- FSA declaration `ЕАЭС N RU Д-CN.РА09.В.52132/25` is active in the official registry, valid 2025-10-22 through 2030-10-20: [FSA record 20749531](https://pub.fsa.gov.ru/rds/declaration/view/20749531/common).
- Ozon record 5920271 is approved; all 929 exact product bindings were read back as approved. Its 929 current products all passed live identity checks and are inside the declaration's TN VED scope.
- WB had 929 exact target cards for this source group. The declaration is now visible on 867 eligible cards: 850 with a WB TN VED code inside the source scope and 17 with a blank WB code, each backed by the same exact offer and in-scope Ozon TN VED code. A full catalog readback confirmed exact number, type and dates on all 867, preserved all prior documents and other card fields on all 929, and found no new document on the 62 cards with conflicting or unconfirmed WB codes. Of the 867 new WB document items, 859 currently show a `valid` verdict and 8 have no verdict yet; no manual review or approval action was taken.
- The source PDF remains local. It covers 1,841 assigned source rows, including out-of-scope offers; only 929 are in scope for Ozon, and 62 of those do not have safe WB scope evidence. Local deletion therefore does not meet the user's cross-platform confirmation rule.
- Five IEK Ozon links were confirmed approved on a fresh readback: 3/3 for `ЕАЭС RU С-CN.АЯ46.В.47749/26` and 2/2 for `ЕАЭС RU С-CN.АЯ46.В.48571/26`. Gauss `ЕАЭС RU С-CN.НВ12.В.00069/22` still has 70/70 target links awaiting verification on Ozon; the exact document is valid on all 70 WB target cards. Its local PDF remains.
- Evidence: `arlight_52132_ozon_postwrite_readback_20261020.json`, `arlight_52132_wb_postwrite_readback_20261020.json`, `arlight_52132_wb_pending_eight_live_recheck_20261021.json`, `pending_certificate_link_readback_latest_20261020.json`, and `gauss_00069_crossplatform_live_recheck_20261020.json`.
- No local source PDFs were deleted in this continuation. Overall all-product/all-brand coverage remains incomplete.


## Latest continuation — 2026-10-21 (Dubai)

- Re-read the complete marketplace snapshot: Ozon has 22,741 active products, 688 document records and 30,692 product-document bindings; WB has 19,962 unique cards after verified boundary-duplicate normalization. Across all current Ozon products, 16,824 have at least one approved binding, 408 have bindings but none approved, and 5,509 have no binding. WB has a valid document on 15,093 cards, pending-only documents on 273, invalid/unknown-only documents on 379, and no document rows on 4,217. These are marketplace record counts, not a legal assessment of every product-document match.
- The refreshed source-assignment audit covers 30,598 unique offer-document edges. Ozon states: 12,189 approved links, 1,256 missing bindings, 14,412 missing records, 498 pending, 787 declined, 1,315 expired/future and 141 type conflicts. WB states: 12,381 valid, 682 pending/no verdict, 972 rejected/invalid, 15,738 missing documents, 684 with no exact card and 141 type conflicts. See `live_marketplaces_snapshot_complete_20261021.json`, `all_confirmed_source_assignments_live_20261021.json` and its CSV.
- Arlight `ЕАЭС N RU Д-CN.РА09.В.52132/25` (Ozon 5920271) now reads back as 929/929 approved Ozon bindings and 867/867 valid WB documents; the eight WB items that previously had no verdict have since become valid. The remaining 62 exact Ozon offers were kept off WB because their WB-side scope evidence is conflicting or unconfirmed. The source stays local while those exclusions and other source-assigned offers remain unresolved.
- Arlight `ЕАЭС N RU Д-CN.РА03.В.33344/26` (Ozon 5920706) reads back as 26/26 approved on Ozon. WB has the document on 14 exact cards, all still pending review; 12 source offers have no exact WB card. The document remains local.
- Fresh readbacks for previously handled Feron groups: `04998/22` has 300/300 approved Ozon bindings and valid WB documents on 259 matching cards; `54301/25` has 64/64 approved Ozon bindings and 61 valid WB documents; `87165/22` has 13/13 approved Ozon bindings and 12 valid WB documents; `58134/25` has 11/11 approved Ozon bindings and 11 valid WB documents. Do not count unmatched WB offers as complete. The two remaining `58134/25` offers are exact Feron LD1500/LD1501 products but Ozon currently classifies them under TN VED 8481806900 and WB has no exact seller card; neither was linked.
- Rechecked additional found documents against current product data. Kosmos `ЕАЭС RU C-CN.НВ28.В.00181/25` is valid on all 58 matching WB cards, but its 56 Ozon offers with a code use 8539213009 (and two have no code), whereas the FSA extract lists LED codes 8539520009/8539520003; no Ozon upload was made. Stekker `ЕАЭС RU C-CN.НВ85.В.02314/23` names the five matching HM extension-cord models, but all five Ozon listings currently carry unrelated TN VED 8517620003 and WB has no exact document rows; no links were added. Gauss `TR011` offers were also skipped because their current Ozon code 9405110013 conflicts with the code 9405110039 shown in the found Gauss documents.
- For NEOX `ЕАЭС N RU Д-CN.РА06.В.30232/26`, the live FSA extract lists codes 9405420012, 9405420032 and 9405110033 and states that the declaration applies from the manufacture date of the sampled product. Current rows show 25 matching-code offers already have marketplace-valid links; the 14 unlinked exact offers are coded 9405190039, outside the declared code set, and 12 further offers have no exact WB card. No additional links were sent without scope/date evidence.
- No new document or binding writes were made in this continuation because the remaining checked candidates failed exact code/card/scope checks or were already linked. No local files were deleted; pending review, unmatched offers and out-of-scope assignments remain. Overall all-brand/all-product completion is still incomplete.


## Continued — Kosmos 03254/23 — 2026-10-21

- Official FSA certificate `ЕАЭС RU С-CN.НВ93.В.03254/23` (record 3249749) is active through 18.05.2028 and lists LED lamp codes `8539520002`, `8539520003`, `8539520009`, Kosmos/SuperMax marks and exact lamp models. The FSA product entry states that covered serial goods must be manufactured no earlier than the 01.07.2022 sample date; the marketplace cards do not expose actual lot manufacture dates.
- A fresh WB preflight found 232 unique exact seller cards, all brand `Космос` with TN VED `8539520009`; none already had this certificate. The older declaration 78454/22 was present and valid on all 232.
- WB accepted one `POST /content/v2/cards/update` batch for all 232 cards. Post-write readback confirmed exact number/type/dates and a `valid` verdict on 232/232 cards; all prior documents and unrelated card fields were preserved. WB completed its verification automatically; no manual review action was taken. Official endpoint documentation: [WB product-card API](https://dev.wildberries.ru/openapi/work-with-products).
- Fresh Ozon checks found no exact Ozon record for 03254/23 and no in-scope offers among the same 232: 227 current TN VED values are outside the FSA LED code set, five are missing, and one listing also has a brand mismatch. No Ozon record or binding was created for this certificate.
- The source PDF remains local because Ozon still lacks an in-scope record/link and other assignments reuse the source. Evidence: `kosmos_03254_wb_preflight_live_20261021.json`, `kosmos_03254_ozon_preflight_live_20261021.json`, `kosmos_03254_wb_execution_20261021.json`, `kosmos_03254_wb_readback_verified_20261021.json`, and `kosmos_03254_wb_before_20261021.json`.
- Overall all-brand/all-product completion remains incomplete; Ozon misclassification and unresolved production-lot dates remain open issues.


## Continued — Feron 58098/25 — 2026-10-21

- FSA declaration `ЕАЭС N RU Д-CN.РА06.В.58098/25` (record 20431007) is active through 31.07.2030 and covers Feron EK emergency power units under TN VED `8504409100`.
- Fresh Ozon reads matched all four exact offers and Feron brand, but each listing currently reports TN VED `8504909800`; no Ozon record exists. The code is outside this declaration scope, so no Ozon upload or binding was created.
- WB has four exact EK cards. The declaration was already valid on EK40; it was added to EK50, EK100 and EK51. Final live readback shows the exact declaration on 4/4 cards and a `valid` WB verdict on 4/4. Existing documents and other card fields were preserved; automatic WB validation completed without manual review.
- The source PDF remains local because the Ozon links are unresolved. Evidence: `feron_58098_crossplatform_preflight_live_20261021.json`, `feron_58098_wb_execution_20261021.json`, `feron_58098_wb_reconciled_readback_20261021.json`, and `feron_58098_wb_preservation_audit_20261021.json`.
- All-brand/all-product completion remains incomplete.


## Continued — Arlight 41382/26 — 2026-10-21

- Live FSA record 21895502 remains active through 15.09.2031; its product scope lists Arlight lighting series SP, IM, MS, LTD, LGD, DL, ALT, CL, LT and LTM.
- Fresh Ozon readback confirms record 5625289 is approved and all 339 in-scope offers have exact approved bindings with matching product/SKU identity and TN VED. The 29 remaining source assignments use code 9405190039, which the FSA record does not list, and were excluded.
- The latest complete WB catalog read confirms exact declaration metadata and a valid verdict on all 339 in-scope cards. The local source PDF had one unique copy and was referenced only by 368 rows for this declaration. After confirming both platforms, deleted its 555,914-byte local copy. Receipt: `arlight_41382_local_pdf_cleanup_receipt_20261021.json`.
- Evidence: `arlight_41382_crossplatform_readback_live_20261021.json`. Overall all-brand/all-product completion remains incomplete.


## Continued — Arlight 69060/25 — 2026-10-21

- FSA record 19978046 was live and active through 09.03.2030. It lists power-supply series including ARS and TN VED 8504408300, with a manufacture-from-tested-sample-date condition.
- Fresh Ozon readback: record 5624646 is approved, with 552/552 exact in-scope product/SKU bindings approved. Fresh WB catalog/card reads found exact declaration metadata and a `valid` verdict on 552/552 cards (549 base offers plus 3 supplemental offers).
- One source-map offer, `028858(1)-1`, remains correctly unlinked: its current Ozon TN VED is 8504409100, outside the record's 8504408300 code. A separate family candidate `029543(1)-1` matches the ARS series and TN VED, but its product manufacture date is not available; it remains unlinked and one local copy is retained for follow-up.
- WB cards do not expose TN VED on 324 of the 552 confirmed cards and one card has a blank brand field. This does not change the exact vendorCode/nmID matches or the valid document verdicts recorded above.
- Deleted 5 redundant local PDFs (3,032,475 bytes) after both-platform confirmation; retained one 590,592-byte source PDF for the unresolved family candidate. Receipt: `arlight_69060_local_pdf_cleanup_receipt_20261021.json`.
- Overall all-brand/all-product completion remains incomplete.


## Continued — Stekker 15150/25 — 2026-10-21

- Official FSA declaration [20491822](https://pub.fsa.gov.ru/rds/declaration/view/20491822/product) is active from 25.08.2025 through 24.08.2030 for Stekker PSW/RSW/MSW/GLS switches and PST/RST/MST/GLS sockets, with TN VED codes 8536500700, 8536691000, 8536699008 and 8504405500. The registry notes application to products manufactured from the sample-manufacture date in the sampling act; the public record shows the 31.07.2025 test protocol, not the sampling-act date.
- Ozon record 5924853 was created and is approved. Live readback confirms 370 exact product/SKU bindings of 371 TN VED/brand-eligible offers: 301 approved and 69 in `background_check`. Offer `50831-1` has no Ozon SKU and could not be bound; four other offers have TN VED 8536508008 outside the record's scope, and one offer has no live Ozon brand value. The API rejected a first oversized batch because it contained the empty SKU; after reading back 301 links, the remaining 69 non-empty SKUs were bound and verified.
- WB accepted the update for 303 safe exact cards. Final readback after WB's indexing delay confirms the document on 303/303 cards: 301 have a `valid` verdict and 2 still await a verdict. No manual WB review action was taken. Earlier readback missed 7 cards; a later targeted read confirmed all 7 had settled as valid, without resubmitting them. Prior documents and unrelated card fields were preserved.
- 73 WB assignments remain skipped: 72 have conflicting or unconfirmed TN VED scope, and `39512-1` has no exact WB card. Twelve additional source-assignment rows are marked partial coverage and were not treated as confirmed scope.
- Kept the source PDF. Ozon offer `50831-1` lacks a bindable SKU, 69 Ozon bindings remain in background check, 2 WB items have no verdict, and other assigned offers remain unresolved. Evidence: `stekker_15150_crossplatform_preflight_live_20261021.json`, `stekker_15150_ozon_execution_20261021.json`, `stekker_15150_ozon_recovery_20261021.json`, `stekker_15150_wb_execution_20261021.json`, `stekker_15150_wb_readback_20261021.json`, and `stekker_15150_wb_delayed_settlement_20261021.json`.
- Overall all-brand/all-product completion remains incomplete.


### Correction — WB scope audit, 2026-10-21

- A broad reconciliation pass mistakenly added declaration `15150/25` to 67 extra Stekker WB cards with TN VED `8536508008`, outside the official declaration code list. I removed only those new document rows. A delayed final readback confirms the declaration is absent on all 67 cards; prior documents and unrelated card fields are preserved on all 67. The 303 in-scope Stekker WB cards verified earlier remain the confirmed WB total for this declaration.
- The same broad pass added one separate Systeme Electric declaration `14020/23` to exact offer `C9F34116-1`. Ozon already has an approved exact binding and the declaration names the matching City 9 SET automatic breaker, but the WB card has no TN VED value. I have kept this row for scope follow-up and do not count it toward Stekker or all-brand completion.
- No local certificate files were deleted in this correction. Evidence: `stekker_15150_wb_scope_correction_20261021.json`, `stekker_15150_wb_scope_correction_final_readback_20261021.json`, `stekker_15150_wb_scope_correction_followup_20261021.json`, and `all_found_coverage_summary_20261021.json`. Overall all-brand/all-product coverage remains incomplete.

- Fresh Ozon recheck of 9 pending records covered 609 exact bindings: 573 are approved and 36 still await verification (one whole document record has 25 pending links). No local source file met the two-platform cleanup rule. Evidence: `all_found_pending_ozon_recheck_20261021.json`.


## Arlight certificate 03451/22 — 2026-10-21

- The manufacturer certificate `ЕАЭС RU С-HK.НА46.В.03451/22` is valid 16.04.2022–15.04.2027 and covers Arlight power-supply series ARJ, ARPJ, ARPV and ARV. Its source PDF SHA-256 is `22f5bd0657cf8c55754b3bd0d73d102de1b9520d6c167242555ae63349398add`.
- Fresh Ozon readback confirms record 5925989 is `approved` and all 462 exact product/SKU bindings are `approved`.
- WB now shows the exact document number, type and dates on all 462 assigned cards. The 206 cards with in-scope TN VED were matched directly; 256 blank-TN-VED cards were confirmed through exact seller-offer, brand and Ozon product/model evidence. The final eight were added in one accepted batch and confirmed after delayed readback; no write was repeated. Prior documents and unrelated fields are preserved on all 462 cards. WB review remains pending on all 462; no manual review action was taken.
- Deleted all four identical local PDF copies (4,743,256 bytes total) only after exact Ozon bindings and WB card readbacks were confirmed; no copy with this SHA-256 remains in the workspace. Receipt: `arlight_03451_local_pdf_cleanup_receipt_20261021.json`.
- Evidence: `arlight_03451_crossplatform_readback_final_20261021.json`, `arlight_03451_ozon_final_recheck_20261021_0948.json`, `arlight_03451_remaining_8_wb_delayed_readback_20261021.json`. Overall all-brand/all-product completion remains incomplete.

## Continued — Arlight 46747/26 — 2026-10-21

- Fresh Ozon readback confirms record 5445163 is approved and all 114 source-confirmed product links remain approved. One additional assigned offer, `029543(1)-1`, remains unlinked because the original certificate PDF limits applicability to products manufactured from a 01.2026 sample, and the offer's manufacture date is unknown.
- Fresh WB readback found the exact document on 113 of 114 target cards; the exact card for `045399-1` is still not returned by WB search. Of the 113 visible rows, 3 have a valid document verdict and a final valid card verdict, 21 have a valid document-item verdict while the overall card status still says `documents_missing`, and 89 have no final document-item verdict. WB review remains with the platform.
- The first targeted check's verdict field was incomplete because its projection helper omitted raw item verdicts; the raw API recheck supersedes that count. The local source PDF was retained because not all links and outcomes are confirmed.
- A fresh residual check still finds no WB card for `045399-1`. Ozon identifies candidate `029543(1)-1` as ARS-250-24-L1 (created 2023-08-21) but exposes no manufacture-date or batch attribute; creation date does not establish that the sold lot meets the PDF's 01.2026 sample cutoff. No new link was made and the source PDF remains.
- A fresh read-only check of 10 existing Ozon document records (1,071 binding edges) found exact binding sets and document metadata; statuses are unchanged, with 36 product bindings and one document record still awaiting verification. No mutation was sent. Evidence: `all_found_pending_ozon_recheck_20261021_continued_0955.json` and `arlight_46747_residual_offers_20261021_0955.json`.
- Evidence: `arlight_46747_crossplatform_live_recheck_20261021.json` and `arlight_46747_wb_verdicts_raw_recheck_20261021.json`. Overall all-brand/all-product completion remains incomplete.


## Candidate review — Jazzway 06273/22 — 2026-10-21

- OCR of the preserved manufacturer PDF identifies `ЕАЭС RU С-HK.АБ53.В.06273/22` as a certificate of conformity for serial production of general-purpose JAZZWAY/FAZA LED lamps. The printed term is 29.11.2022–28.11.2027 and the listed TN VED codes are 8539520001/0002/0003/0009.
- The assignment map contains 276 rows under one spelling/type label and 4 under a Latin/Cyrillic `C` variant with another type label, all pointing to the same PDF hash. I did not create separate records or attach the document while the exact FSA record status and this type/number discrepancy remain unresolved. The FSA search page returned blank in the current session and a direct public read returned HTTP 403; no workaround was used.
- The source PDF remains local and no Ozon or WB mutation was made for this candidate. Evidence: `jazzway_06273_candidate_audit_20261021.json`.


## Arlight certificate 02669/21 — 2026-10-21

- The official FSA extract (record 3008100) confirms the Arlight serial-production certificate `ЕАЭС RU С-HK.АБ53.В.02669/21` was active on 21.10.2026 and expires 07.12.2026. It names the ART, MAG, FLEX and other Arlight general-purpose luminaire series. The original PDF hash was `9b9c776c47d6e805fc9a18b4717a64407b348289c7b0dcf4f8c42de5e90b275f`.
- Exact live source assignments and Ozon identity/brand/model checks matched all 578 target SKUs; no Ozon record existed before upload. Ozon record 5928221 is now `approved`, with 578/578 exact product/SKU links all `approved`.
- WB returned one exact assigned card for each of 578 offers. The exact number/type/dates are now visible on 578/578 cards; prior documents and unrelated fields are preserved. WB review remains pending by design; no manual review action was taken. The FSA extract uses legacy TN VED `9405109803`, while current marketplace cards show codes `9405190039`, `9405110033` and `9405110039`; this discrepancy is recorded, and no TN VED fields were changed.
- After both platform readbacks, deleted the sole local source PDF copy (609,631 bytes). Receipt: `arlight_02669_local_pdf_cleanup_receipt_20261021.json`. The official FSA extract and API evidence remain saved.
- Overall all-brand/all-product coverage remains incomplete.
