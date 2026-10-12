"""Reconcile live IEK/Generica XML documents for new Ozon offers.

Read-only. Exact Article-to-seller-code associations come from the current
official IEK feed. A package-suffix candidate remains visible in the output.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from group4_ozon import doc_identity

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
TODAY = date.today().isoformat()
OZON_TYPES = {"Сертификат 004": "certificate_of_conformity",
              "Сертификат 004, 020": "certificate_of_conformity",
              "Декларация 004": "declaration", "Декларация 004, 020": "declaration",
              "Декларация 025": "declaration", "Декларация 037": "declaration"}
TYPE_LABELS = {"certificate_of_conformity": "CERTIFICATE_OF_CONFORMITY", "declaration": "DECLARATION"}
PACK_SUFFIXES = ("-1", "-2", "-3", "-5", "-10", "-20", "-50")


def match_article(offer: str, article_rows: dict[str, list[dict]]) -> tuple[str | None, str]:
    if offer in article_rows:
        return offer, "exact seller article equals official Article"
    matches = []
    for suffix in PACK_SUFFIXES:
        if offer.endswith(suffix) and offer[:-len(suffix)] in article_rows:
            matches.append((offer[:-len(suffix)], f"candidate pack suffix {suffix}"))
            break
    if len(matches) == 1:
        return matches[0]
    return None, "no unique official Article candidate"


def source_docs_for(article_record: dict) -> list[dict]:
    result = []
    for doc in article_record.get("documents") or []:
        type_code = OZON_TYPES.get(doc.get("type", ""))
        issue, expiry = str(doc.get("start_date") or ""), str(doc.get("end_date") or "")
        number = str(doc.get("number") or "").strip()
        if not type_code or len(issue) < 10 or len(expiry) < 10 or not number:
            continue
        if issue[:10] > TODAY or expiry[:10] < TODAY:
            continue
        result.append({**doc, "type_code": type_code, "ozon_create_type": TYPE_LABELS[type_code]})
    return result


def main() -> None:
    new_doc = json.loads((BASE / "ozon_new_offers_attributes.json").read_text())
    xml_doc = json.loads((BASE / "iek_live_new_offers_docs.json").read_text())
    ozon_doc = json.loads((BASE / "ozon_live.json").read_text())
    if not (new_doc.get("complete") and xml_doc.get("complete") and ozon_doc.get("complete")):
        raise RuntimeError("Complete live Ozon/new-offer and official IEK XML audits required")

    records_by_article: dict[str, list[dict]] = defaultdict(list)
    for group in xml_doc.get("matched_articles") or []:
        for row in group:
            records_by_article[row["article"]].append(row)

    product_by_offer = {str(x["offer_id"]): x for x in new_doc.get("products") or []}
    ozon_by_identity: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for cert in ozon_doc.get("certificates") or []:
        identity = doc_identity(cert.get("certificate_number") or "")
        ozon_by_identity[(cert.get("type_code", ""), identity)].append(cert)

    csv_path = ROOT / "output_to_user/certificates/document_catalog_master.csv"
    catalog_files = defaultdict(list)
    if csv_path.is_file():
        with csv_path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                for number in (row.get("Номера/названия документов") or "").split("; "):
                    if number.strip():
                        catalog_files[doc_identity(number)].append(row)

    assignments = []
    products = []
    for product in new_doc.get("products") or []:
        if product.get("brand") not in {"IEK", "Generica"}:
            continue
        offer = str(product.get("offer_id") or "")
        article, match_basis = match_article(offer, records_by_article)
        rows = records_by_article.get(article, []) if article else []
        product_entry = {"offer_id": offer, "product_id": product.get("product_id"), "sku": product.get("sku"),
                         "brand": product.get("brand"), "model": product.get("model"), "name": product.get("name"),
                         "official_article": article, "article_match_basis": match_basis,
                         "official_records_count": len(rows), "document_actions": []}
        if len(rows) != 1:
            product_entry["status"] = "unmatched_or_ambiguous_official_article"
            products.append(product_entry)
            continue
        source_record = rows[0]
        product_entry["official_name"] = source_record.get("official_name")
        product_entry["official_category"] = source_record.get("category")
        product_entry["official_subgroup"] = source_record.get("subgroup")
        docs = source_docs_for(source_record)
        if not docs:
            product_entry["status"] = "no_active_mandatory_eaeu_document_in_official_feed"
            products.append(product_entry)
            continue

        for source in docs:
            identity = doc_identity(source["number"])
            matches = ozon_by_identity.get((source["type_code"], identity), [])
            wrong_identity_records = [x for (type_code, number_id), records in ozon_by_identity.items()
                                      if number_id == identity and type_code != source["type_code"] for x in records]
            chosen = None
            outcome = "new_upload_requires_pdf_validation"
            proof = None
            if wrong_identity_records and not matches:
                outcome = "blocked_existing_number_with_different_ozon_type"
            elif matches:
                date_matches = [x for x in matches
                                if str(x.get("issue_date") or "")[:10] == source["start_date"][:10]
                                and str(x.get("expire_date") or "")[:10] == source["end_date"][:10]
                                and x.get("accordance_type_code") == "EAEU"]
                if not date_matches:
                    outcome = "blocked_existing_ozon_metadata_conflict"
                else:
                    approved_records = [x for x in date_matches if x.get("status_code") == "approved"]
                    if not approved_records:
                        outcome = "blocked_existing_ozon_document_not_approved"
                    else:
                        pairs_by_record = {
                            str(c.get("certificate_id")): [b for b in c.get("live_bindings") or []
                                if str(b.get("product_id")) == str(product.get("product_id"))
                                and str(b.get("sku")) == str(product.get("sku"))]
                            for c in approved_records
                        }
                        bound_records = [c for c in approved_records if any(
                            b.get("product_status_code") == "approved"
                            for b in pairs_by_record[str(c.get("certificate_id"))])]
                        pending_records = [c for c in approved_records if pairs_by_record[
                            str(c.get("certificate_id"))] and c not in bound_records]
                        if bound_records:
                            chosen = max(bound_records, key=lambda c: c.get("live_binding_count", 0))
                            outcome = "already_approved_and_bound"
                        elif pending_records:
                            chosen = pending_records[0]
                            outcome = "blocked_existing_product_pair_not_approved"
                        else:
                            # Duplicate Ozon records with identical number, type, dates and EAEU basis
                            # are reused; choose the already-approved record with broadest live scope.
                            chosen = max(approved_records,
                                         key=lambda c: (c.get("live_binding_count", 0), -int(c.get("certificate_id", 0))))
                            outcome = "bind_existing_approved_record"
                        proof = {"certificate_id": chosen.get("certificate_id"),
                                 "certificate_status": chosen.get("status_code"),
                                 "equivalent_record_ids": [x.get("certificate_id") for x in date_matches],
                                 "product_pair": pairs_by_record[str(chosen.get("certificate_id"))]}

            existing_local = []
            source_url = source.get("url") or ""
            for row in catalog_files.get(identity, []):
                local_paths = [x for x in (row.get("Файл/файлы проекта") or "").split("; ") if x]
                source_urls = [x for x in (row.get("URL источников") or "").split("; ") if x]
                if source_url in source_urls:
                    existing_local.append({"paths": local_paths, "sha256": row.get("SHA256"),
                                           "size_bytes": row.get("Размер байт"), "source_url_match": True})
            assignment = {
                "offer_id": offer, "product_id": product.get("product_id"), "sku": product.get("sku"),
                "brand": product.get("brand"), "model": product.get("model"),
                "official_article": article, "article_match_basis": match_basis,
                "official_name": source_record.get("official_name"),
                "document_type": source["type"], "ozon_type_code": source["type_code"],
                "number": source["number"], "issue_date": source["start_date"], "expire_date": source["end_date"],
                "source_url": source_url, "source_issuer": source.get("issuer"),
                "ozon_outcome": outcome, "ozon_record_proof": proof,
                "existing_local_files": existing_local,
            }
            assignments.append(assignment)
            product_entry["document_actions"].append({"number": assignment["number"], "type": assignment["document_type"],
                                                       "outcome": outcome})
        product_entry["status"] = "has_active_official_eaeu_documents"
        products.append(product_entry)

    actions = Counter(x["ozon_outcome"] for x in assignments)
    unique_docs = {}
    for row in assignments:
        key = (row["ozon_type_code"], doc_identity(row["number"]))
        unique_docs.setdefault(key, {"type_code": row["ozon_type_code"], "type": row["document_type"],
                                     "number": row["number"], "issue_date": row["issue_date"],
                                     "expire_date": row["expire_date"], "source_url": row["source_url"],
                                     "offers": [], "local_files": row["existing_local_files"],
                                     "upload_statuses": set()})
        entry = unique_docs[key]
        if (entry["issue_date"][:10], entry["expire_date"][:10]) != (row["issue_date"][:10], row["expire_date"][:10]):
            raise RuntimeError(f"Conflicting current IEK feed dates for {row['number']}")
        entry["offers"].append({"offer_id": row["offer_id"], "product_id": row["product_id"], "sku": row["sku"],
                                "action": row["ozon_outcome"]})
        entry["upload_statuses"].add(row["ozon_outcome"])
    for entry in unique_docs.values():
        entry["upload_statuses"] = sorted(entry["upload_statuses"])

    plan = {
        "created_at": datetime.now(timezone.utc).isoformat(), "as_of": TODAY,
        "ozon_catalog_checked_at": new_doc.get("ozon_products_checked_at"),
        "ozon_certificate_audit_checked_at": ozon_doc.get("checked_at"),
        "official_iek_feed_checked_at": xml_doc.get("checked_at"),
        "official_iek_feed_last_modified": xml_doc.get("source_last_modified"),
        "official_iek_feed_sha256": xml_doc.get("source_sha256"),
        "summary": {"selected_products": len(products), "matched_products": sum(x["status"] == "has_active_official_eaeu_documents" for x in products),
                    "assignments": len(assignments), "unique_active_conformity_docs": len(unique_docs),
                    "action_counts": dict(actions), "unmatched_or_ambiguous": sum(x["status"] == "unmatched_or_ambiguous_official_article" for x in products),
                    "no_active_eaeu_doc_in_feed": sum(x["status"] == "no_active_mandatory_eaeu_document_in_official_feed" for x in products)},
        "products": products, "document_assignments": assignments,
        "unique_documents": list(unique_docs.values()),
    }
    out = BASE / "iek_new_offer_document_plan.json"
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    out_csv = BASE / "iek_new_offer_document_assignments.csv"
    fields = ["offer_id", "product_id", "sku", "brand", "model", "official_article", "article_match_basis",
              "official_name", "document_type", "ozon_type_code", "number", "issue_date", "expire_date",
              "source_url", "source_issuer",
              "ozon_outcome", "ozon_record_proof", "existing_local_files"]
    with out_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in assignments:
            writer.writerow({**row, "ozon_record_proof": json.dumps(row["ozon_record_proof"], ensure_ascii=False),
                             "existing_local_files": json.dumps(row["existing_local_files"], ensure_ascii=False)})
    print(json.dumps({"summary": plan["summary"], "file": str(out), "csv": str(out_csv)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
