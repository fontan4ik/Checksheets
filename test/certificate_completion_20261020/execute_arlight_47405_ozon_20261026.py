"""Upload verified Arlight certificate 47405/26 and bind only uncovered, in-scope Ozon dimmers."""
from __future__ import annotations
import base64, datetime as dt, hashlib, json, sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "certificate_api_pilot_20261012"
sys.path.insert(0, str(BASE))
from api_client import Client, now, digest

ROOT = BASE.parents[1]
OUT = Path(__file__).with_name("arlight_47405_ozon_execution_20261026.json")
JOURNAL = Path(__file__).with_name("arlight_47405_ozon_mutation_journal_20261026.jsonl")
PREFLIGHT = Path(__file__).with_name("arlight_47405_ozon_preflight_20261026.json")
PDF = ROOT / "output_to_user/certificates/group_1/documents/arlight/A03142CBD22EEA4C858E069A414FBA52.pdf"
NUMBER = "ЕАЭС RU С-CN.АЯ46.В.47405/26"
FSA_URL = "https://pub.fsa.gov.ru/rss/certificate/view/3664775/baseInfo"
TARGETS = [
    {"offer_id":"021707-1","product_id":"4030777900","sku":"3859220611"},
    {"offer_id":"026403-1","product_id":"2384427632","sku":"2605715434"},
    {"offer_id":"029279-1","product_id":"2384427943","sku":"2605715647"},
    {"offer_id":"032994-1","product_id":"4030777917","sku":"3859220390"},
    {"offer_id":"033760-1","product_id":"5148047314","sku":"4779762770"},
    {"offer_id":"039135-1","product_id":"2384427739","sku":"2605939839"},
]
COVERED_TARGETS = [
    {"offer_id":"046120-1","product_id":"5148047312","sku":"4779763895"},
    {"offer_id":"046131-1","product_id":"5148047348","sku":"4779762668"},
]

CHAR_MAP = str.maketrans({"А":"A","В":"B","Е":"E","К":"K","М":"M","Н":"H","О":"O","Р":"P","С":"C","Т":"T","У":"Y","Х":"X","Я":"R"})
def norm(s: object) -> str:
    return "".join(c for c in str(s or "").upper().translate(CHAR_MAP) if c.isalnum())
