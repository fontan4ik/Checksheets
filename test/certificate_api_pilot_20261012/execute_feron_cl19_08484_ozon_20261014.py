"""Create/bind Feron certificate 08484 only to exact live Ozon offer 32331-1, then read back."""
from __future__ import annotations
import base64, collections, hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
from api_client import BASE, Client, now, save

OFFER="32331-1"
PRODUCT_ID="4629050746"
SKU="4342668207"
NUMBER="ЕАЭС KG 417/043.CN.02.08484"
REGISTRY="https://swis.trade.kg/Doc/1668deef-c92e-4cf0-b6f4-d9d47942314b"
ISSUE="2025-03-21"
EXPIRY="2030-03-20"
SOURCE=Path("/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron/По_артикулам/32331-1/01_Сертификат.jpg")
UPLOAD=BASE/"feron_cl19_32331_upload/feron_certificate_08484_original_scan.pdf"
SOURCE_SHA="2b38844a910866f6321208a5be14c45ccff624e82d7022881bce074fbbbce1ee"
UPLOAD_SHA="3743351b855971d49619e53e51a77acf0c28bc2202843cbd03593228aeab9714"
OUT="feron_cl19_08484_ozon_execution_20261014.json"
WB_TNVED_ID="15000001"

def norm(value):
    table=str.maketrans({"А":"A","В":"B","Е":"E","К":"K","М":"H","Н":"H","О":"O","Р":"P","С":"C","Т":"T","У":"Y","Х":"X","Ё":"E","Э":"E","Д":"D","П":"P"})
    return "".join(ch for ch in str(value or "").upper().translate(table) if ch.isalnum())

def listing_certs(client):
    out=[]
    for page in range(1,101):
        result=client.call("ozon","/v1/product/certificate/list",{"page":page,"page_size":100}).get("result",{})
        rows=result.get("certificates")
        if not isinstance(rows,list): raise RuntimeError("Ozon certificate list malformed")
        out.extend(rows)
        if len(rows)<100: return out
    raise RuntimeError("Ozon certificate list exceeded page limit")

def get_target(client):
    body=client.call("ozon","/v3/product/info/list",{"offer_id":[OFFER]})
    rows=body.get("items") or body.get("result",{}).get("items")
    if not isinstance(rows,list) or len(rows)!=1 or str(rows[0].get("offer_id") or "")!=OFFER: raise RuntimeError("Ozon target offer missing/ambiguous")
    base=rows[0]
    if str(base.get("id") or base.get("product_id") or "")!=PRODUCT_ID: raise RuntimeError("Ozon Product ID changed")
    detail_body=client.call("ozon","/v3/product/info/list",{"product_id":[int(PRODUCT_ID)]})
    details=detail_body.get("items") or detail_body.get("result",{}).get("items")
    if not isinstance(details,list) or len(details)!=1: raise RuntimeError("Ozon product details missing")
    detail=details[0]
    if str(detail.get("offer_id") or "")!=OFFER or str(detail.get("sku") or "")!=SKU: raise RuntimeError("Ozon exact Product ID/SKU mismatch")
    if detail.get("is_archived") is not False: raise RuntimeError("Ozon target is archived or archive status unknown")
    attrs_body=client.call("ozon","/v4/product/info/attributes",{"filter":{"offer_id":[OFFER]},"limit":1})
    attrs_rows=attrs_body.get("result") or attrs_body.get("items")
    if not isinstance(attrs_rows,list) or len(attrs_rows)!=1: raise RuntimeError("Ozon attributes missing")
    attrs={str(x.get("id")):x for x in attrs_rows[0].get("attributes") or []}
    brand=[str(x.get("value") or "") for x in (attrs.get("85") or {}).get("values") or []]
    tnved=[str(x.get("value") or "") for x in (attrs.get("22232") or {}).get("values") or []]
    if brand!=["Feron"] or not any(x.split(" - ",1)[0].strip()=="9405310000" for x in tnved):
        raise RuntimeError(f"Ozon target brand/TNVED changed: {brand!r} / {tnved!r}")
    return {"offer_id":OFFER,"product_id":PRODUCT_ID,"sku":SKU,"name":detail.get("name"),"brand":brand,"tnved_values":tnved,
            "is_archived":detail.get("is_archived"),"statuses":detail.get("statuses")}

