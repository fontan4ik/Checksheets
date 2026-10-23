#!/usr/bin/env python3
"""Fresh read-only preflight for Gauss declaration 48971/24."""
from __future__ import annotations
import collections,csv,hashlib,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/"test/certificate_api_pilot_20261012"))
from api_client import Client,now
from reconcile_approved_ozon_docs_to_wb import norm_number

NUMBER="ЕАЭС N RU Д-CN.РА08.В.48971/24"
ASSIGNMENT_FRAGMENT="48971/24"
FSA_ID="19381489"
SOURCE="output_to_user/certificates/group_1/documents/gauss/22073e3d9c4580581bbf9d92.pdf"
SHA="81173faa80fa3b88c9ddf83ccc980fbb2448bce7e370df17424991f19e3ab9d7"
ISSUE,EXPIRY="2024-09-18","2029-09-17"
TNVED={"8539519009"}
OUT=HERE/"gauss_48971_crossplatform_preflight_20261023.json"

def values(attrs,ident):
    d={str(x.get("id")):x for x in attrs or []}
    return [str(v.get("value") or "").strip() for v in (d.get(str(ident)) or {}).get("values") or [] if str(v.get("value") or "").strip()]
def codes(raw):
    if not isinstance(raw,list):raw=[raw]
    return sorted({str(x).split(" - ",1)[0].strip() for x in raw if str(x).strip()})
def wb_codes(card):
    out=[]
    for c in card.get("characteristics") or []:
        label="".join(str(c.get("name") or "").casefold().split()).replace("ё","е")
        if "тнвэд" in label or "тнвед" in label:
            v=c.get("value");out.extend(v if isinstance(v,list) else [v])
    return codes(out)
def records(client):
    out=[]
    for page in range(1,101):
        result=client.call("ozon","/v1/product/certificate/list",{"page":page,"page_size":100}).get("result") or {}
        batch=result.get("certificates")
        if not isinstance(batch,list):raise RuntimeError("ozon_certificate_list_invalid")
        out+=batch
        if not batch or page>=int(result.get("page_count") or 0):return out
    raise RuntimeError("ozon_certificate_page_limit")

