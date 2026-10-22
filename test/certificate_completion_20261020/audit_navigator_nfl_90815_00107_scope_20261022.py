from __future__ import annotations
import csv, hashlib, json, re
from pathlib import Path
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
PREFLIGHT=HERE/'navigator_nfl_90815_00107_fresh_v2_20261022.json'
OCR=HERE/'navigator_00107_certificate_ocr_20261022.json'
ASSIGN=ROOT/'output_to_user/certificates/document_assignments.csv'
DOCS={
 'declaration': {'number':'ЕАЭС N RU Д-RU.РА11.В.90815/24','file':ROOT/'output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_declaration_14150_fb47c7e7dab0.pdf','sha256':'fb47c7e7dab06d12e4560432589f86a8303cca3431ada97a4c0e00aea0763fc5','issue':'2024-12-27','expiry':'2029-12-25','tnved':'9405420012'},
 'certificate': {'number':'ЕАЭС RU С-RU.НВ28.В.00107/24','file':ROOT/'output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_eac_certificate_14150_f7b78b7b869e.pdf','sha256':'f7b78b7b869ebc131519ea8694ee0fa33f2d6afc1c38ec9aedc9963f5778bf8e','issue':'2024-12-24','expiry':'2029-12-23','tnved':'9405420012'}
}
def norm(s):return re.sub(r'[^A-Z0-9]','',str(s or '').upper())
pre=json.loads(PREFLIGHT.read_text());ocr=json.loads(OCR.read_text())
rows=[]
with ASSIGN.open(encoding='utf-8-sig',newline='') as f:
 for row in csv.DictReader(f):
  if row.get('Номер/название документа')==DOCS['declaration']['number']:
   source=json.loads(row.get('Исходная запись JSON') or '{}')
   rows.append({'offer_id':row.get('Артикул продавца'),'model_heading':source.get('provider_exact_product_heading'),'source_row_status':source.get('document_status'),'declared_valid_until':source.get('valid_until'),'pdf_hash':source.get('sha256')})
if len({x['offer_id'] for x in rows})!=11: raise RuntimeError('source_target_offer_count_mismatch')
cert_text=norm(' '.join(line for page in ocr for line in page['lines']))
decl_text=norm(' '.join((page.extract_text() or '') for page in PdfReader(str(DOCS['declaration']['file'])).pages))
for row in rows:
 m=re.search(r'NFL-[A-Z0-9.-]+',row['model_heading'] or '',re.I)
 if not m: raise RuntimeError('model_missing_from_source_heading:'+str(row['offer_id']))
 model=m.group(0); key=norm(model)
 row['exact_model']=model
 row['model_found_in_declaration_appendix']=key in decl_text
 row['model_found_in_certificate_appendix_ocr']=key in cert_text
 if not row['model_found_in_declaration_appendix'] or not row['model_found_in_certificate_appendix_ocr']:
  raise RuntimeError('model_not_found_in_both_document_scopes:'+str(row['offer_id'])+':'+model)
for key,d in DOCS.items():
 if hashlib.sha256(d['file'].read_bytes()).hexdigest()!=d['sha256']: raise RuntimeError('source_pdf_hash_mismatch:'+key)
if pre.get('target_count')!=11 or pre.get('ozon_eligible_targets')!=11 or pre.get('wb_eligible_targets')!=11: raise RuntimeError('fresh_preflight_not_all_eligible')
if pre.get('ozon_tnved_distribution')!={'9405420012':11} or pre.get('wb_tnved_distribution')!={'9405420012':11}: raise RuntimeError('live_tnved_mismatch')
if pre.get('ozon_record_matches')!={'declaration':[],'certificate':[]}: raise RuntimeError('ozon_duplicate_or_existing_record')
if any(x.get('wb_brand')!='Navigator Group' for x in pre.get('targets',[])): raise RuntimeError('wb_brand_alias_changed')
if pre.get('wb_declaration_valid') or pre.get('wb_certificate_valid'): raise RuntimeError('wb_document_already_present_or_valid')
for row in rows:
 target=next(x for x in pre['targets'] if x['offer_id']==row['offer_id'])
 row.update({'ozon_eligible':target['ozon_eligible'],'ozon_tnved':target['ozon_tnved'],'ozon_product_name':target['product_name'],'wb_eligible':target['wb_eligible'],'wb_tnved':target['wb_tnved'],'wb_brand':target.get('wb_brand'),'wb_nmID':target['wb_nmID']})
result={'checked_at_utc':pre['checked_at_utc'],'read_only':True,'declaration_document':{**{k:v for k,v in DOCS['declaration'].items() if k!='file'},'source_file':str(DOCS['declaration']['file'])},'certificate_document':{**{k:v for k,v in DOCS['certificate'].items() if k!='file'},'source_file':str(DOCS['certificate']['file'])},'certificate_explicit_scope':'Navigator NFL series; Appendix 1 lists exact model variants including all 11 below; TN VED 9405420012.','declaration_explicit_scope':'Navigator NFL series; Appendix 1 lists exact model variants including all 11 below; TN VED 9405420012.','date_limit_from_declaration':'series production manufactured on or after sample manufacture date 2024-06-01','target_count':11,'target_rows':rows,'ozon_preflight_summary':{k:pre[k] for k in ['ozon_eligible_targets','ozon_skipped_targets','ozon_tnved_distribution','ozon_record_matches']},'wb_preflight_summary':{k:pre[k] for k in ['wb_eligible_targets','wb_skipped_targets','wb_tnved_distribution','wb_declaration_valid','wb_certificate_valid']},'wb_brand_alias_observed':'Navigator Group; original field left unchanged','all_models_present_in_both_scopes':True,'local_source_files_deleted':False}
path=HERE/'navigator_nfl_90815_00107_scope_audit_20261022.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'checked_at_utc':result['checked_at_utc'],'target_count':11,'models':[r['exact_model'] for r in rows],'all_models_in_both_scopes':True,'ozon_tnved_distribution':pre['ozon_tnved_distribution'],'wb_tnved_distribution':pre['wb_tnved_distribution'],'wb_brand_alias':'Navigator Group','files_kept':True},ensure_ascii=False,indent=2))
