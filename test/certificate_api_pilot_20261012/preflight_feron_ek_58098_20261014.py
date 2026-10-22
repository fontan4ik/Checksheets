"""Read-only marketplace preflight for Feron EK emergency power supplies."""
from __future__ import annotations
import collections, json
from api_client import Client, now, save

OFFERS = ["41326-1", "41327-1", "48990-1", "51661-1"]
DOCS = {
    "certificate": "ЕАЭС RU C-CN.НА92.В.00951/22",
    "declaration": "ЕАЭС N RU Д-CN.PA06.В.58098/25",
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
    c = Client()
    info = c.call("ozon", "/v3/product/info/list", {"offer_id": OFFERS})
    rows = info.get("items") or info.get("result", {}).get("items")
    if not isinstance(rows, list) or len(rows) != len(OFFERS):
        raise RuntimeError("Ozon exact offer list incomplete")
    by_offer = {str(x.get("offer_id") or ""): x for x in rows}
    if set(by_offer) != set(OFFERS):
        raise RuntimeError("Ozon exact offer list ambiguous")
    pids = {o: str(by_offer[o].get("id") or by_offer[o].get("product_id") or "") for o in OFFERS}
    if "" in pids.values() or len(set(pids.values())) != len(OFFERS):
        raise RuntimeError("Ozon product identities missing or duplicated")
    details_response = c.call("ozon", "/v3/product/info/list", {"product_id": [int(x) for x in pids.values()]})
    details = details_response.get("items") or details_response.get("result", {}).get("items")
    if not isinstance(details, list) or len(details) != len(OFFERS):
        raise RuntimeError("Ozon product details incomplete")
    by_pid = {str(x.get("id") or x.get("product_id") or ""): x for x in details}
    attrs_response = c.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": OFFERS}, "limit": len(OFFERS)})
    attrs_rows = attrs_response.get("result") or attrs_response.get("items")
    if not isinstance(attrs_rows, list) or len(attrs_rows) != len(OFFERS):
        raise RuntimeError("Ozon attributes incomplete")
    attrs_by_offer = {str(x.get("offer_id") or ""): {str(a.get("id")): a for a in x.get("attributes") or []}
                      for x in attrs_rows}
    if set(attrs_by_offer) != set(OFFERS):
        raise RuntimeError("Ozon attribute identities incomplete")
    listing_response = c.call("ozon", "/v3/product/list", {
        "filter": {"product_id": list(pids.values()), "visibility": "ALL"}, "limit": 1000, "last_id": ""})
    listings = (listing_response.get("result") or {}).get("items")
    if not isinstance(listings, list):
        raise RuntimeError("Ozon listing malformed")
    listed = {str(x.get("product_id") or x.get("id") or ""): x for x in listings}
    if set(listed) != set(pids.values()) or len(listed) != len(listings):
        raise RuntimeError("Ozon listing identities incomplete or duplicated")

    targets = []
    for offer in OFFERS:
        pid = pids[offer]
        base = by_offer[offer]
        detail = by_pid[pid]
        listing = listed[pid]
        if str(detail.get("offer_id") or "") != offer or str(listing.get("offer_id") or "") != offer:
            raise RuntimeError(f"Ozon product identity mismatch for {offer}")
        attrs = attrs_by_offer[offer]
        brand = [str(v.get("value") or "") for v in (attrs.get("85") or {}).get("values") or []]
        tnved = [str(v.get("value") or "") for v in (attrs.get("22232") or {}).get("values") or []]
        sku = str(detail.get("sku") or base.get("sku") or listing.get("sku") or "")
        wb_cards = []
        for card in c.wb_cards(offer):
            if str(card.get("vendorCode") or "") != offer:
                continue
            values = [str(v) for a in card.get("characteristics") or []
                      if str(a.get("id")) == WB_TNVED_ID for v in (a.get("value") or [])]
            docs = card.get("documents") or card.get("docs") or {}
            wb_cards.append({"nmID": str(card.get("nmID") or ""), "vendorCode": str(card.get("vendorCode") or ""),
                "brand": card.get("brand"), "title": card.get("title"), "tnved_values": values,
                "tnved_codes": codes(values), "excludeDocuments": docs.get("excludeDocuments"),
                "overallVerdict": docs.get("overallVerdict"),
                "document_matches": [{"type": d.get("type"), "number": d.get("number"),
                    "startDate": d.get("startDate"), "endDate": d.get("endDate"), "verdict": d.get("verdict")}
                    for d in docs.get("items") or [] if any(norm(d.get("number")) == norm(n) for n in DOCS.values())]})
        targets.append({"offer_id": offer, "product_id": pid, "sku": sku, "sku_usable": sku not in {"", "0"},
            "name": base.get("name"), "is_archived": detail.get("is_archived"),
            "statuses": detail.get("statuses"), "errors": detail.get("errors"),
            "brand_values": brand, "tnved_values": tnved, "tnved_codes": codes(tnved), "wb_cards": wb_cards})

    certificates = []
    for page in range(1, 101):
        body = c.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})
        batch = (body.get("result") or {}).get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list malformed")
        certificates.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("Ozon certificate list page cap reached")
    state = {"checked_at_utc": now(), "read_only": True, "documents": DOCS,
             "official_scan_code": "8504409100", "production_date_condition": "Date of manufacture must be on/after the date in the product selection act; the declaration scan does not state that date.",
             "targets": targets, "ozon_matching_records": {}}
    for kind, number in DOCS.items():
        matched = []
        for cert in certificates:
            if norm(cert.get("certificate_number")) != norm(number):
                continue
            bindings = c.ozon_bindings(cert["certificate_id"])
            target_bindings = []
            for target in targets:
                hits = [b for b in bindings if str(b.get("product_id") or "") == target["product_id"]
                        and str(b.get("sku") or "") == target["sku"]]
                target_bindings.append({"offer_id": target["offer_id"], "count": len(hits),
                                        "statuses": [b.get("product_status_code") for b in hits]})
            matched.append({"certificate_id": str(cert.get("certificate_id")),
                "number": cert.get("certificate_number"), "type_code": cert.get("type_code"),
                "status_code": cert.get("status_code"), "issue_date": cert.get("issue_date"),
                "expire_date": cert.get("expire_date"), "binding_count": len(bindings),
                "binding_status_counts": dict(collections.Counter(str(b.get("product_status_code") or "") for b in bindings)),
                "target_bindings": target_bindings})
        state["ozon_matching_records"][kind] = matched
    save("feron_ek_58098_live_preflight_20261014.json", state)
    print(json.dumps({"checked_at_utc": state["checked_at_utc"],
        "targets": [{"offer_id": t["offer_id"], "product_id": t["product_id"], "sku": t["sku"],
            "name": t["name"], "brand": t["brand_values"], "tnved": t["tnved_codes"],
            "status": t["statuses"], "wb": [{"nmID": w["nmID"], "brand": w["brand"], "tnved": w["tnved_codes"],
                "documents": w["document_matches"]} for w in t["wb_cards"]]} for t in targets],
        "ozon_matching_records": state["ozon_matching_records"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
