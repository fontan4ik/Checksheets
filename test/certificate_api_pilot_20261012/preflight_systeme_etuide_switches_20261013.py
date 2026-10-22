"""Read-only live audit of Systeme Electric / Schneider Etude offer documents."""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

from api_client import BASE, Client, now, save

OFFERS = ["BA10-001B-1", "BA10-001B-2", "BA10-001B-5",
          "PA16-007B-1", "PA16-007B-2", "PA16-007B-5"]
NUMBERS = {
    "ЕАЭС RU C-RU.АТ21.В.00153/25": "5448305",
    "ЕАЭС N RU Д-RU.РА01.В.69737/25": "5448307",
    "ЕАЭС RU C-RU.АТ21.В.00159/25": "5448308",
    "ЕАЭС N RU Д-RU.РА01.В.70012/25": "5448309",
}


def norm(value: object) -> str:
    table = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "H",
                           "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
                           "У": "Y", "Х": "X", "Ё": "E", "Э": "E", "Д": "D", "П": "P"})
    return "".join(ch for ch in str(value or "").upper().translate(table) if ch.isalnum())


def list_certs(client: Client) -> list[dict]:
    out = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        rows = result.get("certificates")
        if not isinstance(rows, list):
            raise RuntimeError("Malformed Ozon certificate listing")
        out.extend(rows)
        if len(rows) < 100:
            if len({str(x.get("certificate_id")) for x in out}) != len(out):
                raise RuntimeError("Duplicate Ozon certificate IDs")
            return out
    raise RuntimeError("Ozon certificate pagination limit exceeded")


def get_bindings(client: Client, cert_id: str) -> list[dict]:
    out = []
    last = 0
    expected = None
    seen = set()
    while True:
        result = client.call("ozon", "/v1/product/certificate/products/list",
                             {"certificate_id": int(cert_id), "last_id": last, "limit": 1000}).get("result") or {}
        rows, count = result.get("items"), result.get("count")
        if not isinstance(rows, list) or not isinstance(count, int):
            raise RuntimeError(f"Malformed Ozon bindings for {cert_id}")
        expected = count if expected is None else expected
        if expected != count:
            raise RuntimeError("Ozon binding count changed while reading")
        for row in rows:
            pid = str(row.get("product_id") or "")
            if not pid or pid in seen:
                raise RuntimeError("Missing or duplicate product_id in bindings")
            seen.add(pid)
        out.extend(rows)
        if len(out) == expected:
            return out
        if not rows or len(out) > expected:
            raise RuntimeError("Incomplete Ozon binding pagination")
        last = int(rows[-1]["product_id"])


