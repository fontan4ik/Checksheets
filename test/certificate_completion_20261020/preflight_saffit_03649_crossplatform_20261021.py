"""Fresh read-only cross-platform preflight for Saffit declaration 03649/23."""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import re
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import copy_documents, norm_number  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА07.В.03649/23"
ISSUE = "2023-08-31"
EXPIRY = "2028-08-30"
FSA_ID = 18059184
FSA_TNVED = {"9405420032", "9405490036", "9405110033"}
ALLOWED_BRANDS = {"feron", "saffit"}
ALLOWED_SERIES = {"SP", "DH", "SSL", "SPL", "SAL"}
SOURCE = ROOT / "output_to_user/certificates/group_2/SAFFIT/documents/FSA_extract_18059184_03649_23.pdf"
SOURCE_SHA256 = "ded9250ca265af5cd86f2aba8baa66271e5f24cbc35ccdbd8203ee2c32c6a7c2"
ASSIGNMENTS = HERE / "all_confirmed_source_assignments_live_20261020.csv"
OUT = HERE / "saffit_03649_preflight_live_20261021.json"


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def attr_values(row: dict, attr_id: str) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(x.get("value") or "").strip()
            for x in (attrs.get(attr_id) or {}).get("values") or []
            if str(x.get("value") or "").strip()]


def tnved(values: list[str]) -> list[str]:
    return sorted({str(v).split(" - ", 1)[0].strip() for v in values if str(v).strip()})


def card_tnved(card: dict) -> list[str]:
    codes = []
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        values = raw if isinstance(raw, list) else [raw]
        codes.extend(str(v or "").split(" - ", 1)[0].strip() for v in values if v)
    return sorted(set(codes))


def series_mentions(text: str) -> list[str]:
    normalized = str(text or "").upper()
    return sorted({series for series in ALLOWED_SERIES
                   if re.search(rf"(?<![A-Z0-9]){re.escape(series)}(?![A-Z0-9])", normalized)})


def read_targets() -> list[dict]:
    rows = []
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if norm_number(row.get("number", "")) != norm_number(NUMBER):
                continue
            if str(row.get("brand") or "").strip().casefold() not in ALLOWED_BRANDS:
                continue
            rows.append({
                "offer_id": str(row.get("offer_id") or "").strip(),
                "expected_product_id": str(row.get("ozon_product_id") or ""),
                "expected_sku": str(row.get("ozon_sku") or ""),
                "expected_wb_nmID": str(row.get("wb_nmID") or ""),
                "source_file": str(row.get("source_files") or ""),
                "source_row_ozon_state": row.get("ozon_state"),
                "source_row_wb_state": row.get("wb_state"),
            })
    offers = [x["offer_id"] for x in rows]
    if len(rows) != 5 or len(set(offers)) != 5 or any(not x for x in offers):
        raise RuntimeError(f"Expected five unique assigned offers; got {len(rows)}")
    return sorted(rows, key=lambda x: x["offer_id"])


def certificates(client: Client) -> list[dict]:
    out = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {
            "page": page, "page_size": 100,
        }).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list incomplete")
        out.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            ids = [str(x.get("certificate_id") or "") for x in out]
            if len(ids) != len(set(ids)):
                raise RuntimeError("Duplicate Ozon certificate IDs in list")
            return out
    raise RuntimeError("Ozon certificate list page limit")


