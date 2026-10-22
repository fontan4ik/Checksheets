"""Read-only audit of official IEK docs already approved on Ozon for newly-listed offers."""
from __future__ import annotations
import concurrent.futures, hashlib, io, json, re, sys
from collections import defaultdict
from datetime import date
from pathlib import Path
sys.path.insert(0,'/Users/vladimirgrebennikov/.cache/codex-runtimes/codex-primary-runtime/dependencies/python')
from pypdf import PdfReader
from urllib.request import Request, urlopen
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
X=json.loads((HERE/'new_iek_itk_official_crosswalk_20261020.json').read_text())
S=json.loads((HERE/'live_marketplaces_snapshot.json').read_text())
CACHE=ROOT/'test/certificate_api_pilot_20261012/found_document_text_cache_20261014'
OUT=HERE/'iek_current_ozon_docs_audit_20261020'
OUT.mkdir(exist_ok=True)
TR=str.maketrans({'А':'A','В':'B','Е':'E','К':'K','М':'H','Н':'H','О':'O','Р':'P','С':'C','Т':'T','У':'Y','Х':'X','Ё':'E','Э':'E','Д':'D','П':'P'})
def norm(v):return ''.join(c for c in str(v or '').upper().translate(TR) if c.isalnum())
def base(v):
 x=norm(v)
 for p in ('EAEC','EAEU','EAC'):
  if x.startswith(p):x=x[len(p):];break
 if x.startswith('N'):x=x[1:]
 for p in ('RU','KG','BY','KZ','AM'):
  if x.startswith(p):x=x[len(p):];break
 return x
certs=defaultdict(list)
for c in S['ozon_certificates']['certificates']:certs[base(c.get('certificate_number'))].append(c)
groups={}
for r in X['results']:
 if 'product_url' not in r:continue
 for d in r.get('certificate_summary') or []:
  typ='declaration' if 'деклара' in str(d.get('type','')).lower() else 'certificate_of_conformity' if 'сертификат' in str(d.get('type','')).lower() else None
  if not typ:continue
  matches=[c for c in certs[base(d.get('number'))] if c.get('type_code')==typ]
  active=[c for c in matches if c.get('status_code')=='approved' and (c.get('expire_date') or '')[:10]>=date.today().isoformat()]
  if len(active)!=1:continue
  c=active[0]
  if str(c.get('issue_date',''))[:10] != str(d.get('dateStart',''))[:10] or str(c.get('expire_date',''))[:10] != str(d.get('dateEnd',''))[:10]:continue
  key=(base(d.get('number')),typ)
  z=groups.setdefault(key,{'number':d.get('number'),'type':d.get('type'),'ozon_id':c['certificate_id'],'issue_date':c['issue_date'],'expire_date':c['expire_date'],'url':d.get('url'),'offers':[]})
  target={'offer_id':r['offer_id'],'article':r.get('product_article'),'product_url':r['product_url'],'brand':r.get('official_brand'),'name':r.get('official_name'),'feacn':(r.get('official_product_flags') or {}).get('feacn'),'firstSaleDate':(r.get('official_product_flags') or {}).get('firstSaleDate')}
  if target['offer_id'] not in {x['offer_id'] for x in z['offers']}:z['offers'].append(target)

def extract(item):
 key, g=item
 try:
  req=Request(g['url'],headers={'User-Agent':'Mozilla/5.0 certification-audit/1.0'})
  with urlopen(req,timeout=60) as resp:data=resp.read()
  if not data.startswith(b'%PDF-'):raise ValueError('official url did not return PDF')
  digest=hashlib.sha256(data).hexdigest()
  file=OUT/(digest+'.pdf');file.write_bytes(data)
  text='\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(data)).pages)
  txtfile=None
  if len(text.strip())<100:
   cache=CACHE/(digest+'.txt')
   if cache.exists():text=cache.read_text(errors='replace');txtfile=str(cache)
  codes=sorted(set(re.findall(r'(?<!\d)\d{10}(?!\d)',text)))
  # Give precedence to a code list immediately following the TNVED label.
  match=re.search(r'(?:тн\s*вэд|код(?:\s*\(код[ыы]\))?\s*тн\s*вэд)(.{0,500})',text,re.I|re.S)
  local=[]
  if match:local=sorted(set(re.findall(r'(?<!\d)\d{10}(?!\d)',match.group(1))))
  g.update({'downloaded_sha256':digest,'local_pdf':str(file),'pdf_bytes':len(data),'extract_chars':len(text),'all_10_digit_codes':codes,'scope_codes_near_label':local,'text_cache_used':txtfile})
 except Exception as e:g['download_error_type']=type(e).__name__
 return key,g
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
 for key,g in ex.map(extract,list(groups.items())):groups[key]=g
# compare actual product codes with read document scope
for g in groups.values():
 allowed=set(g.get('scope_codes_near_label') or [])
 for t in g['offers']:
  t['code_in_document_scope']=bool(allowed and t.get('feacn') in allowed)
summary={'checked_at':S.get('updated_at'),'crosswalk_offers':X.get('new_offer_count'),'current_approved_exact_ozon_document_groups':len(groups),'groups':list(groups.values())}
path=HERE/'iek_current_ozon_docs_audit_20261020.json';path.write_text(json.dumps(summary,ensure_ascii=False,indent=2))
print(json.dumps({'groups':len(groups),'download_errors':sum('download_error_type' in g for g in groups.values()),'groups_with_parsed_tnved':sum(bool(g.get('scope_codes_near_label')) for g in groups.values()),'offers_by_doc':[(g['number'],len(g['offers']),len([t for t in g['offers'] if t['code_in_document_scope']]),g.get('scope_codes_near_label'),g.get('download_error_type')) for g in groups.values()],'report':str(path)},ensure_ascii=False))
