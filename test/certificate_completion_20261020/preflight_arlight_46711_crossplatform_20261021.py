"""Fresh, read-only scope check for Arlight declaration 46711/26."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import copy_documents, norm_number, wb_datetime  # noqa: E402

PDF = ROOT / "output_to_user/certificates/group_1/documents/arlight/97331E1740F80745A33F67528E33A9AB.pdf"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
SNAPSHOT = HERE / "live_marketplaces_snapshot_final_20261020.json"
OUT = HERE / "arlight_46711_preflight_live_20261021.json"
NUMBER = "ЕАЭС N RU Д-HK.РА01.В.46711/26"
ISSUE = "2026-01-30"
EXPIRY = "2031-01-29"
ALLOWED_TNVED = {"8536901000", "8536699008"}
FSA_RECORD_ID = 21106697


def save(value: dict) -> None:
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(OUT)


def attr_values(row: dict, attr_id: int) -> list[str]:
    attrs = {str(a.get("id")): a for a in row.get("attributes") or []}
    return [str(v.get("value") or "").strip()
            for v in (attrs.get(str(attr_id)) or {}).get("values") or []
            if str(v.get("value") or "").strip()]


def wb_tnved(card: dict) -> list[str]:
    out = []
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        values = raw if isinstance(raw, list) else [raw]
        out.extend(str(v or "").split(" - ", 1)[0].strip() for v in values if v)
    return sorted(set(out))


def model_codes(name: str) -> list[str]:
    return sorted(set(re.findall(r"(?:NEO|ARL)-[A-Z0-9]+(?:-[A-Z0-9]+)*", name.upper())))


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_output_exists")
    digest = hashlib.sha256(PDF.read_bytes()).hexdigest()
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assigned_rows = [r for r in rows if "46711/26" in str(r.get("Номер/название документа") or "")
                     and str(r.get("Бренд Ozon") or "").strip().casefold() == "arlight"]
    exact_rows = [r for r in assigned_rows
                  if "коннектор" in str(r.get("Название товара Ozon") or "").casefold()]
    by_offer: dict[str, list[dict]] = collections.defaultdict(list)
    for row in exact_rows:
        by_offer[str(row.get("Артикул продавца") or "")].append(row)
    by_offer.pop("", None)
    if len(by_offer) != 7 or any(len({r.get("Название товара Ozon") for r in rs}) != 1
                                 for rs in by_offer.values()):
        raise RuntimeError(f"unexpected_exact_connector_assignments:{len(by_offer)}")
    for offer, rs in by_offer.items():
        title = str(rs[0].get("Название товара Ozon") or "")
        if not any(series in title.upper() for series in ("NEO-", "ARL-")):
            raise RuntimeError("assigned_offer_not_exact_series:" + offer)

    old = json.loads(SNAPSHOT.read_text())
    products = {str(x.get("offer_id")): x for x in old["ozon_products"]["products"]}
    if not old["ozon_products"].get("complete") or not old["wb_catalog"].get("complete"):
        raise RuntimeError("complete_previous_crossplatform_snapshot_required")
    targets = []
    for offer, rs in sorted(by_offer.items()):
        p = products.get(offer)
        if not p or p.get("is_archived") is not False or "Arlight" not in (p.get("brand_values") or []):
            raise RuntimeError("ozon_snapshot_identity_or_brand_mismatch:" + offer)
        title = str(rs[0].get("Название товара Ozon") or "")
        codes = model_codes(title)
        if len(codes) != 1 or codes[0] not in title.upper():
            raise RuntimeError("assigned_model_code_ambiguous:" + offer)
        targets.append({"offer_id": offer, "product_id": str(p["product_id"]),
                        "sku": str(p["sku"]), "name": p.get("name"),
                        "assigned_title": title, "model_code": codes[0]})
    client = Client()
    ids = [x["product_id"] for x in targets]
    details = {}
    for start in range(0, len(ids), 100):
        batch = ids[start:start + 100]
        response = client.call("ozon", "/v3/product/info/list", {
            "product_id": [int(x) for x in batch]}).get("items")
        if not isinstance(response, list):
            raise RuntimeError("ozon_live_products_missing")
        for row in response:
            pid = str(row.get("product_id") or row.get("id") or "")
            if pid not in batch or pid in details:
                raise RuntimeError("ozon_live_product_identity_mismatch")
            details[pid] = row
    attributes = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": [x["offer_id"] for x in targets]}, "limit": len(targets)
    }).get("result")
    if not isinstance(attributes, list) or len(attributes) != len(targets):
        raise RuntimeError("ozon_live_attributes_incomplete")
    attrs_by_offer = {str(x.get("offer_id")): x for x in attributes}
    if set(attrs_by_offer) != {x["offer_id"] for x in targets}:
        raise RuntimeError("ozon_live_attribute_offers_mismatch")
    ozon_rows = []
    for target in targets:
        detail = details[target["product_id"]]
        attr = attrs_by_offer[target["offer_id"]]
        brands = attr_values(attr, 85)
        live_tnved = sorted({x.split(" - ", 1)[0].strip() for x in attr_values(attr, 22232)})
        if (str(detail.get("offer_id") or "") != target["offer_id"]
                or str(detail.get("product_id") or detail.get("id") or "") != target["product_id"]
                or str(detail.get("sku") or "") != target["sku"]
                or detail.get("is_archived") is not False or brands != ["Arlight"]
                or "коннектор" not in str(detail.get("name") or "").casefold()
                or target["model_code"] not in str(detail.get("name") or "").upper()):
            raise RuntimeError("ozon_live_product_not_exact_connector:" + target["offer_id"])
        ozon_rows.append({**target, "brand_values": brands, "live_name": detail.get("name"),
                          "tnved_values": attr_values(attr, 22232), "tnved_codes": live_tnved,
                          "tnved_matches_fsa": bool(live_tnved and set(live_tnved) <= ALLOWED_TNVED)})

    meta = []
    page = 1
    while True:
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_missing")
        meta.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            break
        page += 1
    ozon_matches = [x for x in meta if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if ozon_matches:
        raise RuntimeError("ozon_exact_record_already_exists:" + ",".join(str(x.get("certificate_id")) for x in ozon_matches))
    # Verify exact-number absence separately; Ozon returns HTTP 404/code 5 for an absent number.
    payload = {"certificate_number": NUMBER}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    response = client.http.post("https://api-seller.ozon.ru/v1/product/certificate/info",
                                data=encoded, headers=client.ozon_headers, timeout=(15, 60))
    try:
        exact_body = response.json()
    except ValueError:
        exact_body = {}
    if not (response.status_code == 404 and isinstance(exact_body, dict)
            and exact_body.get("code") == 5
            and "not found" in str(exact_body.get("message") or "").casefold()
            and NUMBER in str(exact_body.get("message") or "")):
        raise RuntimeError("ozon_exact_record_absence_unconfirmed")

    wb_rows = []
    for target in targets:
        cards = client.wb_cards(target["offer_id"])
        if len(cards) != 1:
            wb_rows.append({"offer_id": target["offer_id"],
                            "exact_card_count": len(cards), "safe_for_update": False,
                            "problem": "wb_exact_card_missing" if not cards else "wb_exact_card_duplicate"})
            continue
        card = cards[0]
        if (str(card.get("vendorCode") or "") != target["offer_id"]
                or str(card.get("brand") or "").strip().casefold() != "arlight"
                or "коннектор" not in str(card.get("title") or "").casefold()
                or target["model_code"] not in str(card.get("title") or "").upper()):
            wb_rows.append({"offer_id": target["offer_id"], "nmID": str(card.get("nmID")),
                            "exact_card_count": 1, "safe_for_update": False,
                            "problem": "wb_live_card_identity_or_scope_mismatch",
                            "brand": card.get("brand"), "title": card.get("title"),
                            "full_card": card})
            continue
        docs = copy_documents(card)
        same = [d for d in docs if norm_number(d.get("number")) == norm_number(NUMBER)]
        doc_state = "missing" if not same else "conflict"
        if same:
            if (len(same) == 1 and same[0].get("type") == 2
                    and str(same[0].get("startDate", ""))[:10] == ISSUE
                    and str(same[0].get("endDate", ""))[:10] == EXPIRY):
                doc_state = "already_exact"
            else:
                wb_rows.append({"offer_id": target["offer_id"], "nmID": str(card.get("nmID")),
                                "exact_card_count": 1, "safe_for_update": False,
                                "problem": "wb_same_number_metadata_conflict", "full_card": card})
                continue
        codes = wb_tnved(card)
        wb_rows.append({"offer_id": target["offer_id"], "nmID": str(card.get("nmID")),
                        "brand": card.get("brand"), "title": card.get("title"),
                        "model_code": target["model_code"], "tnved_codes": codes,
                        "tnved_matches_fsa": bool(codes and set(codes) <= ALLOWED_TNVED),
                        "existing_documents": docs, "document_state": doc_state,
                        "safe_for_update": True, "full_card": card})
    output = {
        "checked_at": now(), "read_only": True, "number": NUMBER,
        "official_fsa_record_id": FSA_RECORD_ID, "official_status": "active",
        "official_issue_date": ISSUE, "official_expiry_date": EXPIRY,
        "official_product_scope": "Non-household connectors, series ARL and NEO, Arlight",
        "official_tnved_scope": sorted(ALLOWED_TNVED), "source_pdf": str(PDF),
        "source_pdf_sha256": digest, "source_pdf_pages": 2,
        "raw_assignment_rows": len(assigned_rows), "exact_connector_assignment_rows": len(exact_rows),
        "unique_exact_connector_offers": len(targets),
        "excluded_assigned_items": [
            {"offer_id": str(r.get("Артикул продавца") or ""),
             "name": str(r.get("Название товара Ozon") or ""),
             "reason": "not_a_connector_under_exact_FSA_product_description"}
            for r in assigned_rows if str(r.get("Артикул продавца") or "") not in by_offer
        ],
        "ozon_targets": ozon_rows, "ozon_target_count": len(ozon_rows),
        "ozon_record_matches": len(ozon_matches), "ozon_exact_info_absent": True,
        "wb_targets": wb_rows, "wb_target_count": len(wb_rows),
        "tnved_mismatch_offers": sorted({x["offer_id"] for x in ozon_rows + wb_rows
                                         if x.get("tnved_matches_fsa") is False}),
        "eligible_for_upload": len(ozon_rows) == 7 and len(targets) == 7
            and all("connector" in x["live_name"].casefold() or "коннектор" in x["live_name"].casefold()
                    for x in ozon_rows),
        "wb_safe_targets": sum(x.get("safe_for_update") is True for x in wb_rows),
        "wb_problematic_targets": [x for x in wb_rows if x.get("safe_for_update") is not True],
        "wb_review_left_pending": True, "local_files_deleted": False,
    }
    save(output)
    print(json.dumps({k: v for k, v in output.items() if k not in {"ozon_targets", "wb_targets"}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
