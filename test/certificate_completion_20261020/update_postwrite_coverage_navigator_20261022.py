from __future__ import annotations
import csv,datetime,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
path=HERE/'postwrite_coverage_addendum_20261022.json'
data=json.loads(path.read_text())
final=json.loads((HERE/'navigator_nll_and_nfl_ozon_final_bindings_20261022.json').read_text())
source_rows={}
with (ROOT/'output_to_user/certificates/document_assignments.csv').open(encoding='utf-8-sig',newline='') as f:
 for row in csv.DictReader(f):
  n=row.get('Номер/название документа')
  if n and n not in source_rows:
   source_rows[n]={'local_file':row.get('Локальный файл'),'sha256':row.get('SHA256 фактический') or row.get('SHA256 заявленный'),'source_pdf_url':row.get('URL документа')}
configs=[
 {'group':'navigator_nll_08110_06643','brand':'Navigator','preflight':'navigator_nll_08110_06643_fresh_preflight_20261022.json','wb_readback':'navigator_nll_08110_06643_readback_reconciled_20261022.json','docs':[('ЕАЭС N RU Д-CN.РА11.В.08110/24','declaration',5945402),('ЕАЭС RU С-CN.НВ54.В.06643/24','certificate_of_conformity',5945406)]},
 {'group':'navigator_nll_93270_43404','brand':'Navigator','preflight':'navigator_14009_93270_43404_preflight_20261022.json','wb_readback':'navigator_14009_93270_43404_delayed_readback_final_20261022.json','docs':[('ЕАЭС N RU Д-CN.РА08.В.93270/25','declaration',5945811),('ЕАЭС RU С-CN.АЯ46.В.43404/25','certificate_of_conformity',5945813)]},
 {'group':'navigator_nfl_90815_00107','brand':'Navigator','preflight':'navigator_nfl_90815_00107_fresh_v2_20261022.json','wb_readback':'navigator_nfl_90815_00107_wb_delayed_readback_20261022.json','docs':[('ЕАЭС N RU Д-RU.РА11.В.90815/24','declaration',5946929),('ЕАЭС RU С-RU.НВ28.В.00107/24','certificate_of_conformity',5947021)]}
]
known={(x.get('document_number'),x.get('ozon_certificate_id')) for x in data.get('post_snapshot_writes',[])}
added=[]
for cfg in configs:
 pre=json.loads((HERE/cfg['preflight']).read_text())
 wb=json.loads((HERE/cfg['wb_readback']).read_text())
 offers_wb=sorted(x['offer_id'] for x in pre['targets'] if x.get('wb_eligible') is True)
 offers_ozon=sorted(x['offer_id'] for x in pre['targets'] if x.get('ozon_eligible') is True)
 group_final=next(g for g in final['groups'] if g['group']==cfg['group'])
 if wb.get('complete') is not True or wb.get('failures'):
  raise RuntimeError('wb_readback_incomplete:'+cfg['group'])
 for num,doctype,cid in cfg['docs']:
  if (num,cid) in known:continue
  original=source_rows.get(num)
  if not original or not original['local_file']:raise RuntimeError('source_assignment_missing:'+num)
  original_abs=ROOT/original['local_file']
  if not original_abs.is_file():raise RuntimeError('source_pdf_missing:'+num)
  actual_hash=hashlib.sha256(original_abs.read_bytes()).hexdigest()
  if actual_hash!=original['sha256']:raise RuntimeError('source_hash_changed:'+num)
  oz=next(x for x in group_final['documents'] if x['number']==num)
  entry={'brand':cfg['brand'],'source_group':cfg['group'],'document_number':num,'type':doctype,'ozon_certificate_id':cid,'ozon_record_status':oz['record_status'],'ozon_eligible_offers':offers_ozon,'ozon_expected_bindings':oz['expected_bindings'],'ozon_visible_bindings':oz['visible_bindings'],'ozon_binding_status_counts':oz['binding_status_counts'],'ozon_missing_bindings':oz['missing_bindings'],'ozon_outside_bindings':oz['outside_bindings'],'wb_offers':offers_wb,'wb_valid_cards':len(wb['cards']),'wb_valid_document_rows':len(wb['cards']),'wb_readback_complete':True,'wb_readback_failures':0,'local_source_file':str(original_abs),'local_source_sha256':actual_hash,'source_pdf_url':original.get('source_pdf_url'),'local_source_file_deleted':False}
  if cfg['group']=='navigator_nll_08110_06643':entry['ozon_tnved_mismatch_held']=sorted(pre['ozon_skipped_targets'])
  if cfg['group']=='navigator_nfl_90815_00107' and doctype=='certificate_of_conformity':
   up=HERE/'navigator_00107_certificate_ozon_upload_q75_20261022.pdf'
   entry['ozon_uploaded_copy']=str(up);entry['ozon_uploaded_copy_sha256']=hashlib.sha256(up.read_bytes()).hexdigest();entry['ozon_upload_bytes']=up.stat().st_size
  added.append(entry);known.add((num,cid))