def main() -> None:
    if OUT.exists():
        raise RuntimeError("Output already exists; inspect it instead of overwriting")
    if not SOURCE.is_file() or digest(SOURCE) != SOURCE_SHA256:
        raise RuntimeError("Official FSA extract missing or hash changed")

    targets = read_targets()
    offers = [x["offer_id"] for x in targets]
    client = Client()
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items")
    attrs = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": offers}, "limit": len(offers),
    }).get("result")
    if not isinstance(products, list) or not isinstance(attrs, list):
        raise RuntimeError("Ozon live product/attribute read incomplete")
    pmap = {str(x.get("offer_id") or ""): x for x in products}
    amap = {str(x.get("offer_id") or ""): x for x in attrs}
    if set(pmap) != set(offers) or set(amap) != set(offers) or len(pmap) != 5 or len(amap) != 5:
        raise RuntimeError("Ozon live target set differs from assignment")

    ozon_targets = []
    for target in targets:
        offer = target["offer_id"]
        product, attribute = pmap[offer], amap[offer]
        brands = attr_values(attribute, "85")
        raw_tnved = attr_values(attribute, "22232")
        codes = tnved(raw_tnved)
        name = str(product.get("name") or "")
        model = attr_values(attribute, "85")
        mentions = series_mentions(name + " " + " ".join(model))
        ozon_targets.append({
            **target,
            "live_product_id": str(product.get("product_id") or product.get("id") or ""),
            "live_sku": str(product.get("sku") or ""),
            "live_archived": product.get("is_archived"),
            "live_name": name,
            "brand_values": brands,
            "tnved_values": raw_tnved,
            "tnved_codes": codes,
            "series_mentions_in_name": mentions,
            "product_id_matches": str(product.get("product_id") or product.get("id") or "") == target["expected_product_id"],
            "sku_matches": str(product.get("sku") or "") == target["expected_sku"],
            "brand_matches_fsa": len(brands) == 1 and brands[0].casefold() in ALLOWED_BRANDS,
            "tnved_matches_fsa": bool(codes) and set(codes) <= FSA_TNVED,
        })

    exact = [x for x in certificates(client)
             if norm_number(x.get("certificate_number") or x.get("number")) == norm_number(NUMBER)]
    if len(exact) > 1:
        raise RuntimeError("Multiple exact Ozon certificate records require reconciliation")
    ozon_record = exact[0] if exact else None
    ozon_bindings = client.ozon_bindings(ozon_record["certificate_id"]) if ozon_record else []
    bound_pairs = {(str(x.get("product_id") or ""), str(x.get("sku") or "")): x
                   for x in ozon_bindings}
    for target in ozon_targets:
        row = bound_pairs.get((target["live_product_id"], target["live_sku"]))
        target["existing_ozon_binding"] = ({
            "product_status_code": row.get("product_status_code"),
            "sku": str(row.get("sku") or ""),
            "product_id": str(row.get("product_id") or ""),
        } if row else None)

    wb_targets = []
    for target in ozon_targets:
        offer = target["offer_id"]
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            wb_targets.append({"offer_id": offer, "card_count": len(cards),
                               "safe_identity": False, "problem": "missing_or_duplicate_exact_wb_card"})
            continue
        card = cards[0]
        docs = copy_documents(card)
        same = [x for x in docs if norm_number(x.get("number") or "") == norm_number(NUMBER)]
        exact_doc = (len(same) == 1 and int(same[0].get("type") or 0) == 2
                     and str(same[0].get("startDate", ""))[:10] == ISSUE
                     and str(same[0].get("endDate", ""))[:10] == EXPIRY)
        codes = card_tnved(card)
        brand = str(card.get("brand") or "").strip()
        wb_targets.append({
            "offer_id": offer,
            "expected_nmID": target["expected_wb_nmID"],
            "nmID": str(card.get("nmID") or ""),
            "title": card.get("title"),
            "brand": brand,
            "tnved_codes": codes,
            "same_number_rows": same,
            "already_exact": exact_doc,
            "identity_matches": str(card.get("vendorCode") or "") == offer
                                and brand.casefold() in ALLOWED_BRANDS
                                and (not target["expected_wb_nmID"] or str(card.get("nmID") or "") == target["expected_wb_nmID"]),
            "tnved_matches_fsa_or_blank": not codes or set(codes) <= FSA_TNVED,
            "full_card": card,
        })

    output = {
        "checked_at_utc": now(),
        "read_only": True,
        "number": NUMBER,
        "official_fsa": {
            "record_id": FSA_ID,
            "status": "active",
            "issue_date": ISSUE,
            "expiry_date": EXPIRY,
            "applicant": "ООО СИЛА СВЕТА",
            "product_scope": "Stationary outdoor LED luminaires; Feron and SAFFIT, series SP, DH, SSL, SPL, SAL",
            "tnved": sorted(FSA_TNVED),
            "sample_date_wording": "Declaration states product must be manufactured from the selected sample date; the public testing panel shows protocol dates but no sample manufacture date",
            "url": f"https://pub.fsa.gov.ru/rds/declaration/view/{FSA_ID}/product",
            "source_of_current_status": "Official FSA search result and product tab read live during this preflight",
        },
        "source_pdf": str(SOURCE),
        "source_pdf_sha256": digest(SOURCE),
        "assigned_targets": targets,
        "ozon_record_matches": exact,
        "ozon_record_status": ozon_record.get("status_code") if ozon_record else None,
        "ozon_binding_rows": len(ozon_bindings),
        "ozon_targets": ozon_targets,
        "wb_targets": wb_targets,
        "no_mutation_attempted": True,
        "local_file_deleted": False,
        "fsa_tnved_assignment_check": all(x["tnved_matches_fsa"] for x in ozon_targets),
        "ozon_target_identity_check": all(x["product_id_matches"] and x["sku_matches"]
                                           and x["live_archived"] is False
                                           and x["brand_matches_fsa"] and x["tnved_matches_fsa"]
                                           for x in ozon_targets),
        "wb_exact_card_count": sum(x.get("identity_matches") is True for x in wb_targets),
        "wb_exact_document_count": sum(x.get("already_exact") is True for x in wb_targets),
    }
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(OUT)
    summary = {k: v for k, v in output.items()
               if k not in {"assigned_targets", "ozon_targets", "wb_targets", "ozon_record_matches"}}
    summary["ozon_targets"] = [{k: x.get(k) for k in ("offer_id", "live_product_id", "live_sku", "live_name",
                                                        "brand_values", "tnved_codes", "series_mentions_in_name",
                                                        "product_id_matches", "sku_matches", "brand_matches_fsa",
                                                        "tnved_matches_fsa", "existing_ozon_binding")}
                                for x in ozon_targets]
    summary["wb_targets"] = [{k: x.get(k) for k in ("offer_id", "nmID", "title", "brand", "tnved_codes",
                                                      "already_exact", "identity_matches", "tnved_matches_fsa_or_blank",
                                                      "same_number_rows", "problem")}
                              for x in wb_targets]
    summary["existing_ozon_binding_statuses"] = dict(Counter(
        str((x.get("existing_ozon_binding") or {}).get("product_status_code") or "missing")
        for x in ozon_targets))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
