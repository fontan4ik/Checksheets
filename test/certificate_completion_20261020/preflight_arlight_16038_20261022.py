#!/usr/bin/env python3
"""Fresh read-only cross-platform preflight for Arlight declaration 16038/26."""
from __future__ import annotations
import collections, csv, datetime, hashlib, json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PILOT = ROOT / "test/certificate_api_pilot_20261012"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
SNAPSHOT = HERE / "live_marketplaces_snapshot_resume_20261022.json"
ADDENDUM = HERE / "postwrite_coverage_addendum_20261022.json"
SOURCE_REL = "output_to_user/certificates/group_1/documents/arlight/C9DD9733E0AC9143BC53B1630E0D873A.pdf"
SOURCE = ROOT / SOURCE_REL
SOURCE_SHA256 = "83df9e5cfe549317edcb64a4c5f706127ef174ee41be39ddfe7421bdf12ef25c"
NUMBER = "ЕАЭС N RU Д-CN.РА01.В.16038/26"
ISSUE, EXPIRE = "2026-01-19", "2031-01-18"
REGISTRY_ID = "21071412"
TNVED = {"9405110014"}
OUT = HERE / "arlight_16038_crossplatform_preflight_20261022.json"
sys.path.insert(0, str(PILOT))
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import copy_documents, norm_number


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tnved(values):
    if not isinstance(values, list):
        values = [values]
    return sorted({str(x).split(" - ", 1)[0].strip() for x in values if str(x).strip()})


def wb_tnved(card):
    values = []
    for item in card.get("characteristics") or []:
        label = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" in label or "тнвед" in label:
            raw = item.get("value")
            values.extend(raw if isinstance(raw, list) else [raw])
    return tnved(values)


def load_candidates():
    snapshot = json.loads(SNAPSHOT.read_text())
    products = snapshot["ozon_products"]["products"]
    by_offer = {str(x.get("offer_id")): x for x in products if x.get("offer_id")}
    by_sku = {str(x.get("sku")): x for x in products if x.get("sku")}
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    covered = set()
    for cert in snapshot["ozon_certificates"]["certificates"]:
        if (cert.get("status_code") != "approved"
                or str(cert.get("issue_date") or "")[:10] > today
                or str(cert.get("expire_date") or "")[:10] < today):
            continue
        for binding in cert.get("live_bindings") or []:
            product = by_sku.get(str(binding.get("sku") or ""))
            if (product and str(product.get("product_id")) == str(binding.get("product_id"))
                    and binding.get("product_status_code") == "approved"):
                covered.add(str(product.get("product_id")))
    assigned = {}
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if (row.get("Локальный файл") != SOURCE_REL
                    or row.get("Применимость") != "Подтверждено статусом покрытия"
                    or row.get("Бренд подтвержденный") != "Arlight"):
                continue
            offer = str(row.get("Артикул продавца") or "").strip()
            if not offer or offer in assigned:
                raise RuntimeError("missing_or_duplicate_assignment:" + offer)
            assigned[offer] = {
                "offer_id": offer,
                "article": offer[:-2] if offer.endswith("-1") else offer,
                "source_name": row.get("Название товара Ozon"),
                "source_evidence": row.get("Основание сопоставления"),
                "source_url": row.get("URL карточки/основания"),
            }
    baseline_missing = set()
    baseline_product = {}
    for offer, target in assigned.items():
        product = by_offer.get(offer)
        if product and product.get("is_archived") is False:
            baseline_product[offer] = product
            if str(product.get("product_id")) not in covered:
                baseline_missing.add(offer)

    # Exclude any target independently confirmed as approved in post-snapshot write readbacks.
    updated = set()
    addendum = json.loads(ADDENDUM.read_text())
    refs = set()
    for entry in addendum.get("post_snapshot_writes") or []:
        values = entry.get("verification_artifacts") or []
        if isinstance(values, dict):
            values = list(values.values())
        for value in values:
            if isinstance(value, str):
                ref = pathlib.Path(value)
                refs.add(ref if ref.is_absolute() else HERE / ref)
    for path in refs:
        if not path.is_file() or path.suffix != ".json":
            continue
        try:
            doc = json.loads(path.read_text())
        except Exception:
            continue
        rows = []
        ob = doc.get("ozon_bindings")
        if isinstance(ob, dict):
            rows.extend((x.get("offer_id"), x.get("exact") is True and x.get("status") == "approved")
                        for x in ob.get("bindings") or [])
        for key in ("ozon_rows", "rows"):
            for x in doc.get(key) or []:
                if not isinstance(x, dict) or not x.get("offer_id"):
                    continue
                exact = x.get("exact_binding_count") == 1 or x.get("identity_exact") is True or x.get("exact") is True
                status = x.get("binding_status") or x.get("product_status_code") or x.get("status")
                rows.append((x.get("offer_id"), exact and status == "approved"))
        updated.update(str(offer) for offer, ok in rows if offer and ok)
    candidates = sorted(baseline_missing - updated)
    if not candidates:
        raise RuntimeError("no_current_uncovered_candidates")
    return assigned, candidates, baseline_product, {
        "source_assignment_count": len(assigned),
        "baseline_uncovered_count": len(baseline_missing),
        "post_snapshot_approved_target_offers_excluded": len(baseline_missing & updated),
        "candidate_count": len(candidates),
        "baseline_snapshot_checked_at": snapshot["ozon_certificates"]["checked_at"],
        "post_snapshot_readback_files_checked": len(refs),
    }


