"""Delete only source PDFs with a fresh, complete marketplace confirmation."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST_PATH = HERE / "iek_missing_new_docs_manifest_20261020.json"
OZON_REPORT_PATH = HERE / "post_upload_reconciliation_20261020.json"
WB_READBACK_PATH = HERE / "wb_article_recheck_20261020.json"
RECEIPT_PATH = HERE / "local_pdf_cleanup_receipt_20261020.json"

CLEAN_EAEU_NUMBERS = {
    "ЕАЭС N RU Д-CN.РА02.В.66507/26",
    "ЕАЭС N RU Д-CN.РА02.В.68364/26",
    "ЕАЭС N RU Д-CN.РА02.В.71161/26",
    "ЕАЭС N RU Д-RU.РА04.В.27073/26",
}
NATIONAL_PREFLIGHTS = {
    "RU С-RU.АЮ64.В.00560/25": HERE / "iek_national_fire_cert_00560_preflight_20261020.json",
    "RU С-RU.АЮ64.В.00631/26": HERE / "iek_national_fire_cert_preflight_20261020.json",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    report = load(OZON_REPORT_PATH)
    wb = load(WB_READBACK_PATH)
    manifest = load(MANIFEST_PATH)
    ozon_by_number = {row["number"]: row for row in report["ozon"]["new_docs"]}
    eaeu_by_number = {row["number"]: row for row in manifest["groups"]}

    documents: dict[str, dict] = {}
    for number in CLEAN_EAEU_NUMBERS:
        documents[number] = eaeu_by_number[number]["upload_file"]
    for number, path in NATIONAL_PREFLIGHTS.items():
        documents[number] = load(path)["manifest"]["upload_file"]

    target_offers: set[str] = set()
    target_products: dict[str, int] = {}
    for number in documents:
        ozon_doc = ozon_by_number[number]
        assert ozon_doc["status_code"] == "approved", f"Ozon document is not approved: {number}"
        assert ozon_doc["verified_expected_links"] == ozon_doc["expected_targets"], f"Missing Ozon link: {number}"
        assert all(row["exact_binding_visible"] and row["product_status_code"] == "approved"
                   for row in ozon_doc["targets"]), f"Unapproved or missing Ozon product link: {number}"
        target_offers.update(str(row["offer_id"]) for row in ozon_doc["targets"])
        target_products[number] = len(ozon_doc["targets"])

    assert wb.get("read_only") is True, "WB result must be read-only"
    wb_rows = {str(row["offer_id"]): row for row in wb["results"]}
    assert target_offers <= wb_rows.keys(), "WB article check did not cover every target offer"
    assert all(not wb_rows[offer]["article_relevant_cards"] and
               wb_rows[offer]["exact_offer_card_count"] == 0 for offer in target_offers), \
        "A relevant WB card exists; retain the local PDF until its link is confirmed"

    file_rows = []
    for number, metadata in documents.items():
        path = Path(metadata["path"])
        if not path.is_absolute():
            path = ROOT / path
        assert path.is_file(), f"Expected uploaded source PDF is missing: {path}"
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        assert digest == metadata["sha256"], f"Uploaded source PDF changed after verification: {path}"
        duplicates = []
        for candidate in ROOT.rglob("*.pdf"):
            if ".git" in candidate.parts:
                continue
            if hashlib.sha256(candidate.read_bytes()).hexdigest() == digest:
                duplicates.append(candidate.resolve())
        assert duplicates == [path.resolve()], f"Unexpected local duplicate for {number}: {duplicates}"
        file_rows.append({
            "number": number,
            "path": str(path.resolve()),
            "sha256": digest,
            "size_bytes": len(data),
            "ozon_certificate_id": ozon_by_number[number]["certificate_id"],
            "ozon_document_status": ozon_by_number[number]["status_code"],
            "ozon_expected_targets": target_products[number],
            "ozon_approved_target_links": sum(row["product_status_code"] == "approved"
                                               for row in ozon_by_number[number]["targets"]),
            "wb_target_offers": sorted(str(row["offer_id"]) for row in ozon_by_number[number]["targets"]),
            "wb_relevant_card_matches": 0,
        })

    now = datetime.now(timezone.utc).isoformat()
    receipt = {
        "status": "prepared",
        "prepared_at": now,
        "ozon_readback_at": report["checked_at"],
        "wb_readback_at": wb["checked_at"],
        "ozon_readback_basis": "Every listed Ozon document is approved and every expected target binding is visible with product_status_code=approved.",
        "wb_readback_basis": "Fresh textSearch checks covered all target offers; no exact offer card or article-relevant card was returned.",
        "distinct_wb_target_offers": len(target_offers),
        "source_files": file_rows,
    }
    atomic_json(RECEIPT_PATH, receipt)

    for row in file_rows:
        Path(row["path"]).unlink()
        row["deleted"] = True
        row["deleted_at"] = datetime.now(timezone.utc).isoformat()
        atomic_json(RECEIPT_PATH, receipt)

    receipt["status"] = "deleted"
    receipt["completed_at"] = datetime.now(timezone.utc).isoformat()
    receipt["total_bytes_reclaimed"] = sum(row["size_bytes"] for row in file_rows)
    atomic_json(RECEIPT_PATH, receipt)

    cleanup_summary = {
        "status": "deleted_after_marketplace_confirmation",
        "receipt": str(RECEIPT_PATH),
        "completed_at": receipt["completed_at"],
        "documents": [row["number"] for row in file_rows],
        "files_deleted": len(file_rows),
        "bytes_reclaimed": receipt["total_bytes_reclaimed"],
    }
    manifest["local_file_cleanup"] = cleanup_summary
    for group in manifest["groups"]:
        group["local_file_cleanup"] = (
            cleanup_summary if group["number"] in CLEAN_EAEU_NUMBERS else
            {"status": "retained", "reason": "Ozon bindings incomplete, declined, or removed."}
        )
    atomic_json(MANIFEST_PATH, manifest)
    for number, path in NATIONAL_PREFLIGHTS.items():
        wrapper = load(path)
        status = cleanup_summary if number in documents else None
        wrapper["local_file_cleanup"] = status
        wrapper["manifest"]["local_file_cleanup"] = status
        atomic_json(path, wrapper)

    report["local_source_files_deleted"] = True
    report["local_source_files_deleted_count"] = len(file_rows)
    report["local_source_files_deleted_bytes"] = receipt["total_bytes_reclaimed"]
    report["local_source_files_deleted_documents"] = cleanup_summary["documents"]
    report["local_source_files_cleanup_receipt"] = str(RECEIPT_PATH)
    report["wildberries"]["fresh_article_recheck_at"] = wb["checked_at"]
    report["wildberries"]["fresh_article_recheck_offers"] = len(wb["results"])
    report["wildberries"]["fresh_article_recheck_target_offers"] = len(target_offers)
    report["wildberries"]["fresh_article_recheck_target_card_matches"] = 0
    report["wildberries"]["fresh_article_recheck_target_exact_offer_cards"] = 0
    for number, doc in ozon_by_number.items():
        if number in CLEAN_EAEU_NUMBERS or number in NATIONAL_PREFLIGHTS:
            doc["local_source_pdf_deleted"] = True
    atomic_json(OZON_REPORT_PATH, report)

    o = report["ozon"]
    w = report["wildberries"]
    lines = [
        "# Certificate reconciliation — 2026-10-20", "",
        f"Fresh Ozon API readback at {report['checked_at']}. Complete catalog snapshot at {report['snapshot_basis']['complete_marketplace_snapshot_checked_at']}.", "",
        "## Ozon", "",
        f"- {o['active_products']:,} active products.",
        f"- {o['products_with_current_approved_document_after_updates']:,} have at least one current approved certificate or declaration; {o['products_without_current_approved_document_after_updates']:,} do not.",
        f"- {o['products_with_at_least_one_current_non_declined_link_after_updates']:,} have at least one current link that is not declined; {o['products_without_any_current_non_declined_link_after_updates']:,} have none.",
        f"- {o['new_documents_uploaded_and_visible']} new document records are visible; target-link states across overlapping documents: {o['new_document_edge_status_counts_including_overlapping_docs']}. {o['sample_date_unbindings_verified']} ambiguous sample-date links were removed and verified absent.",
        f"- Current Ozon document records: {o['current_certificate_status_counts']}; reported product-link count: {o['current_products_count_across_certificate_records']:,}.", "",
        "## Wildberries", "",
        f"- {w['complete_unique_cards']:,} unique cards: {w['cards_with_at_least_one_valid_document']:,} have a valid document, {w['cards_pending_only']} are pending only, {w['cards_rejected_only']} rejected only, and {w['cards_without_any_current_valid_document']:,} have no valid document.",
        f"- Fresh WB textSearch readback at {wb['checked_at']} covered {len(target_offers)} unique offers tied to the six fully approved documents. It found 0 matching cards. No WB write was made.", "",
        "## Uploaded Ozon documents", "",
    ]
    for doc in o["new_docs"]:
        states = {}
        for row in doc["targets"]:
            if row["exact_binding_visible"]:
                states[row["product_status_code"]] = states.get(row["product_status_code"], 0) + 1
        lines.append(f"- `{doc['number']}` — Ozon ID {doc['certificate_id']}; record `{doc['status_code']}`; {doc['verified_expected_links']}/{doc['expected_targets']} target bindings visible; link states {states}.")
    lines += [
        "", "The six source PDFs were deleted only after fresh Ozon readback showed every target link approved and the WB article searches found no matching cards. The source SHA-256 values, sizes, Ozon IDs, and readback times are preserved in `local_pdf_cleanup_receipt_20261020.json`.",
        "", "Retained files include documents with declined, missing, or removed Ozon links and all other unresolved candidates. The overall product-coverage task remains incomplete; WB review remains pending wherever a matching card is later identified.", "",
    ]
    (HERE / "post_upload_reconciliation_20261020.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({
        "status": receipt["status"],
        "deleted_files": len(file_rows),
        "bytes_reclaimed": receipt["total_bytes_reclaimed"],
        "documents": cleanup_summary["documents"],
        "wb_target_offers_checked": len(target_offers),
        "receipt": str(RECEIPT_PATH),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
