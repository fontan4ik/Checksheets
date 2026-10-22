"""Delete the one Arlight 79626/26 source PDF after exact Ozon and WB confirmation."""
from __future__ import annotations
import csv, hashlib, json, pathlib, sys
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import now
SOURCE=ROOT/'output_to_user/certificates/group_1/documents/arlight/AF84AD86AF506A41B7A2C69EC958CA8B.pdf'
PREFLIGHT=json.loads((HERE/'arlight_79626_preflight_live_20261021.json').read_text())
OZON=json.loads((HERE/'arlight_79626_ozon_final_readback_20261021.json').read_text())
WB=json.loads((HERE/'arlight_79626_wb_delayed_readback_20261021.json').read_text())
ASSIGN=ROOT/'output_to_user/certificates/document_assignments.csv'
RECEIPT=HERE/'arlight_79626_local_cleanup_20261021.json'
JOURNAL=HERE/'arlight_79626_local_cleanup_journal_20261021.jsonl'
if RECEIPT.exists() or JOURNAL.exists(): raise RuntimeError('cleanup_artifact_exists')
if not SOURCE.is_file(): raise RuntimeError('source_pdf_missing')
h=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
if h!=PREFLIGHT.get('source_pdf_sha256'): raise RuntimeError('source_pdf_hash_changed')
if not (OZON.get('complete') is True and OZON.get('verified_target_bindings')==70
        and OZON.get('binding_status_counts')=={'approved':70}): raise RuntimeError('ozon_confirmation_incomplete')
if not (WB.get('complete') is True and WB.get('verified_target_cards')==70
        and WB.get('status_counts')=={'valid':70} and not WB.get('failures')): raise RuntimeError('wb_confirmation_incomplete')
rows=[]
with ASSIGN.open(encoding='utf-8-sig',newline='') as f:
 for r in csv.DictReader(f):
  if '79626' in str(r.get('Номер/название документа') or ''):
   rows.append(r)
offers={str(r.get('Артикул продавца') or '').strip() for r in rows}
files={str(r.get('Локальный файл') or '').strip() for r in rows}
if len(rows)!=70 or len(offers)!=70 or files!={'output_to_user/certificates/group_1/documents/arlight/AF84AD86AF506A41B7A2C69EC958CA8B.pdf'}:
 raise RuntimeError('assignment_manifest_changed_or_incomplete')
if any(str(r.get('Бренд подтвержденный') or '').strip()!='Arlight' for r in rows): raise RuntimeError('assignment_brand_conflict')
entry={'phase':'prepared_for_delete','at':now(),'path':str(SOURCE),'sha256':h,'bytes':SOURCE.stat().st_size,
       'assignments':70,'ozon_approved_bindings':70,'wb_valid_cards':70}
with JOURNAL.open('a',encoding='utf-8') as f: f.write(json.dumps(entry,ensure_ascii=False)+'\n')
size=SOURCE.stat().st_size
SOURCE.unlink()
if SOURCE.exists(): raise RuntimeError('source_pdf_still_exists_after_unlink')
receipt={**entry,'phase':'deleted_and_verified_absent','verified_at':now(),'bytes_reclaimed':size,
         'same_hash_copies_left':0,'local_pdf_deleted':True,
         'ozon_evidence':OZON['complete'],'wb_evidence':WB['complete']}
tmp=RECEIPT.with_suffix('.tmp');tmp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2));tmp.replace(RECEIPT)
with JOURNAL.open('a',encoding='utf-8') as f: f.write(json.dumps(receipt,ensure_ascii=False)+'\n')
print(json.dumps(receipt,ensure_ascii=False,indent=2))
