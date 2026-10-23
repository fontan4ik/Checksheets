"""Safely fill exact missing Gauss 02947/22 links on Ozon and WB."""
from __future__ import annotations
import csv, datetime as dt, hashlib, json, re, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now, save, digest
from reconcile_approved_ozon_docs_to_wb import norm_number, doc_key, copy_documents, comparable_card, UPDATE_CARD_FIELDS
from run_all_found_certificates_20261014 import merge_wb

NUMBER = "RU C-CN.HB54.B.02947/22"
OZON_CERT_ID_EXPECTED = ""
ISSUE = "2022-06-08"
EXPIRY = "2027-06-07"
TNVED = "9405420012"
LOCAL = ROOT / "output_to_user/certificates/group_1/documents/gauss/06b64537525886ce56ab0e3a.pdf"
ASSIGNMENTS = HERE / "all_confirmed_source_assignments_live_reconciled_20261023.csv"
PREFLIGHT_PATH = HERE / "gauss_02947_gaps_preflight_20261023.json"
OUT_PATH = HERE / "gauss_02947_gaps_execution_readback_20261023.json"
JOURNAL_PATH = HERE / "gauss_02947_gaps_mutation_journal_20261023.jsonl"
TARGET_MODELS = {"613100150P", "613100200", "613100200P", "613100350", "613100370P", "613511150", "613511310", "613511320", "613511350", "687511370"}


def brand_key(s): return re.sub(r"[^a-z0-9]", "", str(s or "").casefold())
def tnved_from_ozon(attrs):
    amap = {str(x.get("id")): x for x in attrs.get("attributes") or []}
    vals = [str(v.get("value") or "") for v in (amap.get("22232") or {}).get("values") or []]
    return sorted({v.split(" - ", 1)[0].strip() for v in vals if v.strip()})
def wb_tnved(card):
    codes=[]
    for ch in card.get("characteristics") or []:
        name=re.sub(r"\s+", "", str(ch.get("name") or "").casefold()).replace("ё","е")
        if "тнвэд" in name or "тнвед" in name:
            values=ch.get("value") if isinstance(ch.get("value"),list) else [ch.get("value")]
            codes.extend(str(v or "").split(" - ",1)[0].strip() for v in values if str(v or "").strip())
    return sorted(set(codes))
def wb_docs(card): return ((card.get("documents") or {}).get("items") or [])
def dated_match(doc):
    return doc_key(doc)==(1,norm_number(NUMBER)) and str(doc.get("startDate") or "")[:10]==ISSUE and str(doc.get("endDate") or "")[:10]==EXPIRY

def journal(row):
    with JOURNAL_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row,ensure_ascii=False)+"\n"); f.flush()