def main():
    if OUT.exists():raise RuntimeError("preflight_artifact_exists_inspect_before_retry")
    source=ROOT/SOURCE
    digest=hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else None
    if digest!=SHA:raise RuntimeError("source_missing_or_hash_mismatch")
    with (ROOT/"output_to_user/certificates/document_assignments.csv").open(encoding="utf-8-sig",newline="") as f:
        assignments=[r for r in csv.DictReader(f) if ASSIGNMENT_FRAGMENT in str(r.get("Номер/название документа") or "")
                     and r.get("Локальный файл")==SOURCE and r.get("SHA256 фактический")==SHA]
    assignments.sort(key=lambda r:r.get("Артикул продавца") or "")
    offers=[r.get("Артикул продавца") for r in assignments]
    if len(offers)!=26 or len(set(offers))!=26:raise RuntimeError("assignment_count_or_duplicate_conflict")
    client=Client()
    products=client.call("ozon","/v3/product/info/list",{"offer_id":offers}).get("items") or []
    attrs=client.call("ozon","/v4/product/info/attributes",{"filter":{"offer_id":offers},"limit":len(offers)}).get("result") or []
    pm,am=collections.defaultdict(list),collections.defaultdict(list)
    for x in products:pm[str(x.get("offer_id") or "")].append(x)
    for x in attrs:am[str(x.get("offer_id") or "")].append(x)
    matches=[r for r in records(client) if norm_number(r.get("certificate_number"))==norm_number(NUMBER)]
    if len(matches)>1:raise RuntimeError("duplicate_ozon_records_for_document")
    record=matches[0] if matches else None
    record_exact=bool(record and record.get("type_code")=="declaration"
                      and str(record.get("issue_date") or "")[:10]==ISSUE
                      and str(record.get("expire_date") or "")[:10]==EXPIRY)
    bindings=client.ozon_bindings(int(record["certificate_id"])) if record else []
    by_product=collections.defaultdict(list)
    for b in bindings:by_product[str(b.get("product_id") or "")].append(b)
    targets=[]
    for a in assignments:
        offer=a["Артикул продавца"];conf=[]
        if len(pm[offer])!=1 or len(am[offer])!=1:
            p,attr={},{};conf.append("ozon_identity_missing_or_ambiguous")
        else:p,attr=pm[offer][0],am[offer][0]
        pid=str(p.get("product_id") or p.get("id") or "");sku=str(p.get("sku") or "")
        brand=values(attr.get("attributes"),85);otn= codes(values(attr.get("attributes"),22232))
        title=str(p.get("name") or "")
        if not pid or not sku:conf.append("ozon_identity_missing")
        if p.get("is_archived") is not False:conf.append("ozon_archived_or_unknown")
        if [x.casefold() for x in brand]!=["gauss"]:conf.append("ozon_brand_mismatch")
        if not otn or not set(otn).issubset(TNVED):conf.append("ozon_tnved_out_of_scope")
        if title.casefold()!=str(a.get("Название товара Ozon") or "").casefold():conf.append("ozon_title_changed_from_assignment")
        if record and (not record_exact or record.get("status_code") not in {"approved","under_review"}):conf.append("ozon_record_metadata_or_status_conflict")
        prior=by_product.get(pid,[])
        if prior and (len(prior)!=1 or str(prior[0].get("sku") or "")!=sku):conf.append("ozon_existing_binding_conflict")
        cards=[c for c in client.wb_cards(offer) if str(c.get("vendorCode") or "")==offer]
        card=cards[0] if len(cards)==1 else {}
        if len(cards)!=1:conf.append("wb_card_missing_or_ambiguous")
        wbrand=str(card.get("brand") or "");wtn=wb_codes(card)
        if wbrand.casefold()!="gauss":conf.append("wb_brand_mismatch")
        if not card.get("nmID"):conf.append("wb_nm_id_missing")
        if not wtn or not set(wtn).issubset(TNVED):conf.append("wb_tnved_out_of_scope")
        existing=((card.get("documents") or {}).get("items") or [])
        same=[x for x in existing if norm_number(x.get("number"))==norm_number(NUMBER)]
        exact=[x for x in same if str(x.get("type"))=="2" and str(x.get("startDate") or "")[:10]==ISSUE
               and str(x.get("endDate") or "")[:10]==EXPIRY and x.get("isEndless") is False]
        if same and len(exact)!=1:conf.append("wb_document_metadata_conflict")
        targets.append({"offer_id":offer,"ozon":{"product_id":pid,"sku":sku,"title":title,"brand":brand,"tnved":otn,
                       "existing_document_binding_count":sum(1 for b in prior if str(b.get("sku") or "")==sku)},
                       "wb":{"nmID":str(card.get("nmID") or ""),"vendorCode":str(card.get("vendorCode") or ""),
                       "title":card.get("title"),"brand":wbrand,"tnved":wtn,"same_number_count":len(same),"exact_count":len(exact)},
                       "assignment_evidence":a.get("Основание сопоставления"),"conflicts":conf,
                       "eligible_both_platforms":not conf})
    report={"checked_at_utc":now(),"read_only":True,
        "document":{"number":NUMBER,"type_code":"declaration","incorrect_assignment_type_label":"Сертификат соответствия",
                    "issue_date":ISSUE,"expiry_date":EXPIRY,"fsa_registry_id":FSA_ID,
                    "fsa_status_from_live_ui":"Действует","fsa_tnved":sorted(TNVED),
                    "fsa_scope":"Gauss LED strip series Black; exact model/article list in annex; TR EAEU 037/2016; serial production sampled 2024-05-15",
                    "sample_manufacture_date":"2024-05-15","source":SOURCE,"source_sha256":digest},
        "ozon_record":({k:record.get(k) for k in ["certificate_id","certificate_number","type_code","status_code","issue_date","expire_date"]} if record else None),
        "targets":targets,"summary":{"offers":len(targets),"eligible_both_platforms":sum(x["eligible_both_platforms"] for x in targets),
        "ozon_blockers":dict(collections.Counter(c for x in targets for c in x["conflicts"] if c.startswith("ozon_"))),
        "wb_blockers":dict(collections.Counter(c for x in targets for c in x["conflicts"] if c.startswith("wb_")))},
        "writes_performed":False,"local_files_deleted":False,
        "limitation":"The declaration applies to serial products manufactured from samples dated 2024-05-15; individual lot manufacture dates are not visible in marketplace data."}
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report["summary"],ensure_ascii=False,indent=2))
if __name__=="__main__":main()
