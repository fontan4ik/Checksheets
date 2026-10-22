"""Fresh read-only marketplace reconciliation for FERON EL docs 05934/22 and 53534/22."""
from __future__ import annotations

import collections
import datetime as dt
import json
import sys
from pathlib import Path

from api_client import Client, digest, now
import build_feron_54301_ozon_plan as workbook_reader
from audit_feron_01315_53551 import FERON, norm
from execute_feron_04998_ozon import read_bindings

BASE = Path(__file__).resolve().parent
DOCS = {
    "05934/22": {
        "number": "ЕАЭС RU С-CN.ПФ02.В.05934/22",
        "type_code": "certificate_of_conformity",
        "wb_type": 1,
        "issue_date": "2022-09-20",
        "expire_date": "2027-09-19",
        "registry_url": "https://pub.fsa.gov.ru/rss/certificate/view/3143959/product",
        "registry_record": "3143959",
    },
    "53534/22": {
        "number": "ЕАЭС N RU Д-CN.РА06.В.53534/22",
        "type_code": "declaration",
        "wb_type": 2,
        "issue_date": "2022-09-15",
        "expire_date": "2027-09-14",
        "registry_url": "https://pub.fsa.gov.ru/rds/declaration/view/17025605/product",
        "registry_record": "17025605",
    },
}


def list_certificates(client: Client) -> list[dict]:
    out: list[dict] = []
    page = 1
    seen: set[str] = set()
    while page <= 100:
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})["result"]
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Invalid Ozon certificate list response")
        ids = [str(x.get("certificate_id")) for x in batch]
        if seen.intersection(ids):
            raise RuntimeError("Duplicate Ozon certificate ID during pagination")
        seen.update(ids)
        out.extend(batch)
        if len(batch) < 100:
            return out
        page += 1
    raise RuntimeError("Ozon certificate list pagination limit exceeded")


def read_targets(suffix: str) -> list[dict[str, str]]:
    workbook_reader.WORKBOOK_NUMBER_SUFFIX = suffix
    return workbook_reader.read_target_rows()


