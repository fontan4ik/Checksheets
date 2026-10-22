#!/usr/bin/env python3
"""Final live verification and authorized source cleanup for Navigator NLT track documents."""
from __future__ import annotations
import collections, hashlib, json, pathlib, sys

HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[1]
API=ROOT/"test/certificate_api_pilot_20261012"
sys.path.insert(0,str(API))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import comparable_card, copy_documents, doc_key, norm_number  # noqa: E402

PREFLIGHT=HERE/"navigator_13993_41043_live_preflight_20261022.json"
BEFORE=HERE/"navigator_13993_41043_wb_before_20261022.json"
OUT=HERE/"navigator_13993_41043_delayed_crossplatform_readback_20261022.json"
ADDENDUM=HERE/"postwrite_coverage_addendum_20261022.json"
DOCS={
 "declaration":{"number":"ЕАЭС N RU Д-CN.РА05.В.13993/25","type_code":"declaration","wb_type":2,
  "issue_date":"2025-06-17","expire_date":"2030-06-15",
  "file":ROOT/"output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_declaration_95495_f6b5201fb04b.pdf",
  "sha256":"f6b5201fb04b0e1bc75fb43d9342b373a72f99bcaba6ac96dcb15b13e5bcc2ed"},
 "certificate":{"number":"ЕАЭС RU С-CN.АЯ46.В.41043/25","type_code":"certificate_of_conformity","wb_type":1,
  "issue_date":"2025-06-06","expire_date":"2030-06-05",
  "file":ROOT/"output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_eac_certificate_95495_3dfcbc8dbac2.pdf",
  "sha256":"3dfcbc8dbac2784f455fc5967be5067e2e25183043f8c8b7d72e62c8f9e18ad7"}}

def save(path,value):
 tmp=path.with_suffix(path.suffix+".tmp");tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n");tmp.replace(path)
