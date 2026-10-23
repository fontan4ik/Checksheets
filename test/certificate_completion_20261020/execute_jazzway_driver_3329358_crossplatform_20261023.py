#!/usr/bin/env python3
"""Upload the exact Jazzway BSPS 12V driver docs to one Ozon offer and WB card."""
from __future__ import annotations
import base64, collections, datetime as dt, hashlib, json, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import norm_number, wb_datetime
from run_all_found_certificates_20261014 import merge_wb

OFFER = "3329358-1"
WB_NMID = "489273184"
PREFLIGHT = HERE / "jazzway_driver_3329358_preflight_20261023.json"
STATE = HERE / "jazzway_driver_3329358_execution_20261023.json"
JOURNAL = HERE / "jazzway_driver_3329358_mutation_journal_20261023.jsonl"
WB_BEFORE = HERE / "jazzway_driver_3329358_wb_before_20261023.json"
READBACK = HERE / "jazzway_driver_3329358_readback_20261023.json"
DOCS = [
    {"number": "ЕАЭС RU C-HK.НВ90.В.00268/24", "type_code": "certificate_of_conformity",
     "wb_type": 1, "ozon_type": "CERTIFICATE_OF_CONFORMITY", "issue": "2024-09-24",
     "expiry": "2029-09-23", "tnved": "8504408300",
     "file": "output_to_user/certificates/additional_search/brand_research/jazzway/followup_2026_10_02/jazzway_driver_004_020_2029.pdf",
     "sha256": "956b78369981ad73a13d14d30e335118204936d5c873c02c65415faf7f3379ab"},
    {"number": "ЕАЭС N RU Д-HK.РА08.В.69871/24", "type_code": "declaration",
     "wb_type": 2, "ozon_type": "DECLARATION", "issue": "2024-09-24",
     "expiry": "2029-09-23", "tnved": "8504408300",
     "file": "output_to_user/certificates/additional_search/brand_research/jazzway/followup_2026_10_02/jazzway_driver_037_2029.pdf",
     "sha256": "ab6ec523525995a0114a526df28d1fc93497d4bdb4a90f911e566bd8e6535a1e"},
]
EXPECTED = {"product_id": "411950870", "sku": "792676299", "brand": "Jazzway",
            "wb_brand": "Jazzway", "tnved_live": "8504409100", "title_terms": ["12", "15"]}

def save(path: Path, obj: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)

def log(obj: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at_utc": now(), **obj}, ensure_ascii=False) + "\n")
        f.flush()

def attr_values(row: dict, attr_id: str) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(v.get("value") or "").strip() for v in (attrs.get(attr_id) or {}).get("values") or []
            if str(v.get("value") or "").strip()]

def certs(client: Client) -> list[dict]:
    out=[]
    for page in range(1, 101):
        result=client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch=result.get("certificates")
        if not isinstance(batch, list): raise RuntimeError("ozon_certificate_list_invalid")
        out.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0): return out
    raise RuntimeError("ozon_certificate_list_page_limit")

def exact_record(client: Client, doc: dict) -> list[dict]:
    key=norm_number(doc["number"])
    return [c for c in certs(client) if norm_number(c.get("certificate_number")) == key]

