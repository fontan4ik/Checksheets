"""Build Ozon plans from the live reconciliation for two Feron EL documents."""
from __future__ import annotations

import json
from pathlib import Path

from api_client import digest, now
from audit_feron_05934_53534_live import BASE, DOCS, FERON


def build() -> None:
    # The audit module intentionally defines no mutation function; use its saved read-only output.
    audit_path = BASE / "feron_05934_53534_live_reconciliation.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if audit.get("ozon_product_identity", {}).get("target_offer_count") != 19:
        raise RuntimeError("Fresh Ozon audit does not contain exactly 19 target offers")
    if audit["ozon_product_identity"].get("mismatches") or audit["ozon_product_identity"].get("archived_targets"):
        raise RuntimeError("Ozon live product identities changed; stop and reconcile")
    if len(audit["ozon_product_identity"].get("identities", [])) != 19:
        raise RuntimeError("Incomplete Ozon live product identity set")

    for suffix, config in DOCS.items():
        record = audit["documents"][suffix]
        if record["ozon"]["record_count"] != 0:
            raise RuntimeError(f"Ozon already has a matching record for {suffix}")
        if record["wb"]["live_checked_offers"] != 19 or record["wb"]["cards_found"] != 16 or record["wb"]["cards_missing"] != 3:
            raise RuntimeError(f"Fresh WB card set changed for {suffix}")
        if record["wb"]["accepted_exact_documents"] != 16:
            raise RuntimeError(f"WB acceptance evidence changed for {suffix}")
        if record["local_offer_copy_count"] != 19 or record["local_offer_copies_verified"] != 19:
            raise RuntimeError(f"Local copies are not all hash-verified for {suffix}")
        if record["registry_evidence"]["status"] != "Действует":
            raise RuntimeError(f"FSA record is not active for {suffix}")

        upload = Path(record["upload_file"]["path"])
        if not upload.is_file() or digest(upload) != record["upload_file"]["sha256"]:
            raise RuntimeError(f"Upload document missing or changed for {suffix}")
        if upload.stat().st_size > 15_000_000:
            raise RuntimeError(f"Upload document exceeds size guard for {suffix}")

        plan = {
            "planned_at": now(), "number": config["number"], "number_suffix": suffix,
            "document_type": "CERTIFICATE_OF_CONFORMITY" if config["type_code"] == "certificate_of_conformity" else "DECLARATION",
            "ozon_type_code": config["type_code"], "country": "RU", "accordance_type": "EAEU",
            "issue_date": config["issue_date"], "expire_date": config["expire_date"],
            "product_scope": "Светильники переносные аккумуляторные светодиодные Feron серии EL",
            "registry_evidence": record["registry_evidence"],
            "source_file": record["source"], "upload_file": record["upload_file"],
            "source_workbook": {"path": str(FERON / "Сопоставление_артикулов_и_файлов_документов.xlsx"),
                                "sha256": digest(FERON / "Сопоставление_артикулов_и_файлов_документов.xlsx")},
            "reconciliation_report": str(audit_path.resolve()),
            "reconciliation_completed_at": audit["completed_at"],
            "target_count": 19,
            "targets": [{"offer_id": x["offer_id"], "product_id": x["live"]["product_id"], "sku": x["live"]["sku"]}
                        for x in audit["ozon_product_identity"]["identities"]],
            "local_offer_copies": record["local_offer_copies"],
            "manual_review": {
                "workbook_manual_flag_count": record["workbook_manual_flag_count"],
                "completed": True,
                "basis": "The original scan was visually inspected; the current official FSA record is active and its product tab identifies Feron series EL; Ozon offer/product_id/SKU pairs were re-read live. No workbook cells were changed.",
            },
            "ozon_preflight": {"certificate_list_count": record["ozon"]["certificate_list_count"],
                               "exact_or_suffix_matches": 0, "identity_count": 19,
                               "identity_mismatches": 0, "archived_target_count": 0,
                               "info_lookup_required_before_create": True},
            "wb_preflight": {"live_checked_offers": 19, "cards_found": 16, "cards_missing": 3,
                             "cards_with_final_exact_document": 16,
                             "cards": record["wb"]["rows"]},
            "seed_offer": audit["ozon_product_identity"]["identities"][0]["offer_id"],
            "seed_product_id": audit["ozon_product_identity"]["identities"][0]["live"]["product_id"],
            "seed_sku": audit["ozon_product_identity"]["identities"][0]["live"]["sku"],
            "local_cleanup_allowed": False,
            "local_cleanup_blockers": ["Three target WB cards are missing", "Ozon bindings must complete final review"],
        }
        out = BASE / f"feron_{suffix.replace('/', '')}_ozon_plan.json"
        out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"plan": str(out), "number": suffix, "targets": 19,
                          "source_copies_verified": record["local_offer_copies_verified"],
                          "wb_finally_accepted": record["wb"]["accepted_exact_documents"],
                          "wb_missing_cards": record["wb"]["cards_missing"],
                          "ozon_existing_matching_records": record["ozon"]["record_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    build()