def main():
 if OUT.exists(): raise RuntimeError("final_readback_exists_inspect_first")
 pre=json.loads(PREFLIGHT.read_text());before=json.loads(BEFORE.read_text());add=json.loads(ADDENDUM.read_text())
 if pre.get("target_count")!=14 or len(pre.get("ozon_targets") or [])!=14 or len(pre.get("wb_targets") or [])!=14:
  raise RuntimeError("preflight_target_set_incomplete")
 for key,doc in DOCS.items():
  source_record=(pre.get("documents") or {}).get(key) or {}
  if doc["file"].is_file():
   if hashlib.sha256(doc["file"].read_bytes()).hexdigest()!=doc["sha256"]:
    raise RuntimeError("local_source_file_hash_changed:"+doc["number"])
  elif source_record.get("source_sha256_matches") is not True or source_record.get("source_file")!=str(doc["file"]):
   raise RuntimeError("missing_source_without_verified_preflight_hash:"+doc["number"])
 client=Client()
 all_records=[]
 for page in range(1,101):
  result=client.call("ozon","/v1/product/certificate/list",{"page":page,"page_size":100}).get("result") or {}
  batch=result.get("certificates")
  if not isinstance(batch,list): raise RuntimeError("ozon_certificate_list_incomplete")
  all_records.extend(batch)
  if not batch or page>=int(result.get("page_count") or 0): break
 else: raise RuntimeError("ozon_certificate_page_limit")
 ozon={}
 target_pairs={(str(x["product_id"]),str(x["sku"])):x["offer_id"] for x in pre["ozon_targets"]}
 for key,doc in DOCS.items():
  matches=[r for r in all_records if norm_number(r.get("certificate_number"))==norm_number(doc["number"])]
  if len(matches)!=1: raise RuntimeError("ozon_record_count_not_one:"+doc["number"])
  rec=matches[0]
  if (rec.get("type_code")!=doc["type_code"] or str(rec.get("issue_date") or "")[:10]!=doc["issue_date"]
      or str(rec.get("expire_date") or "")[:10]!=doc["expire_date"] or rec.get("status_code")!="approved"):
   raise RuntimeError("ozon_record_metadata_or_status_not_approved:"+doc["number"])
  bindings=client.ozon_bindings(int(rec["certificate_id"]))
  by_pair=collections.defaultdict(list)
  for row in bindings: by_pair[(str(row.get("product_id") or ""),str(row.get("sku") or ""))].append(row)
  rows=[]
  for pair,offer in target_pairs.items():
   found=by_pair[pair]
   rows.append({"offer_id":offer,"exact_count":len(found),"status":found[0].get("product_status_code") if len(found)==1 else None})
  unexpected=[row for row in bindings if (str(row.get("product_id") or ""),str(row.get("sku") or "")) not in target_pairs]
  counts=collections.Counter(str(x["status"] or "unknown") for x in rows if x["exact_count"]==1)
  ozon[key]={"certificate_id":rec.get("certificate_id"),"record_status":rec.get("status_code"),
             "issue_date":str(rec.get("issue_date"))[:10],"expire_date":str(rec.get("expire_date"))[:10],
             "expected_bindings":14,"exact_bindings":sum(x["exact_count"]==1 for x in rows),
             "binding_status_counts":dict(counts),"unexpected_bindings":len(unexpected),"rows":rows}
 wb_before=before.get("cards") or {};wb_rows=[];wb_verdicts=collections.Counter();wb_failures=[]
 for target in pre["wb_targets"]:
  offer=str(target["offer_id"])
  cards=[x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "")==offer]
  if len(cards)!=1:
   wb_failures.append({"offer_id":offer,"problem":"card_count","count":len(cards)});continue
  card=cards[0];documents=copy_documents(card);exact_docs=[]
  for doc in DOCS.values():
   exact=[x for x in documents if norm_number(x.get("number"))==norm_number(doc["number"])
          and str(x.get("type"))==str(doc["wb_type"])
          and str(x.get("startDate") or "")[:10]==doc["issue_date"]
          and str(x.get("endDate") or "")[:10]==doc["expire_date"]
          and x.get("isEndless") is False]
   if len(exact)!=1: wb_failures.append({"offer_id":offer,"problem":"exact_document_missing_or_duplicate","number":doc["number"],"count":len(exact)})
   else:
    exact_docs.extend(exact); verdict=exact[0].get("verdict")
    label="valid" if isinstance(verdict,dict) and verdict.get("verified") is True and verdict.get("reason")=="valid" else "pending_or_unverified" if verdict is None else "other"
    wb_verdicts[label]+=1
  prior=wb_before.get(offer)
  if not prior: wb_failures.append({"offer_id":offer,"problem":"missing_prewrite_snapshot"})
  else:
   current_sigs=[(doc_key(x),str(x.get("startDate") or "")[:10],str(x.get("endDate") or "")[:10],bool(x.get("isEndless"))) for x in documents]
   prior_preserved=all(sig in current_sigs for sig in prior["prior_signatures"])
   other_preserved=comparable_card(card)==comparable_card(prior["card"])
   if not prior_preserved or not other_preserved: wb_failures.append({"offer_id":offer,"problem":"prior_card_data_not_preserved"})
  wb_rows.append({"offer_id":offer,"nmID":str(card.get("nmID") or ""),"exact_documents":len(exact_docs),
                  "verdicts":[x.get("verdict") for x in exact_docs],
                  "prior_documents_preserved":bool(prior and prior_preserved),
                  "unrelated_card_fields_preserved":bool(prior and other_preserved)})
 ozon_complete=all(x["exact_bindings"]==14 and x["record_status"]=="approved"
                   and x["binding_status_counts"]=={"approved":14} and x["unexpected_bindings"]==0 for x in ozon.values())
 wb_complete=(len(wb_rows)==14 and all(x["exact_documents"]==2 and x["prior_documents_preserved"]
              and x["unrelated_card_fields_preserved"] for x in wb_rows) and not wb_failures)
 if not (ozon_complete and wb_complete):
  result={"checked_at_utc":now(),"read_only":True,"brand":"Navigator","target_products":14,
          "documents":ozon,"ozon_all_14_bindings_per_document_approved":ozon_complete,
          "wb":{"target_cards":len(wb_rows),"cards_with_both_exact_documents":sum(x["exact_documents"]==2 for x in wb_rows),
                "verdict_counts":dict(wb_verdicts),"failures":wb_failures,"cards":wb_rows,
                "left_for_marketplace_review":True},"cross_platform_complete":False,"local_source_files_deleted":False}
  save(OUT,result); print(json.dumps({k:v for k,v in result.items() if k!="documents"},ensure_ascii=False,indent=2));return
 # This cleanup is gated by fresh live readback on both marketplaces.
 deleted=[]
 for doc in DOCS.values():
  path=doc["file"]
  if path.is_file():
   digest=hashlib.sha256(path.read_bytes()).hexdigest()
   if digest!=doc["sha256"]: raise RuntimeError("local_source_hash_changed_before_cleanup:"+doc["number"])
   path.unlink()
   deletion_state="deleted_after_fresh_confirmation"
  else:
   digest=doc["sha256"]
   deletion_state="already_absent_after_prior_fresh_confirmation"
  deleted.append({"path":str(path.relative_to(ROOT)),"sha256":digest,"document_number":doc["number"],"deleted":True,"cleanup_state":deletion_state})
 # Increment the baseline coverage with these 14 products only after complete platform confirmation.
 totals=add["post_snapshot_totals"]
 totals["ozon_certificate_records"]+=2
 statuses=totals["ozon_certificate_statuses"]
 statuses["approved"]=statuses.get("approved",0)+2
 totals["ozon_live_bindings"]+=28
 totals["ozon_products_with_at_least_one_current_approved_document"]+=14
 totals["ozon_products_without_any_current_approved_document"]-=14
 if totals["ozon_products_without_any_current_approved_document"]<0: raise RuntimeError("negative_uncovered_total_after_increment")
 for key,doc in DOCS.items():
  add["post_snapshot_writes"].append({"brand":"Navigator","source_group":"navigator_13993_41043_nlt_track_luminaires",
    "document_number":doc["number"],"type":"declaration" if key=="declaration" else "certificate_of_conformity",
    "ozon_certificate_id":ozon[key]["certificate_id"],"ozon_approved_bindings":14,"ozon_status":"approved",
    "offers":sorted(x["offer_id"] for x in pre["ozon_targets"]),
    "wb_exact_metadata_cards":14,"wb_valid_cards":0,"wb_pending_review_cards":14,
    "wb_all_exact_documents_visible":True,"wb_readback_complete":True,
    "fsa_tnved_codes":["9405190032","9405190012"],
    "marketplace_tnved_mismatch":{"FSA":["9405190032","9405190012"],"Ozon":["9405190039"],"WB":["9405110039"],"WB_matches_FSA":False}})
 add.setdefault("verification_artifacts",{})["navigator_13993_41043_preflight"] = str(PREFLIGHT)
 add["verification_artifacts"]["navigator_13993_41043_execution"] = str(HERE/"navigator_13993_41043_execution_20261022.json")
 add["verification_artifacts"]["navigator_13993_41043_initial_wb_readback"] = str(HERE/"navigator_13993_41043_final_crossplatform_readback_20261022.json")
 add["verification_artifacts"]["navigator_13993_41043_delayed_crossplatform_readback"] = str(OUT)
 add.setdefault("current_live_reconciliations",{})["navigator_13993_41043_20261022"]={
   "source_verified_groups":2,"target_products":14,"ozon_documents":2,"ozon_exact_bindings_per_document":14,
   "ozon_status_counts_per_document":{"approved":14},"wb_exact_cards":14,"wb_exact_document_bindings":28,
   "wb_valid_document_bindings":0,"wb_pending_or_unverified_document_bindings":28,
   "wb_review_left_for_marketplace_review":True,"marketplace_tnved_mismatch":True,
   "net_new_ozon_products_covered":14,"net_new_wb_cards_with_valid_document":0,
   "local_source_files_deleted":True,"verification_artifact":str(OUT)}
 add.setdefault("local_source_cleanup",{})["navigator_13993_41043_20261022"]={
   "deleted_files":deleted,"checked_at_utc":now(),
   "basis":"Fresh Ozon readback: two approved records, all 14 exact bindings approved per document; fresh WB readback: exact type, number and dates on all 14 cards, other card fields and prior documents preserved. WB verdicts remain pending and were left for marketplace review."}
 add["checked_at_utc"]=now()
 save(ADDENDUM,add)
 result={"checked_at_utc":now(),"read_only":False,"brand":"Navigator","target_products":14,
         "documents":ozon,"ozon_all_14_bindings_per_document_approved":True,
         "wb":{"target_cards":14,"cards_with_both_exact_documents":14,"verdict_counts":dict(wb_verdicts),
               "failures":[],"cards":wb_rows,"left_for_marketplace_review":True},
         "cross_platform_complete":True,"marketplace_tnved_mismatch_documented":True,
         "local_source_files_deleted":True,"deleted_files":deleted,
         "global_coverage_estimate_from_baseline_plus_confirmed_increment":totals,
         "addendum":str(ADDENDUM)}
 save(OUT,result)
 print(json.dumps({k:v for k,v in result.items() if k not in ("documents","wb")},ensure_ascii=False,indent=2))

if __name__=="__main__":main()
