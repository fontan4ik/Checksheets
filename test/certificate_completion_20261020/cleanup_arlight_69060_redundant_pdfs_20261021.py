#!/usr/bin/env python3
"""After live two-platform confirmation, remove redundant 69060/25 PDFs only."""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
BASE_OZON = HERE / "arlight_69060_crossplatform_preflight_live_20261021.json"
BASE_WB = HERE / "arlight_69060_wb_live_readback_20261021.json"
SUPPLEMENTAL = HERE / "arlight_69060_supplemental_live_readback_20261021.json"
ALL_BINDINGS = HERE / "arlight_69060_all_ozon_bindings_live_20261021.json"
EXCLUDED = HERE / "arlight_69060_out_of_scope_offer_live_20261021.json"
REMAINING = HERE / "arlight_69060_candidate_029543_live_20261021.json"
SOURCE_PREFLIGHT = API / "arlight_69060_preflight_20261012.json"
ASSIGNMENTS = HERE / "all_confirmed_source_assignments_live_20261021.csv"
CATALOG = ROOT / "output_to_user/certificates/document_catalog_master.csv"
REPORT_JSON = HERE / "post_upload_reconciliation_20261020.json"
REPORT_MD = HERE / "post_upload_reconciliation_20261020.md"
NUMBER = "ЕАЭС N RU Д-HK.РА02.В.69060/25"
EXPECTED_F652 = "baeb142abdd28d42ae6cbbe4993134f3726364e94ca66c3b09d913d52b81db04"
EXPECTED_703 = "283c1f57322d9244c0bcc0420500f27d6ede0c41603da00db51865326c550a44"
KEEP = (ROOT / "output_to_user/certificates/additional_search/brand_research/arlight/"
        "followup_2026_10_02_partial_missing_regs/documents/69060_25_decl_Arlight_power_supplies_037.pdf")
RECEIPT = HERE / "arlight_69060_local_pdf_cleanup_receipt_20261021.json"
JOURNAL = HERE / "arlight_69060_local_pdf_cleanup_journal_20261021.jsonl"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def abort(reason: str) -> None:
    raise RuntimeError(reason)