def main() -> None:
    client = Client()
    product_rows = client.call("ozon", "/v3/product/info/list", {"offer_id": OFFERS})
    products = product_rows.get("items") or product_rows.get("result", {}).get("items")
    if not isinstance(products, list) or len(products) != len(OFFERS):
        raise RuntimeError("Fresh Ozon product read is incomplete")
    by_offer = {str(x.get("offer_id") or ""): x for x in products}
    if set(by_offer) != set(OFFERS):
        raise RuntimeError("Ozon offer identity mismatch")

    attr_resp = client.call("ozon", "/v4/product/info/attributes",
                            {"filter": {"offer_id": OFFERS}, "limit": len(OFFERS)})
    attrs = attr_resp.get("result") or attr_resp.get("items")
    if not isinstance(attrs, list) or len(attrs) != len(OFFERS):
        raise RuntimeError("Fresh Ozon attribute read is incomplete")
    by_attr = {str(x.get("offer_id") or ""): x for x in attrs}
    if set(by_attr) != set(OFFERS):
        raise RuntimeError("Ozon attribute identity mismatch")

    certs = list_certs(client)
    by_num: dict[str, list[dict]] = collections.defaultdict(list)
    for record in certs:
        by_num[norm(record.get("certificate_number"))].append(record)
    cert_data = {}
    targets = []
    for number, expected_id in NUMBERS.items():
        records = by_num.get(norm(number), [])
        if not records:
            cert_data[number] = {"record_present": False}
            continue
        record_data = []
        for record in records:
            cid = str(record.get("certificate_id") or "")
            bindings = get_bindings(client, cid)
            record_data.append({
                "certificate_id": cid, "expected_snapshot_id": expected_id,
                "id_matches_previous_snapshot": cid == expected_id,
                "status": record.get("status"), "certificate_type": record.get("certificate_type"),
                "record": {k: v for k, v in record.items() if k not in {"certificate_file", "file_content"}},
                "bindings_count": len(bindings),
                "binding_status_counts": dict(collections.Counter(str(b.get("status")) for b in bindings)),
                "target_bindings": [b for b in bindings if str(b.get("product_id")) in
                                    {str(p.get("id") or "") for p in products}],
            })
        cert_data[number] = {"record_present": True, "matching_records": record_data}

    wb_targets = []
    for offer in OFFERS:
        p = by_offer[offer]
        row = by_attr[offer]
        attr_map = {str(x.get("id")): x for x in row.get("attributes") or []}
        brand = [str(v.get("value") or "") for v in (attr_map.get("85") or {}).get("values") or []]
        codes_raw = [str(v.get("value") or "") for v in (attr_map.get("22232") or {}).get("values") or []]
        codes = sorted({x.split(" - ", 1)[0].strip() for x in codes_raw if x.strip()})
        cards = client.wb_cards(offer)
        parsed_cards = []
        for c in cards:
            docs = c.get("documents") or c.get("docs") or {}
            parsed_cards.append({
                "vendorCode": c.get("vendorCode"), "nmID": c.get("nmID"), "brand": c.get("brand"),
                "documents": docs,
                "tnved_characteristics": [ch for ch in (c.get("characteristics") or [])
                                            if str(ch.get("id")) in {"15000001", "15001136"}],
            })
        target = {"offer_id": offer, "product_id": str(p.get("id") or ""),
                  "sku": str(p.get("sku") or ""), "name": p.get("name"),
                  "is_archived": p.get("is_archived"), "brand_values": brand,
                  "tnved_values": codes_raw, "tnved_codes": codes,
                  "wb_cards": parsed_cards}
        targets.append(target)
        wb_targets.append(target)

    ozon_target_links = []
    for number, data in cert_data.items():
        for record in data.get("matching_records") or []:
            for b in record.get("target_bindings") or []:
                ozon_target_links.append({"number": number, "certificate_id": record.get("certificate_id"),
                                          "product_id": str(b.get("product_id")), "status": b.get("status"),
                                          "sku": str(b.get("sku") or "")})

    state = {"checked_at_utc": now(), "read_only": True, "complete": True,
             "offer_ids": OFFERS, "certificate_records": cert_data, "targets": targets,
             "ozon_target_bindings_by_offer": {
                 offer: [x for x in ozon_target_links if x["product_id"] == str(by_offer[offer].get("id"))]
                 for offer in OFFERS},
             "checks": {"all_six_products_exact": len(targets) == 6,
                        "all_six_archived_false": all(t["is_archived"] is False for t in targets),
                        "all_six_wb_exact_card": all(len(t["wb_cards"]) == 1 and
                            t["wb_cards"][0]["vendorCode"] == t["offer_id"] for t in targets),
                        "all_six_have_tnved": all(bool(t["tnved_codes"]) for t in targets)}}
    save("systeme_etuide_live_preflight_20261013.json", state)
    print(json.dumps({"artifact": str(BASE / "systeme_etuide_live_preflight_20261013.json"),
        "checked_at_utc": state["checked_at_utc"], "checks": state["checks"],
        "certificates": {n: d.get("matching_records", []) for n, d in cert_data.items()},
        "targets": [{k: t[k] for k in ("offer_id", "product_id", "sku", "is_archived", "brand_values", "tnved_codes")}
                    | {"wb_cards": [{k: c.get(k) for k in ("vendorCode", "nmID", "brand")} for c in t["wb_cards"]]}
                    for t in targets]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
