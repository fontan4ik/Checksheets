"""Fresh read-only preflight for IEK declaration 54504/26."""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import copy_documents, norm_number  # noqa: E402

MANIFEST = HERE / "expanded_found_certificates_manifest_20261020.json"
OUT = HERE / "iek_54504_preflight_live_20261021.json"
NUMBER = "RU Д-RU.РА08.В.54504/26"
ISSUE = "2026-09-18"
EXPIRY = "2031-09-17"
FSA_ID = 21675817
ALLOWED_TNVED = {"9403700008"}
ALLOWED_BRANDS = {"IEK", "Generica"}
SOURCE_SHA256 = "595039f65fa2f7939567e3d92f4f79469ef0660073601d4ec85b61540667dcb3"


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
        values = raw if isinstance(raw, list) else [raw]
        out.extend(str(v or "").split(" - ", 1)[0].strip() for v in values if v)
    return sorted(set(out))


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
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    group = next(x for x in manifest["groups"] if norm_number(x["number"]) == norm_number(NUMBER))
    source = pathlib.Path(group["upload_file"]["path"])
    if not source.is_file() or digest(source) != SOURCE_SHA256:
        raise RuntimeError("source_missing_or_hash_changed")
    targets = group.get("targets") or []
    offers = [str(x["offer_id"]) for x in targets]
    if len(targets) != 76 or len(set(offers)) != 76:
        raise RuntimeError("manifest_target_count_or_uniqueness_mismatch")

    client = Client()
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items")
    attrs = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": offers}, "limit": len(offers)
    }).get("result")
    if not isinstance(products, list) or not isinstance(attrs, list):
        raise RuntimeError("ozon_product_or_attribute_read_incomplete")
    pmap = {str(x.get("offer_id") or ""): x for x in products}
    amap = {str(x.get("offer_id") or ""): x for x in attrs}
    if len(pmap) != 76 or len(amap) != 76 or set(pmap) != set(offers) or set(amap) != set(offers):
        raise RuntimeError("ozon_live_offer_set_mismatch")

    ozon_targets = []
    for target in targets:
        offer = str(target["offer_id"])
        p, a = pmap[offer], amap[offer]
        brand = attr_values(a, 85)
        raw_tnved = attr_values(a, 22232)
        codes = tnved(raw_tnved)
        row = {**target, "live_product_id": str(p.get("product_id") or p.get("id") or ""),
               "live_sku": str(p.get("sku") or ""), "live_archived": p.get("is_archived"),
               "live_name": str(p.get("name") or ""), "brand_values": brand,
               "tnved_values": raw_tnved, "tnved_codes": codes,
               "product_id_matches": str(p.get("product_id") or p.get("id") or "") == str(target["product_id"]),
               "sku_matches": str(p.get("sku") or "") == str(target["sku"]),
               "brand_matches": len(brand) == 1 and brand[0] in ALLOWED_BRANDS,
               "tnved_matches_fsa": bool(codes and set(codes) <= ALLOWED_TNVED)}
        ozon_targets.append(row)

    certs = ozon_certificates(client)
    matching = [x for x in certs if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    lookup_raw = json.dumps({"certificate_number": NUMBER}, ensure_ascii=False,
                            separators=(",", ":")).encode()
    lookup_response = client.http.post("https://api-seller.ozon.ru/v1/product/certificate/info",
                                       data=lookup_raw, headers=client.ozon_headers, timeout=(15, 60))
    try:
        lookup_body = lookup_response.json()
    except ValueError:
        lookup_body = {}
    exact_absent = (lookup_response.status_code == 404 and isinstance(lookup_body, dict)
                    and lookup_body.get("code") == 5
                    and norm_number(NUMBER) in norm_number(lookup_body.get("message")))
    ozon_info = lookup_body.get("result") if lookup_response.status_code == 200 else None
    if matching:
        # A list match is authoritative even if the legacy info endpoint is transient.
        ozon_info = matching[0]

    wb_targets = []
    for target in ozon_targets:
        offer = str(target["offer_id"])
        cards = [c for c in client.wb_cards(offer) if str(c.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            wb_targets.append({"offer_id": offer, "card_count": len(cards),
                               "safe_identity": False, "problem": "missing_or_duplicate_exact_wb_card"})
            continue
        card = cards[0]
        code = card_tnved(card)
        docs = copy_documents(card)
        same = [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = (len(same) == 1 and int(same[0].get("type") or 0) == 2
                 and str(same[0].get("startDate", ""))[:10] == ISSUE
                 and str(same[0].get("endDate", ""))[:10] == EXPIRY)
        identity = (str(card.get("vendorCode") or "") == offer
                    and str(card.get("brand") or "").strip().casefold() == "iek")
        code_ok = (not code or set(code) <= ALLOWED_TNVED)
        wb_targets.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                           "title": card.get("title"), "brand": card.get("brand"),
                           "tnved_codes": code, "identity_matches": identity,
                           "tnved_matches_fsa_or_blank": code_ok,
                           "same_number_rows": same, "already_exact": exact,
                           "safe_for_update": identity and code_ok and not same,
                           "full_card": card})

    output = {
        "checked_at_utc": now(), "read_only": True, "number": NUMBER,
        "official_fsa": {"record_id": FSA_ID, "status": "active", "issue_date": ISSUE,
                         "expiry_date": EXPIRY, "scheme": "1д", "release": "serial production",
                         "product_scope": "IEK/GENERICA plastic electrical enclosures; exact appended type/model list",
                         "brands": sorted(ALLOWED_BRANDS), "tnved": sorted(ALLOWED_TNVED),
                         "sample_manufacture_date": "2026-05",
                         "sample_date_wording": "FSA product tab records the tested sample manufacture date; no separate 'applies since' clause was displayed",
                         "url": f"https://pub.fsa.gov.ru/rds/declaration/view/{FSA_ID}/product"},
        "source_pdf": str(source), "source_pdf_sha256": digest(source),
        "assigned_target_count": len(targets), "ozon_target_count": len(ozon_targets),
        "ozon_targets": ozon_targets, "ozon_exact_record_matches": matching,
        "ozon_exact_lookup_http_status": lookup_response.status_code,
        "ozon_exact_lookup_absence_confirmed": exact_absent, "ozon_live_info": ozon_info,
        "wb_targets": wb_targets,
        "ozon_preflight_safe": all(x["product_id_matches"] and x["sku_matches"] and x["brand_matches"]
                                    and x["live_archived"] is False and x["tnved_matches_fsa"]
                                    for x in ozon_targets),
        "wb_safe_update_count": sum(x.get("safe_for_update") is True for x in wb_targets),
        "wb_already_exact_count": sum(x.get("already_exact") is True for x in wb_targets),
        "wb_problem_count": sum(x.get("safe_for_update") is not True and x.get("already_exact") is not True
                                 for x in wb_targets),
        "ozon_brand_counts": {brand: sum(x["brand_values"] == [brand] for x in ozon_targets)
                              for brand in sorted(ALLOWED_BRANDS)},
        "no_mutation_attempted": True, "local_file_deleted": False,
    }
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(OUT)
    print(json.dumps({k: v for k, v in output.items()
                      if k not in {"ozon_targets", "wb_targets", "ozon_exact_record_matches", "ozon_live_info"}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