def validate_source_and_assignment() -> None:
    pre=json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if pre.get("read_only") is not True or pre.get("offer_id") != OFFER or len(pre.get("assignment_rows") or []) != 2:
        raise RuntimeError("preflight_identity_or_assignment_count_changed")
    if not any("официальная карточка jazzway" in str(r.get("Основание сопоставления") or "").casefold()
               and "bsps 12v" in str(r.get("Основание сопоставления") or "").casefold() for r in pre["assignment_rows"]):
        raise RuntimeError("official_model_mapping_missing")
    for doc in DOCS:
        path=ROOT/doc["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != doc["sha256"]:
            raise RuntimeError("source_hash_mismatch:"+doc["number"])
        row=next((r for r in pre["assignment_rows"] if r.get("Номер/название документа")==doc["number"]), None)
        if not row or row.get("Применимость") != "Подтверждено источником":
            raise RuntimeError("source_assignment_not_confirmed:"+doc["number"])
        if doc["tnved"] != "8504408300":
            raise RuntimeError("unexpected_document_scope_code:"+doc["number"])

def ozon_target(client: Client) -> dict:
    p=client.call("ozon", "/v3/product/info/list", {"offer_id": [OFFER]}).get("items") or []
    a=client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": [OFFER]}, "limit": 1}).get("result") or []
    if len(p)!=1 or len(a)!=1: raise RuntimeError("ozon_target_missing_or_ambiguous")
    prod, attr=p[0],a[0]
    brand=attr_values(attr,"85")
    codes=sorted({x.split(" - ",1)[0].strip() for x in attr_values(attr,"22232")})
    title=str(prod.get("name") or "")
    if (str(prod.get("product_id") or prod.get("id") or "") != EXPECTED["product_id"]
            or str(prod.get("sku") or "") != EXPECTED["sku"]
            or prod.get("is_archived") is not False or brand != [EXPECTED["brand"]]
            or not ("12В" in title or "12V" in title) or "15" not in title):
        raise RuntimeError("ozon_identity_brand_or_model_changed")
    return {"offer_id": OFFER, "product_id": EXPECTED["product_id"], "sku": EXPECTED["sku"],
            "name": title, "brand": brand, "tnved": codes,
            "tnved_mismatch_with_document_annex": codes != ["8504408300"],
            "mapping_basis": "Jazzway official catalog: article 3329358 = BSPS 12V1.30A=15W IP20; source assignment maps this article to both document annexes.",
            "tnved_caveat": "Ozon currently lists 8504409100 while both document annexes list 8504408300; the precise article/model mapping is exact, but the classification discrepancy remains flagged."}

def ozon_upload_or_reconcile(client: Client, doc: dict, target: dict, state: dict) -> dict:
    matches=exact_record(client,doc)
    if len(matches)>1: raise RuntimeError("duplicate_ozon_document:"+doc["number"])
    record=matches[0] if matches else None
    if record and (record.get("type_code")!=doc["type_code"]
            or str(record.get("issue_date") or "")[:10]!=doc["issue"]
            or str(record.get("expire_date") or "")[:10]!=doc["expiry"]):
        raise RuntimeError("ozon_document_metadata_conflict:"+doc["number"])
    create_response=None
    if record is None:
        expiry=dt.date.fromisoformat(doc["expiry"])
        source=ROOT/doc["file"]
        name=("Декларация о соответствии № " if doc["type_code"]=="declaration" else "Сертификат соответствия № ")+doc["number"]
        payload={"params":{"name":name,"certificate_type":doc["ozon_type"],"certificate_country":"RU",
            "accordance_type":"EAEU","number":doc["number"],"issue_date":doc["issue"]+"T00:00:00Z",
            "expired_date":{"date":{"day":expiry.day,"month":expiry.month,"year":expiry.year}},
            "skus":[target["sku"]],"product_type":"UNKNOWN",
            "files":[{"file_content":base64.b64encode(source.read_bytes()).decode("ascii"),"name":source.name}]}}
        if len(json.dumps(payload,ensure_ascii=False,separators=(",",":" )).encode())>9_500_000:
            return {"outcome":"skipped_payload_too_large","number":doc["number"]}
        request_hash=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        log({"phase":"ozon_create_prepared","number":doc["number"],"request_sha256":request_hash,"offer_id":OFFER,"sku":target["sku"]})
        state.setdefault("ozon_mutations",[]).append({"phase":"create_pending","number":doc["number"],"request_sha256":request_hash})
        save(STATE,state)
        try:
            create_response=client.call("ozon","/v2/product/certificate/create",payload,mutation=True)
            log({"phase":"ozon_create_response","number":doc["number"],"response":create_response})
        except Exception as exc:
            log({"phase":"ozon_create_outcome_uncertain","number":doc["number"],"error_type":type(exc).__name__})
        for _ in range(6):
            matches=exact_record(client,doc)
            if matches: break
            time.sleep(2)
        if len(matches)!=1:
            return {"outcome":"create_not_visible_no_retry","number":doc["number"],"create_response":create_response,"exact_visible":0,"binding_status":None}
        record=matches[0]
        states=[x.get("state") for x in (create_response or {}).get("params",[]) if isinstance(x,dict)]
        if not create_response or create_response.get("status")!="COMPLETED" or not states or set(states)!={"VALID"}:
            return {"outcome":"record_visible_create_incomplete_no_bind","number":doc["number"],"record":record,"create_response":create_response,"exact_visible":1,"binding_status":None}
    cid=int(record["certificate_id"])
    if record.get("status_code") in {"declined","rejected","invalid","cancelled"}:
        return {"outcome":"record_declined_no_bind","number":doc["number"],"record":record,"exact_visible":1,"binding_status":None}
    bindings=client.ozon_bindings(cid)
    exact=[b for b in bindings if str(b.get("product_id") or "")==target["product_id"]]
    if len(exact)>1 or (exact and str(exact[0].get("sku") or "")!=target["sku"]):
        raise RuntimeError("ozon_binding_identity_conflict:"+doc["number"])
    response=None
    if not exact:
        body={"certificate_id":cid,"skus":[target["sku"]]}
        request_hash=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
        log({"phase":"ozon_bind_prepared","number":doc["number"],"certificate_id":cid,"request_sha256":request_hash,"sku":target["sku"]})
        state.setdefault("ozon_mutations",[]).append({"phase":"bind_pending","number":doc["number"],"request_sha256":request_hash})
        save(STATE,state)
        try:
            response=client.call("ozon","/v1/product/certificate/bind",body,mutation=True)
            log({"phase":"ozon_bind_response","number":doc["number"],"response":response})
        except Exception as exc:
            log({"phase":"ozon_bind_outcome_uncertain","number":doc["number"],"error_type":type(exc).__name__})
    after=client.ozon_bindings(cid)
    rows=[b for b in after if str(b.get("product_id") or "")==target["product_id"] and str(b.get("sku") or "")==target["sku"]]
    return {"outcome":"bound_or_reconciled" if len(rows)==1 else "binding_not_visible_no_retry","number":doc["number"],
            "record":record,"certificate_id":cid,"record_status":record.get("status_code"),
            "exact_binding_count":len(rows),"binding_status":rows[0].get("product_status_code") if rows else None,
            "bind_response":response,"create_response":create_response}

def main() -> None:
    if any(p.exists() for p in [STATE,JOURNAL,WB_BEFORE,READBACK]):
        raise RuntimeError("execution_artifact_exists_reconcile_before_retry")
    validate_source_and_assignment()
    client=Client()
    target=ozon_target(client)
    cards=[c for c in client.wb_cards(OFFER) if str(c.get("vendorCode") or "")==OFFER]
    if len(cards)!=1 or str(cards[0].get("nmID") or "")!=WB_NMID or str(cards[0].get("brand") or "")!=EXPECTED["wb_brand"]:
        raise RuntimeError("wb_target_missing_ambiguous_or_identity_changed")
    card=cards[0]
    before_docs=((card.get("documents") or {}).get("items") or [])
    desired=[{"type":d["wb_type"],"number":d["number"],"startDate":wb_datetime(d["issue"]),"endDate":wb_datetime(d["expiry"]),"isEndless":False} for d in DOCS]
    for wanted in desired:
        same=[x for x in before_docs if norm_number(x.get("number"))==norm_number(wanted["number"])]
        exact=[x for x in same if str(x.get("type"))==str(wanted["type"])
            and str(x.get("startDate") or "")[:10]==wanted["startDate"][:10]
            and str(x.get("endDate") or "")[:10]==wanted["endDate"][:10]
            and x.get("isEndless") is False]
        if same and (len(same)!=1 or len(exact)!=1): raise RuntimeError("wb_document_number_metadata_conflict:"+wanted["number"])
    update=merge_wb(card,desired)
    save(WB_BEFORE,{"checked_at_utc":now(),"read_only":True,"offer_id":OFFER,"card":card,"already_exact_count":sum(any(norm_number(x.get("number"))==norm_number(w["number"]) for x in before_docs) for w in desired)})
    state={"started_at_utc":now(),"offer_id":OFFER,"wb_nmID":WB_NMID,"target":target,
        "documents":[{**d,"sha256":d["sha256"]} for d in DOCS],"date_condition":"Originals state sample manufacture date 08.2024; target lot manufacturing dates are not available, retained as an applicability caveat.",
        "wb_review_left_to_marketplace":True,"local_files_deleted":False,"phase":"fresh_prewrite_verified"}
    save(STATE,state)
    results=[]
    for doc in DOCS:
        try: results.append(ozon_upload_or_reconcile(client,doc,target,state))
        except Exception as exc:
            results.append({"outcome":"ozon_error_skip","number":doc["number"],"error_type":type(exc).__name__})
            log({"phase":"ozon_error_skip","number":doc["number"],"error_type":type(exc).__name__})
        state["ozon_results"]=results
        save(STATE,state)
    wb_result={"update_attempted":False,"response":None,"exact_visible_count":0,"rows":[]}
    if update:
        payload=[update]
        marker=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        log({"phase":"wb_update_prepared","offer_id":OFFER,"nmID":WB_NMID,"request_sha256":marker,"doc_count":2})
        state.update({"phase":"wb_update_pending","wb_update_attempted":True,"wb_update_request_sha256":marker})
        save(STATE,state)
        try:
            response=client.call("wb","/content/v2/cards/update",payload,mutation=True)
            wb_result.update({"update_attempted":True,"response":response})
            log({"phase":"wb_update_response","response":response})
        except Exception as exc:
            wb_result.update({"update_attempted":True,"error_type":type(exc).__name__})
            log({"phase":"wb_update_outcome_uncertain","error_type":type(exc).__name__})
    else:
        wb_result["already_exact_count"]=2
    save(STATE,{**state,"wb_result":wb_result})
    fresh=[c for c in client.wb_cards(OFFER) if str(c.get("vendorCode") or "")==OFFER]
    rows=[]
    if len(fresh)==1 and str(fresh[0].get("nmID") or "")==WB_NMID:
        items=((fresh[0].get("documents") or {}).get("items") or [])
        for doc in DOCS:
            found=[x for x in items if norm_number(x.get("number"))==norm_number(doc["number"])
                and str(x.get("type"))==str(doc["wb_type"])
                and str(x.get("startDate") or "")[:10]==doc["issue"]
                and str(x.get("endDate") or "")[:10]==doc["expiry"]
                and x.get("isEndless") is False]
            rows.append({"number":doc["number"],"exact_visible_count":len(found),"verdicts":[x.get("verdict") for x in found]})
    wb_result["exact_visible_count"]=sum(1 for x in rows if x["exact_visible_count"]==1)
    wb_result["rows"]=rows
    state.update({"phase":"finished_with_readback","finished_at_utc":now(),"ozon_results":results,
        "wb_result":wb_result,"local_files_deleted":False,"local_files_retained_reason":"Ozon binding/review and WB verdicts are not yet fully confirmed; both sources remain in place."})
    save(READBACK,{"checked_at_utc":now(),"offer_id":OFFER,"target":target,"ozon_results":results,"wb_result":wb_result,
        "date_condition":state["date_condition"],"sources_retained":[str(ROOT/d["file"]) for d in DOCS]})
    save(STATE,state)
    print(json.dumps({"state":str(STATE),"ozon_results":[{"number":x.get("number"),"outcome":x.get("outcome"),"record_status":x.get("record_status"),"binding_status":x.get("binding_status")} for x in results],
        "wb_update":wb_result.get("response"),"wb_exact_visible_count":wb_result["exact_visible_count"],"local_files_deleted":False},ensure_ascii=False,indent=2))

if __name__=="__main__": main()
