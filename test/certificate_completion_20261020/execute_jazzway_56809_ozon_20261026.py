"""Upload verified Jazzway declaration 56809/25 and bind its 16 exact Ozon LED-strip cards."""
from __future__ import annotations
import base64, datetime as dt, hashlib, json, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
BASE=HERE.parents[1]/"test/certificate_api_pilot_20261012"
sys.path.insert(0,str(BASE))
from api_client import Client,now,digest
PREFLIGHT=HERE/"jazzway_56809_ozon_preflight_20261026.json"
OUT=HERE/"jazzway_56809_ozon_execution_20261026.json"
JOURNAL=HERE/"jazzway_56809_ozon_mutation_journal_20261026.jsonl"
PDF=HERE.parents[1]/"output_to_user/certificates/group_2/JAZZWAY/documents/certificate_bcfbc14d4a.pdf"
NUMBER="ЕАЭС N RU Д-HK.РА05.В.56809/25"
FSA_URL="https://pub.fsa.gov.ru/rds/declaration/view/20320259/common"

def norm(s):
 tr=str.maketrans({"А":"A","В":"B","Е":"E","К":"K","М":"M","Н":"H","О":"O","Р":"P","С":"C","Т":"T","У":"Y","Х":"X"})
 return "".join(c for c in str(s or "").upper().translate(tr) if c.isalnum())
def log(event):
 with JOURNAL.open("a",encoding="utf-8") as f:f.write(json.dumps({"at_utc":now(),**event},ensure_ascii=False)+"\n")
def cert_list(client):
 out=[]
 for page in range(1,101):
  res=client.call("ozon","/v1/product/certificate/list",{"page":page,"page_size":100}).get("result") or {}; batch=res.get("certificates")
  if not isinstance(batch,list):raise RuntimeError("certificate list response incomplete")
  out.extend(batch)
  if len(batch)<100:return out
 raise RuntimeError("certificate pagination exceeded")
def refresh_targets(client,targets):
 offers=[x["offer_id"] for x in targets]
 ps=client.call("ozon","/v3/product/info/list",{"offer_id":offers}).get("items")
 ars=client.call("ozon","/v4/product/info/attributes",{"filter":{"offer_id":offers},"limit":len(offers)}).get("result")
 if not isinstance(ps,list) or not isinstance(ars,list):raise RuntimeError("fresh target read incomplete")
 pm={str(x.get("offer_id")):x for x in ps}; am={str(x.get("offer_id")):x for x in ars}
 if set(pm)!=set(offers) or set(am)!=set(offers):raise RuntimeError("target list changed")
 checked=[]
 for t in targets:
  p=pm[t["offer_id"]]; a=am[t["offer_id"]]; attrs={str(x.get("id")):x for x in a.get("attributes") or []}
  brands=[str(v.get("value") or "").strip() for v in (attrs.get("85") or {}).get("values") or []]
  codes=[str(v.get("value") or "").split(" - ",1)[0].strip() for v in (attrs.get("22232") or {}).get("values") or []]
  row={**t,"live_product_id":str(p.get("id") or p.get("product_id") or ""),"live_sku":str(p.get("sku") or ""),"is_archived":p.get("is_archived"),"name":p.get("name"),"brand_values":brands,"tnved_codes":codes}
  if row["live_product_id"]!=t["product_id"] or row["live_sku"]!=t["sku"] or row["is_archived"] is not False:raise RuntimeError("identity/archive changed: "+t["offer_id"])
  if len(brands)!=1 or brands[0].casefold()!="jazzway" or codes!=["8539519009"] or "лент" not in str(row["name"]).casefold():raise RuntimeError("brand, model, or TNVED out of scope: "+t["offer_id"])
  checked.append(row)
 return checked
