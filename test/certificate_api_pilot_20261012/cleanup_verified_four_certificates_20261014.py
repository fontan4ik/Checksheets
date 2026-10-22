"""Move source copies to recoverable Trash only after exact live marketplace checks."""
from __future__ import annotations
import collections, csv, datetime as dt, hashlib, json, re, shutil
from pathlib import Path
BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[1]
PLAN=json.loads((BASE/'cleanup_newly_bound_local_certificates_20261012_plan.json').read_text(encoding='utf-8'))
OZON=json.loads((BASE/'cleanup_four_live_recheck_ozon_20261014.json').read_text(encoding='utf-8'))
WB_PATH=BASE/'wb_catalog_minimal_live_20261014.json'
if not WB_PATH.exists():raise RuntimeError('Fresh complete WB catalog read is not available')
WB=json.loads(WB_PATH.read_text(encoding='utf-8'))
if not WB.get('complete') or not WB.get('read_only'):raise RuntimeError('WB catalog snapshot is incomplete')
if not OZON.get('all_four_ozon_records_approved') or not OZON.get('all_four_exact_target_sets_match'):
 raise RuntimeError('Ozon exact live preconditions did not pass')
def parse_time(s):return dt.datetime.fromisoformat(s.replace('Z','+00:00'))
now=dt.datetime.now(dt.timezone.utc)
for stamp in (OZON['checked_at_utc'],WB['checked_at_utc']):
 if now-parse_time(stamp)>dt.timedelta(hours=2):raise RuntimeError('Marketplace snapshot is older than the 2-hour execution window')
if WB.get('duplicate_vendor_codes'):raise RuntimeError('WB exact vendor codes are duplicated')
by_offer={str(x.get('vendorCode') or ''):x for x in WB['cards']}
with (ROOT/'output_to_user/certificates/document_assignments.csv').open(encoding='utf-8-sig',newline='') as f:
 assignments=list(csv.DictReader(f))
def suffix_key(s):
 m=re.search(r'([0-9]{3,}/[0-9]{2})\s*$',str(s or ''))
 return m.group(1) if m else None
checks=[]
for plan_item,ozon_item in zip(PLAN['accepted'],OZON['documents']):
 if plan_item['number']!=ozon_item['number']:raise RuntimeError('Ozon recheck order/number mismatch')
 suffix=suffix_key(plan_item['number'])
 group=[r for r in assignments if suffix and suffix in (r.get('Номер/название документа') or '')]
 offers=sorted({str(r['Артикул продавца']) for r in group})
 if len(offers)!=plan_item['wb_expected_offers'] or len(offers)!=plan_item['ozon_target_pairs']:
  raise RuntimeError(f"Assignment target set changed for {plan_item['number']}: {len(offers)}")
 types={r.get('Тип документа','').casefold() for r in group}
 expected_type=2 if any('деклара' in x for x in types) else 1 if any('сертифик' in x for x in types) else None
 if expected_type is None or len({expected_type})!=1:raise RuntimeError(f"Document type ambiguous for {plan_item['number']}")
 start=ozon_item['issue_date'][:10];end=ozon_item['expire_date'][:10]
 valid_cards=[]
 for offer in offers:
  card=by_offer.get(offer)
  if not card:raise RuntimeError(f"WB exact card missing for {offer}")
  docitems=(card.get('documents') or {}).get('items') or []
  matches=[x for x in docitems if suffix and suffix in str(x.get('number') or '')]
  if len(matches)!=1:raise RuntimeError(f"WB document row count is {len(matches)} for {offer} / {plan_item['number']}")
  doc=matches[0];verdict=doc.get('verdict') or {}
  if doc.get('type')!=expected_type or verdict.get('reason')!='valid' or verdict.get('verified') is not True:
   raise RuntimeError(f"WB row not valid/type mismatch for {offer}")
  if str(doc.get('startDate',''))[:10]!=start or str(doc.get('endDate',''))[:10]!=end:
   raise RuntimeError(f"WB dates differ from Ozon registered dates for {offer}")
  if (card.get('documents') or {}).get('excludeDocuments') is not False:
   raise RuntimeError(f"WB documents are excluded for {offer}")
  valid_cards.append({'offer_id':offer,'nmID':card.get('nmID')})
 # Every source copy must still match the hashed copy tied to this record.
 files=[]
 for f in plan_item['local_files']:
  path=Path(f['path'])
  if not path.is_file():raise RuntimeError(f"Source file missing before cleanup: {path}")
  h=hashlib.sha256(path.read_bytes()).hexdigest()
  if h!=plan_item['source_sha256'] or h!=f['sha256']:
   raise RuntimeError(f"Source file hash mismatch: {path}")
  files.append({'path':str(path),'size':path.stat().st_size,'sha256':h})
 checks.append({'number':plan_item['number'],'certificate_id':plan_item['certificate_id'],
                'ozon_approved_pairs':ozon_item['live_pair_count'],'ozon_exact_pair_set_match':ozon_item['exact_pair_set_match'],
                'wb_exact_cards':len(valid_cards),'wb_valid_rows':len(valid_cards),'expected_wb_type':expected_type,
                'issue_date':start,'expire_date':end,'source_files':files})
# All checks are complete. Move copies to a recoverable Trash folder while preserving their paths.
trash=Path.home()/'.Trash'/f"Сертификаты_подтверждены_Ozon_WB_20261014T{now.strftime('%H%M%SZ')}"
allfiles=[f for c in checks for f in c['source_files']]
if len({f['path'] for f in allfiles})!=len(allfiles):raise RuntimeError('A source path is shared by multiple cleanup targets')
moved=[]
for f in allfiles:
 src=Path(f['path']);relative=src.relative_to(ROOT)
 dst=trash/relative;dst.parent.mkdir(parents=True,exist_ok=True)
 shutil.move(str(src),str(dst))
 h=hashlib.sha256(dst.read_bytes()).hexdigest()
 if h!=f['sha256'] or src.exists():raise RuntimeError(f'Post-move verification failed for {src}')
 moved.append({'source':str(src),'trash_path':str(dst),'sha256':h,'size':dst.stat().st_size})
result={'completed_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'trash_directory':str(trash),
        'ozon_recheck':str(BASE/'cleanup_four_live_recheck_ozon_20261014.json'),'wb_recheck':str(WB_PATH),
        'summary':{'documents':len(checks),'files':len(moved),'ozon_product_document_pairs':sum(x['ozon_approved_pairs'] for x in checks),
                   'wb_cards':sum(x['wb_valid_rows'] for x in checks),'blocked_documents':0},
        'documents':checks,'moved':moved,'local_cleanup_allowed':True}
out=BASE/'cleanup_four_fully_applied_20261014_result.json';out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'completed_at_utc':result['completed_at_utc'],'trash_directory':str(trash),'summary':result['summary'],'result_file':str(out)},ensure_ascii=False))
