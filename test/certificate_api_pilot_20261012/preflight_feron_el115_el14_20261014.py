"""Read-only marketplace preflight for Feron EL115 (12668-1) and EL14 (12634-1)."""
from __future__ import annotations
import collections, json
from api_client import Client, now, save

OFFERS = ["12668-1", "12634-1"]
DOCS = {
    "certificate": "ЕАЭС RU C-CN.ПФ02.В.05934/22",
    "declaration": "ЕАЭС N RU Д-CN.РА06.В.53534/22",
}
WB_TNVED_ID = "15000001"


def norm(value):
    table = str.maketrans({"А":"A", "В":"B", "Е":"E", "К":"K", "М":"H", "Н":"H",
                           "О":"O", "Р":"P", "С":"C", "Т":"T", "У":"Y", "Х":"X",
                           "Ё":"E", "Э":"E", "Д":"D", "П":"P"})
    return "".join(ch for ch in str(value or "").upper().translate(table) if ch.isalnum())


def codes(values):
    return sorted({x.split(" - ", 1)[0].strip().split(" ", 1)[0] for x in values if x.strip()})


def main():
    client = Client()
    info = client.call("ozon", "/v3/product/info/list", {"offer_id": OFFERS})
    items = info.get("items") or info.get("result", {}).get("items")
    if not isinstance(items, list) or len(items) != len(OFFERS):
        raise RuntimeError("Ozon offer identity list incomplete")
    by_offer = {str(x.get("offer_id") or ""): x for x in items}
    if set(by_offer) != set(OFFERS):
        raise RuntimeError("Ozon offer identity list ambiguous")
    pids = {offer: str(by_offer[offer].get("id") or by_offer[offer].get("product_id") or "") for offer in OFFERS}
    if "" in pids.values() or len(set(pids.values())) != len(OFFERS):
        raise RuntimeError("Ozon product IDs missing or duplicated")

    detail_response = client.call("ozon", "/v3/product/info/list", {"product_id": [int(x) for x in pids.values()]})
    details = detail_response.get("items") or detail_response.get("result", {}).get("items")
    if not isinstance(details, list) or len(details) != len(OFFERS):
        raise RuntimeError("Ozon detail list incomplete")
    by_pid = {str(x.get("id") or x.get("product_id") or ""): x for x in details}

    listing_response = client.call("ozon", "/v3/product/list", {
        "filter": {"product_id": list(pids.values()), "visibility": "ALL"}, "limit": 1000, "last_id": ""})
    listings = (listing_response.get("result") or {}).get("items")
    if not isinstance(listings, list):
        raise RuntimeError("Ozon listing response malformed")
    by_listing_pid = {str(x.get("product_id") or x.get("id") or ""): x for x in listings}
    if set(by_listing_pid) != set(pids.values()) or len(by_listing_pid) != len(listings):
        raise RuntimeError("Ozon exact listing identity mismatch")

    targets = []
    for offer in OFFERS:
        base = by_offer[offer]
        pid = pids[offer]
        detail = by_pid[pid]
        attrs_response = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": [offer]}, "limit": 1})
        attrs_rows = attrs_response.get("result") or attrs_response.get("items")
        if not isinstance(attrs_rows, list) or len(attrs_rows) != 1 or str(attrs_rows[0].get("offer_id") or "") != offer:
            raise RuntimeError(f"Ozon attributes missing/ambiguous for {offer}")
        attrs = {str(a.get("id")): a for a in attrs_rows[0].get("attributes") or []}
        brand = [str(v.get("value") or "") for v in (attrs.get("85") or {}).get("values") or []]
        tnv = [str(v.get("value") or "") for v in (attrs.get("22232") or {}).get("values") or []]
        listing = by_listing_pid[pid]
        if str(detail.get("offer_id") or "") != offer or str(listing.get("offer_id") or "") != offer:
            raise RuntimeError(f"Ozon product identity mismatch for {offer}")
        sku = str(detail.get("sku") or base.get("sku") or listing.get("sku") or "")
        wb_cards = []
        for card in client.wb_cards(offer):
            if str(card.get("vendorCode") or "") != offer:
                continue
            charvals = [str(v) for a in card.get("characteristics") or []
                        if str(a.get("id")) == WB_TNVED_ID for v in (a.get("value") or [])]
            docs = card.get("documents") or card.get("docs") or {}
            wb_cards.append({
                "vendorCode": str(card.get("vendorCode") or ""), "nmID": str(card.get("nmID") or ""),
                "brand": card.get("brand"), "title": card.get("title"), "tnved_values": charvals,
                "tnved_codes": codes(charvals), "excludeDocuments": docs.get("excludeDocuments"),
                "overallVerdict": docs.get("overallVerdict"),
                "documents": [{"type": d.get("type"), "number": d.get("number"),
                               "startDate": d.get("startDate"), "endDate": d.get("endDate"),
                               "verdict": d.get("verdict")} for d in docs.get("items") or []],
            })
        targets.append({"offer_id": offer, "product_id": pid, "sku": sku,
            "sku_usable": sku not in {"", "0"}, "name": base.get("name"),
            "is_archived": detail.get("is_archived"), "statuses": detail.get("statuses"),
            "errors": detail.get("errors"), "brand_values": brand, "tnved_values": tnv,
            "tnved_codes": codes(tnv), "wb_cards": wb_cards})

    certs = []
    for page in range(1, 101):
        response = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})
        batch = (response.get("result") or {}).get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list malformed")
        certs.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("Ozon certificate list page cap reached")

    matched = {}
    for kind, number in DOCS.items():
        rows = []
        for cert in [c for c in certs if norm(c.get("certificate_number")) == norm(number)]:
            bindings = client.ozon_bindings(cert["certificate_id"])
            exact = []
            for target in targets:
                hits = [b for b in bindings if str(b.get("product_id") or "") == target["product_id"]
                        and str(b.get("sku") or "") == target["sku"]]
                exact.append({"offer_id": target["offer_id"], "count": len(hits),
                              "statuses": [b.get("product_status_code") for b in hits]})
            rows.append({"certificate_id": str(cert.get("certificate_id")),
                "number": cert.get("certificate_number"), "type_code": cert.get("type_code"),
                "status_code": cert.get("status_code"), "issue_date": cert.get("issue_date"),
                "expire_date": cert.get("expire_date"), "binding_count": len(bindings),
                "binding_status_counts": dict(collections.Counter(str(b.get("product_status_code") or "") for b in bindings)),
                "target_bindings": exact})
        matched[kind] = rows

    state = {"checked_at_utc": now(), "read_only": True, "documents": DOCS,
             "targets": targets, "ozon_matching_records": matched}
    save("feron_el115_el14_live_preflight_20261014.json", state)
    print(json.dumps({"checked_at_utc": state["checked_at_utc"],
        "targets": [{"offer_id": t["offer_id"], "product_id": t["product_id"], "sku": t["sku"],
            "sku_usable": t["sku_usable"], "name": t["name"], "status": t["statuses"],
            "errors": t["errors"], "brand": t["brand_values"], "tnved": t["tnved_codes"],
            "wb": [{"nmID": c["nmID"], "brand": c["brand"], "tnved": c["tnved_codes"],
                "docs": [d for d in c["documents"] if any(norm(d.get("number")) == norm(n) for n in DOCS.values())]}
                for c in t["wb_cards"]]} for t in targets],
        "ozon_matching_records": matched}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
