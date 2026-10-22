from __future__ import annotations
import csv,datetime as dt,hashlib,json,pathlib
HERE=pathlib.Path(__file__).resolve().parent;ROOT=HERE.parents[1]
PDF=ROOT/'output_to_user/certificates/group_1/documents/arlight/772DD20BAEF0AD4FA297663655BFAC3A.pdf'
EXPECTED_COPY_PATHS={
    PDF,
    ROOT/'output_to_user/certificates/additional_search/brand_research/arlight/docs/supplier_011750_nya5ni1p8ggar8l4n1hm5o8ofn6bztsg.pdf',
    ROOT/'output_to_user/certificates/additional_search/brand_research/arlight/docs/772DD20BAEF0AD4FA297663655BFAC3A.pdf',
    ROOT/'output_to_user/certificates/additional_search/brand_research/arlight/docs/supplier_batch_nya5ni1p8ggar8l4n1hm5o8ofn6bztsg.pdf',
}
CROSS=HERE/'arlight_03451_crossplatform_readback_final_20261021.json'
OZON=HERE/'arlight_03451_ozon_final_recheck_20261021_0948.json'
WB=HERE/'arlight_03451_remaining_8_wb_delayed_readback_20261021.json'
RECEIPT=HERE/'arlight_03451_local_pdf_cleanup_receipt_20261021.json'
JOURNAL=HERE/'arlight_03451_local_pdf_cleanup_journal_20261021.jsonl'
SUMMARY=HERE/'post_upload_reconciliation_20261020.json';MD=HERE/'post_upload_reconciliation_20261020.md';GLOBAL=HERE/'all_found_coverage_summary_20261021.json'
NUMBER='ЕАЭС RU С-HK.НА46.В.03451/22';SHA='22f5bd0657cf8c55754b3bd0d73d102de1b9520d6c167242555ae63349398add';EXPECTED=462

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n');t.replace(p)
def main():
 if RECEIPT.exists() or JOURNAL.exists():raise RuntimeError('cleanup_artifact_exists_inspect_before_retry')
 cross=json.loads(CROSS.read_text());oz=json.loads(OZON.read_text());wb=json.loads(WB.read_text())
 if (not cross.get('complete') or not cross.get('crossplatform_all_targets_confirmed') or cross.get('number')!=NUMBER or cross.get('source_pdf_sha256')!=SHA):raise RuntimeError('crossplatform_gate_failed')
 if (not oz.get('complete') or oz.get('certificate_id')!='5925989' or oz.get('certificate_status')!='approved' or oz.get('target_count')!=EXPECTED or oz.get('binding_count')!=EXPECTED or oz.get('exact_target_binding_count')!=EXPECTED or oz.get('identity_mismatch_count')!=0 or oz.get('binding_status_counts')!={'approved':EXPECTED}):raise RuntimeError('ozon_approved_binding_gate_failed')
 if (not wb.get('complete') or wb.get('target_cards')!=8 or wb.get('verified_target_cards')!=8 or wb.get('failures') or wb.get('status_counts')!={'pending_review_or_verdict_missing':8} or wb.get('wb_review_left_pending') is not True or wb.get('mutation_resent') is not False):raise RuntimeError('latest_wb_delayed_readback_gate_failed')
 cardcounts=cross['wildberries']
 if (cardcounts.get('target_count')!=EXPECTED or cardcounts.get('exact_document_cards')!=EXPECTED or cardcounts.get('metadata_exact_cards')!=EXPECTED or cardcounts.get('prior_documents_preserved')!=EXPECTED or cardcounts.get('unrelated_fields_preserved')!=EXPECTED or cardcounts.get('wb_review_left_pending') is not True or cardcounts.get('manual_review_action_taken') is not False):raise RuntimeError('combined_wb_confirmation_gate_failed')
 if not PDF.is_file() or sha(PDF)!=SHA or PDF.stat().st_size!=1185814:raise RuntimeError('source_pdf_identity_changed')
 assignments=HERE/'all_confirmed_source_assignments_live_20261021.csv'
 with assignments.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
 hits=[r for r in rows if PDF.name in str(r.get('source_files') or '') and r.get('normalized_number')=='RUCHKHA46B0345122']
 if len(hits)!=EXPECTED or {r.get('brand') for r in hits}!={'Arlight'} or {r.get('type') for r in hits}!={'certificate_of_conformity'}:raise RuntimeError('assignment_file_usage_changed')
 assignment_csv=ROOT/'output_to_user/certificates/document_assignments.csv'
 with assignment_csv.open(encoding='utf-8-sig',newline='') as f:assignment_rows=list(csv.DictReader(f))
 assignment_hits=[r for r in assignment_rows if str(r.get('Локальный файл') or '').endswith(PDF.name)]
 ozon_offers={str(x.get('offer_id')) for x in oz.get('bindings',[])}
 wb_offers={str(x.get('offer_id')) for x in cardcounts.get('cards',[])}
 live_offers={str(r.get('offer_id')) for r in hits}
 assignment_offers={str(r.get('Артикул продавца')) for r in assignment_hits}
 if len(assignment_hits)!=EXPECTED or not (live_offers==assignment_offers==ozon_offers==wb_offers):raise RuntimeError('crossplatform_assignment_offer_sets_differ')
 copies=[]
 for path in ROOT.rglob('*.pdf'):
  if any(part in {'.git','node_modules','.venv','venv'} for part in path.parts):continue
  if path.is_file() and sha(path)==SHA:copies.append(path)
 copies=sorted(copies)
 expected=sorted(EXPECTED_COPY_PATHS)
 if copies!=expected:raise RuntimeError('duplicate_copy_set_changed:'+json.dumps([str(p) for p in copies],ensure_ascii=False))
 if any(p.stat().st_size!=1185814 for p in copies):raise RuntimeError('duplicate_copy_size_changed')
 sizes={str(p):p.stat().st_size for p in copies};total_size=sum(sizes.values());at=dt.datetime.now(dt.timezone.utc).isoformat()
 with JOURNAL.open('a',encoding='utf-8') as f:f.write(json.dumps({'phase':'prepared','at_utc':at,'source':str(PDF),'copies':{str(p):sizes[str(p)] for p in copies},'sha256':SHA,'bytes_total':total_size,'assignment_rows_using_hash':len(hits),'ozon_approved_bindings':EXPECTED,'wb_exact_documents':EXPECTED},ensure_ascii=False)+'\n')
 for path in copies:path.unlink()
 remaining=[str(path) for path in ROOT.rglob('*.pdf') if not any(part in {'.git','node_modules','.venv','venv'} for part in path.parts) and path.is_file() and sha(path)==SHA]
 if remaining:raise RuntimeError('identical_source_copy_remains:'+json.dumps(remaining,ensure_ascii=False))
 receipt={'deleted_at_utc':at,'number':NUMBER,'fsa_registry_record':3008100,'fsa_registry_status':'Действует','issue_date':'2022-04-16','expiry_date':'2027-04-15','source_path':str(PDF),'source_paths_deleted':[str(p) for p in copies],'sha256':SHA,'bytes_per_copy':1185814,'copy_count_deleted':len(copies),'bytes_deleted':total_size,'identical_local_copies_before_delete':[str(p) for p in copies],'assignment_rows_using_pdf':len(assignment_hits),'live_assignment_rows_for_document':len(hits),'ozon_certificate_id':5925989,'ozon_status':'approved','ozon_exact_approved_bindings':EXPECTED,'ozon_binding_status_counts':{'approved':EXPECTED},'wb_target_cards':EXPECTED,'wb_exact_document_cards':EXPECTED,'wb_document_verdicts':{'pending_review_or_verdict_missing':EXPECTED},'wb_review_left_pending':True,'manual_review_action_taken':False,'source_deleted_only_after_both_platform_readbacks':True,'no_identical_pdf_copy_remains':True,'evidence_files':[str(CROSS),str(OZON),str(WB),str(HERE/'arlight_03451_remaining_8_wb_execution_20261021.json'),str(HERE/'arlight_03451_remaining_8_wb_mutation_journal_20261021.jsonl')]}
 save(RECEIPT,receipt)
 with JOURNAL.open('a',encoding='utf-8') as f:f.write(json.dumps({'phase':'deleted','at_utc':at,'receipt':str(RECEIPT),'sha256':SHA,'copies':len(copies),'bytes':total_size},ensure_ascii=False)+'\n')
 for p in (CROSS,OZON,WB):
  x=json.loads(p.read_text());x['source_pdf_deleted']=True;x['source_pdf_cleanup_receipt']=str(RECEIPT);save(p,x)
 summary=json.loads(SUMMARY.read_text());summary['checked_at']=at
 summary['local_source_files_deleted_count']=int(summary.get('local_source_files_deleted_count') or 0)+len(copies)
 summary['local_source_files_deleted_bytes']=int(summary.get('local_source_files_deleted_bytes') or 0)+total_size
 summary.setdefault('local_source_files_deleted_documents',[]).append({'number':NUMBER,'path':str(PDF),'paths_deleted':[str(p) for p in copies],'sha256':SHA,'copy_count':len(copies),'bytes_each':1185814,'bytes':total_size,'ozon_approved_bindings':EXPECTED,'wb_exact_document_cards':EXPECTED,'wb_review_left_pending':True,'receipt':str(RECEIPT)})
 cont=summary.setdefault('latest_continuation',{});cont['checked_at_utc']=at
 cont['local_source_files_deleted_in_continuation']=int(cont.get('local_source_files_deleted_in_continuation') or 0)+len(copies)
 cont['local_source_file_bytes_deleted_in_continuation']=int(cont.get('local_source_file_bytes_deleted_in_continuation') or 0)+total_size
 cont['local_source_files_deleted']=True
 cont['arlight_03451_22']={'number':NUMBER,'source_pdf_sha256':SHA,'ozon_certificate_id':5925989,'ozon_record_status':'approved','ozon_exact_target_bindings':EXPECTED,'ozon_binding_status_counts':{'approved':EXPECTED},'wb_exact_target_cards':EXPECTED,'wb_cards_with_exact_document':EXPECTED,'wb_blank_tnved_confirmed_by_exact_offer_brand_model_or_specs':256,'wb_document_verdict_counts':{'pending_review_or_verdict_missing':EXPECTED},'wb_review_left_pending':True,'wb_manual_review_action_taken':False,'wb_blank_tnved_unresolved':0,'wb_unresolved_reasons':{},'wb_write_result':'The remaining 8 cards were accepted in one batch; immediate readback saw 3/8, delayed readback confirmed 8/8. No update was resent.','local_source_pdf_deleted':True,'local_source_pdf_copies_deleted':len(copies),'local_source_pdf_hash_verified':True,'local_source_pdf_bytes_deleted':total_size,'cleanup_receipt':str(RECEIPT),'overall_coverage_complete':False,'evidence_files':[p.name for p in (CROSS,OZON,WB,RECEIPT)]}
 cont['overall_coverage_complete']=False;save(SUMMARY,summary)
 global_summary=json.loads(GLOBAL.read_text());global_summary['incremental_followup_arlight_03451_22']=cont['arlight_03451_22'];global_summary['incremental_followup_arlight_03451_22']['checked_at_utc']=at;save(GLOBAL,global_summary)
 body=MD.read_text(encoding='utf-8');start=body.find('## Arlight certificate 03451/22 — 2026-10-21')
 if start<0:raise RuntimeError('report_section_missing')
 nextpos=body.find('\n## Continued — Arlight 46747/26 — 2026-10-21',start)
 if nextpos<0:raise RuntimeError('next_report_section_missing')
 section=('## Arlight certificate 03451/22 — 2026-10-21\n\n'
 '- The manufacturer certificate `ЕАЭС RU С-HK.НА46.В.03451/22` is valid 16.04.2022–15.04.2027 and covers Arlight power-supply series ARJ, ARPJ, ARPV and ARV. Its source PDF SHA-256 is `'+SHA+'`.\n'
 '- Fresh Ozon readback confirms record 5925989 is `approved` and all 462 exact product/SKU bindings are `approved`.\n'
 '- WB now shows the exact document number, type and dates on all 462 assigned cards. The 206 cards with in-scope TN VED were matched directly; 256 blank-TN-VED cards were confirmed through exact seller-offer, brand and Ozon product/model evidence. The final eight were added in one accepted batch and confirmed after delayed readback; no write was repeated. Prior documents and unrelated fields are preserved on all 462 cards. WB review remains pending on all 462; no manual review action was taken.\n'
 '- Deleted all four identical local PDF copies (4,743,256 bytes total) only after exact Ozon bindings and WB card readbacks were confirmed; no copy with this SHA-256 remains in the workspace. Receipt: `arlight_03451_local_pdf_cleanup_receipt_20261021.json`.\n'
 '- Evidence: `arlight_03451_crossplatform_readback_final_20261021.json`, `arlight_03451_ozon_final_recheck_20261021_0948.json`, `arlight_03451_remaining_8_wb_delayed_readback_20261021.json`. Overall all-brand/all-product completion remains incomplete.\n\n')
 MD.write_text(body[:start]+section+body[nextpos+1:],encoding='utf-8')
 print(json.dumps({'deleted':True,'paths': [str(p) for p in copies],'sha256':SHA,'copies_deleted':len(copies),'bytes_deleted':total_size,'ozon_approved':EXPECTED,'wb_exact_documents':EXPECTED,'wb_review_left_pending':True,'receipt':str(RECEIPT)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
