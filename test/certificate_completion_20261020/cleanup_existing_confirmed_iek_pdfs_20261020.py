"""Remove only cached PDFs for existing Ozon docs after fresh cross-market checks."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RECHECK = HERE / "existing_iek_certificates_cleanup_recheck_20261020.json"
MAIN_RECEIPT = HERE / "local_pdf_cleanup_receipt_20261020.json"
SUPPLEMENT = HERE / "existing_iek_local_cleanup_receipt_20261020.json"
REPORT = HERE / "post_upload_reconciliation_20261020.json"
CURRENT_AUDIT = HERE / "iek_current_ozon_docs_audit_20261020.json"
MANIFEST = HERE / "iek_validated_binding_manifest_20261020.json"
SAFE_NUMBERS = {
    "ЕАЭС N RU Д-CN.РА02.В.68390/26",
    "ЕАЭС N RU Д-CN.РА02.В.71342/26",
    "ЕАЭС N RU Д-CN.РА07.В.40532/26",
}


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    check = read(RECHECK)
    main_receipt = read(MAIN_RECEIPT)
    report = read(REPORT)
    manifest = read(MANIFEST)
    audit = read(CURRENT_AUDIT)
    assert check["read_only"] is True
    assert check["documents_with_all_live_links_approved"] == 3
    assert check["wb_articles_with_relevant_cards"] == 0
    assert check["wb_articles_checked"] == 33
    docs = {row["number"]: row for row in check["documents"]}
    assert SAFE_NUMBERS <= docs.keys()
    assert all(docs[number]["all_expected_links_approved"] and
               docs[number]["all_live_ozon_links_approved"] for number in SAFE_NUMBERS)
    assert all(not row["relevant_cards"] for row in check["wb_article_results"])

    audit_by_number = {row["number"]: row for row in audit["groups"]}
    rows = []
    for number in sorted(SAFE_NUMBERS):
        doc = docs[number]
        path = Path(doc["local_pdf"])
        assert path.is_file(), f"Missing local PDF: {path}"
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        assert digest == doc["local_pdf_sha256"] == audit_by_number[number]["downloaded_sha256"]
        duplicates = []
        for candidate in ROOT.rglob("*.pdf"):
            if ".git" not in candidate.parts and hashlib.sha256(candidate.read_bytes()).hexdigest() == digest:
                duplicates.append(candidate.resolve())
        assert path.resolve() in duplicates, f"Verified source PDF is absent from duplicate set for {number}: {duplicates}"
        duplicates = sorted(set(duplicates))
        rows.append({
            "number": number,
            "path": str(path.resolve()),
            "duplicate_paths": [str(candidate) for candidate in duplicates],
            "sha256": digest,
            "size_bytes": sum(candidate.stat().st_size for candidate in duplicates),
            "single_copy_size_bytes": len(data),
            "duplicate_copy_count": len(duplicates),
            "ozon_certificate_id": doc["certificate_id"],
            "ozon_live_binding_count": doc["ozon_binding_count"],
            "ozon_live_binding_statuses": doc["ozon_binding_statuses"],
            "ozon_expected_targets": len(doc["expected_targets"]),
            "wb_articles_checked": sum(row["offer_id"] in {target["offer_id"] for target in doc["expected_targets"]}
                                        for row in check["wb_article_results"]),
            "wb_relevant_cards": 0,
        })

    receipt = {
        "status": "prepared",
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "ozon_readback_at": check["checked_at"],
        "wb_readback_at": check["checked_at"],
        "basis": "Fresh Ozon API readback verified every live link is approved; live WB article searches found no relevant cards.",
        "documents": rows,
    }
    save(SUPPLEMENT, receipt)
    for row in rows:
        for file_path in row["duplicate_paths"]:
            Path(file_path).unlink()
        row["deleted"] = True
        row["deleted_at"] = datetime.now(timezone.utc).isoformat()
        save(SUPPLEMENT, receipt)
    receipt["status"] = "deleted"
    receipt["completed_at"] = datetime.now(timezone.utc).isoformat()
    receipt["bytes_reclaimed"] = sum(row["size_bytes"] for row in rows)
    save(SUPPLEMENT, receipt)

    main_receipt["source_files"].extend(rows)
    main_receipt["source_files"] = list({row["sha256"]: row for row in main_receipt["source_files"]}.values())
    main_receipt["total_bytes_reclaimed"] = sum(row["size_bytes"] for row in main_receipt["source_files"])
    main_receipt["additional_cleanup_receipts"] = [str(SUPPLEMENT)]
    main_receipt["completed_at"] = receipt["completed_at"]
    save(MAIN_RECEIPT, main_receipt)

    cleanup = {
        "status": "deleted_after_marketplace_confirmation",
        "receipt": str(MAIN_RECEIPT),
        "completed_at": receipt["completed_at"],
        "documents": [row["number"] for row in main_receipt["source_files"]],
        "files_deleted": sum(len(row.get("duplicate_paths") or [row["path"]])
                              for row in main_receipt["source_files"]),
        "bytes_reclaimed": main_receipt["total_bytes_reclaimed"],
        "additional_receipt": str(SUPPLEMENT),
    }
    report["local_source_files_deleted"] = True
    report["local_source_files_deleted_count"] = cleanup["files_deleted"]
    report["local_source_files_deleted_bytes"] = cleanup["bytes_reclaimed"]
    report["local_source_files_deleted_documents"] = cleanup["documents"]
    report["local_source_files_cleanup_receipt"] = str(MAIN_RECEIPT)
    live_checked_offers = {str(row["offer_id"]) for row in check["wb_article_results"]}
    for row in main_receipt["source_files"]:
        live_checked_offers.update(str(offer) for offer in row.get("wb_target_offers", []))
    report["wildberries"]["fresh_article_recheck_target_offers"] = len(live_checked_offers)
    report["wildberries"]["existing_document_articles_checked"] = check["wb_articles_checked"]
    report["wildberries"]["existing_document_article_matches"] = 0
    save(REPORT, report)

    for group in manifest["groups"]:
        group["local_file_cleanup"] = (
            cleanup if group["number"] in SAFE_NUMBERS else
            {"status": "retained", "reason": "A current Ozon binding is declined."}
        )
    manifest["local_file_cleanup"] = cleanup
    save(MANIFEST, manifest)

    for group in audit["groups"]:
        if group["number"] in SAFE_NUMBERS:
            group["local_pdf_deleted_after_marketplace_confirmation"] = True
            group["local_pdf_deleted_at"] = receipt["completed_at"]
            group["local_pdf_deleted_paths"] = next(row["duplicate_paths"] for row in rows
                                                     if row["number"] == group["number"])
        elif group["number"] == "ЕАЭС N RU Д-CN.РА07.В.34398/26":
            group["local_pdf_retained_reason"] = "Ozon currently shows one declined product binding."
    save(CURRENT_AUDIT, audit)

    lines = [
        "# Certificate reconciliation — 2026-10-20", "",
        f"Fresh Ozon API readback at {report['checked_at']}. Full catalog snapshot at {report['snapshot_basis']['complete_marketplace_snapshot_checked_at']}.", "",
        "## Ozon", "",
        f"- {report['ozon']['active_products']:,} active products; {report['ozon']['products_with_current_approved_document_after_updates']:,} have at least one current approved document and {report['ozon']['products_without_current_approved_document_after_updates']:,} do not.",
        f"- {report['ozon']['new_documents_uploaded_and_visible']} newly uploaded document records; target-link states: {report['ozon']['new_document_edge_status_counts_including_overlapping_docs']}. Five ambiguous sample-date bindings were unbound and verified absent.",
        f"- Current Ozon certificate records: {report['ozon']['current_certificate_status_counts']}; reported binding count: {report['ozon']['current_products_count_across_certificate_records']:,}.", "",
        "## Wildberries", "",
        f"- {report['wildberries']['complete_unique_cards']:,} cards; {report['wildberries']['cards_with_at_least_one_valid_document']:,} have a valid document, {report['wildberries']['cards_pending_only']} are pending only, {report['wildberries']['cards_rejected_only']} rejected only, and {report['wildberries']['cards_without_any_current_valid_document']:,} have no valid document.",
        f"- Live WB search found no matching cards for {report['wildberries'].get('fresh_article_recheck_target_offers', 0)} recently checked offer entries covering the confirmed documents. No WB writes were needed.", "",
        "## Local PDF cleanup", "",
        f"- Deleted {cleanup['files_deleted']} local PDF copies across {len(cleanup['documents'])} confirmed documents and reclaimed {cleanup['bytes_reclaimed']:,} bytes ({cleanup['bytes_reclaimed'] / (1024 * 1024):.1f} MiB). Each document had approved Ozon links and no matching WB article card.",
        "- One otherwise verified Ozon document with a declined binding remains local. Unresolved and declined document PDFs also remain available.",
        f"- Full cleanup evidence: `{MAIN_RECEIPT.name}` and `{SUPPLEMENT.name}`.", "",
        "## Ozon documents handled", "",
    ]
    for doc in report["ozon"]["new_docs"]:
        states = {}
        for row in doc["targets"]:
            if row["exact_binding_visible"]:
                states[row["product_status_code"]] = states.get(row["product_status_code"], 0) + 1
        lines.append(f"- `{doc['number']}` — Ozon ID {doc['certificate_id']}; record `{doc['status_code']}`; {doc['verified_expected_links']}/{doc['expected_targets']} target bindings visible; links {states}.")
    lines += [
        "", "The twelve DVO links for declaration 68171/26 remain declined because its PDF lists different DVO models. One PDU link is declined. Other uncertain candidates are retained for follow-up.",
        "", "Overall coverage remains incomplete. WB review stays pending wherever a matching card is found.", "",
    ]
    (HERE / "post_upload_reconciliation_20261020.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "documents_cleaned": len(rows),
                      "local_pdf_copies_deleted": sum(len(row["duplicate_paths"]) for row in rows),
                      "bytes_reclaimed_this_pass": receipt["bytes_reclaimed"],
                      "bytes_reclaimed_total": main_receipt["total_bytes_reclaimed"],
                      "retained_declined_document": "ЕАЭС N RU Д-CN.РА07.В.34398/26"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
