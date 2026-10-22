"""Fresh, read-only partial-scope preflight for Arlight 33344/26."""
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

NUMBER = "ЕАЭС N RU Д-CN.РА03.В.33344/26"
FSA_ID = 21321061
ISSUE = "2026-04-13"
EXPIRY = "2031-04-09"
ALLOWED_TNVED = {"8537109800"}
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/arlight/DCE8C157436F3C4E9898E20868978ACD.pdf"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
OUT = HERE / "arlight_33344_partial_preflight_live_20261021.json"


def save(value: dict) -> None:
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(OUT)


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def attr_values(row: dict, attr_id: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(x.get("value") or "").strip()
            for x in (attrs.get(str(attr_id)) or {}).get("values") or []
            if str(x.get("value") or "").strip()]


def tnv_codes(values: list[str]) -> list[str]:
    return sorted({str(x).split(" - ", 1)[0].strip() for x in values if str(x).strip()})


def card_tnv(card: dict) -> list[str]:
    out = []
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        vals = raw if isinstance(raw, list) else [raw]
        out.extend(str(v or "").split(" - ", 1)[0].strip() for v in vals if v)
    return sorted(set(out))


def assignments() -> dict[str, dict]:
    by_offer: dict[str, dict] = {}
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if norm_number(row.get("Номер/название документа")) != norm_number(NUMBER):
                continue
            offer = str(row.get("Артикул продавца") or "").strip()
            if not offer or offer in by_offer:
                raise RuntimeError("missing_or_duplicate_assigned_offer:" + offer)
            if str(row.get("Бренд подтвержденный") or "").strip() != "Arlight":
                raise RuntimeError("assigned_brand_mismatch:" + offer)
            by_offer[offer] = {
                "offer_id": offer,
                "assignment_name": str(row.get("Название товара Ozon") or ""),
                "source_file": str(row.get("Локальный файл") or ""),
                "source_url": str(row.get("URL документа") or ""),
                "validity": str(row.get("Сроки/валидность") or ""),
                "evidence": str(row.get("Основание сопоставления") or ""),
            }
    if len(by_offer) != 90:
        raise RuntimeError(f"unexpected_assignment_offer_count:{len(by_offer)}")
    return by_offer