def get_wb_target(client):
    cards=[x for x in client.wb_cards(OFFER) if str(x.get("vendorCode") or "")==OFFER]
    if len(cards)!=1: raise RuntimeError(f"WB exact target card count changed: {len(cards)}")
    card=cards[0]
    docs=card.get("documents") or card.get("docs") or {}
    exact=[d for d in docs.get("items") or [] if norm(d.get("number"))==norm(NUMBER) and int(d.get("type") or 0)==1]
    if len(exact)!=1: raise RuntimeError("WB exact certificate row is missing/ambiguous")
    verdict=exact[0].get("verdict") or {}
    if not (verdict.get("verified") is True and verdict.get("status")==1 and verdict.get("reason")=="valid"):
        raise RuntimeError("WB exact certificate row is not currently valid")
    if docs.get("excludeDocuments") is not False: raise RuntimeError("WB excludeDocuments changed")
    return {"nmID":str(card.get("nmID") or ""),"vendorCode":OFFER,"brand":card.get("brand"),"title":card.get("title"),
            "excludeDocuments":docs.get("excludeDocuments"),"document":exact[0],"overallVerdict":docs.get("overallVerdict")}

def exact_matches(certs):
    return [x for x in certs if norm(x.get("certificate_number"))==norm(NUMBER)]

def main():
    if not SOURCE.is_file() or not UPLOAD.is_file(): raise RuntimeError("Source or prepared PDF is missing")
    source_sha=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    upload_sha=hashlib.sha256(UPLOAD.read_bytes()).hexdigest()
    if source_sha!=SOURCE_SHA or upload_sha!=UPLOAD_SHA: raise RuntimeError("Source/PDF SHA-256 changed")
    file_bytes=UPLOAD.read_bytes()
    client=Client()
    target=get_target(client)
    wb_before=get_wb_target(client)
    certs_before=listing_certs(client)
    existing=exact_matches(certs_before)
    if existing: raise RuntimeError("Exact Ozon certificate record already exists; reconcile instead of creating a duplicate")
    params={
        "name":"Сертификат соответствия № "+NUMBER,
        "certificate_type":"CERTIFICATE_OF_CONFORMITY",
        "certificate_country":"RU",
        "accordance_type":"EAEU",
        "number":NUMBER,
        "issue_date":ISSUE+"T00:00:00Z",
        "expired_date":{"date":{"day":20,"month":3,"year":2030}},
        "skus":[SKU],
        "product_type":"UNKNOWN",
        "files":[{"file_content":base64.b64encode(file_bytes).decode("ascii"),"name":UPLOAD.name}],
        "link_to_registry":REGISTRY,
    }
    request={"params":params}
    request_size=len(json.dumps(request,ensure_ascii=False,separators=(",",":")).encode())
    if request_size>15_000_000: raise RuntimeError("Ozon request size exceeds the proven safety cap")
    pre={"started_at_utc":now(),"read_only_preflight":{"ozon_target":target,"wb_target":wb_before,
        "exact_existing_record_count":0,"source_sha256":source_sha,"uploaded_pdf_sha256":upload_sha,
        "uploaded_pdf_bytes":len(file_bytes),"request_json_bytes":request_size,"registry_url":REGISTRY}}
    save(OUT,pre)
    response=client.call("ozon","/v2/product/certificate/create",request,mutation=True)
    state={**pre,"mutation_response":response,"mutation_finished_at_utc":now()}
    save(OUT,state)
    cert_id=response.get("certificate_id")
    if not cert_id or response.get("status")!="COMPLETED" or any(x.get("state")=="INVALID" for x in response.get("params") or []):
        raise RuntimeError("Ozon create did not return a complete valid result; do not retry, reconcile live state")
    record_result=client.call("ozon","/v1/product/certificate/info",{"certificate_number":NUMBER}).get("result")
    if not isinstance(record_result,dict): raise RuntimeError("Ozon create record cannot be read back")
    cert_id_live=str(record_result.get("certificate_id") or "")
    bindings=client.ozon_bindings(int(cert_id_live))
    exact_bindings=[x for x in bindings if str(x.get("product_id") or "")==PRODUCT_ID and str(x.get("sku") or "")==SKU]
    wb_after=get_wb_target(client)
    final={"certificate_id":cert_id_live,"ozon_record":record_result,"ozon_binding_count":len(bindings),
        "ozon_binding_status_counts":dict(collections.Counter(str(x.get("product_status_code") or "") for x in bindings)),
        "exact_ozon_binding_count":len(exact_bindings),"exact_ozon_binding_statuses":[x.get("product_status_code") for x in exact_bindings],
        "wb_target_after":wb_after,"ozon_record_approved":record_result.get("status_code")=="approved",
        "ozon_exact_binding_approved":len(exact_bindings)==1 and exact_bindings[0].get("product_status_code")=="approved",
        "wb_exact_row_valid":bool((wb_after.get("document") or {}).get("verdict",{}).get("verified") is True
                                   and (wb_after.get("document") or {}).get("verdict",{}).get("status")==1
                                   and (wb_after.get("document") or {}).get("verdict",{}).get("reason")=="valid"),
        "read_back_at_utc":now()}
    state["readback"]=final
    state["finished_at_utc"]=now()
    save(OUT,state)
    print(json.dumps({"artifact":str(BASE/OUT),"readback":final},ensure_ascii=False,indent=2))

if __name__=="__main__": main()
