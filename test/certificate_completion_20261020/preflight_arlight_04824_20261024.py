#!/usr/bin/env python3
"""Read-only live preflight for Ardecoled certificate 04824/22."""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

NUMBER = "ЕАЭС RU С-HK.АБ53.В.04824/22"
ISSUE = "2022-06-20"
EXPIRY = "2027-06-19"
FSA_ID = "3109217"
SOURCE_REL = "output_to_user/certificates/group_1/documents/arlight/B5C5BB7F9BA5554A937519F74325C68F.pdf"
SOURCE = ROOT / SOURCE_REL
SOURCE_SHA = "36244cfcdf8583978b0528ed4e39338edf0f0fdfdf8fbe81894715ed7dfb10d9"
OUT = HERE / "arlight_04824_crossplatform_preflight_20261024.json"
ALLOWED_TNVED = {"9405310000"}


def value_map(row: dict) -> dict[str, list[str]]:
    return {str(x.get("id")): [str(v.get("value") or "").strip()
            for v in x.get("values") or [] if str(v.get("value") or "").strip()]
            for x in row.get("attributes") or []}


def codes(items: list[str]) -> list[str]:
    return sorted({str(x).split(" - ", 1)[0].strip() for x in items if str(x).strip()})


def wb_codes(card: dict) -> list[str]:
    found = []
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" in name or "тнвед" in name:
            raw = item.get("value")
            found.extend(raw if isinstance(raw, list) else [raw])
    return codes([str(x) for x in found if x])