def main() -> None:
    report: dict = {"started_at": now(), "documents": {}, "source_workbook": str(workbook_reader.WORKBOOK)}
    target_rows = {suffix: read_targets(suffix) for suffix in DOCS}
    identity_source = target_rows["05934/22"]
    if len(identity_source) != 19 or len({x["offer_id"] for x in identity_source}) != 19:
        raise RuntimeError("Expected 19 unique workbook offers for 05934/22")
    if {(x["offer_id"], x["workbook_product_id"], x["workbook_sku"]) for x in identity_source} != {
        (x["offer_id"], x["workbook_product_id"], x["workbook_sku"]) for x in target_rows["53534/22"]
    }:
        raise RuntimeError("The two EL documents do not map to the same exact workbook product set")

    sources = {
        "05934/22": next((FERON / x["file_in_offer"] for x in target_rows["05934/22"]), None),
        "53534/22": next((FERON / x["file_in_offer"] for x in target_rows["53534/22"]), None),
    }
    expected_source_sha = {
        "05934/22": "c6cdca181bc7d33d07a148f522887766ead0e3b94d33845af5aebbcb19742a20",
        "53534/22": "841590a6a3fb06201c8954003e1f4301a51fa94fdfab025f7c2bff2592f11c16",
    }
    original_paths = {
        "05934/22": Path("/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron/00_Оригиналы_файлов/Сертификат__05934_Светильники_переносные_аккумуляторные_светодиодные,_тм_Feron,_серия_EL._Сертификат_по_004_и_020_1__c6cdca181b.pdf"),
        "53534/22": Path("/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron/00_Оригиналы_файлов/Декларация__53534_22_Светильники_переносные_аккумуляторные_светодиодные,_тм_Feron,_серия_EL._Декларация_по_037_1__841590a6a3.jpg"),
    }

    client = Client()
    records = list_certificates(client)
    offer_ids = sorted({x["offer_id"] for x in identity_source})
    live: dict[str, dict] = {}
    for offset in range(0, len(offer_ids), 100):
        body = client.call("ozon", "/v3/product/info/list", {"offer_id": offer_ids[offset:offset + 100]})
        items = body.get("items") or body.get("result", {}).get("items")
        if not isinstance(items, list):
            raise RuntimeError("Invalid Ozon product info response")
        for item in items:
            offer = str(item.get("offer_id", ""))
            if not offer or offer in live:
                raise RuntimeError("Duplicate or empty live Ozon offer identity")
            live[offer] = {"product_id": str(item.get("id", "")), "sku": str(item.get("sku", "")),
                           "is_archived": bool(item.get("is_archived"))}

    identity_mismatches = {}
    for row in identity_source:
        current = live.get(row["offer_id"])
        if not current or current["product_id"] != row["workbook_product_id"] or current["sku"] != row["workbook_sku"]:
            identity_mismatches[row["offer_id"]] = {"workbook": row, "live": current}

    wb_live_by_offer: dict[str, list[dict]] = {}
    for offer in offer_ids:
        wb_live_by_offer[offer] = client.wb_cards(offer)

    for suffix, config in DOCS.items():
        rows = target_rows[suffix]
        original = original_paths[suffix]
        if not original.is_file() or digest(original) != expected_source_sha[suffix]:
            raise RuntimeError("Official original hash mismatch for " + suffix)
        copies = []
        for row in rows:
            copy = FERON / row["file_in_offer"]
            copies.append({"path": str(copy), "exists": copy.is_file(),
                           "sha256": digest(copy) if copy.is_file() else None,
                           "matches_original": copy.is_file() and digest(copy) == expected_source_sha[suffix]})
        key = norm(config["number"])
        tail = norm(suffix)
        matches = [x for x in records if norm(x.get("certificate_number")) == key or
                   (norm(x.get("certificate_number", "")).endswith(tail) and x.get("type_code") == config["type_code"])]
        unique = {str(x.get("certificate_id")): x for x in matches}
        binding_reports = []
        for item in unique.values():
            record_id = int(item["certificate_id"])
            info_result = client.call("ozon", "/v1/product/certificate/info",
                                      {"certificate_number": str(item.get("certificate_number", ""))}).get("result")
            bindings = read_bindings(client, record_id)
            by_sku: dict[str, list[dict]] = collections.defaultdict(list)
            for binding in bindings:
                by_sku[str(binding.get("sku", ""))].append(binding)
            target_skus = {str(x["workbook_sku"]): str(x["workbook_product_id"]) for x in rows}
            binding_reports.append({
                "certificate_id": record_id, "stored_number": item.get("certificate_number"),
                "type_code": item.get("type_code"), "status_code": item.get("status_code"),
                "info": info_result, "binding_count": len(bindings),
                "target_count": len(target_skus),
                "missing_target_skus": sorted(set(target_skus) - set(by_sku)),
                "outside_skus": sorted(set(by_sku) - set(target_skus)),
                "duplicate_skus": sorted(sku for sku, group in by_sku.items() if len(group) != 1),
                "product_id_mismatches": sorted(sku for sku, group in by_sku.items()
                                                 if sku in target_skus and str(group[0].get("product_id")) != target_skus[sku]),
                "binding_statuses": dict(collections.Counter(str(x.get("status")) for x in bindings)),
            })

        wb_rows = []
        for row in rows:
            cards = wb_live_by_offer[row["offer_id"]]
            card = cards[0] if len(cards) == 1 else None
            docs = ((card.get("documents") or {}).get("items") or []) if card else []
            matching_docs = [d for d in docs if norm(d.get("number")) == key or
                             (norm(d.get("number", "")).endswith(tail) and int(d.get("type") or 0) == config["wb_type"])]
            accepted = [d for d in matching_docs if int(d.get("type") or 0) == config["wb_type"] and
                        str(d.get("startDate", ""))[:10] == config["issue_date"] and
                        str(d.get("endDate", ""))[:10] == config["expire_date"] and
                        (d.get("verdict") or {}).get("verified") is True and
                        (d.get("verdict") or {}).get("status") == 1]
            wb_rows.append({
                "offer_id": row["offer_id"], "nmID": str(card.get("nmID")) if card else None,
                "card_count": len(cards), "matching_document_count": len(matching_docs),
                "accepted_document_count": len(accepted),
                "documents": [{k: d.get(k) for k in ("id", "type", "number", "startDate", "endDate", "verdict")} for d in matching_docs],
            })

        report["documents"][suffix] = {
            "registry_evidence": {"url": config["registry_url"], "record_id": config["registry_record"],
                                  "status": "Действует", "registration_date": config["issue_date"],
                                  "valid_until": config["expire_date"],
                                  "product_scope": "Светильники переносные аккумуляторные светодиодные Feron серии EL"},
            "canonical_number": config["number"], "type_code": config["type_code"],
            "source": {"path": str(original), "sha256": digest(original), "size": original.stat().st_size},
            "upload_file": ({"path": str(original.resolve()), "sha256": digest(original),
                             "size": original.stat().st_size}
                            if suffix == "05934/22"
                            else ({"path": str((BASE / "feron_53534_upload_files/decl_53534_22.pdf").resolve()),
                                   "sha256": digest(BASE / "feron_53534_upload_files/decl_53534_22.pdf"),
                                   "size": (BASE / "feron_53534_upload_files/decl_53534_22.pdf").stat().st_size}
                                  if suffix == "53534/22" and (BASE / "feron_53534_upload_files/decl_53534_22.pdf").is_file()
                                  else None)),
            "local_offer_copy_count": len(copies),
            "local_offer_copies_verified": sum(x["matches_original"] for x in copies),
            "local_offer_copies": copies,
            "workbook_manual_flag_count": sum(r["manual_flag"].strip().lower() == "да" for r in rows),
            "workbook_review_context": [{"offer_id": r["offer_id"], "state": r["registry_state"],
                                         "status": r["official_status"], "applicability": r["applicability"]} for r in rows[:3]],
            "ozon": {"certificate_list_count": len(records), "matching_records": list(unique.values()),
                     "record_count": len(unique), "binding_reports": binding_reports},
            "wb": {"live_checked_offers": len(wb_rows),
                   "cards_found": sum(x["card_count"] == 1 for x in wb_rows),
                   "cards_missing": sum(x["card_count"] == 0 for x in wb_rows),
                   "cards_ambiguous": sum(x["card_count"] > 1 for x in wb_rows),
                   "accepted_exact_documents": sum(x["accepted_document_count"] == 1 for x in wb_rows),
                   "rows": wb_rows},
        }

    report["ozon_product_identity"] = {
        "target_offer_count": len(identity_source), "live_offer_count": len(live),
        "mismatches": identity_mismatches,
        "archived_targets": sorted(offer for offer, item in live.items() if item["is_archived"]),
        "identities": [{"offer_id": row["offer_id"], "workbook_product_id": row["workbook_product_id"],
                        "workbook_sku": row["workbook_sku"], "live": live.get(row["offer_id"])} for row in identity_source],
    }
    report["completed_at"] = now()
    out = BASE / "feron_05934_53534_live_reconciliation.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"report": str(out), "ozon_product_identity": report["ozon_product_identity"],
               "documents": {suffix: {"record_count": d["ozon"]["record_count"],
                                      "wb_cards_found": d["wb"]["cards_found"],
                                      "wb_cards_missing": d["wb"]["cards_missing"],
                                      "wb_accepted": d["wb"]["accepted_exact_documents"],
                                      "source_copies_verified": d["local_offer_copies_verified"]}
                             for suffix, d in report["documents"].items()}}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
