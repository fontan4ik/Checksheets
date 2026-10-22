"""Read-only fresh partial-scope preflight for Arlight declaration 79626/26."""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import copy_documents, norm_number  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА03.В.79626/26"
FSA_ID = 21373550
ISSUE = "2026-04-29"
EXPIRY = "2031-04-27"
ALLOWED_TNVED = {"9405420012", "9405420019"}
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/arlight/AF84AD86AF506A41B7A2C69EC958CA8B.pdf"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
OUT = HERE / "arlight_79626_preflight_live_20261021.json"


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def attr_values(row: dict, attr_id: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(x.get("value") or "").strip()
            for x in (attrs.get(str(attr_id)) or {}).get("values") or []
            if str(x.get("value") or "").strip()]


def tnved(values: list[str]) -> list[str]:
    return sorted({str(v).split(" - ", 1)[0].strip() for v in values if str(v).strip()})


def card_tnved(card: dict) -> list[str]:
    out = []
    for x in card.get("characteristics") or []:
        name = "".join(str(x.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = x.get("value")
        vals = raw if isinstance(raw, list) else [raw]
        out.extend(str(v or "").split(" - ", 1)[0].strip() for v in vals if v)
    return sorted(set(out))


def load_assignments() -> dict[str, dict]:
    result = {}
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if norm_number(r.get("Номер/название документа")) != norm_number(NUMBER):
                continue
            offer = str(r.get("Артикул продавца") or "").strip()
            if not offer or offer in result:
                raise RuntimeError("missing_or_duplicate_assignment_offer:" + offer)
            if str(r.get("Бренд подтвержденный") or "").strip() != "Arlight":
                raise RuntimeError("assignment_brand_conflict:" + offer)
            result[offer] = {"offer_id": offer, "assignment_name": str(r.get("Название товара Ozon") or ""),
                             "source_file": str(r.get("Локальный файл") or ""),
                             "source_url": str(r.get("URL документа") or ""),
                             "evidence": str(r.get("Основание сопоставления") or "")}
    if len(result) != 70:
        raise RuntimeError(f"unexpected_assignment_count:{len(result)}")
    return result


def ozon_certificates(client: Client) -> list[dict]:
    result = []
    page = 1
    while page <= 100:
        response = client.call("ozon", "/v1/product/certificate/list",
                               {"page": page, "page_size": 100}).get("result") or {}
        batch = response.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        result.extend(batch)
        if not batch or page >= int(response.get("page_count") or 0):
            return result
        page += 1
    raise RuntimeError("ozon_certificate_list_page_limit")


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_output_exists")
    if not SOURCE.is_file():
        raise RuntimeError("source_pdf_missing")
    assignment = load_assignments()
    offers = sorted(assignment)
    client = Client()
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items")
    attrs = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": offers}, "limit": len(offers)
    }).get("result")
    if not isinstance(products, list) or len(products) != 70:
        raise RuntimeError("ozon_products_incomplete")
    if not isinstance(attrs, list) or len(attrs) != 70:
        raise RuntimeError("ozon_attributes_incomplete")
    pmap = {str(x.get("offer_id") or ""): x for x in products}
    amap = {str(x.get("offer_id") or ""): x for x in attrs}
    if set(pmap) != set(offers) or set(amap) != set(offers):
        raise RuntimeError("ozon_offer_set_mismatch")

    ozon_targets = []
    skipped = []
    for offer in offers:
        p, a = pmap[offer], amap[offer]
        brand = attr_values(a, 85)
        codes = tnved(attr_values(a, 22232))
        name = str(p.get("name") or "")
        if (p.get("is_archived") is not False or brand != ["Arlight"]
                or "прожектор" not in name.casefold()):
            raise RuntimeError("ozon_exact_projector_identity_changed:" + offer)
        row = {**assignment[offer], "product_id": str(p.get("product_id") or p.get("id") or ""),
               "sku": str(p.get("sku") or ""), "name": name, "brand_values": brand,
               "tnved_values": attr_values(a, 22232), "tnved_codes": codes,
               "tnved_matches_fsa": bool(codes and set(codes) <= ALLOWED_TNVED)}
        if not row["product_id"] or not row["sku"]:
            skipped.append({**row, "problem": "missing_product_id_or_sku"})
        elif row["tnved_matches_fsa"]:
            ozon_targets.append(row)
        else:
            skipped.append({**row, "problem": "ozon_tnved_missing_or_outside_fsa_scope"})
    if not ozon_targets:
        raise RuntimeError("no_current_ozon_in_scope_targets")

    matching_records = [x for x in ozon_certificates(client)
                        if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    raw = json.dumps({"certificate_number": NUMBER}, ensure_ascii=False,
                     separators=(",", ":")).encode()
    response = client.http.post("https://api-seller.ozon.ru/v1/product/certificate/info",
                                data=raw, headers=client.ozon_headers, timeout=(15, 60))
    try:
        body = response.json()
    except ValueError:
        body = {}
    exact_absent = (response.status_code == 404 and isinstance(body, dict) and body.get("code") == 5
                    and "not found" in str(body.get("message") or "").casefold()
                    and NUMBER in str(body.get("message") or ""))
    if matching_records or not exact_absent:
        raise RuntimeError("ozon_existing_record_or_absence_unclear")

    wb_targets = []
    for target in ozon_targets:
        cards = client.wb_cards(target["offer_id"])
        if not cards:
            wb_targets.append({"offer_id": target["offer_id"], "card_count": 0,
                               "safe_for_update": False, "problem": "no_exact_wb_card"})
            continue
        if len(cards) != 1:
            wb_targets.append({"offer_id": target["offer_id"], "card_count": len(cards),
                               "safe_for_update": False, "problem": "duplicate_wb_cards"})
            continue
        card = cards[0]
        title = str(card.get("title") or "")
        codes = card_tnved(card)
        if (str(card.get("vendorCode") or "") != target["offer_id"]
                or str(card.get("brand") or "").strip().casefold() != "arlight"
                or "прожектор" not in title.casefold()):
            wb_targets.append({"offer_id": target["offer_id"], "nmID": str(card.get("nmID") or ""),
                               "card_count": 1, "safe_for_update": False,
                               "problem": "wb_identity_or_projector_scope_mismatch", "full_card": card})
            continue
        if codes and not set(codes) <= ALLOWED_TNVED:
            wb_targets.append({"offer_id": target["offer_id"], "nmID": str(card.get("nmID") or ""),
                               "card_count": 1, "safe_for_update": False,
                               "problem": "wb_tnved_conflict", "tnved_codes": codes,
                               "full_card": card})
            continue
        same = [d for d in copy_documents(card) if norm_number(d.get("number")) == norm_number(NUMBER)]
        if same:
            exact = (len(same) == 1 and int(same[0].get("type") or 0) == 2
                     and str(same[0].get("startDate", ""))[:10] == ISSUE
                     and str(same[0].get("endDate", ""))[:10] == EXPIRY)
            wb_targets.append({"offer_id": target["offer_id"], "nmID": str(card.get("nmID") or ""),
                               "card_count": 1, "safe_for_update": False,
                               "problem": "already_exact" if exact else "same_number_metadata_conflict",
                               "full_card": card})
            continue
        wb_targets.append({"offer_id": target["offer_id"], "nmID": str(card.get("nmID") or ""),
                           "title": title, "brand": card.get("brand"), "tnved_codes": codes,
                           "scope_basis": "exact WB TNVED code" if codes else
                               "exact vendor code and brand plus live in-scope Ozon offer",
                           "card_count": 1, "safe_for_update": True, "full_card": card})

    output = {"checked_at": now(), "read_only": True, "number": NUMBER,
              "official_fsa": {"record_id": FSA_ID, "status": "active", "issue_date": ISSUE,
                               "expiry_date": EXPIRY, "scheme": "1d", "release": "serial production",
                               "product_scope": "Arlight LED floodlights series AR, ALT, KT",
                               "tnved": sorted(ALLOWED_TNVED),
                               "url": f"https://pub.fsa.gov.ru/rds/declaration/view/{FSA_ID}/product"},
              "source_pdf": str(SOURCE), "source_pdf_sha256": digest(SOURCE),
              "assigned_offer_count": 70, "ozon_current_in_scope_count": len(ozon_targets),
              "ozon_out_of_scope_skipped": skipped, "ozon_record_count_before_upload": len(matching_records),
              "ozon_exact_info_absent": exact_absent, "ozon_targets": ozon_targets,
              "wb_targets": wb_targets,
              "wb_safe_targets": sum(x.get("safe_for_update") is True for x in wb_targets),
              "wb_no_card_count": sum(x.get("problem") == "no_exact_wb_card" for x in wb_targets),
              "wb_problematic_targets": [x for x in wb_targets if x.get("safe_for_update") is not True],
              "eligible_for_partial_upload": bool(ozon_targets) and len(matching_records) == 0
                  and exact_absent and all(x.get("product_id") and x.get("sku") for x in ozon_targets),
              "wb_review_left_pending": True, "local_file_deleted": False}
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    tmp.replace(OUT)
    print(json.dumps({k: v for k, v in output.items()
                      if k not in {"ozon_targets", "wb_targets", "wb_problematic_targets", "ozon_out_of_scope_skipped"}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
