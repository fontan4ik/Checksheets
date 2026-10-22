"""Read-only exact-card preflight for Feron AL2115 articles 48528 and 48529."""
from __future__ import annotations
import collections, json, re
from api_client import Client, now, save

OFFERS = ["48528-1", "48528-4", "48529-1", "48529-4"]
DOCS = {
    "certificate": "ЕАЭС RU C-CN.НА68.В.00065/22",
    "declaration": "ЕАЭС N RU Д-CN.РА02.В.87172/22",
}
WB_TNVED_ID = "15000001"


def norm(value):
    table = str.maketrans({"А":"A","В":"B","Е":"E","К":"K","М":"H","Н":"H","О":"O",
                           "Р":"P","С":"C","Т":"T","У":"Y","Х":"X","Ё":"E","Э":"E","Д":"D","П":"P"})
    return "".join(ch for ch in str(value or "").upper().translate(table) if ch.isalnum())


def codes(values):
    return sorted({x.split(" - ",1)[0].strip().split(" ",1)[0] for x in values if x.strip()})


def main():
    client = Client()
    info_body = client.call("ozon", "/v3/product/info/list", {"offer_id": OFFERS})
    items = info_body.get("items") or info_body.get("result",{}).get("items")
    if not isinstance(items,list) or len(items)!=len(OFFERS): raise RuntimeError("Ozon offer identity list incomplete")
    by_offer = {str(x.get("offer_id") or ""):x for x in items}
    if set(by_offer)!=set(OFFERS): raise RuntimeError("Ozon offer identity list ambiguous")
    pids = sorted({str(x.get("id") or x.get("product_id") or "") for x in items})
    if "" in pids or len(pids)!=len(OFFERS): raise RuntimeError("Ozon product IDs missing/duplicate")
    detail_body = client.call("ozon", "/v3/product/info/list", {"product_id":[int(x) for x in pids]})
    details = detail_body.get("items") or detail_body.get("result",{}).get("items")
    if not isinstance(details,list) or len(details)!=len(OFFERS): raise RuntimeError("Ozon product detail list incomplete")
    by_pid = {str(x.get("id") or x.get("product_id") or ""):x for x in details}
    list_body = client.call("ozon", "/v3/product/list", {"filter":{"product_id":pids,"visibility":"ALL"},"limit":1000,"last_id":""})
    listed = (list_body.get("result") or {}).get("items")
    if not isinstance(listed,list): raise RuntimeError("Ozon product-list response malformed")
    listed_by_pid = {str(x.get("product_id") or x.get("id") or ""):x for x in listed}
    if len(listed_by_pid)!=len(listed) or set(listed_by_pid)!=set(pids): raise RuntimeError("Ozon targeted product-list identity mismatch")

    targets=[]
    for offer in OFFERS:
        base=by_offer[offer]; pid=str(base.get("id") or base.get("product_id") or ""); detail=by_pid[pid]
        attrs_body=client.call("ozon","/v4/product/info/attributes",{"filter":{"offer_id":[offer]},"limit":1})
        attrs_rows=attrs_body.get("result") or attrs_body.get("items")
        if not isinstance(attrs_rows,list) or len(attrs_rows)!=1 or str(attrs_rows[0].get("offer_id") or "")!=offer:
            raise RuntimeError(f"Ozon attributes missing/ambiguous for {offer}")
        attrs={str(x.get("id")):x for x in attrs_rows[0].get("attributes") or []}
        brand=[str(x.get("value") or "") for x in (attrs.get("85") or {}).get("values") or []]
        tnv=[str(x.get("value") or "") for x in (attrs.get("22232") or {}).get("values") or []]
        listing=listed_by_pid[pid]
        sku=str(detail.get("sku") or base.get("sku") or listing.get("sku") or "")
        if str(detail.get("offer_id") or "")!=offer or str(listing.get("offer_id") or "")!=offer:
            raise RuntimeError(f"Ozon product/SKU identity mismatch for {offer}")
        wb_cards=[]
        for card in client.wb_cards(offer):
            if str(card.get("vendorCode") or "")!=offer: continue
            charvals=[str(v) for x in card.get("characteristics") or [] if str(x.get("id"))==WB_TNVED_ID for v in (x.get("value") or [])]
            documents=card.get("documents") or card.get("docs") or {}
            wb_cards.append({"vendorCode":str(card.get("vendorCode") or ""),"nmID":str(card.get("nmID") or ""),
                "brand":card.get("brand"),"title":card.get("title"),"tnved_values":charvals,"tnved_codes":codes(charvals),
                "excludeDocuments":documents.get("excludeDocuments"),"overallVerdict":documents.get("overallVerdict"),
                "documents":[{"type":d.get("type"),"number":d.get("number"),"startDate":d.get("startDate"),
                               "endDate":d.get("endDate"),"verdict":d.get("verdict")}
                              for d in documents.get("items") or []]})
        targets.append({"offer_id":offer,"product_id":pid,"sku":sku,"sku_usable":sku not in {"","0"},
            "name":base.get("name"),"is_archived":detail.get("is_archived"),"statuses":detail.get("statuses"),
            "errors":detail.get("errors"),"brand_values":brand,"tnved_values":tnv,"tnved_codes":codes(tnv),"wb_cards":wb_cards})

    all_certs=[]
    for page in range(1,101):
        response=client.call("ozon","/v1/product/certificate/list",{"page":page,"page_size":100})
        batch=(response.get("result") or {}).get("certificates")
        if not isinstance(batch,list): raise RuntimeError("Ozon certificate list malformed")
        all_certs.extend(batch)
        if len(batch)<100: break
    else: raise RuntimeError("Ozon certificate page cap reached")
    matched={}
    for kind,number in DOCS.items():
        rows=[]
        for cert in [x for x in all_certs if norm(x.get("certificate_number"))==norm(number)]:
            bindings=client.ozon_bindings(cert["certificate_id"])
            exact=[]
            for target in targets:
                hits=[x for x in bindings if str(x.get("product_id") or "")==target["product_id"] and str(x.get("sku") or "")==target["sku"]]
                exact.append({"offer_id":target["offer_id"],"count":len(hits),"statuses":[x.get("product_status_code") for x in hits]})
            rows.append({"certificate_id":str(cert.get("certificate_id")),"number":cert.get("certificate_number"),
                "type_code":cert.get("type_code"),"status_code":cert.get("status_code"),"issue_date":cert.get("issue_date"),
                "expire_date":cert.get("expire_date"),"binding_count":len(bindings),
                "binding_status_counts":dict(collections.Counter(str(x.get("product_status_code") or "") for x in bindings)),
                "target_bindings":exact})
        matched[kind]=rows
    state={"checked_at_utc":now(),"read_only":True,"documents":DOCS,"targets":targets,"ozon_matching_records":matched}
    save("feron_al2115_live_preflight_20261013.json",state)
    print(json.dumps({"checked_at_utc":state["checked_at_utc"],
        "targets":[{"offer_id":x["offer_id"],"product_id":x["product_id"],"sku":x["sku"],"sku_usable":x["sku_usable"],
                     "name":x["name"],"status":x["statuses"],"errors":x["errors"],"brand":x["brand_values"],
                     "tnved":x["tnved_codes"],"wb":[{"nmID":c["nmID"],"brand":c["brand"],"title":c["title"],
                           "tnved":c["tnved_codes"],"docs":[d for d in c["documents"] if any(norm(d.get("number"))==norm(n) for n in DOCS.values())]}
                            for c in x["wb_cards"]]} for x in targets],
        "ozon_matching_records":matched},ensure_ascii=False,indent=2))


if __name__=="__main__": main()