if not added:raise RuntimeError('no_new_writes_to_add')
data['post_snapshot_writes'].extend(added)
t=data['post_snapshot_totals']
t['ozon_certificate_records']+=6
t['ozon_certificate_statuses']['approved']+=6
t['ozon_live_bindings']+=282
t['ozon_products_with_at_least_one_current_approved_document']+=141
t['ozon_products_without_any_current_approved_document']-=141
t['wb_cards_with_at_least_one_valid_document']+=238
t['newly_verified_wb_cards']+=238
data['verification_artifacts'].update({
 'navigator_nll_08110_06643_preflight':str(HERE/'navigator_nll_08110_06643_fresh_preflight_20261022.json'),
 'navigator_nll_08110_06643_execution':str(HERE/'navigator_nll_08110_06643_execution_20261022.json'),
 'navigator_nll_08110_06643_wb_readback':str(HERE/'navigator_nll_08110_06643_readback_reconciled_20261022.json'),
 'navigator_nll_93270_43404_preflight':str(HERE/'navigator_14009_93270_43404_preflight_20261022.json'),
 'navigator_nll_93270_43404_execution':str(HERE/'navigator_14009_93270_43404_execution_20261022.json'),
 'navigator_nll_93270_43404_wb_readback':str(HERE/'navigator_14009_93270_43404_delayed_readback_final_20261022.json'),
 'navigator_nll_and_nfl_ozon_final_readback':str(HERE/'navigator_nll_and_nfl_ozon_final_bindings_20261022.json'),
 'navigator_nfl_90815_00107_scope_audit':str(HERE/'navigator_nfl_90815_00107_scope_audit_20261022.json'),
 'navigator_nfl_90815_00107_wb_readback':str(HERE/'navigator_nfl_90815_00107_wb_delayed_readback_20261022.json'),
 'navigator_nfl_90815_00107_ozon_upload_manifest':str(HERE/'navigator_00107_certificate_ozon_upload_q75_20261022.json'),
 'navigator_nfl_90815_00107_ozon_execution':str(HERE/'navigator_00107_ozon_certificate_retry_20261022.json')
})
data['checked_at_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
data['local_source_pdfs_deleted']=False
data['complete']=False
data['limitation']='Totals equal the verified 2026-10-22 baseline plus reconciled writes recorded in post_snapshot_writes; a new full catalog snapshot is still required for a current whole-marketplace total. Ozon TN VED mismatches and products absent from a marketplace remain outside these additions.'
path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'added_entries':len(added),'ozon_total_records':t['ozon_certificate_records'],'ozon_approved_records':t['ozon_certificate_statuses']['approved'],'ozon_live_bindings':t['ozon_live_bindings'],'ozon_products_covered':t['ozon_products_with_at_least_one_current_approved_document'],'ozon_products_without_any_current_approved_document':t['ozon_products_without_any_current_approved_document'],'wb_unique_cards_with_valid_documents':t['wb_cards_with_at_least_one_valid_document'],'newly_verified_wb_cards':t['newly_verified_wb_cards'],'complete':data['complete'],'deleted':data['local_source_pdfs_deleted']},ensure_ascii=False,indent=2))