def read_certificates(client: Client) -> list[dict]:
    out = []
    page = 1
    while page <= 100:
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_page_invalid")
        out.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return out
        page += 1
    raise RuntimeError("ozon_certificate_pages_exceeded")


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_output_exists")
    if not SOURCE.is_file():
        raise RuntimeError("source_pdf_missing")
    source_hash = sha256(SOURCE)
    assigned = assignments()
    client = Client()
    offers = sorted(assigned)

    product_rows = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items")
    if not isinstance(product_rows, list) or len(product_rows) != len(offers):
        raise RuntimeError("ozon_live_product_info_incomplete")
    products = {str(x.get("offer_id") or ""): x for x in product_rows}
    if set(products) != set(offers):
        raise RuntimeError("ozon_live_offer_set_mismatch")
    attrs_rows = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": offers}, "limit": len(offers)
    }).get("result")
    if not isinstance(attrs_rows, list) or len(attrs_rows) != len(offers):
        raise RuntimeError("ozon_live_attributes_incomplete")
    attrs = {str(x.get("offer_id") or ""): x for x in attrs_rows}
    if set(attrs) != set(offers):
        raise RuntimeError("ozon_attribute_offer_set_mismatch")

    rows = []
    ozon_in_scope = []
    for offer in offers:
        p, a = products[offer], attrs[offer]
        brand_values = attr_values(a, 85)
        codes = tnv_codes(attr_values(a, 22232))
        name = str(p.get("name") or "")
        if (str(p.get("offer_id") or "") != offer or p.get("is_archived") is not False
                or brand_values != ["Arlight"] or "диммер" not in name.casefold()):
            raise RuntimeError("ozon_live_product_identity_or_scope_changed:" + offer)
        row = {**assigned[offer], "product_id": str(p.get("product_id") or p.get("id") or ""),
               "sku": str(p.get("sku") or ""), "name": name, "brand_values": brand_values,
               "tnved_values": attr_values(a, 22232), "tnved_codes": codes,
               "tnved_matches_fsa": bool(codes and set(codes) <= ALLOWED_TNVED)}
        if not row["product_id"] or not row["sku"]:
            raise RuntimeError("ozon_live_product_missing_id_or_sku:" + offer)
        rows.append(row)
        if row["tnved_matches_fsa"]:
            ozon_in_scope.append(row)
    if len(ozon_in_scope) != 26:
        raise RuntimeError(f"unexpected_current_in_scope_offer_count:{len(ozon_in_scope)}")

    all_certs = read_certificates(client)
    matches = [x for x in all_certs if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if matches:
        raise RuntimeError("ozon_certificate_record_already_exists:" + ",".join(str(x.get("certificate_id")) for x in matches))
    raw = json.dumps({"certificate_number": NUMBER}, ensure_ascii=False, separators=(",", ":")).encode()
    response = client.http.post("https://api-seller.ozon.ru/v1/product/certificate/info",
                                data=raw, headers=client.ozon_headers, timeout=(15, 60))
    try:
        body = response.json()
    except ValueError:
        body = {}
    exact_absence = (response.status_code == 404 and isinstance(body, dict) and body.get("code") == 5
                     and "not found" in str(body.get("message") or "").casefold()
                     and NUMBER in str(body.get("message") or ""))
    if not exact_absence:
        raise RuntimeError("ozon_exact_certificate_absence_unconfirmed")

    wb_rows = []
    for target in ozon_in_scope:
        cards = client.wb_cards(target["offer_id"])
        if not cards:
            wb_rows.append({"offer_id": target["offer_id"], "card_count": 0,
                            "safe_for_update": False, "problem": "no_exact_wb_card"})
            continue
        if len(cards) != 1:
            wb_rows.append({"offer_id": target["offer_id"], "card_count": len(cards),
                            "safe_for_update": False, "problem": "duplicate_wb_cards"})
            continue
        card = cards[0]
        title = str(card.get("title") or "")
        brand = str(card.get("brand") or "").strip()
        codes = card_tnv(card)
        if (str(card.get("vendorCode") or "") != target["offer_id"] or brand.casefold() != "arlight"
                or "диммер" not in title.casefold()):
            wb_rows.append({"offer_id": target["offer_id"], "nmID": str(card.get("nmID") or ""),
                            "card_count": 1, "safe_for_update": False,
                            "problem": "wb_card_identity_or_product_scope_mismatch", "full_card": card})
            continue
        if codes and not set(codes) <= ALLOWED_TNVED:
            wb_rows.append({"offer_id": target["offer_id"], "nmID": str(card.get("nmID") or ""),
                            "card_count": 1, "safe_for_update": False,
                            "problem": "wb_tnved_conflicts_with_fsa", "tnved_codes": codes,
                            "full_card": card})
            continue
        same = [d for d in copy_documents(card) if norm_number(d.get("number")) == norm_number(NUMBER)]
        if same:
            exact = (len(same) == 1 and int(same[0].get("type") or 0) == 2
                     and str(same[0].get("startDate", ""))[:10] == ISSUE
                     and str(same[0].get("endDate", ""))[:10] == EXPIRY)
            wb_rows.append({"offer_id": target["offer_id"], "nmID": str(card.get("nmID") or ""),
                            "card_count": 1, "safe_for_update": False,
                            "problem": "already_exact" if exact else "same_number_metadata_conflict",
                            "full_card": card})
            continue
        wb_rows.append({"offer_id": target["offer_id"], "nmID": str(card.get("nmID") or ""),
                        "title": title, "brand": brand, "tnved_codes": codes,
                        "scope_basis": "exact_vendor_code_and_brand_plus_live_in_scope_ozon_offer"
                            if not codes else "exact_wb_tnved_code",
                        "card_count": 1, "safe_for_update": True, "full_card": card})

    output = {
        "checked_at": now(), "read_only": True, "number": NUMBER,
        "official_fsa": {"record_id": FSA_ID, "status": "active", "issue_date": ISSUE,
                         "expiry_date": EXPIRY, "scheme": "1d", "release": "serial production",
                         "product_scope": "Arlight / INTELLIGENT ARLIGHT dimmers and microdimmers; series SMART, SR, LN, TY, TUYA, MATTER, ZB, DALI, KNX, ARL, VT, WF, TRIAC, SENS",
                         "tnved": sorted(ALLOWED_TNVED),
                         "url": f"https://pub.fsa.gov.ru/rds/declaration/view/{FSA_ID}/product"},
        "source_pdf": str(SOURCE), "source_pdf_sha256": source_hash,
        "assigned_offer_count": len(offers), "ozon_live_offer_count": len(products),
        "ozon_current_in_scope_count": len(ozon_in_scope),
        "ozon_out_of_scope_skipped": len(offers) - len(ozon_in_scope),
        "ozon_record_count_before_upload": len(matches), "ozon_exact_info_absent": True,
        "ozon_targets": ozon_in_scope, "wb_targets": wb_rows,
        "wb_safe_targets": sum(1 for x in wb_rows if x.get("safe_for_update") is True),
        "wb_no_card_count": sum(1 for x in wb_rows if x.get("problem") == "no_exact_wb_card"),
        "wb_problematic_targets": [x for x in wb_rows if x.get("safe_for_update") is not True],
        "eligible_for_partial_upload": len(ozon_in_scope) == 26 and len(matches) == 0
            and all(x.get("product_id") and x.get("sku") for x in ozon_in_scope),
        "wb_review_left_pending": True, "local_file_deleted": False,
    }
    save(output)
    print(json.dumps({k: v for k, v in output.items()
                      if k not in {"ozon_targets", "wb_targets", "wb_problematic_targets"}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
