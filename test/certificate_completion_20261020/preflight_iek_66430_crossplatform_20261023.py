"""Read-only exact-marketplace preflight for IEK declaration 66430/26."""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import copy_documents, norm_number  # noqa: E402

MANIFEST = HERE / "ready_found_documents_manifest_20261023.json"
OUT = HERE / "iek_66430_crossplatform_preflight_20261023.json"
NUMBER = "ЕАЭС N RU Д-CN.РА02.В.66430/26"
ISSUE = "2026-03-18"
EXPIRY = "2027-10-17"
FSA_ID = 21245281
SOURCE_SHA256 = "a09742c42dba8a9066f8e7ba26ad624a9b9a7a0c3901b6ca1a5285bdd1b39caf"
ALLOWED_TNVED = {"8536201007"}


def read_certificates(client: Client) -> list[dict]:
    result = []
    for page in range(1, 101):
        payload = client.call("ozon", "/v1/product/certificate/list",
                              {"page": page, "page_size": 100}).get("result") or {}
        batch = payload.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        result.extend(batch)
        if not batch or page >= int(payload.get("page_count") or 0):
            return result
    raise RuntimeError("ozon_certificate_page_limit")


def attr_values(row: dict, attr_id: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(x.get("value") or "").strip()
            for x in (attrs.get(str(attr_id)) or {}).get("values") or []
            if str(x.get("value") or "").strip()]


def tnved(values: list[str]) -> list[str]:
    return sorted({str(v).split(" - ", 1)[0].strip() for v in values if str(v).strip()})


def card_tnved(card: dict) -> list[str]:
    values = []
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        for value in raw if isinstance(raw, list) else [raw]:
            if value:
                values.append(str(value).split(" - ", 1)[0].strip())
    return sorted(set(values))


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_output_exists")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    group = next(g for g in manifest["groups"] if norm_number(g["number"]) == norm_number(NUMBER))
    if len(group.get("targets") or []) != 1:
        raise RuntimeError("manifest_target_count_changed")
    target = group["targets"][0]
    source = pathlib.Path(group["upload_file"]["path"])
    if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("source_file_missing_or_hash_changed")

    client = Client()
    offer = str(target["offer_id"])
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": [offer]}).get("items")
    attrs = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": [offer]}, "limit": 1
    }).get("result")
    if not isinstance(products, list) or len(products) != 1 or not isinstance(attrs, list) or len(attrs) != 1:
        raise RuntimeError("ozon_target_read_incomplete")
    product, attr = products[0], attrs[0]
    brand = attr_values(attr, 85)
    raw_tnved = attr_values(attr, 22232)
    codes = tnved(raw_tnved)

    certs = read_certificates(client)
    matches = [c for c in certs if norm_number(c.get("certificate_number")) == norm_number(NUMBER)]
    record_readbacks = []
    for cert in matches:
        bindings = client.ozon_bindings(cert["certificate_id"])
        record_readbacks.append({"record": cert, "bindings": bindings})

    cards = [c for c in client.wb_cards(offer) if str(c.get("vendorCode") or "") == offer]
    wb = []
    for card in cards:
        docs = copy_documents(card)
        same = [d for d in docs if norm_number(d.get("number")) == norm_number(NUMBER)]
        exact = (len(same) == 1 and int(same[0].get("type") or 0) == 2
                 and str(same[0].get("startDate", ""))[:10] == ISSUE
                 and str(same[0].get("endDate", ""))[:10] == EXPIRY)
        code = card_tnved(card)
        wb.append({"nmID": str(card.get("nmID") or ""), "brand": card.get("brand"),
                   "title": card.get("title"), "tnved_codes": code,
                   "documents_for_number": same, "already_exact": exact,
                   "safe_for_update": (str(card.get("brand") or "").strip().casefold() == "iek"
                                       and (not code or set(code) <= ALLOWED_TNVED) and not same)})

    output = {
        "checked_at_utc": now(), "read_only": True, "number": NUMBER,
        "official_fsa": {"record_id": FSA_ID, "status": "Действует", "issue_date": ISSUE,
                         "expiry_date": EXPIRY, "applicant": "ПАО ИЭК ХОЛДИНГ",
                         "product_scope": "IEK KARAT automatic residual-current circuit breakers, types АВДТ32/АВДТ34; serial production",
                         "tnved": sorted(ALLOWED_TNVED),
                         "url": f"https://pub.fsa.gov.ru/rds/declaration/view/{FSA_ID}/product"},
        "source_file": str(source), "source_file_sha256": SOURCE_SHA256,
        "assigned_target": target,
        "ozon_live": {"product": product, "brand_values": brand, "tnved_values": raw_tnved,
                      "tnved_codes": codes, "product_id_matches": str(product.get("product_id") or product.get("id") or "") == str(target["product_id"]),
                      "sku_matches": str(product.get("sku") or "") == str(target["sku"]),
                      "active": product.get("is_archived") is False,
                      "brand_matches": brand == ["IEK"],
                      "tnved_matches_fsa": bool(codes and set(codes) <= ALLOWED_TNVED),
                      "exact_record_match_count": len(matches), "records": record_readbacks},
        "wb_live": {"exact_card_count": len(cards), "cards": wb},
        "no_mutation_attempted": True, "local_file_deleted": False,
    }
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(OUT)
    print(json.dumps({"checked_at_utc": output["checked_at_utc"], "number": NUMBER,
                      "offer_id": offer, "ozon_live": output["ozon_live"], "wb_live": output["wb_live"],
                      "source_file_sha256": SOURCE_SHA256}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
