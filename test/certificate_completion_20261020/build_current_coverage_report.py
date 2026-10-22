"""Reconcile source assignment edges against complete live marketplace snapshots."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SNAPSHOT = HERE / "live_marketplaces_snapshot.json"
MANIFEST = ROOT / "test/certificate_api_pilot_20261012/all_source_certificates_verified_manifest_20261014.json"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
OUT_JSON = HERE / "current_coverage_report.json"
OUT_CSV = HERE / "verified_group_edges_current.csv"

TRANSLATE = str.maketrans({
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
    "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
    "Ё": "E", "Э": "E", "Д": "D", "П": "P",
})


def norm(value: object) -> str:
    text = str(value or "").strip().upper()
    text = re.sub(r"^(?:ЕАЭС|EAEU|EAEC|EAC)\s*", "", text)
    text = re.sub(r"^(?:N|№)\s*", "", text)
    return "".join(c for c in text.translate(TRANSLATE) if c.isalnum())


def brand_key(value: object) -> str:
    return "".join(str(value or "").casefold().split())


def first_code(values: list[str]) -> set[str]:
    out = set()
    for value in values:
        code = str(value or "").split(" - ", 1)[0].strip()
        if code:
            out.add(code)
    return out


def wb_codes(card: dict) -> set[str]:
    values = []
    for char in card.get("characteristics") or []:
        label = "".join(str(char.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in label and "тнвед" not in label:
            continue
        raw = char.get("value")
        values.extend(raw if isinstance(raw, list) else [raw])
    return first_code(values)


def wb_doc_state(card: dict, group: dict) -> str:
    expected_number = norm(group["number"])
    expected_type = {"certificate_of_conformity": 1, "declaration": 2}.get(group["type_code"])
    rows = [x for x in ((card.get("documents") or {}).get("items") or [])
            if norm(x.get("number")) == expected_number]
    if not rows:
        return "missing"
    exact = [x for x in rows if int(x.get("type") or 0) == expected_type and
             str(x.get("startDate") or "")[:10] == group["issue_date"][:10] and
             str(x.get("endDate") or "")[:10] == group["expire_date"][:10]]
    if not exact:
        return "type_or_date_conflict"
    verdicts = [x.get("verdict") or {} for x in exact]
    if any(v.get("verified") is True and v.get("status") == 1 and v.get("reason") == "valid"
           for v in verdicts):
        return "valid"
    if any(v.get("status") not in (None, 1) or v.get("reason") not in (None, "", "valid")
           for v in verdicts):
        return "review_rejected_or_invalid"
    return "pending_review_or_verdict_absent"


def main() -> None:
    snapshot = json.loads(SNAPSHOT.read_text())
    if not all(snapshot.get(k, {}).get("complete") is True for k in
               ("ozon_products", "ozon_certificates", "wb_catalog", "wb_trash")):
        raise RuntimeError("A complete current live snapshot is required")
    products = snapshot["ozon_products"]["products"]
    certificates = snapshot["ozon_certificates"]["certificates"]
    cards = snapshot["wb_catalog"]["cards"]
    products_by_offer = defaultdict(list)
    products_by_sku = {}
    for p in products:
        products_by_offer[str(p.get("offer_id") or "")].append(p)
        if p.get("sku"):
            products_by_sku[str(p["sku"])] = p
    cards_by_offer = defaultdict(list)
    for card in cards:
        cards_by_offer[str(card.get("vendorCode") or "")].append(card)
    certs_by_number = defaultdict(list)
    for cert in certificates:
        certs_by_number[norm(cert.get("certificate_number"))].append(cert)

    today = date.today().isoformat()
    active_approved_product_ids = set()
    for cert in certificates:
        if cert.get("status_code") != "approved":
            continue
        if str(cert.get("issue_date") or "")[:10] > today or str(cert.get("expire_date") or "")[:10] < today:
            continue
        for binding in cert.get("live_bindings") or []:
            product = products_by_sku.get(str(binding.get("sku") or ""))
            if (binding.get("product_status_code") == "approved" and product and
                    str(product.get("product_id")) == str(binding.get("product_id"))):
                active_approved_product_ids.add(str(product["product_id"]))
    wb_with_valid_doc = set()
    wb_pending_only = set()
    wb_rejected_only = set()
    for card in cards:
        items = (card.get("documents") or {}).get("items") or []
        valid = [d for d in items if (d.get("verdict") or {}).get("verified") is True and
                 (d.get("verdict") or {}).get("status") == 1 and
                 (d.get("verdict") or {}).get("reason") == "valid"]
        pending = [d for d in items if (d.get("verdict") or {}).get("status") in (None, 1) and
                   (d.get("verdict") or {}).get("reason") in (None, "", "valid") and
                   not ((d.get("verdict") or {}).get("verified") is True and
                        (d.get("verdict") or {}).get("status") == 1 and
                        (d.get("verdict") or {}).get("reason") == "valid")]
        rejected = [d for d in items if (d.get("verdict") or {}).get("status") not in (None, 1) or
                    (d.get("verdict") or {}).get("reason") not in (None, "", "valid")]
        if valid:
            wb_with_valid_doc.add(str(card.get("nmID")))
        elif pending:
            wb_pending_only.add(str(card.get("nmID")))
        elif rejected:
            wb_rejected_only.add(str(card.get("nmID")))

    assignment_rows = 0
    assignment_by_offer = defaultdict(set)
    confirmed_assignment_by_offer = defaultdict(set)
    applicability = Counter()
    source_brands = Counter()
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            assignment_rows += 1
            offer = str(row.get("Артикул продавца") or "").strip()
            if not offer:
                continue
            assignment_by_offer[offer].add((str(row.get("Тип документа") or "").strip(),
                                             norm(row.get("Номер/название документа"))))
            applicability[str(row.get("Применимость") or "") or "(пусто)"] += 1
            source_brands[str(row.get("Бренд подтвержденный") or "") or "(пусто)"] += 1
            if row.get("Применимость") in ("Подтверждено статусом покрытия", "Подтверждено источником"):
                confirmed_assignment_by_offer[offer].add((str(row.get("Тип документа") or "").strip(),
                                                          norm(row.get("Номер/название документа"))))

    brand_coverage = {}
    for offer, rows in assignment_by_offer.items():
        product_rows = products_by_offer.get(offer, [])
        card_rows = cards_by_offer.get(offer, [])
        brands = {str(p.get("brand_values", [""])[0] if p.get("brand_values") else "") for p in product_rows}
        brand = next(iter(brands), "Unknown")
        stats = brand_coverage.setdefault(brand, {"offers_with_assignments": 0,
            "offers_on_ozon": 0, "offers_missing_from_ozon": 0,
            "offers_on_wb": 0, "offers_missing_from_wb": 0})
        stats["offers_with_assignments"] += 1
        stats["offers_on_ozon"] += int(len(product_rows) == 1)
        stats["offers_missing_from_ozon"] += int(len(product_rows) != 1)
        stats["offers_on_wb"] += int(len(card_rows) == 1)
        stats["offers_missing_from_wb"] += int(len(card_rows) != 1)

    manifest = json.loads(MANIFEST.read_text())
    edge_rows = []
    outcomes = {"ozon": Counter(), "wb": Counter()}
    per_brand = defaultdict(lambda: {"targets": 0, "ozon_approved_links": 0,
        "ozon_pending_links": 0, "ozon_declined_links": 0, "ozon_missing_links": 0,
        "wb_valid": 0, "wb_pending": 0, "wb_rejected_or_conflict": 0, "wb_missing": 0,
        "wb_no_exact_card": 0})
    group_rows = []
    for group in manifest.get("groups") or []:
        number_key = norm(group["number"])
        matching = certs_by_number.get(number_key, [])
        exact = [c for c in matching if c.get("type_code") == group["type_code"] and
                 str(c.get("issue_date") or "")[:10] == group["issue_date"][:10] and
                 str(c.get("expire_date") or "")[:10] == group["expire_date"][:10]]
        for target in group.get("targets") or []:
            offer = str(target["offer_id"])
            brand = str(target.get("brand") or "Unknown")
            per_brand[brand]["targets"] += 1
            p_rows = products_by_offer.get(offer, [])
            c_rows = cards_by_offer.get(offer, [])
            p = p_rows[0] if len(p_rows) == 1 else None
            c = c_rows[0] if len(c_rows) == 1 else None

            ozon_state = "missing_product"
            if p:
                identity_ok = (str(p.get("product_id")) == str(target.get("product_id")) and
                               str(p.get("sku")) == str(target.get("sku")) and
                               p.get("is_archived") is False and
                               brand_key(next(iter(p.get("brand_values") or [""]))) == brand_key(brand))
                allowed = set(map(str, group.get("allowed_tnved") or []))
                actual = first_code(p.get("tnved_values") or [])
                tnved_ok = not allowed or (actual and actual <= allowed)
                if not identity_ok:
                    ozon_state = "product_identity_or_brand_changed"
                elif not tnved_ok:
                    ozon_state = "tnved_unconfirmed_or_out_of_scope"
                elif len(exact) != 1:
                    ozon_state = "missing_or_duplicate_exact_ozon_record"
                else:
                    cert = exact[0]
                    binding = next((b for b in (cert.get("live_bindings") or [])
                                    if str(b.get("product_id")) == str(target["product_id"])), None)
                    if binding and str(binding.get("sku")) != str(target["sku"]):
                        ozon_state = "binding_identity_conflict"
                    elif binding and binding.get("product_status_code") == "approved" and cert.get("status_code") == "approved":
                        ozon_state = "approved_link"
                    elif binding and binding.get("product_status_code") == "declined":
                        ozon_state = "declined_link"
                    elif binding:
                        ozon_state = "pending_link_or_document"
                    elif cert.get("status_code") != "approved":
                        ozon_state = "document_not_approved"
                    else:
                        ozon_state = "missing_binding"
            outcomes["ozon"][ozon_state] += 1

            wb_state = "no_exact_card" if c is None else "missing"
            if c:
                if brand_key(c.get("brand")) != brand_key(brand):
                    wb_state = "brand_mismatch"
                else:
                    allowed = set(map(str, group.get("allowed_tnved") or []))
                    actual = wb_codes(c)
                    if allowed and (not actual or not actual <= allowed):
                        wb_state = "tnved_unconfirmed_or_out_of_scope"
                    else:
                        wb_state = wb_doc_state(c, group)
            outcomes["wb"][wb_state] += 1
            if ozon_state == "approved_link": per_brand[brand]["ozon_approved_links"] += 1
            elif ozon_state == "pending_link_or_document" or ozon_state == "document_not_approved": per_brand[brand]["ozon_pending_links"] += 1
            elif ozon_state == "declined_link": per_brand[brand]["ozon_declined_links"] += 1
            elif ozon_state == "missing_binding": per_brand[brand]["ozon_missing_links"] += 1
            if wb_state == "valid": per_brand[brand]["wb_valid"] += 1
            elif wb_state == "pending_review_or_verdict_absent": per_brand[brand]["wb_pending"] += 1
            elif wb_state in ("review_rejected_or_invalid", "type_or_date_conflict"): per_brand[brand]["wb_rejected_or_conflict"] += 1
            elif wb_state == "missing": per_brand[brand]["wb_missing"] += 1
            elif wb_state == "no_exact_card": per_brand[brand]["wb_no_exact_card"] += 1
            edge_rows.append({"brand": brand, "number": group["number"], "type": group["type_code"],
                "offer_id": offer, "product_id": target["product_id"], "sku": target["sku"],
                "ozon_state": ozon_state, "wb_nmID": c.get("nmID") if c else "",
                "wb_state": wb_state})
        group_rows.append({"number": group["number"], "type": group["type_code"],
            "targets": len(group.get("targets") or []), "ozon_records_by_number": len(matching),
            "exact_ozon_records": len(exact), "source_evidence_verified": group.get("source_evidence_verified")})

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(edge_rows[0]) if edge_rows else [])
        writer.writeheader()
        writer.writerows(edge_rows)
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "marketplace_snapshot_checked_at": {k: snapshot[k].get("checked_at") for k in
            ("ozon_products", "ozon_certificates", "wb_catalog", "wb_trash")},
        "marketplace_snapshot_complete": True,
        "catalog": {"ozon_active_products": snapshot["ozon_products"].get("active_products"),
            "ozon_archived_products": snapshot["ozon_products"].get("archived_products"),
            "ozon_products_missing_sku": snapshot["ozon_products"].get("missing_sku"),
            "ozon_certificate_records": len(certificates),
            "ozon_certificate_statuses": snapshot["ozon_certificates"].get("status_counts"),
            "ozon_live_bindings": snapshot["ozon_certificates"].get("total_bindings"),
            "ozon_products_with_at_least_one_current_approved_document": len(active_approved_product_ids),
            "ozon_products_without_any_current_approved_document": len(products) - len(active_approved_product_ids),
            "wb_unique_cards": len(cards), "wb_trash_cards": len(snapshot["wb_trash"].get("cards") or []),
            "wb_cards_with_at_least_one_valid_document": len(wb_with_valid_doc),
            "wb_cards_with_pending_documents_but_no_valid_document": len(wb_pending_only),
            "wb_cards_with_rejected_documents_but_no_valid_document": len(wb_rejected_only)},
        "source_assignments": {"rows": assignment_rows,
            "unique_offers": len(assignment_by_offer),
            "unique_offer_document_edges": sum(len(x) for x in assignment_by_offer.values()),
            "unique_confirmed_offer_document_edges": sum(len(x) for x in confirmed_assignment_by_offer.values()),
            "offers_with_at_least_one_confirmed_source_row": len(confirmed_assignment_by_offer),
            "applicability_rows": dict(applicability), "source_brands_rows": dict(source_brands),
            "offers_on_both": sum(1 for o in assignment_by_offer if len(products_by_offer.get(o, [])) == 1 and len(cards_by_offer.get(o, [])) == 1),
            "offers_missing_from_ozon": sum(1 for o in assignment_by_offer if len(products_by_offer.get(o, [])) != 1),
            "offers_missing_from_wb": sum(1 for o in assignment_by_offer if len(cards_by_offer.get(o, [])) != 1),
            "brand_coverage": brand_coverage},
        "verified_manifest": {"groups": len(manifest.get("groups") or []),
            "target_edges": len(edge_rows), "ozon_edge_states": dict(outcomes["ozon"]),
            "wb_edge_states": dict(outcomes["wb"]), "brands": dict(per_brand),
            "groups": group_rows},
        "post_snapshot_wb_update_confirmation": json.loads((HERE / "wb_delayed_readback_20261019.json").read_text())
            if (HERE / "wb_delayed_readback_20261019.json").exists() else None,
        "wb_review_status_recheck": json.loads((HERE / "wb_review_status_recheck_20261019.json").read_text())
            if (HERE / "wb_review_status_recheck_20261019.json").exists() else None,
        "files": {"edge_csv": str(OUT_CSV), "no_local_cleanup_performed": True},
    }
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"report": str(OUT_JSON), "edge_csv": str(OUT_CSV),
        "catalog": report["catalog"], "source_assignments": {
            k: report["source_assignments"][k] for k in
            ("rows", "unique_offers", "unique_offer_document_edges", "unique_confirmed_offer_document_edges",
             "offers_with_at_least_one_confirmed_source_row", "offers_on_both",
             "offers_missing_from_ozon", "offers_missing_from_wb")},
        "verified_manifest": {"group_count": len(report["verified_manifest"]["groups"]),
            "target_edges": report["verified_manifest"]["target_edges"],
            "ozon_edge_states": report["verified_manifest"]["ozon_edge_states"],
            "wb_edge_states": report["verified_manifest"]["wb_edge_states"]}},
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