def main():
 if JOURNAL.exists():raise RuntimeError("mutation journal exists; reconcile before any further write")
 pre=json.loads(PREFLIGHT.read_text(encoding="utf-8"))
 if not pre.get("upload_eligible"):raise RuntimeError("read-only preflight failed")
 if not PDF.is_file() or digest(PDF)!=pre["source_pdf"]["sha256"]:raise RuntimeError("source file missing or hash changed")
 targets=pre["targets"]
 client=Client()
 certs=cert_list(client)
 matches=[c for c in certs if norm(c.get("certificate_number"))==norm(NUMBER)]
 if matches:raise RuntimeError("matching Ozon record appeared; reconcile without creating")
 live=refresh_targets(client,targets)
 expiry=dt.date(2030,6,30)
 if dt.date.today()>expiry:raise RuntimeError("document expired")
 params={"name":"Декларация о соответствии №"+NUMBER,"certificate_type":"DECLARATION","certificate_country":"RU","accordance_type":"EAEU","number":NUMBER,"issue_date":"2025-07-01T00:00:00Z","expired_date":{"date":{"day":30,"month":6,"year":2030}},"skus":[targets[0]["sku"]],"product_type":"UNKNOWN","files":[{"file_content":base64.b64encode(PDF.read_bytes()).decode("ascii"),"name":PDF.name}],"link_to_registry":FSA_URL}
 payload={"params":params}
 req_hash=hashlib.sha256(json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
 if len(json.dumps(payload).encode())>9_500_000:raise RuntimeError("create request too large")
 log({"phase":"prepared","operation":"create","endpoint":"/v2/product/certificate/create","request_sha256":req_hash,"source_sha256":digest(PDF),"target_count":len(targets),"seed_sku":targets[0]["sku"]})
 created=client.call("ozon","/v2/product/certificate/create",payload,mutation=True)
 states=[x.get("state") for x in created.get("params",[]) if isinstance(x,dict)]; cid=str(created.get("certificate_id") or "")
 log({"phase":"response","operation":"create","certificate_id":cid,"status":created.get("status"),"param_states":states})
 if not cid or created.get("status")!="COMPLETED" or not states or set(states)!={"VALID"}:raise RuntimeError("create response not validated; reconcile before retry")
 bindings=client.ozon_bindings(cid); bypid={str(b.get("product_id")):b for b in bindings}
 tbyid={t["product_id"]:t for t in targets}
 for pid,b in bypid.items():
  if pid in tbyid and str(b.get("sku"))!=tbyid[pid]["sku"]:raise RuntimeError("binding identity conflict after create")
 missing=[]
 for t in targets:
  b=bypid.get(t["product_id"])
  if b and b.get("product_status_code")=="declined":continue
  if not b:missing.append(t)
 if missing:
  skus=[x["sku"] for x in missing]; bind_payload={"certificate_id":int(cid),"skus":skus}
  bind_hash=hashlib.sha256(json.dumps(bind_payload,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
  log({"phase":"prepared","operation":"bind","endpoint":"/v1/product/certificate/bind","request_sha256":bind_hash,"certificate_id":cid,"sku_count":len(skus),"skus":skus})
  result=client.call("ozon","/v1/product/certificate/bind",bind_payload,mutation=True)
  log({"phase":"response","operation":"bind","certificate_id":cid,"result":result.get("result")})
  if result.get("result") is not True:raise RuntimeError("Ozon bind not confirmed; reconcile before retry")
 readback=client.ozon_bindings(cid); bypid={str(b.get("product_id")):b for b in readback}
 verified=[]
 for t in targets:
  b=bypid.get(t["product_id"]); verified.append({**t,"binding_found":bool(b),"binding_sku":str((b or {}).get("sku") or ""),"binding_status":(b or {}).get("product_status_code")})
 if not all(r["binding_found"] and r["binding_sku"]==r["sku"] for r in verified):raise RuntimeError("binding readback incomplete")
 certs_after=cert_list(client); matching=[c for c in certs_after if norm(c.get("certificate_number"))==norm(NUMBER)]
 if len(matching)!=1:raise RuntimeError("created record not uniquely visible")
 c=matching[0]
 out={"checked_at_utc":now(),"complete":True,"certificate_id":cid,"certificate_number":NUMBER,"ozon_status":c.get("status_code"),"issue_date":c.get("issue_date"),"expire_date":c.get("expire_date"),"products_count":c.get("products_count"),"target_bindings":verified,"binding_status_counts":{s:sum(1 for b in readback if b.get("product_status_code")==s) for s in sorted({str(b.get("product_status_code")) for b in readback})},"source_pdf_sha256":digest(PDF),"fsa_record_url":FSA_URL,"local_file_deleted":False}
 OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({"artifact":str(OUT),"certificate_id":cid,"ozon_status":out["ozon_status"],"product_count":out["products_count"],"binding_status_counts":out["binding_status_counts"],"bindings":verified},ensure_ascii=False))
if __name__=="__main__":main()
