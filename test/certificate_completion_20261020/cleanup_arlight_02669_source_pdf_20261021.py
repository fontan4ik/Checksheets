from __future__ import annotations
import csv,datetime as dt,hashlib,json,pathlib,sys
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PDF=ROOT/'output_to_user/certificates/group_1/documents/arlight/B40746683BE4E24A9A25CD278FD53917.pdf'
PREFLIGHT=HERE/'arlight_02669_crossplatform_preflight_live_20261021.json'
OZON=HERE/'arlight_02669_ozon_final_recheck_20261021.json'
WB=HERE/'arlight_02669_wb_readback_20261021.json'
STATE_OZON=HERE/'arlight_02669_ozon_execution_20261021.json'
STATE_WB=HERE/'arlight_02669_wb_execution_20261021.json'
RECEIPT=HERE/'arlight_02669_local_pdf_cleanup_receipt_20261021.json'
JOURNAL=HERE/'arlight_02669_local_pdf_cleanup_journal_20261021.jsonl'
SUMMARY=HERE/'post_upload_reconciliation_20261020.json'
SUMMARY_MD=HERE/'post_upload_reconciliation_20261020.md'
GLOBAL=HERE/'all_found_coverage_summary_20261021.json'
NUMBER='ЕАЭС RU С-HK.АБ53.В.02669/21'
SHA='9b9c776c47d6e805fc9a18b4717a64407b348289c7b0dcf4f8c42de5e90b275f'
EXPECTED=578

def hash_file(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,obj):
 t=p.with_suffix(p.suffix+'.tmp'); t.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n'); t.replace(p)
