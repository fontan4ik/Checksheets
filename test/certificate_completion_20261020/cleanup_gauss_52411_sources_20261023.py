#!/usr/bin/env python3
"""Move confirmed duplicate Gauss 52411/23 local PDFs to recoverable Trash."""
from __future__ import annotations
import csv, datetime as dt, hashlib, json, os, pathlib, subprocess
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[1]
REPORT=HERE/'gauss_52411_final_verified_crossplatform_20261023.json'
WB=HERE/'gauss_52411_wb_fresh_recheck_20261023.json'
PREFLIGHT=HERE/'gauss_52411_crossplatform_preflight_20261023.json'
RECEIPT=HERE/'gauss_52411_local_pdf_cleanup_20261023.json'
SHA='b9503157b344ec2ed68fe168f8b7c9f7046d28a1e7734b8a9949589c5b12ad3d'
FILES=[
 ROOT/'output_to_user/certificates/group_1/documents/gauss/25aeb2f93ed587f14b19dc21.pdf',
 ROOT/'output_to_user/certificates/additional_search/brand_research/gauss/docs/gfl_rechargeable_037.pdf',
]
def digest(p:pathlib.Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def main():
 if RECEIPT.exists():raise RuntimeError('receipt_exists; inspect before retry')
 report=json.loads(REPORT.read_text()); wb=json.loads(WB.read_text()); pre=json.loads(PREFLIGHT.read_text())
 checked=dt.datetime.fromisoformat(report['checked_at_utc'].replace('Z','+00:00'))
 if report.get('read_only') is not True or (dt.datetime.now(dt.timezone.utc)-checked).total_seconds()>3600:raise RuntimeError('crossplatform_readback_stale')
 if report.get('number')!='ЕАЭС N RU Д-CN.РА04.В.52411/23' or report.get('ozon_record_status')!='approved' or report.get('ozon_target_count')!=26 or report.get('ozon_exact_approved_count')!=26:raise RuntimeError('ozon_verification_not_complete')
 if report.get('ozon_out_of_scope_skipped')!=['GF001-1','GF002-1','GF801-1']:raise RuntimeError('unexpected_ozon_scope_exclusions')
 if wb.get('read_only') is not True or wb.get('targets')!=29 or wb.get('exact_count')!=29 or wb.get('status_counts')!={'valid':29} or wb.get('missing_count')!=0:raise RuntimeError('wb_verification_not_complete')
 if len(pre.get('targets',[]))!=29:raise RuntimeError('preflight_target_count_changed')
 if not all(x.get('ozon_safe') is True or x['offer_id'] in report['ozon_out_of_scope_skipped'] for x in pre['targets']):raise RuntimeError('unexpected_preflight_target')
 if len(FILES)!=2 or any(not p.is_file() or digest(p)!=SHA for p in FILES):raise RuntimeError('source_hash_or_presence_mismatch')
 # The master catalog must show this PDF as one declaration with exactly the same 29 assigned offers.
 found=[]
 with (ROOT/'output_to_user/certificates/document_catalog_master.csv').open(newline='',encoding='utf-8-sig') as f:
  for row in csv.DictReader(f):
   if row.get('SHA256')==SHA:found.append(row)
 if len(found)!=1 or int(found[0].get('Связанных артикулов') or 0)!=29:raise RuntimeError('source_catalog_assignment_count_mismatch')
 offers=set(found[0].get('Артикулы','').split('; '))
 if len(offers)!=29 or offers!={x['offer_id'] for x in pre['targets']}:raise RuntimeError('source_catalog_target_set_mismatch')
 entries=[{'original_path':str(p),'sha256':digest(p),'size_bytes':p.stat().st_size,'moved_to_trash':False,'recovery_path':None} for p in FILES]
 state={'prepared_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'status':'prepared','document_number':report['number'],'verification_report':str(REPORT),'verification_checked_at_utc':report['checked_at_utc'],'ozon_approved_bindings':26,'wb_valid_card_bindings':29,'ozon_out_of_scope_skips':report['ozon_out_of_scope_skipped'],'files':entries,'trash_tool':'/usr/bin/trash','trash_was_not_emptied':True}
 RECEIPT.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
 result=subprocess.run(['/usr/bin/trash',*[str(p) for p in FILES]],capture_output=True,text=True)
 state['trash_exit_code']=result.returncode; state['trash_stdout']=result.stdout.strip();state['trash_stderr']=result.stderr.strip()
 if result.returncode:state['status']='trash_move_failed';RECEIPT.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n');raise RuntimeError('trash_move_failed')
 if any(p.exists() for p in FILES):state['status']='post_move_verification_failed';RECEIPT.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n');raise RuntimeError('source_still_present')
 roots=[pathlib.Path(f'/Volumes/жесткач/.Trashes/{os.getuid()}'),pathlib.Path.home()/'.Trash']
 for e in entries:
  name=pathlib.Path(e['original_path']).name;matches=[]
  for root in roots:
   if root.exists():matches += [p for p in root.rglob(name) if p.is_file()]
  valid=[p for p in matches if digest(p)==SHA]
  e['moved_to_trash']=bool(valid);e['matching_trash_copies']=len(valid);e['recovery_path']=str(valid[0]) if len(valid)==1 else None
 state.update({'status':'moved_to_trash','finished_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'all_original_paths_absent':all(not p.exists() for p in FILES),'all_sources_recoverable':all(e['moved_to_trash'] and e['matching_trash_copies']==1 for e in entries)})
 RECEIPT.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'status':state['status'],'file_count':len(entries),'all_original_paths_absent':state['all_original_paths_absent'],'all_sources_recoverable':state['all_sources_recoverable'],'receipt':str(RECEIPT),'files':[{'name':pathlib.Path(e['original_path']).name,'sha256':e['sha256'],'recovery_path':e['recovery_path']} for e in entries]},ensure_ascii=False))
if __name__=='__main__':main()