def list_certificates(client):
    rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        rows.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("ozon_certificate_page_limit")


def main():
    if OUT.exists():
        raise RuntimeError("preflight_output_exists_inspect_before_retry:" + OUT.name)
    if not SOURCE.is_file() or sha(SOURCE) != SOURCE_SHA256:
        raise RuntimeError("source_missing_or_sha256_mismatch")
    assigned, offers, baseline_products, candidate_stats = load_candidates()
    client = Client()

    products, attrs = [], []
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        products.extend(client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or [])
        attrs.extend(client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)}).get("result") or [])
    pmap, amap = collections.defaultdict(list), collections.defaultdict(list)
    for x in products: pmap[str(x.get("offer_id") or "")].append(x)
    for x in attrs: amap[str(x.get("offer_id") or "")].append(x)

    records = [x for x in list_certificates(client)
               if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(records) > 1:
        raise RuntimeError("duplicate_ozon_records_for_document")
    record = records[0] if records else None
    record_exact = bool(record and record.get("type_code") == "declaration"
                         and str(record.get("issue_date") or "")[:10] == ISSUE
                         and str(record.get("expire_date") or "")[:10] == EXPIRE)
    bindings = client.ozon_bindings(int(record["certificate_id"])) if record else []
    by_product = collections.defaultdict(list)
    for b in bindings:
        by_product[str(b.get("product_id") or "")].append(b)

    ozon_targets, wb_targets = [], []
    ozon_counts, wb_counts = collections.Counter(), collections.Counter()
    for offer in offers:
        target = assigned[offer]
        conflicts = []
        if len(pmap[offer]) != 1 or len(amap[offer]) != 1:
            product, attr = {}, {}
            conflicts.append("ozon_product_or_attributes_not_unique")
        else:
            product, attr = pmap[offer][0], amap[offer][0]
        product_id = str(product.get("id") or product.get("product_id") or "")
        sku = str(product.get("sku") or "")
        attrs_by_id = {str(x.get("id")): x for x in attr.get("attributes") or []}
        brands = [str(v.get("value") or "").strip() for v in (attrs_by_id.get("85") or {}).get("values") or []]
        codes = [str(v.get("value") or "").strip() for v in (attrs_by_id.get("22232") or {}).get("values") or []]
        oz_tnved = tnved(codes)
        live_name = str(product.get("name") or "").strip()
        source_name = str(target.get("source_name") or "").strip()
        baseline = baseline_products.get(offer) or {}
        if not product_id or not sku: conflicts.append("ozon_identity_missing")
        if product.get("is_archived") is not False: conflicts.append("ozon_archived_or_unknown")
        if brands != ["Arlight"]: conflicts.append("ozon_brand_mismatch")
        if not oz_tnved or not set(oz_tnved).issubset(TNVED): conflicts.append("ozon_tnved_out_of_scope")
        if str(baseline.get("product_id") or "") != product_id: conflicts.append("ozon_product_id_changed_since_baseline")
        if live_name.casefold() != source_name.casefold():
            conflicts.append("ozon_name_not_exact_to_verified_assignment")
        if record and (not record_exact or record.get("status_code") not in {"approved", "under_review"}):
            conflicts.append("existing_ozon_record_metadata_or_status_conflict")
        prior = by_product.get(product_id, [])
        already_exact = False
        if prior:
            exact = [b for b in prior if str(b.get("sku") or "") == sku
                     and b.get("product_status_code") in {"approved", "under_review"}]
            if len(exact) == 1 and len(prior) == 1:
                already_exact = True
            else:
                conflicts.append("existing_ozon_binding_conflict")
        row = {**target, "product_id": product_id, "sku": sku, "live_name": live_name,
               "brand_values": brands, "tnved_codes": oz_tnved,
               "already_exact": already_exact, "eligible": not conflicts, "conflicts": conflicts}
        ozon_targets.append(row); ozon_counts.update(conflicts)

        cards = client.wb_cards(offer)
        wconflicts = []
        card = cards[0] if len(cards) == 1 else {}
        if len(cards) != 1: wconflicts.append("no_unique_exact_wb_card")
        vendor = str(card.get("vendorCode") or "")
        brand = str(card.get("brand") or "")
        nm_id = str(card.get("nmID") or "")
        wb_codes = wb_tnved(card)
        if vendor != offer: wconflicts.append("wb_vendor_code_mismatch")
        if brand.casefold() != "arlight": wconflicts.append("wb_brand_mismatch")
        if not nm_id: wconflicts.append("wb_nm_id_missing")
        if not wb_codes or not set(wb_codes).issubset(TNVED): wconflicts.append("wb_tnved_out_of_scope")
        same = [x for x in copy_documents(card) if norm_number(x.get("number")) == norm_number(NUMBER)] if card else []
        exact_docs = [x for x in same if int(x.get("type") or 0) == 2
                      and str(x.get("startDate") or "")[:10] == ISSUE
                      and str(x.get("endDate") or "")[:10] == EXPIRE]
        if same and len(exact_docs) != 1: wconflicts.append("wb_same_number_metadata_conflict")
        wb_targets.append({**target, "nmID": nm_id, "vendorCode": vendor, "brand": brand,
                           "title": card.get("title"), "tnved_codes": wb_codes,
                           "already_exact": len(exact_docs) == 1, "eligible": not wconflicts,
                           "conflicts": wconflicts, "full_card": card})
        wb_counts.update(wconflicts)

    result = {
        "checked_at_utc": now(), "read_only": True, "brand": "Arlight", "number": NUMBER,
        "fsa_registry_id": REGISTRY_ID, "fsa_status": "active",
        "issue_date": ISSUE, "expire_date": EXPIRE, "fsa_tnved": sorted(TNVED),
        "fsa_scope": "Sealed Arlight LED strips from ARL, MOONLIGHT, WAVE series; TR EAEU 037/2016; TN VED 9405110014.",
        "source_file": SOURCE_REL, "source_sha256": sha(SOURCE),
        "manufacturer_pdf_url": "https://pub.fsa.gov.ru/rds/declaration/view/21071412",
        "candidate_stats": candidate_stats, "ozon_record": record,
        "ozon_record_metadata_exact": record_exact,
        "ozon_targets": ozon_targets, "wb_targets": wb_targets,
        "summary": {
            "candidate_offer_document_pairs": len(offers),
            "ozon_eligible_pairs": sum(x["eligible"] and not x["already_exact"] for x in ozon_targets),
            "ozon_already_exact_pairs": sum(x["already_exact"] for x in ozon_targets),
            "wb_exact_cards": sum(bool(x["nmID"]) for x in wb_targets),
            "wb_eligible_pairs": sum(x["eligible"] and not x["already_exact"] for x in wb_targets),
            "wb_already_exact_pairs": sum(x["already_exact"] for x in wb_targets),
            "ozon_conflicts": dict(ozon_counts), "wb_conflicts": dict(wb_counts),
        },
    }
    temp = OUT.with_suffix(".json.tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(OUT)
    print(json.dumps({"output": str(OUT), "candidate_stats": candidate_stats,
                      "summary": result["summary"],
                      "ozon_record": {k: record.get(k) for k in ("certificate_id","type_code","status_code","issue_date","expire_date")} if record else None},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