def main():
 if RECEIPT.exists() or JOURNAL.exists(): raise RuntimeError('cleanup_receipt_exists_inspect_before_retry')
 pre=json.loads(PREFLIGHT.read_text()); oz=json.loads(OZON.read_text()); wb=json.loads(WB.read_text())
 ozstate=json.loads(STATE_OZON.read_text()); wbstate=json.loads(STATE_WB.read_text())
 if not pre.get('eligible_for_upload') or pre.get('source_pdf_sha256')!=SHA: raise RuntimeError('preflight_source_hash_or_scope_failed')
 if (not oz.get('complete') or oz.get('certificate_id')!='5928221' or oz.get('certificate_status')!='approved' or oz.get('target_count')!=EXPECTED or oz.get('binding_count')!=EXPECTED or oz.get('exact_target_binding_count')!=EXPECTED or oz.get('identity_mismatch_count')!=0 or oz.get('binding_status_counts')!={'approved':EXPECTED}): raise RuntimeError('ozon_all_approved_exact_binding_gate_failed')
 if (ozstate.get('phase')!='ozon_verified_complete' or ozstate.get('verified_target_pairs')!=EXPECTED): raise RuntimeError('ozon_creation_state_gate_failed')
 if (not wb.get('complete') or wb.get('target_cards')!=EXPECTED or wb.get('verified_target_cards')!=EXPECTED or wb.get('failures') or wb.get('status_counts')!={'pending_review_or_verdict_missing':EXPECTED} or wb.get('wb_review_left_pending') is not True): raise RuntimeError('wb_exact_pending_document_gate_failed')
 if (wbstate.get('phase')!='verified_complete' or wbstate.get('writes_sent')!=6 or wbstate.get('wb_review_left_pending') is not True): raise RuntimeError('wb_execution_state_gate_failed')
 for row in wb.get('cards') or []:
  if not (row.get('verified') and row.get('metadata_exact') and row.get('prior_documents_preserved') and row.get('unrelated_fields_preserved') and row.get('identity_preserved') and row.get('brand_preserved')): raise RuntimeError('wb_card_readback_gate_failed:'+str(row.get('offer_id')))
 if not PDF.is_file() or hash_file(PDF)!=SHA: raise RuntimeError('source_pdf_hash_changed')
 assignments=HERE/'all_confirmed_source_assignments_live_20261021.csv'
 with assignments.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
 hits=[r for r in rows if PDF.name in str(r.get('source_files') or '')]
 if len(hits)!=EXPECTED or {r.get('brand') for r in hits}!={'Arlight'} or {r.get('type') for r in hits}!={'certificate_of_conformity'}: raise RuntimeError('source_assignment_usage_changed')
 copies=[]
 for folder in (ROOT/'output_to_user/certificates',HERE/'source_docs',ROOT/'test/certificate_api_pilot_20261012'):
  if folder.exists():
   for p in folder.rglob('*.pdf'):
    if p.is_file() and hash_file(p)==SHA: copies.append(str(p))
 if copies!=[str(PDF)]: raise RuntimeError('identical_copy_set_changed:'+json.dumps(copies,ensure_ascii=False))
 size=PDF.stat().st_size; at=dt.datetime.now(dt.timezone.utc).isoformat()
 with JOURNAL.open('a',encoding='utf-8') as f:
  f.write(json.dumps({'phase':'prepared','at_utc':at,'path':str(PDF),'sha256':SHA,'bytes':size,'ozon_approved_bindings':EXPECTED,'wb_exact_pending_documents':EXPECTED},ensure_ascii=False)+'\n')
 PDF.unlink()
 if PDF.exists(): raise RuntimeError('source_pdf_remains_after_unlink')
 receipt={'deleted_at_utc':at,'number':NUMBER,'fsa_record_id':3008100,'fsa_registry_status':'Действует; official extract dated 2026-10-21','issue_date':'2021-12-08','expiry_date':'2026-12-07','source_path':str(PDF),'sha256':SHA,'bytes_deleted':size,'identical_local_copies_before_delete':copies,'assignment_rows_using_pdf':len(hits),'ozon_certificate_id':5928221,'ozon_certificate_status':'approved','ozon_exact_approved_bindings':EXPECTED,'ozon_binding_status_counts':{'approved':EXPECTED},'wb_exact_document_cards':EXPECTED,'wb_metadata_exact':EXPECTED,'wb_document_verdict':'pending review / verdict not yet returned','wb_review_left_pending':True,'wb_manual_review_action_taken':False,'source_deleted_only_after_both_platform_readbacks':True,'tnved_note':'FSA 2021 extract lists 9405109803; current Ozon/WB cards use current marketplace codes. Product inclusion was verified by exact Arlight assignment and FSA-listed series; no TNVED value was changed.','evidence_files':[str(PREFLIGHT),str(OZON),str(WB),str(STATE_OZON),str(STATE_WB),str(HERE/'fsa_arlight_02669_certificate_extract_20261021.pdf')]}
 save(RECEIPT,receipt)
 with JOURNAL.open('a',encoding='utf-8') as f: f.write(json.dumps({'phase':'deleted','at_utc':at,'receipt':str(RECEIPT),'sha256':SHA,'bytes':size},ensure_ascii=False)+'\n')
 wb['source_pdf_deleted']=True;wb['source_pdf_cleanup_receipt']=str(RECEIPT);save(WB,wb)
 oz['source_pdf_deleted']=True;oz['source_pdf_cleanup_receipt']=str(RECEIPT);save(OZON,oz)
 ozstate['source_pdf_deleted']=True;ozstate['cleanup_receipt']=str(RECEIPT);save(STATE_OZON,ozstate)
 wbstate['local_file_deleted']=True;wbstate['cleanup_receipt']=str(RECEIPT);save(STATE_WB,wbstate)
 pre['local_file_cleanup_allowed']=True;pre['local_file_deleted']=True;pre['local_cleanup_receipt']=str(RECEIPT)
 pre['applicability_assessment']['local_file_cleanup_allowed']=True;save(PREFLIGHT,pre)
 summary=json.loads(SUMMARY.read_text())
 summary['checked_at']=at
 summary['local_source_files_deleted_count']=int(summary.get('local_source_files_deleted_count') or 0)+1
 summary['local_source_files_deleted_bytes']=int(summary.get('local_source_files_deleted_bytes') or 0)+size
 docs=summary.setdefault('local_source_files_deleted_documents',[])
 docs.append({'number':NUMBER,'path':str(PDF),'sha256':SHA,'bytes':size,'ozon_approved_bindings':EXPECTED,'wb_exact_document_cards':EXPECTED,'wb_review_left_pending':True,'receipt':str(RECEIPT)})
 continuation=summary.setdefault('latest_continuation',{})
 continuation['checked_at_utc']=at
 continuation['local_source_files_deleted_in_continuation']=int(continuation.get('local_source_files_deleted_in_continuation') or 0)+1
 continuation['local_source_file_bytes_deleted_in_continuation']=int(continuation.get('local_source_file_bytes_deleted_in_continuation') or 0)+size
 continuation['local_source_files_deleted']=True
 continuation['arlight_02669_21']={'number':NUMBER,'fsa_record_id':3008100,'fsa_status':'active','issue_date':'2021-12-08','expiry_date':'2026-12-07','ozon_certificate_id':5928221,'ozon_certificate_status':'approved','ozon_target_bindings':EXPECTED,'ozon_approved_bindings':EXPECTED,'wb_target_cards':EXPECTED,'wb_exact_documents':EXPECTED,'wb_status':'pending_review','tnved_mismatch_recorded':True,'source_pdf_deleted':True,'source_pdf_bytes_deleted':size,'cleanup_receipt':str(RECEIPT),'evidence_files':[p.name for p in (PREFLIGHT,OZON,WB,STATE_OZON,STATE_WB,RECEIPT)]}
 continuation['overall_coverage_complete']=False
 save(SUMMARY,summary)
 global_summary=json.loads(GLOBAL.read_text())
 global_summary['incremental_followup_arlight_02669_21']=continuation['arlight_02669_21']
 global_summary['incremental_followup_arlight_02669_21']['checked_at_utc']=at
 save(GLOBAL,global_summary)
 body=SUMMARY_MD.read_text(encoding='utf-8')
 heading='## Arlight certificate 02669/21 — 2026-10-21'
 if heading not in body:
  body+='\n\n'+heading+'\n\n'
  body+=('- The official FSA extract (record 3008100) confirms the Arlight serial-production certificate `ЕАЭС RU С-HK.АБ53.В.02669/21` was active on 21.10.2026 and expires 07.12.2026. It names the ART, MAG, FLEX and other Arlight general-purpose luminaire series. The original PDF hash was `'+SHA+'`.\n')
  body+=('- Exact live source assignments and Ozon identity/brand/model checks matched all 578 target SKUs; no Ozon record existed before upload. Ozon record 5928221 is now `approved`, with 578/578 exact product/SKU links all `approved`.\n')
  body+=('- WB returned one exact assigned card for each of 578 offers. The exact number/type/dates are now visible on 578/578 cards; prior documents and unrelated fields are preserved. WB review remains pending by design; no manual review action was taken. The FSA extract uses legacy TN VED `9405109803`, while current marketplace cards show codes `9405190039`, `9405110033` and `9405110039`; this discrepancy is recorded, and no TN VED fields were changed.\n')
  body+=('- After both platform readbacks, deleted the sole local source PDF copy (609,631 bytes). Receipt: `arlight_02669_local_pdf_cleanup_receipt_20261021.json`. The official FSA extract and API evidence remain saved.\n')
  body+=('- Overall all-brand/all-product coverage remains incomplete.\n')
  SUMMARY_MD.write_text(body,encoding='utf-8')
 print(json.dumps({'deleted':True,'path':str(PDF),'sha256':SHA,'bytes_deleted':size,'ozon_approved_bindings':EXPECTED,'wb_exact_document_cards':EXPECTED,'wb_review_left_pending':True,'receipt':str(RECEIPT)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
