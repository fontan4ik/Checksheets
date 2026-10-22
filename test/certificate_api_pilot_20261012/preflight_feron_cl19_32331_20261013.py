"""Read-only exact-card preflight for Feron CL19 offer 32331-1."""
from __future__ import annotations
import collections, json
from api_client import Client, now, save

OFFER="32331-1"
NUMBER="ЕАЭС KG 417/043.CN.02.08484"
WB_TNVED_ID="15000001"

def norm(value):
    table=str.maketrans({"А":"A","В":"B","Е":"E","К":"K","М":"H","Н":"H","О":"O","Р":"P","С":"C","Т":"T","У":"Y","Х":"X","Ё":"E","Э":"E","Д":"D","П":"P"})
    return "".join(ch for ch in str(value or "").upper().translate(table) if ch.isalnum())

def main():
    c=Client()
    body=c.call("ozon","/v3/product/info/list",{"offer_id":[OFFER]})
    rows=body.get("items") or body.get("result",{}).get("items")
    if not isinstance(rows,list) or len(rows)!=1 or str(rows[0].get("offer_id") or "")!=OFFER: raise RuntimeError("Ozon offer missing/ambiguous")
    base=rows[0]; pid=str(base.get("id") or base.get("product_id") or "")
    detailbody=c.call("ozon","/v3/product/info/list",{"product_id":[int(pid)]})
    details=detailbody.get("items") or detailbody.get("result",{}).get("items")
    if not isinstance(details,list) or len(details)!=1 or str(details[0].get("offer_id") or "")!=OFFER: raise RuntimeError("Ozon exact detail missing")
    detail=details[0]
    attrsbody=c.call("ozon","/v4/product/info/attributes",{"filter":{"offer_id":[OFFER]},"limit":1})
    attrrows=attrsbody.get("result") or attrsbody.get("items")
    if not isinstance(attrrows,list) or len(attrrows)!=1: raise RuntimeError("Ozon attributes missing")
    attrs={str(x.get("id")):x for x in attrrows[0].get("attributes") or []}
    brands=[str(x.get("value") or "") for x in (attrs.get("85") or {}).get("values") or []]
    tnved=[str(x.get("value") or "") for x in (attrs.get("22232") or {}).get("values") or []]
    listing=c.call("ozon","/v3/product/list",{"filter":{"product_id":[pid],"visibility":"ALL"},"limit":1000,"last_id":""}).get("result",{})
    listed=listing.get("items") or []
    if len(listed)!=1 or str(listed[0].get("offer_id") or "")!=OFFER: raise RuntimeError("Ozon live listing identity mismatch")
    sku=str(detail.get("sku") or base.get("sku") or listed[0].get("sku") or "")
    wb=[]
    for card in c.wb_cards(OFFER):
        if str(card.get("vendorCode") or "")!=OFFER: continue
        vals=[str(v) for a in card.get("characteristics") or [] if str(a.get("id"))==WB_TNVED_ID for v in (a.get("value") or [])]
        docs=card.get("documents") or card.get("docs") or {}
        wb.append({"nmID":str(card.get("nmID") or ""),"vendorCode":str(card.get("vendorCode") or ""),"brand":card.get("brand"),
            "title":card.get("title"),"tnved_values":vals,"excludeDocuments":docs.get("excludeDocuments"),"overallVerdict":docs.get("overallVerdict"),
            "documents":[{"type":d.get("type"),"number":d.get("number"),"startDate":d.get("startDate"),"endDate":d.get("endDate"),"verdict":d.get("verdict")} for d in docs.get("items") or []]})
    certs=[]
    for page in range(1,101):
        result=c.call("ozon","/v1/product/certificate/list",{"page":page,"page_size":100}).get("result",{})
        batch=result.get("certificates")
        if not isinstance(batch,list): raise RuntimeError("Ozon certificate list malformed")
        certs.extend(batch)
        if len(batch)<100: break
    else: raise RuntimeError("Ozon certificate page limit reached")
    matching=[]
    for cert in [x for x in certs if norm(x.get("certificate_number"))==norm(NUMBER)]:
        bindings=c.ozon_bindings(cert["certificate_id"])
        target=[x for x in bindings if str(x.get("product_id") or "")==pid and str(x.get("sku") or "")==sku]
        matching.append({"certificate_id":str(cert.get("certificate_id")),"number":cert.get("certificate_number"),"type_code":cert.get("type_code"),
            "status_code":cert.get("status_code"),"issue_date":cert.get("issue_date"),"expire_date":cert.get("expire_date"),
            "binding_count":len(bindings),"binding_status_counts":dict(collections.Counter(str(x.get("product_status_code") or "") for x in bindings)),
            "exact_target_binding_count":len(target),"target_statuses":[x.get("product_status_code") for x in target]})
    state={"checked_at_utc":now(),"read_only":True,"offer_id":OFFER,"ozon":{"product_id":pid,"sku":sku,"sku_usable":sku not in {"","0"},
        "name":base.get("name"),"is_archived":detail.get("is_archived"),"statuses":detail.get("statuses"),"errors":detail.get("errors"),
        "brand_values":brands,"tnved_values":tnved,"ozon_record_matches":matching},"wb":{"exact_cards":wb,"exact_card_count":len(wb)}}
    save("feron_cl19_32331_live_preflight_20261013.json",state)
    print(json.dumps(state,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