def log(event: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at_utc":now(), **event}, ensure_ascii=False)+"\n")

def list_certs(client: Client) -> list[dict]:
    out=[]
    for page in range(1,101):
        result=client.call("ozon","/v1/product/certificate/list",{"page":page,"page_size":100}).get("result") or {}
        batch=result.get("certificates")
        if not isinstance(batch,list): raise RuntimeError("certificate list response incomplete")
        out.extend(batch)
        if len(batch)<100: return out
    raise RuntimeError("certificate list pagination limit exceeded")

def fresh_targets(client: Client, targets: list[dict]) -> list[dict]:
    offers=[x["offer_id"] for x in targets]
    raw=client.call("ozon","/v3/product/info/list",{"offer_id":offers}).get("items")
    attrs=client.call("ozon","/v4/product/info/attributes",{"filter":{"offer_id":offers},"limit":len(offers)}).get("result")
    if not isinstance(raw,list) or not isinstance(attrs,list): raise RuntimeError("fresh product read incomplete")
    byp={str(x.get("offer_id")):x for x in raw}; bya={str(x.get("offer_id")):x for x in attrs}
    if set(byp)!=set(offers) or set(bya)!=set(offers): raise RuntimeError("fresh product identity set mismatch")
    checked=[]
    for target in targets:
        p=byp[target["offer_id"]]; a=bya[target["offer_id"]]
        amap={str(x.get("id")):x for x in a.get("attributes") or []}
        brands=[str(v.get("value") or "").strip() for v in (amap.get("85") or {}).get("values") or []]
        codes=[str(v.get("value") or "").split(" - ",1)[0].strip() for v in (amap.get("22232") or {}).get("values") or []]
        actual_id=str(p.get("id") or p.get("product_id") or ""); actual_sku=str(p.get("sku") or "")
        row={**target,"live_product_id":actual_id,"live_sku":actual_sku,"is_archived":p.get("is_archived"),"name":p.get("name"),"brand_values":brands,"tnved_codes":codes}
        if actual_id!=target["product_id"] or actual_sku!=target["sku"] or p.get("is_archived") is not False: raise RuntimeError("target identity/archive changed: "+target["offer_id"])
        if brands!=["Arlight"] or codes!=["8537109800"]: raise RuntimeError("live brand or TNVED is out of scope: "+target["offer_id"])
        checked.append(row)
    return checked

def main() -> None:
    if JOURNAL.exists(): raise RuntimeError("mutation journal already exists; reconcile before any action")
    pre=json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if not pre.get("upload_eligible"): raise RuntimeError("read-only preflight did not pass")
    if not PDF.is_file() or digest(PDF)!=pre["source_pdf"]["sha256"]: raise RuntimeError("source PDF missing or hash changed")
    if norm(NUMBER)!=norm(pre["official_fsa_record"]["number"]): raise RuntimeError("official FSA number differs")
    client=Client()
    certs=list_certs(client)
    dups=[c for c in certs if norm(c.get("certificate_number"))==norm(NUMBER)]
    if dups: raise RuntimeError("matching Ozon record appeared; reconcile rather than create")
    # Existing approved coverage for the two other correctly classified products must still be live.
    covered_id=5920706
    old_bindings=client.ozon_bindings(covered_id)
    for t in COVERED_TARGETS:
        match=[b for b in old_bindings if str(b.get("product_id"))==t["product_id"]]
        if len(match)!=1 or str(match[0].get("sku"))!=t["sku"] or match[0].get("product_status_code")!="approved":
            raise RuntimeError("existing approved coverage changed for "+t["offer_id"])
    checked=fresh_targets(client,TARGETS)
    expiry=dt.date(2031,4,19)
    if dt.date.today()>expiry: raise RuntimeError("document expired")
    params={
        "name":"Сертификат соответствия № "+NUMBER,
        "certificate_type":"CERTIFICATE_OF_CONFORMITY",
        "certificate_country":"RU",
        "accordance_type":"EAEU",
        "number":NUMBER,
        "issue_date":"2026-04-20T00:00:00Z",
        "expired_date":{"date":{"day":19,"month":4,"year":2031}},
        "skus":[TARGETS[0]["sku"]],
        "product_type":"UNKNOWN",
        "files":[{"file_content":base64.b64encode(PDF.read_bytes()).decode("ascii"),"name":PDF.name}],
        "link_to_registry":FSA_URL,
    }
    payload={"params":params}
    request_hash=hashlib.sha256(json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
    if len(json.dumps(payload).encode())>9_500_000: raise RuntimeError("create request too large")
    log({"phase":"prepared","operation":"create","endpoint":"/v2/product/certificate/create","request_sha256":request_hash,"source_sha256":digest(PDF),"target_skus":[x["sku"] for x in TARGETS],"seed_sku":TARGETS[0]["sku"]})
    created=client.call("ozon","/v2/product/certificate/create",payload,mutation=True)
    states=[x.get("state") for x in created.get("params",[]) if isinstance(x,dict)]
    cid=str(created.get("certificate_id") or "")
    log({"phase":"response","operation":"create","certificate_id":cid,"status":created.get("status"),"param_states":states})
    if not cid or created.get("status")!="COMPLETED" or not states or set(states)!={"VALID"}:
        raise RuntimeError("create response was not validated; reconcile live state before retry")
    # Read back immediately; bind only remaining exact pairs once.
    bindings=client.ozon_bindings(cid)
    initial={str(b.get("product_id")):b for b in bindings}
    eligible_ids={x["product_id"]:x for x in TARGETS}
    for pid,b in initial.items():
        if pid in eligible_ids and str(b.get("sku"))!=eligible_ids[pid]["sku"]:
            raise RuntimeError("binding identity conflict after create")
    missing=[]
    for t in TARGETS:
        b=initial.get(t["product_id"])
        if b and b.get("product_status_code")=="declined": continue
        if not b: missing.append(t)
    bind_response=None
    if missing:
        skus=[x["sku"] for x in missing]
        bind_payload={"certificate_id":int(cid),"skus":skus}
        bind_hash=hashlib.sha256(json.dumps(bind_payload,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
        log({"phase":"prepared","operation":"bind","endpoint":"/v1/product/certificate/bind","request_sha256":bind_hash,"certificate_id":cid,"skus":skus})
        bind_response=client.call("ozon","/v1/product/certificate/bind",bind_payload,mutation=True)
        log({"phase":"response","operation":"bind","certificate_id":cid,"result":bind_response.get("result")})
        if bind_response.get("result") is not True: raise RuntimeError("Ozon did not confirm binding; reconcile before retry")
    readback=client.ozon_bindings(cid)
    bypid={str(b.get("product_id")):b for b in readback}
    verified=[]
    for t in TARGETS:
        b=bypid.get(t["product_id"])
        verified.append({**t,"binding_found":bool(b),"binding_sku":str((b or {}).get("sku") or ""),"binding_status":(b or {}).get("product_status_code")})
    if not all(x["binding_found"] and x["binding_sku"]==x["sku"] for x in verified):
        raise RuntimeError("binding readback incomplete")
    certs_after=list_certs(client)
    matching=[c for c in certs_after if norm(c.get("certificate_number"))==norm(NUMBER)]
    if len(matching)!=1: raise RuntimeError("created certificate record not unique on readback")
    c=matching[0]
    out={"checked_at_utc":now(),"complete":True,"fsa_record_url":FSA_URL,"certificate_id":cid,"certificate_number":NUMBER,"ozon_status":c.get("status_code"),"issue_date":c.get("issue_date"),"expire_date":c.get("expire_date"),"created_record_count":len(matching),"target_bindings":verified,"binding_count_before_create":0,"binding_count_after":len(readback),"binding_status_counts":{s:sum(1 for b in readback if b.get("product_status_code")==s) for s in sorted({str(b.get("product_status_code")) for b in readback})},"covered_elsewhere":[{"offer_id":t["offer_id"],"certificate_id":covered_id,"status":"approved"} for t in COVERED_TARGETS],"skipped_due_to_tnved_mismatch":20,"source_pdf_sha256":digest(PDF),"source_pdf_path":str(PDF)}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"artifact":str(OUT),"certificate_id":cid,"ozon_status":out["ozon_status"],"bindings":verified,"binding_status_counts":out["binding_status_counts"],"covered_elsewhere":out["covered_elsewhere"]},ensure_ascii=False))

if __name__=="__main__": main()