def main() -> None:
    if RECEIPT.exists() or JOURNAL.exists():
        abort("cleanup receipt exists; inspect before any repeat")
    ozon = json.loads(BASE_OZON.read_text())
    wb = json.loads(BASE_WB.read_text())
    supplemental = json.loads(SUPPLEMENTAL.read_text())
    bindings = json.loads(ALL_BINDINGS.read_text())
    excluded = json.loads(EXCLUDED.read_text())
    remaining = json.loads(REMAINING.read_text())
    source_preflight = json.loads(SOURCE_PREFLIGHT.read_text())

    # Ozon base group: exact active identity/brand/TN VED plus an approved record.
    base_record = (ozon.get("ozon", {}).get("exact_document_records") or [])
    base_targets = ozon.get("ozon", {}).get("targets") or []
    if (ozon.get("complete") is not True or ozon.get("ozon", {}).get("eligible") != 549
            or len(base_record) != 1 or base_record[0].get("certificate_id") != 5624646
            or base_record[0].get("status_code") != "approved"
            or base_record[0].get("type_code") != "declaration"
            or len(base_targets) != 549 or any(not x.get("eligible") for x in base_targets)):
        abort("Ozon base readback gate failed")
    if ozon["ozon"].get("target_binding_status_counts") != {"approved": 549}:
        abort("Ozon base approved-binding gate failed")

    # WB base group: all exact source nmIDs have one exact valid declaration row.
    wb_targets = wb.get("wildberries", {}).get("targets") or []
    source_targets = {str(t["offer_id"]): t for t in source_preflight.get("targets", [])}
    if len(wb_targets) != 549 or len(source_targets) != 549:
        abort("WB/source base target count mismatch")
    for row in wb_targets:
        source = source_targets.get(str(row.get("offer_id")))
        if not source or str(row.get("wb_nmID")) != str(source.get("wb_nmID")):
            abort("WB source identity changed for " + str(row.get("offer_id")))
        if len(row.get("document_rows") or []) != 1 or row.get("verdict_valid") is not True:
            abort("WB exact document/verdict missing for " + str(row.get("offer_id")))
        if any("exact_vendor_code_or_source_nmID" in p for p in (row.get("problems") or [])):
            abort("WB exact card identity not confirmed for " + str(row.get("offer_id")))
        if not row.get("model_family_match"):
            abort("Source model family not confirmed for " + str(row.get("offer_id")))

    # Three supplemental offers were separately refreshed on both platforms.
    if (supplemental.get("certificate_id") != 5624646
            or supplemental.get("ozon_certificate_status") != "approved"
            or supplemental.get("supplemental_target_count") != 3
            or supplemental.get("summary", {}).get("ozon_supplemental_active_products_exact_scope_and_approved_binding") != 3
            or supplemental.get("summary", {}).get("wb_supplemental_exact_cards_with_valid_document") != 3):
        abort("Supplemental live readback gate failed")
    if any(x.get("problems") for x in supplemental.get("ozon_products", []) + supplemental.get("wb_products", [])):
        abort("Supplemental product has an unresolved live problem")

    # Exact cross-platform binding pair set: 549 base + 3 supplemental.
    base_pairs = {(str(x.get("product_id")), str(x.get("sku"))) for x in base_targets}
    supplemental_pairs = {(str(x.get("product_id")), str(x.get("sku"))) for x in supplemental.get("ozon_products", [])}
    expected_pairs = base_pairs | supplemental_pairs
    live_rows = bindings.get("bindings") or []
    live_pairs = {(str(x.get("product_id")), str(x.get("sku"))) for x in live_rows
                  if x.get("status") == "approved"}
    if (bindings.get("certificate_id") != 5624646 or bindings.get("certificate_status") != "approved"
            or bindings.get("total_bindings") != 552 or bindings.get("status_counts") != {"approved": 552}
            or len(expected_pairs) != 552 or live_pairs != expected_pairs):
        abort("Ozon full target-pair readback gate failed")

    # Preserve the one family candidate whose production lot/date is still unknown.
    candidate = (remaining.get("wb_exact_cards") or [])
    candidate_sku = "1145220958"
    candidate_pair = [(str(x.get("product_id")), str(x.get("sku"))) for x in remaining.get("ozon_binding_rows", [])]
    if (remaining.get("offer_id") != "029543(1)-1" or not remaining.get("read_only")
            or any(sku == candidate_sku for _, sku in candidate_pair)
            or len(candidate) != 1
            or any("69060" in str(d.get("number")) for d in ((candidate[0].get("documents") or {}).get("items") or []))):
        abort("Unconfirmed family candidate has unexpectedly changed; preserve all source PDFs")

    # The only excluded source-map item is outside the declaration's listed TN VED code.
    excluded_product = excluded.get("ozon_product") or []
    excluded_attrs = excluded.get("ozon_attributes") or []
    excluded_cards = excluded.get("wb_exact_cards") or []
    if len(excluded_product) != 1 or len(excluded_cards) != 1:
        abort("Excluded offer current identity incomplete")
    excluded_attribute_map = {str(a.get("id")): a for a in excluded_attrs[0].get("attributes", [])}
    excluded_codes = [str(v.get("value") or "").split(" - ", 1)[0]
                      for v in excluded_attribute_map.get("22232", {}).get("values", [])]
    if excluded_codes != ["8504409100"]:
        abort("Excluded offer TN VED no longer confirmed out of scope")
    if str(excluded_product[0].get("sku")) in {sku for _, sku in live_pairs}:
        abort("Out-of-scope product unexpectedly has a 69060 binding")
    if any("69060" in str(d.get("number")) for d in ((excluded_cards[0].get("documents") or {}).get("items") or [])):
        abort("Out-of-scope WB card unexpectedly has 69060")

    # Confirm the exact local copy set, and keep the follow-up candidate's source PDF.
    if not KEEP.is_file() or sha(KEEP) != EXPECTED_703:
        abort("Retained candidate PDF is missing or changed")
    folders = [ROOT / "output_to_user/certificates", HERE, API]
    found: list[Path] = []
    for folder in folders:
        for path in folder.rglob("*.pdf"):
            if path.is_file() and sha(path) in {EXPECTED_F652, EXPECTED_703}:
                found.append(path)
    primary = [p for p in found if sha(p) == EXPECTED_F652]
    alternate = [p for p in found if sha(p) == EXPECTED_703]
    if len(primary) != 1 or len(alternate) != 5 or KEEP.resolve() not in {p.resolve() for p in alternate}:
        abort(f"Unexpected matching local copy set: primary={len(primary)} alternate={len(alternate)}")

    # Ensure catalog and assignment sources classify both hashes as this declaration only.
    with CATALOG.open(encoding="utf-8-sig", newline="") as stream:
        catalog_rows = list(csv.DictReader(stream))
    matching_catalog = [r for r in catalog_rows if r.get("SHA256") in {EXPECTED_F652, EXPECTED_703}]
    if (len(matching_catalog) != 2
            or any("69060/25" not in str(r.get("Номера/названия документов")) for r in matching_catalog)):
        abort("Document catalog does not associate both PDF hashes only with 69060/25")
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        assigned = list(csv.DictReader(stream))
    base_rows = [r for r in assigned if "F6522803E046324C87BC430F67671163.pdf" in r.get("source_files", "")]
    if (len(base_rows) != 550
            or Counter((r.get("ozon_state"), r.get("wb_state")) for r in base_rows)
            != Counter({("approved_link", "valid"): 549, ("missing_binding", "missing_document"): 1})):
        abort("Local source assignment count changed")

    # Delete the uploaded source and four redundant copies. Keep one exact PDF for offer 029543(1)-1.
    delete_paths = primary + [p for p in alternate if p.resolve() != KEEP.resolve()]
    if len(delete_paths) != 5:
        abort("Unexpected local deletion count")
    deleted_files = []
    bytes_deleted = 0
    deleted_at = dt.datetime.now(dt.timezone.utc).isoformat()
    for path in delete_paths:
        expected_hash = sha(path)
        size = path.stat().st_size
        path.unlink()
        if path.exists():
            abort("PDF remains after unlink: " + str(path))
        deleted_files.append({"path": str(path), "sha256": expected_hash, "bytes": size})
        bytes_deleted += size

    receipt = {
        "deleted_at_utc": deleted_at,
        "number": NUMBER,
        "fsa_record_id": 19978046,
        "fsa_status": "Действует; checked in the live FSA UI on 2026-10-21",
        "ozon_certificate_id": 5624646,
        "ozon_status": "approved",
        "ozon_approved_in_scope_bindings": 552,
        "wb_exact_cards_with_valid_document": 552,
        "base_targets": 549,
        "supplemental_targets": 3,
        "out_of_scope_tnved_exclusion": {"offer_id": "028858(1)-1", "tnved": "8504409100",
                                         "allowed_tnved": "8504408300", "document_not_linked": True},
        "unresolved_family_candidate_preserved": {"offer_id": "029543(1)-1", "reason": "production lot/date is unconfirmed",
                                                   "retained_source_pdf": str(KEEP)},
        "deleted_files": deleted_files,
        "bytes_deleted": bytes_deleted,
        "retained_files": [{"path": str(KEEP), "sha256": EXPECTED_703, "bytes": KEEP.stat().st_size}],
        "source_deleted_only_after_both_platform_readbacks": True,
        "wb_card_data_quality_gaps": {"tnved_not_present_on_cards": 324, "brand_blank": 1,
                                       "all_552_exact_documents_still_have_valid_verdict": True},
        "evidence_files": [str(BASE_OZON), str(BASE_WB), str(SUPPLEMENTAL), str(ALL_BINDINGS), str(EXCLUDED)],
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"phase": "deleted_redundant_copies", "at_utc": deleted_at,
                                 "receipt": str(RECEIPT), "count": len(deleted_files),
                                 "bytes": bytes_deleted}, ensure_ascii=False) + "\n")

    # Update the durable reconciliation report after the receipt exists.
    summary = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    summary["local_source_files_deleted_count"] = int(summary.get("local_source_files_deleted_count", 0)) + len(deleted_files)
    summary["local_source_files_deleted_bytes"] = int(summary.get("local_source_files_deleted_bytes", 0)) + bytes_deleted
    summary.setdefault("local_source_files_deleted_documents", []).append(NUMBER)
    continuation = summary.setdefault("latest_continuation", {})
    continuation["checked_at_utc"] = deleted_at
    continuation["local_source_files_deleted_in_continuation"] = int(continuation.get("local_source_files_deleted_in_continuation", 0)) + len(deleted_files)
    continuation["local_source_file_bytes_deleted_in_continuation"] = int(continuation.get("local_source_file_bytes_deleted_in_continuation", 0)) + bytes_deleted
    continuation["arlight_69060_25"] = {
        "number": NUMBER,
        "fsa_record_id": 19978046,
        "fsa_status": "active",
        "issue_date": "2025-03-10",
        "expiry_date": "2030-03-09",
        "allowed_tnved": ["8504408300"],
        "ozon_certificate_id": 5624646,
        "ozon_status": "approved",
        "ozon_approved_bindings": 552,
        "wb_exact_valid_cards": 552,
        "out_of_scope_excluded": {"offer_id": "028858(1)-1", "tnved": "8504409100"},
        "unresolved_candidate": {"offer_id": "029543(1)-1", "ozon_binding": False,
                                 "wb_document": False, "reason": "manufacturer series match is confirmed, but applicable batch production date is unknown"},
        "deleted_redundant_pdfs": len(deleted_files),
        "deleted_bytes": bytes_deleted,
        "retained_one_source_pdf_for_unresolved_candidate": str(KEEP),
        "wb_card_data_quality_gaps": {"tnved_unconfirmed": 324, "brand_blank": 1},
        "cleanup_receipt": str(RECEIPT),
        "evidence_files": [p.name for p in [BASE_OZON, BASE_WB, SUPPLEMENTAL, ALL_BINDINGS,
                                              HERE / "arlight_69060_candidate_029543_live_20261021.json"]],
    }
    continuation["overall_coverage_complete"] = False
    tmp = REPORT_JSON.with_suffix(".tmp")
    tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(REPORT_JSON)

    markdown = REPORT_MD.read_text(encoding="utf-8")
    heading = "## Continued — Arlight 69060/25 — 2026-10-21"
    if heading not in markdown:
        markdown += (
            "\n\n" + heading + "\n\n"
            "- FSA record 19978046 was live and active through 09.03.2030. It lists power-supply series including ARS and TN VED 8504408300, with a manufacture-from-tested-sample-date condition.\n"
            "- Fresh Ozon readback: record 5624646 is approved, with 552/552 exact in-scope product/SKU bindings approved. Fresh WB catalog/card reads found exact declaration metadata and a `valid` verdict on 552/552 cards (549 base offers plus 3 supplemental offers).\n"
            "- One source-map offer, `028858(1)-1`, remains correctly unlinked: its current Ozon TN VED is 8504409100, outside the record's 8504408300 code. A separate family candidate `029543(1)-1` matches the ARS series and TN VED, but its product manufacture date is not available; it remains unlinked and one local copy is retained for follow-up.\n"
            "- WB cards do not expose TN VED on 324 of the 552 confirmed cards and one card has a blank brand field. This does not change the exact vendorCode/nmID matches or the valid document verdicts recorded above.\n"
            f"- Deleted {len(deleted_files)} redundant local PDFs ({bytes_deleted:,} bytes) after both-platform confirmation; retained one 590,592-byte source PDF for the unresolved family candidate. Receipt: `arlight_69060_local_pdf_cleanup_receipt_20261021.json`.\n"
            "- Overall all-brand/all-product completion remains incomplete.\n"
        )
        REPORT_MD.write_text(markdown, encoding="utf-8")

    print(json.dumps({"deleted_files": len(deleted_files), "bytes_deleted": bytes_deleted,
                      "ozon_approved_links": 552, "wb_valid_cards": 552,
                      "retained_candidate_pdf": str(KEEP), "receipt": str(RECEIPT)},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