def main():
    if PREFLIGHT_PATH.exists() or OUT_PATH.exists() or JOURNAL_PATH.exists():
        raise RuntimeError("Run artifacts already exist; reconcile them before any retry")
    if digest(LOCAL) != "c1bae8dcead5bd3086090af159f5655a2460dbaa093140bac6068a4d64788108":
        raise RuntimeError("Source PDF hash mismatch")
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as f:
        rows=[r for r in csv.DictReader(f) if r["number"]==NUMBER]
    if not rows: raise RuntimeError("No exact assignment rows")
    needs=[r for r in rows if r["ozon_state"]!="approved_link" or r["wb_state"]!="valid"]
    if len(needs)!=10: raise RuntimeError(f"Unexpected unresolved assignment count: {len(needs)}")
    if any(r["source_type_conflict"]!="False" for r in needs): raise RuntimeError("Source type conflict")
    for r in needs:
        model=r["offer_id"].rsplit("-",1)[0]
        if model not in TARGET_MODELS: raise RuntimeError(f"Target model absent from certificate annex: {r['offer_id']}")

    client=Client()
    offers=sorted({r["offer_id"] for r in needs})
    pr=client.call("ozon","/v3/product/info/list",{"offer_id":offers})
    products=pr.get("items") or pr.get("result",{}).get("items")
    ar=client.call("ozon","/v4/product/info/attributes",{"filter":{"offer_id":offers},"limit":100})
    attr_rows=ar.get("result") or ar.get("items")
    if not isinstance(products,list) or not isinstance(attr_rows,list) or len(products)!=len(offers) or len(attr_rows)!=len(offers):
        raise RuntimeError("Incomplete current Ozon target reads")
    pmap={str(x.get("offer_id")):x for x in products}; amap={str(x.get("offer_id")):x for x in attr_rows}
    if set(pmap)!=set(offers) or set(amap)!=set(offers): raise RuntimeError("Ozon offers missing/duplicated")

    certs=[]
    for page in range(1,100):
        data=client.call("ozon","/v1/product/certificate/list",{"page":page,"page_size":100}).get("result") or {}
        batch=data.get("certificates")
        if not isinstance(batch,list): raise RuntimeError("Malformed Ozon certificate page")
        certs.extend(batch)
        if len(batch)<100: break
    else: raise RuntimeError("Ozon certificate pagination bound exceeded")
    exact=[c for c in certs if norm_number(c.get("certificate_number"))==norm_number(NUMBER)]
    if len(exact)!=1: raise RuntimeError("Exact Ozon document missing or duplicated")
    cert=exact[0]
    cid=str(cert.get("certificate_id"))
    if OZON_CERT_ID_EXPECTED and cid!=OZON_CERT_ID_EXPECTED: raise RuntimeError("Ozon certificate ID changed")
    if (cert.get("status_code")!="approved" or cert.get("type_code")!="certificate_of_conformity"
        or cert.get("accordance_type_code")!="EAEU" or str(cert.get("issue_date",""))[:10]!=ISSUE
        or str(cert.get("expire_date",""))[:10]!=EXPIRY):
        raise RuntimeError("Ozon certificate is no longer exact, approved, or current")
    if not (ISSUE <= dt.datetime.now(dt.timezone.utc).date().isoformat() <= EXPIRY): raise RuntimeError("Certificate not currently date-valid")
    bindings=client.ozon_bindings(cid)
    bind_by_product={}
    for b in bindings:
        pid=str(b.get("product_id") or "")
        if pid in bind_by_product: raise RuntimeError("Duplicate product binding rows")
        bind_by_product[pid]=b

    wb_before={}; target_details=[]
    for r in needs:
        offer=r["offer_id"]; p=pmap[offer]; a=amap[offer]
        pid=str(p.get("id") or p.get("product_id") or ""); sku=str(p.get("sku") or "")
        if pid!=r["ozon_product_id"] or sku!=r["ozon_sku"] or not sku or p.get("is_archived") is not False:
            raise RuntimeError(f"Ozon identity/status changed: {offer}")
        brands=[str(v.get("value") or "") for v in (({str(x.get('id')):x for x in a.get('attributes') or []}).get('85') or {}).get('values') or []]
        oz_codes=tnved_from_ozon(a)
        if len(brands)!=1 or brand_key(brands[0])!="gauss":
            raise RuntimeError(f"Ozon brand mismatch: {offer}; {brands}")
        in_scope = oz_codes == [TNVED]
        ob=bind_by_product.get(pid)
        if ob and (str(ob.get("sku") or "")!=sku or ob.get("product_status_code")!="approved"):
            raise RuntimeError(f"Existing Ozon binding conflicts or is not approved: {offer}")
        cards=[c for c in client.wb_cards(offer) if str(c.get("vendorCode") or "")==offer]
        if len(cards)!=1 or str(cards[0].get("nmID") or "")!=r["wb_nmID"] or brand_key(cards[0].get("brand"))!="gauss":
            raise RuntimeError(f"Exact WB identity/brand changed: {offer}")
        wcodes=wb_tnved(cards[0])
        if wcodes != [TNVED]: raise RuntimeError(f"WB TNVED missing/mismatched: {offer} {wcodes}")
        matches=[d for d in wb_docs(cards[0]) if norm_number(d.get("number"))==norm_number(NUMBER)]
        if matches and (len(matches)!=1 or not dated_match(matches[0])):
            raise RuntimeError(f"WB document type/date conflict: {offer}")
        wb_before[offer]=cards[0]
        target_details.append({"offer_id":offer,"model_code":offer.rsplit("-",1)[0],"expected_product_id":r["ozon_product_id"],"live_product_id":pid,"expected_sku":r["ozon_sku"],"live_sku":sku,"ozon_brand":brands,"ozon_tnved":oz_codes,"ozon_tnved_in_scope":in_scope,"skip_reason":None if in_scope else "current_Ozon_TNVED_outside_certificate_scope","ozon_binding_before":ob,"wb_nmID":str(cards[0].get("nmID")),"wb_brand":cards[0].get("brand"),"wb_tnved":wcodes,"wb_document_before":matches})
    eligible=[x for x in target_details if x["ozon_tnved_in_scope"]]
    oz_missing=[x for x in eligible if not x["ozon_binding_before"]]
    wb_missing=[]
    doc={"type":1,"number":cert.get("certificate_number"),"startDate":ISSUE+"T00:00:00Z","endDate":EXPIRY+"T00:00:00Z","isEndless":False}
    for x in eligible:
        if not x["wb_document_before"]: wb_missing.append(x["offer_id"])
    if {x["offer_id"] for x in eligible}!={"613100150P-2","613100200P-2"} or len(oz_missing)!=2 or set(wb_missing)!={"613100150P-2","613100200P-2"}:
        raise RuntimeError(f"Unexpected in-scope targets/gaps; eligible={[x['offer_id'] for x in eligible]}, Ozon missing={len(oz_missing)}, WB missing={wb_missing}")
    wb_payloads=[]
    for offer in wb_missing:
        payload=merge_wb(wb_before[offer],[doc])
        if not payload: raise RuntimeError("Expected WB addition missing from merge")
        for field in UPDATE_CARD_FIELDS:
            if field in wb_before[offer] and payload.get(field)!=wb_before[offer][field] and field!="documents":
                raise RuntimeError(f"Unrelated WB field changed in payload: {field}")
        old=copy_documents(wb_before[offer]); new=(payload.get("documents") or {}).get("items") or []
        if new[:len(old)]!=old: raise RuntimeError("Existing WB documents changed")
        wb_payloads.append(payload)

    preflight={"checked_at_utc":now(),"read_only":True,"number":cert.get("certificate_number"),"certificate_id":cid,"type_code":cert.get("type_code"),"accordance_type":cert.get("accordance_type_code"),"status":cert.get("status_code"),"issue_date":ISSUE,"expire_date":EXPIRY,"allowed_tnved":[TNVED],"source_file":str(LOCAL),"source_sha256":digest(LOCAL),"certificate_annex_model_codes":sorted(TARGET_MODELS),"assignment_edges_for_document":len(rows),"candidate_gap_targets":len(target_details),"in_scope_targets":len(eligible),"out_of_scope_targets":[x["offer_id"] for x in target_details if not x["ozon_tnved_in_scope"]],"current_ozon_gap_targets":len(oz_missing),"current_wb_gap_targets":len(wb_missing),"targets":target_details,"wb_payloads":wb_payloads}
    PREFLIGHT_PATH.write_text(json.dumps(preflight,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Preflight verified:",json.dumps({"certificate_id":cid,"status":cert.get("status_code"),"eligible":len(eligible),"skipped_out_of_scope":len(target_details)-len(eligible),"ozon_missing":len(oz_missing),"wb_missing":len(wb_missing),"offers":offers},ensure_ascii=False),flush=True)

    execution={"started_at_utc":now(),"certificate_id":cid,"number":cert.get("certificate_number"),"ozon":None,"wb":None,"readback":None}
    if oz_missing:
        skus=sorted(x["live_sku"] for x in oz_missing)
        journal({"phase":"prepared","platform":"ozon","endpoint":"/v1/product/certificate/bind","certificate_id":cid,"skus":skus,"at_utc":now()})
        try:
            response=client.call("ozon","/v1/product/certificate/bind",{"certificate_id":int(cid),"skus":skus},mutation=True)
        except Exception as exc:
            execution["ozon"]={"phase":"uncertain","error":type(exc).__name__}; save(OUT_PATH.name,execution); raise
        execution["ozon"]={"phase":"response","response":response}
        journal({"phase":"response","platform":"ozon","response":response,"at_utc":now()})
        save(OUT_PATH.name,execution)
        if response.get("result") is not True: raise RuntimeError("Ozon API did not confirm binding; reconcile without retry")

    current_cards=[]
    if wb_payloads:
        journal({"phase":"prepared","platform":"wb","endpoint":"/content/v2/cards/update","offers":wb_missing,"payload_sha256":hashlib.sha256(json.dumps(wb_payloads,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),"at_utc":now()})
        try:
            response=client.call("wb","/content/v2/cards/update",wb_payloads,mutation=True)
        except Exception as exc:
            execution["wb"]={"phase":"uncertain","error":type(exc).__name__}; save(OUT_PATH.name,execution); raise
        execution["wb"]={"phase":"response","response":response}
        journal({"phase":"response","platform":"wb","response":response,"at_utc":now()})
        save(OUT_PATH.name,execution)
        if response.get("error") is not False: raise RuntimeError("WB API did not accept update; reconcile before retry")

    final_bindings=client.ozon_bindings(cid)
    binding_map={str(x.get("product_id") or ""):x for x in final_bindings}
    oz_readback=[]
    for x in eligible:
        b=binding_map.get(x["live_product_id"])
        oz_readback.append({"offer_id":x["offer_id"],"product_id":x["live_product_id"],"sku":x["live_sku"],"binding_visible":bool(b and str(b.get("sku"))==x["live_sku"]),"binding_status":b.get("product_status_code") if b else None})
    if len([x for x in oz_readback if x["binding_visible"] and x["binding_status"]=="approved"])!=len(eligible):
        execution["readback"]={"ozon":oz_readback,"wb":None,"phase":"partial_or_pending"};save(OUT_PATH.name,execution);raise RuntimeError("Ozon binding readback not fully approved")

    wb_readback=[]
    for offer in offers:
        fresh=[c for c in client.wb_cards(offer) if str(c.get("vendorCode") or "")==offer]
        if len(fresh)!=1 or str(fresh[0].get("nmID") or "")!=str(wb_before[offer].get("nmID")):
            raise RuntimeError(f"WB exact readback missing/changed: {offer}")
        after=fresh[0]; match=[d for d in wb_docs(after) if dated_match(d)]
        old=copy_documents(wb_before[offer]); new=copy_documents(after)
        prior_preserved=all(any(doc_key(y)==doc_key(x) and str(y.get("startDate",""))[:10]==str(x.get("startDate",""))[:10] and str(y.get("endDate",""))[:10]==str(x.get("endDate",""))[:10] for y in new) for x in old)
        unrelated_preserved=comparable_card(wb_before[offer])==comparable_card(after)
        visible=len(match)==1
        verdict=(match[0].get("verdict") if match else None)
        wb_readback.append({"offer_id":offer,"nmID":str(after.get("nmID")),"document_visible":visible,"verdict":verdict,"prior_documents_preserved":prior_preserved,"unrelated_fields_preserved":unrelated_preserved,"review_left_to_wb":bool(visible and not ((verdict or {}).get("verified") is True and (verdict or {}).get("reason")=="valid"))})
    if len(wb_readback)!=len(offers) or any(not x["document_visible"] or not x["prior_documents_preserved"] or not x["unrelated_fields_preserved"] for x in wb_readback):
        execution["readback"]={"ozon":oz_readback,"wb":wb_readback,"phase":"partial_or_pending"};save(OUT_PATH.name,execution);raise RuntimeError("WB readback incomplete; do not delete source")
    execution.update({"finished_at_utc":now(),"phase":"complete_with_scope_skips","candidate_gap_targets":len(target_details),"out_of_scope_targets":[x["offer_id"] for x in target_details if not x["ozon_tnved_in_scope"]],"ozon":{"target_count":len(oz_readback),"approved_bindings":sum(x["binding_status"]=="approved" for x in oz_readback),"rows":oz_readback},"wb":{"target_count":len(wb_readback),"exact_documents_visible":sum(x["document_visible"] for x in wb_readback),"valid_now":sum((x["verdict"] or {}).get("verified") is True and (x["verdict"] or {}).get("reason")=="valid" for x in wb_readback),"pending_review":sum(x["review_left_to_wb"] for x in wb_readback),"rows":wb_readback},"local_source_deleted":False,"local_source_retained_reason":"Retain the source while two WB documents are under review and the remaining out-of-scope assignment rows stay unresolved."})
    save(OUT_PATH.name,execution)
    print(json.dumps({"output":str(OUT_PATH),"phase":execution["phase"],"candidate_gap_targets":execution["candidate_gap_targets"],"out_of_scope_targets":execution["out_of_scope_targets"],"ozon_approved_bindings":execution["ozon"]["approved_bindings"],"wb_visible":execution["wb"]["exact_documents_visible"],"wb_valid":execution["wb"]["valid_now"],"wb_pending_review":execution["wb"]["pending_review"],"source_deleted":False},ensure_ascii=False,indent=2))

if __name__=="__main__": main()
