"""Read-only two-marketplace preflight for the Innolux fire-safety certificate."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
from pathlib import Path

from api_client import BASE, Client, now, save

ROOT = BASE.parents[1]
MANIFEST = ROOT / "output_to_user/certificates/group_4/manifest.csv"
SOURCE = ROOT / "output_to_user/certificates/group_4/docs/innolux/innolux_fire_safety_certificate.pdf"
NUMBER = "РОСС RU.32132.04СПК0.ОС001.01324"
OFFERS = ["92304-1", "92305-1", "92306-1", "92311-1"]


def norm(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    with MANIFEST.open(encoding="utf-8-sig", newline="") as f:
        assignments = [r for r in csv.DictReader(f) if r.get("Артикул") in OFFERS
                       and r.get("Doc type/number", "").endswith(NUMBER)]
    if {r.get("Артикул") for r in assignments} != set(OFFERS) or len(assignments) != 4:
        raise RuntimeError("Manifest does not contain the four exact Innolux assignments")
    if not SOURCE.is_file():
        raise RuntimeError("Official source certificate missing")

    client = Client()
    response = client.call("ozon", "/v3/product/info/list", {"offer_id": OFFERS})
    products = response.get("items") or response.get("result", {}).get("items")
    if not isinstance(products, list) or len(products) != 4:
        raise RuntimeError("Fresh Ozon product response incomplete")
    by_offer = {str(p.get("offer_id") or ""): p for p in products}
    if set(by_offer) != set(OFFERS):
        raise RuntimeError("Ozon product identities differ from exact offers")

    attr_response = client.call("ozon", "/v4/product/info/attributes",
        {"filter": {"offer_id": OFFERS}, "limit": len(OFFERS)})
    attr_rows = attr_response.get("result") or attr_response.get("items")
    if not isinstance(attr_rows, list) or len(attr_rows) != 4:
        raise RuntimeError("Fresh Ozon attributes incomplete")
    by_attr = {str(x.get("offer_id") or ""): x for x in attr_rows}
    if set(by_attr) != set(OFFERS):
        raise RuntimeError("Ozon attribute identities differ from exact offers")

    certificates = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
            {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate listing malformed")
        certificates.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("Ozon certificate listing pagination exceeded")
    exact_records = [c for c in certificates if norm(c.get("certificate_number")) == norm(NUMBER)]
    target_ids = {str(p.get("id") or "") for p in products}
    record_bindings = {}
    for record in exact_records:
        bindings = client.ozon_bindings(record["certificate_id"])
        record_bindings[str(record["certificate_id"])] = {
            "binding_count": len(bindings),
            "binding_status_counts": dict(collections.Counter(str(x.get("product_status_code") or "") for x in bindings)),
            "target_bindings": [x for x in bindings if str(x.get("product_id")) in target_ids],
        }

    targets = []
    for offer in OFFERS:
        p = by_offer[offer]
        attr_map = {str(x.get("id")): x for x in by_attr[offer].get("attributes") or []}
        brand = [v.get("value") for v in (attr_map.get("85") or {}).get("values") or []]
        tnved = [v.get("value") for v in (attr_map.get("22232") or {}).get("values") or []]
        cards = client.wb_cards(offer)
        targets.append({"offer_id": offer, "product_id": str(p.get("id") or ""),
            "sku": str(p.get("sku") or ""), "name": p.get("name"),
            "is_archived": p.get("is_archived"), "brand_values": brand,
            "tnved_values": tnved,
            "wb_cards": [{"vendorCode": c.get("vendorCode"), "nmID": c.get("nmID"),
                "brand": c.get("brand"), "documents": c.get("documents") or c.get("docs") or {}}
                for c in cards]})

    state = {"checked_at_utc": now(), "read_only": True, "complete": True,
        "official_source": {"url": "https://innolux.pro/files/fire-certificate/%D0%A1%D0%A1%20%D0%9F%D0%91%2001324.pdf",
            "path": str(SOURCE), "sha256": sha256(SOURCE), "bytes": SOURCE.stat().st_size,
            "number": NUMBER, "valid_from": "2025-10-22", "valid_to": "2030-10-21",
            "manufacturer_model_scope": "INNOLUX ДСО-02 series; local manifest maps exact four model names"},
        "ozon_certificate_list_count": len(certificates),
        "ozon_exact_records": [{k:v for k,v in x.items() if k not in {"certificate_file","file_content"}}
                               for x in exact_records],
        "ozon_record_bindings": record_bindings, "targets": targets}
    save("innolux_fire_01324_live_preflight_20261013.json", state)
    print(json.dumps({"artifact": str(BASE / "innolux_fire_01324_live_preflight_20261013.json"),
        "checked_at_utc": state["checked_at_utc"], "source_sha256": state["official_source"]["sha256"],
        "ozon_exact_record_count": len(exact_records),
        "ozon_record_bindings": record_bindings,
        "targets": [{k:t[k] for k in ("offer_id","product_id","sku","name","is_archived","brand_values","tnved_values")}
            | {"wb_cards":[{"nmID":c["nmID"],"vendorCode":c["vendorCode"],"brand":c["brand"],
                "number_matches":sum(1 for d in (c.get("documents") or {}).get("items",[])
                    if norm(d.get("number"))==norm(NUMBER)),
                "documents": (c.get("documents") or {}).get("items",[])} for c in t["wb_cards"]]}
            for t in targets]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
