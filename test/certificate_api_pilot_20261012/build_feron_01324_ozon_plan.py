"""Build a guarded Ozon plan for FSA-verified Feron certificate 01324/22."""
from __future__ import annotations

import json
import re
from pathlib import Path

from api_client import digest, now
from audit_feron_01315_53551 import FERON
import build_feron_54301_ozon_plan as workbook_reader

BASE = Path(__file__).resolve().parent
OUT = BASE / "feron_01324_ozon_plan.json"
PRECHECK = BASE / "feron_01324_live_preflight.json"
SUFFIX = "01324/22"
NUMBER = "ЕАЭС RU С-CN.НВ85.В.01324/22"
REGISTRY_URL = "https://pub.fsa.gov.ru/rss/certificate/view/3130797/product"
SOURCE = FERON / "00_Оригиналы_файлов" / (
    "Сертификат__01324_Трансформаторы_(драйверы)_для_светодиодной_продукции,_тм_Feron,_"
    "серия_LB._Сертификат_по_004_и_020_1__11e4a243ee.pdf"
)


def main() -> None:
    precheck = json.loads(PRECHECK.read_text(encoding="utf-8"))
    if precheck.get("registry", {}).get("status") != "Действует":
        raise RuntimeError("FSA registry status is not active")
    if precheck.get("registry", {}).get("number") != NUMBER:
        raise RuntimeError("FSA certificate number does not match the plan")
    if precheck.get("ozon", {}).get("identity_mismatches"):
        raise RuntimeError("Live Ozon product identities differ from the workbook")
    if precheck.get("ozon", {}).get("exact_matches") or precheck.get("ozon", {}).get("same_suffix_records"):
        raise RuntimeError("Matching Ozon certificate appeared; reconcile instead of creating")
    if precheck.get("local_offer_copies_verified") != 103:
        raise RuntimeError("Not all 103 local offer copies match the original")

    workbook_reader.WORKBOOK_NUMBER_SUFFIX = SUFFIX
    rows = workbook_reader.read_target_rows()
    if len(rows) != 103 or len({r["offer_id"] for r in rows}) != 103:
        raise RuntimeError("Workbook target set is not 103 unique offers")
    if any(not re.search(r"трансформ|драйвер|\bLB\b", r["name"], re.I) for r in rows):
        raise RuntimeError("A workbook title does not identify an LB driver/transformer")
    if not SOURCE.is_file() or digest(SOURCE) != precheck["source"]["sha256"]:
        raise RuntimeError("Original certificate PDF changed or disappeared")

    identities = {x["offer_id"]: x for x in precheck["ozon"]["identities"]}
    if set(identities) != {x["offer_id"] for x in rows}:
        raise RuntimeError("Live Ozon offer set differs from workbook target set")
    archived = [o for o, x in identities.items() if x.get("is_archived")]
    if archived:
        raise RuntimeError("Archived target offers require separate reconciliation")
    targets = []
    copies = []
    for row in sorted(rows, key=lambda x: x["offer_id"]):
        live = identities[row["offer_id"]]
        if live["product_id"] != row["workbook_product_id"] or live["sku"] != row["workbook_sku"]:
            raise RuntimeError("Ozon product_id/SKU mapping changed for " + row["offer_id"])
        copy_path = FERON / row["file_in_offer"]
        if not copy_path.is_file() or digest(copy_path) != precheck["source"]["sha256"]:
            raise RuntimeError("Local source copy changed for " + row["offer_id"])
        copies.append({"offer_id": row["offer_id"], "path": str(copy_path),
                       "sha256": digest(copy_path)})
        targets.append({"offer_id": row["offer_id"], "product_id": live["product_id"],
                        "sku": live["sku"], "scope_level": "карточка Feron",
                        "basis": "Точная строка сопоставления в рабочей книге; название — драйвер/трансформатор серии LB.",
                        "manual": row["manual_flag"], "ozon_archived": False})
    if len({x["sku"] for x in targets}) != 103:
        raise RuntimeError("Ozon target SKU set is not one-to-one")

    seed = targets[0]
    report = {
        "planned_at": now(), "number": NUMBER, "workbook_number": "ЕАЭС RU C-CN.HB85.B.01324/22",
        "document_type": "certificate_of_conformity", "country": "RU", "accordance_type": "EAEU",
        "issue_date": "2022-08-17", "expire_date": "2027-08-16",
        "product_scope": "Электронные трансформаторы (драйверы) Feron серии LB; ТР ТС 004/2011 и 020/2011",
        "registry_url": REGISTRY_URL, "registry_evidence": precheck["registry"],
        "source_file": {"path": str(SOURCE), "sha256": digest(SOURCE), "size": SOURCE.stat().st_size},
        "source_workbook": str(workbook_reader.WORKBOOK), "target_count": len(targets),
        "archived_targets_included": 0, "local_offer_copies": copies,
        "ozon_preflight": {"certificate_list_count": precheck["ozon"]["certificate_list_count"],
                           "matching_records": precheck["ozon"]["exact_matches"],
                           "number_substring_matches": precheck["ozon"]["same_suffix_records"],
                           "product_count": precheck["ozon"]["product_count"],
                           "identity_mismatches": precheck["ozon"]["identity_mismatches"],
                           "archived_products": len(archived)},
        "wb_snapshot": {k: precheck["wb"].get(k) for k in
                        ("snapshot_checked_at", "target_cards_found", "target_cards_missing",
                         "duplicate_target_offers", "matching_document_rows", "matching_document_verdicts")},
        "targets": targets, "seed_offer": seed["offer_id"],
        "seed_product_id": seed["product_id"], "seed_sku": seed["sku"],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"plan": str(OUT), "targets": len(targets), "seed_offer": seed["offer_id"],
                      "seed_sku": seed["sku"], "source_sha256": report["source_file"]["sha256"],
                      "ozon_archived_targets": len(archived)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
