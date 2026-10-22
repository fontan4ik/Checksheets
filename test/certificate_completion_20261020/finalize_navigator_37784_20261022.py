#!/usr/bin/env python3
"""Clean only byte-identical Navigator certificate source after delayed readback."""
from __future__ import annotations
import hashlib,json,pathlib
from datetime import datetime,timezone
ROOT=pathlib.Path('/Volumes/жесткач/Code2/Checksheets_Project/Checksheets'); BASE=ROOT/'test/certificate_completion_20261020'
pre=json.loads((BASE/'navigator_37784_scope_preflight_20261022.json').read_text())
exec_state=json.loads((BASE/'navigator_37784_execution_20261022.json').read_text())
rb=json.loads((BASE/'navigator_37784_delayed_readback_20261022.json').read_text())
source=ROOT/'output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_eac_certificate_94205_dc533601c1bf.pdf'
final=BASE/'navigator_37784_final_crossplatform_readback_20261022.json'
assert pre['target_count']==pre['ozon_eligible_targets']==pre['wb_eligible_targets']==32
assert not pre['ozon_record_matches']
assert exec_state['ozon_record']['status_code']=='approved'
assert rb['ozon_certificate_id']==exec_state['ozon_record']['certificate_id']
assert rb['ozon_record_status']=='approved' and rb['ozon_exact_bindings']==32
assert rb['ozon_binding_status_counts']=={'approved':32}
assert rb['wb_target_cards']==rb['wb_exact_cards']==32
assert rb['wb_status_counts']=={'verified_exact':32} and rb['wb_verdict_counts']=={'valid':32}
assert not rb['failures'] and rb['wb_review_state_changed_by_agent'] is False
assert rb['wb_left_for_marketplace_review'] is True
assert source.is_file()
sha=hashlib.sha256(source.read_bytes()).hexdigest(); assert sha==pre['source_pdf_sha256']=='dc533601c1bf7a15e633d901b1cd189a2669dd1ef4a4cc6273e14feb1a22270d'
matching=[]
for p in ROOT.rglob('*.pdf'):
 if p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==sha: matching.append(p)
assert source in matching
now=datetime.now(timezone.utc).isoformat()
proof={'checked_at_utc':now,'document_number':pre['number'],'source_pdf_sha256':sha,'source_files_matching_hash':[str(p) for p in matching],
 'ozon':{'certificate_id':rb['ozon_certificate_id'],'record_status':rb['ozon_record_status'],'exact_product_sku_bindings':rb['ozon_exact_bindings'],'binding_status_counts':rb['ozon_binding_status_counts']},
 'wb':{'exact_cards':rb['wb_exact_cards'],'total_cards':rb['wb_target_cards'],'verdict_counts':rb['wb_verdict_counts'],'left_for_marketplace_review':True,'review_state_changed_by_agent':False},
 'tnved_discrepancy':{'certificate':'8539219200','ozon':'8539213009','wb':'8539520009','marketplace_codes_changed':False},
 'scope_preflight':str(BASE/'navigator_37784_scope_preflight_20261022.json'),'delayed_readback':str(BASE/'navigator_37784_delayed_readback_20261022.json'),
 'cleanup_basis':'Delayed readback confirms the approved Ozon record and all 32 exact approved bindings, and exact type/number/date on all 32 WB cards; all WB verdicts are valid and unrelated card fields and prior documents are preserved.',
 'deleted_files':[],'local_source_files_deleted':False}
final.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
for p in matching: p.unlink(); proof['deleted_files'].append(str(p))
proof['local_source_files_deleted']=True; proof['checked_at_utc']=datetime.now(timezone.utc).isoformat()
final.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
state_path=BASE/'navigator_37784_execution_20261022.json'; st=json.loads(state_path.read_text()); st.update({'phase':'cross_marketplace_readback_complete_sources_cleaned','local_source_deleted':True,'source_cleanup':{'deleted_files':proof['deleted_files'],'source_sha256':sha,'basis':proof['cleanup_basis']},'final_readback_artifact':str(final),'finished_at_utc':proof['checked_at_utc']}); state_path.write_text(json.dumps(st,ensure_ascii=False,indent=2)+'\n')
addp=BASE/'postwrite_coverage_addendum_20261022.json'; add=json.loads(addp.read_text())
entry={'brand':'Navigator','document_number':pre['number'],'type':'certificate_of_conformity','source_sha256':sha,'ozon_certificate_id':rb['ozon_certificate_id'],'ozon_record_status':rb['ozon_record_status'],'ozon_exact_bindings':32,'ozon_binding_status_counts':rb['ozon_binding_status_counts'],'wb_exact_cards':32,'wb_valid_cards':32,'wb_review_state_changed_by_agent':False,'wb_left_for_marketplace_review':True,'tnved_discrepancy_documented':True,'local_source_pdf_deleted':True,'verification_artifacts':['navigator_37784_scope_proof_20261022.json','navigator_37784_scope_preflight_20261022.json','navigator_37784_execution_20261022.json','navigator_37784_delayed_readback_20261022.json','navigator_37784_final_crossplatform_readback_20261022.json']}
entries=add.setdefault('post_snapshot_writes',[]); entries[:]=[x for x in entries if x.get('document_number')!=pre['number']]; entries.append(entry)
add.setdefault('verification_artifacts',{})['navigator_37784_final_readback']=str(final)
add.setdefault('local_source_cleanup',{})['navigator_37784_20261022']={'deleted_files':[{'source_file':str(pathlib.Path(x).relative_to(ROOT)),'sha256':sha,'document_number':pre['number'],'deleted':True} for x in proof['deleted_files']],'checked_at_utc':proof['checked_at_utc'],'basis':proof['cleanup_basis']}
add['complete']=False; add['local_source_pdfs_deleted']=False; add['checked_at_utc']=proof['checked_at_utc']; addp.write_text(json.dumps(add,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'final_artifact':str(final),'deleted_files':proof['deleted_files'],'ozon_bindings':32,'wb_exact_valid':32,'overall_complete':False},ensure_ascii=False,indent=2))
