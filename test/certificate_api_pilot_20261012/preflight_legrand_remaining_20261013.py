"""Read-only exact Ozon/WB audit for four locally mapped Legrand certificates."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from api_client import Client, now, save  # noqa: E402

ROOT = BASE.parents[1]
SUMMARY = ROOT / "output_to_user/certificates/group_3/article_summary.csv"
MANIFEST = ROOT / "output_to_user/certificates/group_3/manifest.csv"
OUT = "legrand_remaining_preflight_20261013.json"
DOCS = {
    "EAC-FR.02.02306": {
        "number": "ЕАЭС KG 417/032.FR.02.02306", "old_number": "EAC KG 417/032.FR.02.02306",
        "certificate_id": "5458727", "issue": "2026-02-06", "expiry": "2031-02-05",
        "tnved": "8536201007", "model_codes": {"419399", "419400", "419401", "419402"},
        "file": "docs/legrand_RX3_AVDT_EAC-FR.02.02306.pdf",
    },
    "EAC-FR.02.030056": {
        "number": "ЕАЭС KG 417/032.FR.02.03056", "old_number": "EAC KG 417/032.FR.02.03056",
        "certificate_id": "5458733", "issue": "2026-03-19", "expiry": "2031-03-18",
        "tnved": "8536508008", "model_codes": {"721101", "721103", "721105", "721111", "721115"},
        "file": "docs/legrand_SUNO_EAC-FR.02.030056.pdf",
    },
    "EAC-FR.02.03134": {
        "number": "ЕАЭС KG 417/032.FR.02.03134", "old_number": "EAC KG 417/032.FR.02.03134",
        "certificate_id": "5458739", "issue": "2026-03-23", "expiry": "2031-03-22",
        "tnved": "8536699008", "model_codes": {"721120", "721123", "721124", "721125", "721129"},
        "file": "docs/legrand_SUNO_thermostat_EAC-FR.02.03134.pdf",
    },
    "EAC-FR.02.03511": {
        "number": "ЕАЭС KG 417/032.FR.02.03511", "old_number": "EAC KG 417/032.FR.02.03511",
        "certificate_id": "5458749", "issue": "2026-04-10", "expiry": "2031-04-09",
        "tnved": "9032102000", "model_codes": {"721137"},
        "file": "docs/legrand_thermostat_EAC-FR.02.03511.pdf",
    },
}
TNVED_CHAR_ID = 15000001


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    manifest = rows(MANIFEST)
    summary = rows(SUMMARY)
    manifest_hashes = {r.get("Локальный файл"): r.get("SHA256", "") for r in manifest}
    targets_by_doc: dict[str, list[dict[str, str]]] = {}
    for label, spec in DOCS.items():
        pdf = ROOT / "output_to_user/certificates/group_3" / spec["file"]
        if not pdf.is_file() or hashlib.sha256(pdf.read_bytes()).hexdigest() != manifest_hashes.get(spec["file"]):
            raise RuntimeError("Official local PDF or SHA changed: " + label)
        doc_rows = [r for r in summary if r.get("Бренд") == "Legrand"
                    and label in (r.get("Документ/номер") or "")]
        if not doc_rows:
            raise RuntimeError("No local target rows for " + label)
        if any(r.get("Локальный файл") and r.get("Локальный файл") != spec["file"] for r in manifest
               if r.get("Артикул продавца") in {x["Артикул продавца"] for x in doc_rows}):
            raise RuntimeError("Manifest file mapping conflicts for " + label)
        targets_by_doc[label] = doc_rows
    all_rows = [r for group in targets_by_doc.values() for r in group]
    offers = [r["Артикул продавца"] for r in all_rows]
    if len(offers) != len(set(offers)):
        raise RuntimeError("Duplicate offers across Legrand document groups")

    client = Client()
    product_response = client.call("ozon", "/v3/product/info/list", {"offer_id": offers})
    products = product_response.get("items") or product_response.get("result", {}).get("items")
    if not isinstance(products, list) or len(products) != len(offers):
        raise RuntimeError("Fresh Ozon product response incomplete")
    by_offer = {str(p.get("offer_id") or ""): p for p in products}
    if set(by_offer) != set(offers) or len(by_offer) != len(offers):
        raise RuntimeError("Ozon offers missing or duplicated")
    attr_response = client.call("ozon", "/v4/product/info/attributes",
                                {"filter": {"offer_id": offers}, "limit": 100})
    attr_rows = attr_response.get("result") or attr_response.get("items")
    if not isinstance(attr_rows, list) or {str(x.get("offer_id")) for x in attr_rows} != set(offers):
        raise RuntimeError("Fresh Ozon attributes incomplete")
    attrs = {str(x["offer_id"]): {str(a.get("id")): a for a in x.get("attributes") or []}
             for x in attr_rows}

    records = []
    for page in range(1, 20):
        data = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result", {})
        batch = data.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list malformed")
        records.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("Ozon certificate pagination limit exceeded")

    result = {"checked_at_utc": now(), "read_only": True,
              "official_scope_evidence": "OCR + visual review of signed Legrand certificate pages and product annexes",
              "documents": {}}
    for label, spec in DOCS.items():
        doc_rows = targets_by_doc[label]
        offers_for_doc = [r["Артикул продавца"] for r in doc_rows]
        matching_records = [c for c in records if str(c.get("certificate_id")) == spec["certificate_id"]]
        record = matching_records[0] if len(matching_records) == 1 else {}
        record_exact = (record.get("status_code") == "approved"
                        and record.get("type_code") == "certificate_of_conformity"
                        and str(record.get("certificate_number")) == spec["number"]
                        and str(record.get("issue_date", ""))[:10] == spec["issue"]
                        and str(record.get("expire_date", ""))[:10] == spec["expiry"])
        bindings = client.ozon_bindings(int(spec["certificate_id"])) if record else []
        by_sku: dict[str, list[dict]] = collections.defaultdict(list)
        for b in bindings:
            by_sku[str(b.get("sku") or "")].append(b)
        doc_result = {"number": spec["number"], "old_number": spec["old_number"],
                      "certificate_id": spec["certificate_id"], "record_unique": len(matching_records) == 1,
                      "record_exact_active": record_exact, "status": record.get("status_code"),
                      "issue_date": spec["issue"], "expire_date": spec["expiry"],
                      "expected_tnved": spec["tnved"], "exact_models_from_official_pdf": sorted(spec["model_codes"]),
                      "sample_date_condition_from_official_pdf": True, "binding_count": len(bindings),
                      "binding_status_counts": dict(collections.Counter(str(b.get("product_status_code") or "") for b in bindings)),
                      "targets": []}
        for row in doc_rows:
            offer = row["Артикул продавца"]
            product = by_offer[offer]
            pid, sku = str(row["Ozon Product ID"]), str(row["Ozon SKU"])
            ozon_identity_ok = (str(product.get("id") or product.get("product_id") or "") == pid
                                and str(product.get("sku") or "") == sku and not product.get("is_archived"))
            brand = [str(v.get("value") or "") for v in (attrs[offer].get("85") or {}).get("values") or []]
            tn = [str(v.get("value") or "") for v in (attrs[offer].get("22232") or {}).get("values") or []]
            codes = sorted({v.split(" - ", 1)[0].strip() for v in tn if v.strip()})
            ozon_brand_ok = brand == ["Legrand"]
            ozon_scope_code_ok = codes == [spec["tnved"]]
            # These Legrand seller offers carry the printed manufacturer model before the pack suffix.
            model = offer.rsplit("-", 1)[0]
            model_matches = [model] if model in spec["model_codes"] else []
            model_match_ok = bool(model_matches)
            exact = by_sku.get(sku, [])
            ozon_binding_ok = (len(exact) == 1 and str(exact[0].get("product_id")) == pid
                               and exact[0].get("product_status_code") == "approved")
            cards = client.wb_cards(offer)
            card = cards[0] if len(cards) == 1 else {}
            wb_identity_ok = (len(cards) == 1 and str(card.get("vendorCode") or "") == offer
                              and bool(str(card.get("nmID") or "")))
            wb_codes = sorted({str(v).strip().split(" ", 1)[0]
                               for ch in card.get("characteristics") or []
                               if int(ch.get("id") or -1) == TNVED_CHAR_ID
                               for v in ch.get("value") or [] if str(v).strip()})
            wb_brand_ok = card.get("brand") == "Legrand"
            wb_scope_code_ok = wb_codes == [spec["tnved"]]
            docs = card.get("documents") or card.get("docs") or {}
            items = docs.get("items") or []
            matching_docs = [d for d in items if int(d.get("type") or 0) == 1
                             and str(d.get("number") or "") in (spec["number"], spec["old_number"])]
            wb_doc = matching_docs[0] if len(matching_docs) == 1 else {}
            wb_dates_ok = (len(matching_docs) == 1
                           and str(wb_doc.get("startDate") or "")[:10] == spec["issue"]
                           and str(wb_doc.get("endDate") or "")[:10] == spec["expiry"])
            verdict = wb_doc.get("verdict") or {}
            state = ("valid" if (wb_doc.get("number") == spec["number"] and verdict.get("verified") is True
                                 and verdict.get("status") == 1 and verdict.get("reason") == "valid")
                     else "needs_correction" if wb_doc.get("number") == spec["old_number"] else
                     "missing_or_conflicting")
            issues = []
            if not record_exact: issues.append("ozon_certificate_record_not_exact_active")
            if not ozon_identity_ok: issues.append("ozon_identity_or_archive_mismatch")
            if not ozon_brand_ok: issues.append("ozon_brand_mismatch")
            if not ozon_scope_code_ok: issues.append("ozon_tnved_outside_official_scope")
            if not model_match_ok: issues.append("manufacturer_model_not_in_official_scope")
            if not ozon_binding_ok: issues.append("ozon_binding_not_approved_exact")
            if not wb_identity_ok: issues.append("wb_exact_card_missing_or_changed")
            if not wb_brand_ok: issues.append("wb_brand_mismatch")
            if not wb_scope_code_ok: issues.append("wb_tnved_outside_official_scope")
            if not wb_dates_ok: issues.append("wb_document_row_or_dates_conflict")
            if docs.get("excludeDocuments") is not False: issues.append("wb_documents_excluded_or_unspecified")
            if len(items) != 1: issues.append("unexpected_additional_or_missing_wb_document_rows")
            eligible = not issues and state == "needs_correction"
            doc_result["targets"].append({"offer": offer, "product_id": pid, "sku": sku,
                                          "nmID": str(card.get("nmID") or ""), "model_from_catalog": model,
                                          "official_model_match": model_matches,
                                          "ozon_identity_ok": ozon_identity_ok, "ozon_brand_values": brand,
                                          "ozon_tnved_codes": codes, "ozon_binding_ok": ozon_binding_ok,
                                          "ozon_binding_status": exact[0].get("product_status_code") if len(exact) == 1 else None,
                                          "wb_identity_ok": wb_identity_ok, "wb_brand": card.get("brand"),
                                          "wb_tnved_codes": wb_codes, "wb_document_state": state,
                                          "wb_document_number": wb_doc.get("number"),
                                          "wb_document_verdict": verdict, "wb_document_row_count": len(matching_docs),
                                          "wb_other_document_rows": len(items)-int(len(matching_docs) == 1),
                                          "excludeDocuments": docs.get("excludeDocuments"),
                                          "eligible_for_number_correction": eligible,
                                          "blockers": issues, "full_card": card})
        doc_result["summary"] = {
            "target_count": len(doc_result["targets"]), "ozon_approved_bindings": len(doc_result["targets"]),
            "wb_exact_cards": len(doc_result["targets"]),
            "wb_states": dict(collections.Counter(x["wb_document_state"] for x in doc_result["targets"])),
            "official_model_matches": sum(bool(x["official_model_match"]) for x in doc_result["targets"]),
            "correction_eligible_count": sum(x["eligible_for_number_correction"] for x in doc_result["targets"]),
            "blocker_counts": dict(collections.Counter(issue for x in doc_result["targets"] for issue in x["blockers"])),
            "all_preflight_safe": all(x["eligible_for_number_correction"] or x["wb_document_state"] == "valid"
                                       for x in doc_result["targets"]),
            "local_pdf_sha256": hashlib.sha256((ROOT / "output_to_user/certificates/group_3" / spec["file"]).read_bytes()).hexdigest(),
        }
        result["documents"][label] = doc_result
    result["summary"] = {"document_count": len(DOCS), "target_count": sum(len(v["targets"]) for v in result["documents"].values()),
                         "wb_states": {k: v["summary"]["wb_states"] for k, v in result["documents"].items()},
                         "correction_eligible_count": sum(v["summary"]["correction_eligible_count"] for v in result["documents"].values()),
                         "all_preflight_safe": all(v["summary"]["all_preflight_safe"] for v in result["documents"].values())}
    save(OUT, result)
    print(json.dumps({"checked_at_utc": result["checked_at_utc"], "summary": result["summary"],
                      "documents": {k: {"certificate_id": v["certificate_id"], "status": v["status"],
                                        "bindings": v["binding_count"], "binding_status_counts": v["binding_status_counts"],
                                        **v["summary"]} for k, v in result["documents"].items()}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
