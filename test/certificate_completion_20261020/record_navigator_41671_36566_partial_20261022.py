#!/usr/bin/env python3
"""Record confirmed partial Ozon/WB coverage without deleting the source PDFs."""
from __future__ import annotations
import hashlib, json, pathlib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ADDENDUM = HERE / "postwrite_coverage_addendum_20261022.json"
READBACK = HERE / "navigator_41671_36566_delayed_crossplatform_readback_20261022.json"
GROUP = "navigator_41671_36566_ndl_downlights"
DOCS = {
    "declaration": {
        "number": "ЕАЭС N RU Д-CN.РА02.В.41671/25",
        "file": ROOT / "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_declaration_14479_72103983d9a2.pdf",
        "sha256": "72103983d9a2239055b00c300d70bdd13388cba7db66b2d9b1f0c194abd83524",
    },
    "certificate": {
        "number": "ЕАЭС RU С-CN.АЯ46.В.36566/24",
        "file": ROOT / "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_eac_certificate_14479_6b3b315368be.pdf",
        "sha256": "6b3b315368be2b2bccf262657c65cc48297a10ca26d41acbe62e9c63bba851e7",
    },
}


def main() -> None:
    add = json.loads(ADDENDUM.read_text())
    readback = json.loads(READBACK.read_text())
    if readback.get("cross_platform_complete") is not False or readback.get("local_source_files_deleted") is not False:
        raise RuntimeError("unexpected_final_readback_state")
    if readback.get("ozon_all_11_bindings_per_document_approved") is not False:
        raise RuntimeError("readback_does_not_show_partial_status")
    if add.get("current_live_reconciliations", {}).get(GROUP):
        raise RuntimeError("partial_reconciliation_already_recorded")
    ozon = readback.get("documents") or {}
    declaration = ozon.get("declaration") or {}
    certificate = ozon.get("certificate") or {}
    if (declaration.get("record_status") != "approved" or declaration.get("exact_bindings") != 11
            or declaration.get("binding_status_counts") != {"approved": 11}
            or certificate.get("record_status") != "approved" or certificate.get("exact_bindings") != 11
            or certificate.get("binding_status_counts") != {"approved": 10, "declined": 1}
            or any(x.get("unexpected_bindings") != 0 for x in (declaration, certificate))):
        raise RuntimeError("live_ozon_readback_changed")
    wb = readback.get("wb") or {}
    if (wb.get("target_cards") != 11 or wb.get("cards_with_both_exact_documents") != 11
            or wb.get("failures") or wb.get("verdict_counts") != {"pending_or_unverified": 22}):
        raise RuntimeError("live_wb_readback_changed")
    retained = []
    for doc in DOCS.values():
        if not doc["file"].is_file():
            raise RuntimeError("source_file_missing_before_all_bindings_confirmed:" + doc["number"])
        digest = hashlib.sha256(doc["file"].read_bytes()).hexdigest()
        if digest != doc["sha256"]:
            raise RuntimeError("source_file_hash_changed:" + doc["number"])
        retained.append({"path": str(doc["file"].relative_to(ROOT)), "sha256": digest,
                         "document_number": doc["number"], "deleted": False})
    totals = add["post_snapshot_totals"]
    totals["ozon_certificate_records"] += 2
    totals["ozon_certificate_statuses"]["approved"] += 2
    totals["ozon_live_bindings"] += 22
    totals["ozon_products_with_at_least_one_current_approved_document"] += 11
    totals["ozon_products_without_any_current_approved_document"] -= 11
    if totals["ozon_products_without_any_current_approved_document"] < 0:
        raise RuntimeError("negative_uncovered_total")
    offers = ["14479-1", "14481-1", "14482-1", "94820-1", "94821-1", "94833-1",
              "94834-1", "94836-1", "94837-1", "94838-1", "94899-1"]
    for key, doc in DOCS.items():
        record = declaration if key == "declaration" else certificate
        add["post_snapshot_writes"].append({
            "brand": "Navigator", "source_group": GROUP, "document_number": doc["number"],
            "type": "declaration" if key == "declaration" else "certificate_of_conformity",
            "ozon_certificate_id": record["certificate_id"],
            "ozon_approved_bindings": 11 if key == "declaration" else 10,
            "ozon_declined_bindings": 0 if key == "declaration" else 1,
            "ozon_binding_status_counts": record["binding_status_counts"],
            "ozon_status": record["record_status"], "offers": offers,
            "wb_exact_metadata_cards": 11, "wb_valid_cards": 0, "wb_pending_review_cards": 11,
            "wb_all_exact_documents_visible": True, "wb_readback_complete": True,
            "fsa_tnved_codes": ["9405110013", "9405110033"],
            "marketplace_tnved_mismatch": {
                "FSA": ["9405110013", "9405110033"],
                "Ozon": {"9405190039": 6, "9405110013": 5},
                "WB": {"9405110039": 4, "9405190039": 6, "9405110033": 1},
                "WB_matches_FSA": False,
            },
        })
    artifacts = add.setdefault("verification_artifacts", {})
    artifacts[GROUP + "_preflight"] = str(HERE / "navigator_41671_36566_live_preflight_20261022_v6.json")
    artifacts[GROUP + "_execution"] = str(HERE / "navigator_41671_36566_execution_20261022.json")
    artifacts[GROUP + "_wb_delayed_readback"] = str(HERE / "navigator_41671_36566_wb_delayed_readback_20261022.json")
    artifacts[GROUP + "_crossplatform_readback"] = str(READBACK)
    add.setdefault("current_live_reconciliations", {})[GROUP] = {
        "target_products": 11, "ozon_documents": 2,
        "ozon_declaration_exact_bindings": 11, "ozon_declaration_approved": 11,
        "ozon_certificate_exact_bindings": 11, "ozon_certificate_approved": 10,
        "ozon_certificate_declined": 1, "ozon_record_statuses": {"approved": 2},
        "wb_exact_cards": 11, "wb_exact_document_bindings": 22,
        "wb_valid_document_bindings": 0, "wb_pending_or_unverified_document_bindings": 22,
        "wb_review_left_for_marketplace_review": True,
        "marketplace_tnved_mismatch": True,
        "net_new_ozon_products_covered": 11, "net_new_wb_cards_with_valid_document": 0,
        "local_source_files_deleted": False, "verification_artifact": str(READBACK),
    }
    add.setdefault("local_source_cleanup", {})[GROUP] = {
        "deleted_files": [], "retained_files": retained,
        "checked_at_utc": readback["checked_at_utc"],
        "basis": "The declaration is approved on all 11 Ozon offers, but certificate binding to 94820-1 is declined. Both documents are visible on 11 WB cards and remain pending marketplace review. Source PDFs are retained because the Ozon certificate binding is incomplete.",
    }
    add["checked_at_utc"] = readback["checked_at_utc"]
    temporary = ADDENDUM.with_suffix(ADDENDUM.suffix + ".tmp")
    temporary.write_text(json.dumps(add, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(ADDENDUM)
    print(json.dumps({"recorded_partial_group": GROUP,
                      "ozon_products_with_current_approved_document": 11,
                      "ozon_certificate_binding": {"approved": 10, "declined": 1},
                      "wb_cards_with_both_exact_documents_pending": 11,
                      "local_source_files_deleted": False,
                      "ozon_products_without_any_current_approved_document": totals["ozon_products_without_any_current_approved_document"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