def all_ozon_records(client: Client) -> list[dict]:
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
    raise RuntimeError("ozon_certificate_list_page_limit")


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_exists_inspect_first")
    if not SOURCE.is_file() or hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA:
        raise RuntimeError("source_file_hash_mismatch")

    assignment_rows = []
    with (ROOT / "output_to_user/certificates/document_assignments.csv").open(
            encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if "04824/22" not in str(row.get("Номер/название документа") or ""):
                continue
            if row.get("Локальный файл") != SOURCE_REL:
                continue
            if row.get("Бренд подтвержденный") != "Arlight":
                raise RuntimeError("assignment_brand_conflict")
            if row.get("Применимость") != "Подтверждено статусом покрытия":
                raise RuntimeError("assignment_scope_not_confirmed")
            if row.get("Тип документа") != "Сертификат соответствия":
                raise RuntimeError("assignment_type_conflict")
            if row.get("SHA256 фактический") != SOURCE_SHA:
                raise RuntimeError("assignment_source_hash_mismatch")
            assignment_rows.append({"offer_id": str(row.get("Артикул продавца") or "").strip(),
                                    "article": str(row.get("Артикул из каталога") or "").strip(),
                                    "official_evidence": row.get("Основание сопоставления"),
                                    "official_product_page": row.get("Официальная страница товара/основания")})
    offers = [x["offer_id"] for x in assignment_rows]
    if len(offers) != len(set(offers)) or not offers:
        raise RuntimeError("assignment_offer_set_missing_or_duplicated")

    client = Client()
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items") or []
    attrs = client.call("ozon", "/v4/product/info/attributes",
                        {"filter": {"offer_id": offers}, "limit": len(offers)}).get("result") or []
    pmap = {str(x.get("offer_id") or ""): x for x in products}
    amap = {str(x.get("offer_id") or ""): x for x in attrs}
    if len(pmap) != len(products) or len(amap) != len(attrs):
        raise RuntimeError("duplicate_live_ozon_offer_info")
    matching = [x for x in all_ozon_records(client)
                if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(matching) > 1:
        raise RuntimeError("duplicate_ozon_certificate_records")
    record = matching[0] if matching else None
    if record and (record.get("type_code") != "certificate_of_conformity"
                   or str(record.get("issue_date") or "")[:10] != ISSUE
                   or str(record.get("expire_date") or "")[:10] != EXPIRY):
        raise RuntimeError("ozon_existing_record_metadata_conflict")
    bindings = client.ozon_bindings(int(record["certificate_id"])) if record else []
    bindings_by_pid: dict[str, list[dict]] = {}
    for binding in bindings:
        bindings_by_pid.setdefault(str(binding.get("product_id") or ""), []).append(binding)

    targets = []
    for source in assignment_rows:
        offer = source["offer_id"]
        p, a = pmap.get(offer), amap.get(offer)
        ozon_blockers = []
        if not p or not a:
            ozon_blockers.append("offer_not_currently_found_on_ozon")
            p, a = p or {}, a or {}
        attr = value_map(a)
        brand = attr.get("85", [])
        tnved = codes(attr.get("22232", []))
        is_archived = p.get("is_archived")
        product_id, sku = str(p.get("product_id") or p.get("id") or ""), str(p.get("sku") or "")
        name = str(p.get("name") or "")
        if is_archived is not False:
            ozon_blockers.append("archived_or_unclear")
        if brand != ["Arlight"]:
            ozon_blockers.append("brand_mismatch")
        if tnved != sorted(ALLOWED_TNVED):
            ozon_blockers.append("tnved_mismatch_or_missing")
        if not any(token in name.casefold() for token in ("гирлянд", "светодиодная фигура", "световая фигура")):
            ozon_blockers.append("product_name_not_garland_or_light_figure")
        existing = bindings_by_pid.get(product_id, [])
        if len(existing) > 1:
            ozon_blockers.append("duplicate_existing_binding")
        elif existing and str(existing[0].get("sku") or "") != sku:
            ozon_blockers.append("existing_binding_sku_conflict")

        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        card = cards[0] if len(cards) == 1 else {}
        wb_brand, wb_tnved, title = str(card.get("brand") or ""), wb_codes(card) if card else [], str(card.get("title") or "")
        wb_blockers = []
        if len(cards) != 1:
            wb_blockers.append("missing_or_duplicate_exact_wb_card")
        if wb_brand.casefold() != "arlight":
            wb_blockers.append("brand_mismatch")
        if wb_tnved != sorted(ALLOWED_TNVED):
            wb_blockers.append("tnved_mismatch_or_missing")
        if not any(token in title.casefold() for token in ("гирлянд", "светодиодная фигура", "световая фигура")):
            wb_blockers.append("product_title_not_garland_or_light_figure")
        same = [x for x in ((card.get("documents") or {}).get("items") or [])
                if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in same if str(x.get("type")) == "1"
                 and str(x.get("startDate") or "")[:10] == ISSUE
                 and str(x.get("endDate") or "")[:10] == EXPIRY
                 and x.get("isEndless") is False]
        if same and (len(same) != 1 or len(exact) != 1):
            wb_blockers.append("existing_same_number_document_conflict")
        targets.append({**source, "product_id": product_id, "sku": sku, "ozon_name": p.get("name"),
                        "ozon_brand": brand, "ozon_tnved": tnved, "ozon_existing_binding_count": len(existing),
                        "ozon_existing_binding_status": existing[0].get("product_status_code") if len(existing) == 1 else None,
                        "ozon_safe": not ozon_blockers, "ozon_blockers": ozon_blockers,
                        "nmID": str(card.get("nmID") or ""), "wb_brand": wb_brand, "wb_title": title,
                        "wb_tnved": wb_tnved, "wb_exact_document_visible": bool(exact),
                        "wb_safe": not wb_blockers, "wb_blockers": wb_blockers})

    result = {"checked_at_utc": now(), "read_only": True, "number": NUMBER,
              "document_type": "certificate_of_conformity", "fsa_record_id": FSA_ID,
              "fsa_url": f"https://pub.fsa.gov.ru/rss/certificate/view/{FSA_ID}/product",
              "fsa_status": "Действует", "issue_date": ISSUE, "expiry_date": EXPIRY,
              "fsa_tnved": sorted(ALLOWED_TNVED), "fsa_scope": "Ardecoled LED garlands and figures, series ARD",
              "source_file": SOURCE_REL, "source_sha256": SOURCE_SHA,
              "ozon_record": ({k: record.get(k) for k in ("certificate_id", "certificate_number", "type_code",
                               "status_code", "issue_date", "expire_date", "products_count")} if record else None),
              "ozon_existing_binding_count": len(bindings), "assignment_target_count": len(assignment_rows),
              "targets": targets, "ozon_safe_count": sum(x["ozon_safe"] for x in targets),
              "ozon_blocker_counts": dict(Counter(r for x in targets for r in x["ozon_blockers"])),
              "wb_safe_count": sum(x["wb_safe"] for x in targets),
              "wb_blocker_counts": dict(Counter(r for x in targets for r in x["wb_blockers"])),
              "wb_existing_exact_count": sum(x["wb_exact_document_visible"] for x in targets),
              "writes_performed": False, "local_file_deleted": False}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("checked_at_utc", "assignment_target_count", "ozon_record",
          "ozon_safe_count", "ozon_blocker_counts", "wb_safe_count", "wb_blocker_counts",
          "wb_existing_exact_count")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
