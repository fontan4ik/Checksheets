"""Read-only original PDF extraction; hash-keyed text caches, all brands, no API calls.
Use bundled Python (pypdf) and pdftoppm. OCR uses macOS Vision rus+eng.
Text is evidence for review, never automatic proof of document validity or scope.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, os, re, shutil, subprocess, time
from pathlib import Path
from datetime import datetime, timezone
BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[1]
CACHE=BASE/'found_document_text_cache_20261014'
PROGRESS=BASE/'found_document_text_extraction_progress_20261014.json'
BINS=Path('/Users/vladimirgrebennikov/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override')
LEGAL=re.compile(r'(?:ЕАЭС\s*(?:№|N)?\s*)?(?:RU|BY|KG|KZ|AM)[\s/]+.*(?:[СCДD]-|ТР\s*\d{3}|417-).*\d',re.I)

def now():return datetime.now(timezone.utc).isoformat()
def atomic(path,value):
 path.parent.mkdir(parents=True,exist_ok=True)
 temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2));temp.replace(path)
def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
 return h.hexdigest()
def inventory():
 entries={};skips=[]
 def add(path,number,expected='',source=''):
  path=Path(path);path=path if path.is_absolute() else ROOT/path
  numbers=[x.strip() for x in str(number).split(';') if x.strip()]
  if len(numbers)!=1 or not LEGAL.search(numbers[0]):return
  if path.suffix.lower()!='.pdf' or not path.is_file():return
  # Registry summary extracts and manually prepared supporting letters are not originals.
  if re.search(r'(?:fsa_extract|registry_extract|manual_letter|support_letter|letter_prepared)',path.name,re.I):
   skips.append({'path':str(path),'reason':'generated_or_support_material'});return
  actual=digest(path)
  if expected and expected!=actual:
   skips.append({'path':str(path),'reason':'hash_mismatch','expected':expected,'actual':actual});return
  entry=entries.setdefault(actual,{'sha256':actual,'paths':[],'numbers':[],'sources':[]})
  if str(path) not in entry['paths']:entry['paths'].append(str(path))
  if numbers[0] not in entry['numbers']:entry['numbers'].append(numbers[0])
  if source and source not in entry['sources']:entry['sources'].append(source)
 catalog=ROOT/'output_to_user/certificates/document_catalog_master.csv'
 if catalog.exists():
  with catalog.open(encoding='utf-8-sig',newline='') as f:
   for row in csv.DictReader(f):
    for path in row['Файл/файлы проекта'].split('; '):add(path,row['Номера/названия документов'],row['SHA256'],row.get('URL источников',''))
 audit=BASE/'iek_new_docs_pdf_text_audit.json'
 if audit.exists():
  for d in json.loads(audit.read_text()).get('documents',[]):
   if d.get('type_code') in ('certificate_of_conformity','declaration'):add(d.get('file',''),d.get('number',''),d.get('sha256_actual',''),d.get('source_url',''))
 manifest=BASE/'all_found_certificates_bulk_manifest_20261014.json'
 if manifest.exists():
  for d in json.loads(manifest.read_text()).get('groups',[]):
   if d.get('type_code') in ('certificate_of_conformity','declaration'):
    u=d.get('upload_file') or {};add(u.get('path',''),d.get('number',''),u.get('sha256',''),'all_found_manifest')
 result=[]
 for entry in entries.values():
  # Distinct number labels for identical original require separate review.
  if len(entry['numbers'])!=1:skips.append({**entry,'reason':'multiple_legal_number_labels'});continue
  result.append(entry)
 return sorted(result,key=lambda x:(not any('/iek_new_docs/' in p for p in x['paths']),x['sha256'])),skips

def extract(entry,ocr=True,preview=False):
 sha=entry['sha256'];path=Path(entry['paths'][0]);txt=CACHE/(sha+'.txt');meta=CACHE/(sha+'.json')
 if meta.exists() and txt.exists():
  old=json.loads(meta.read_text())
  if old.get('complete') and old.get('sha256')==digest(path):return {**old,'cache_hit':True}
 started=time.monotonic(); pages=[];method='embedded';errors=[]
 pdftotext=shutil.which('pdftotext')
 if pdftotext:
  p=subprocess.run([pdftotext,'-layout',str(path),'-'],capture_output=True,text=True,timeout=300)
  if p.returncode==0:pages=p.stdout.split('\f')
 if not pages:
  from pypdf import PdfReader
  reader=PdfReader(path);pages=[p.extract_text() or '' for p in reader.pages]
 page_count=len(pages)
 sparse=[i+1 for i,t in enumerate(pages) if len(re.sub(r'\s','',t))<100]
 rendered=[]
 if (sparse and ocr) or preview:
  stage=CACHE/'rendered'/sha;stage.mkdir(parents=True,exist_ok=True)
  render_pages=sorted(set(sparse if ocr else [])|({1} if preview else set()))
  helper=BASE/'found_document_vision_ocr_20261014'
  if sparse and ocr and not helper.exists():
   subprocess.run(['swiftc',str(BASE/'found_document_vision_ocr_20261014.swift'),'-o',str(helper)],check=True,capture_output=True,timeout=300)
  for n in render_pages:
   prefix=stage/f'page-{n:05d}'
   subprocess.run([str(BINS/'pdftoppm'),'-f',str(n),'-l',str(n),'-r','180','-singlefile','-png',str(path),str(prefix)],check=True,capture_output=True,timeout=300)
   png=prefix.with_suffix('.png');rendered.append(str(png))
   if n in sparse and ocr:
    result=subprocess.run([str(helper),str(png)],capture_output=True,text=True,timeout=180)
    if result.returncode:errors.append({'page':n,'error':result.stderr[-1000:]});continue
    recognized=json.loads(result.stdout);pages[n-1]=recognized['text'];method='embedded+vision_ocr'
 # OCR pages include all sparse appendix pages, not only cover pages.
 text='\n\n'.join(f'--- PAGE {i+1} ---\n{t}' for i,t in enumerate(pages))
 txt.write_text(text)
 result={**entry,'complete':not errors and (ocr or not sparse),'processed_at':now(),'method':method,'page_count':page_count,'ocr_pages':sparse if ocr else [],'text_chars':len(text),'text_path':str(txt),'rendered_pages':rendered,'errors':errors,'seconds':round(time.monotonic()-started,2),'original_hash_after':digest(path),'original_unchanged':digest(path)==sha,'requires_validity_and_scope_review':True}
 atomic(meta,result);return result

def main():
 p=argparse.ArgumentParser();p.add_argument('--limit',type=int);p.add_argument('--sha256');p.add_argument('--inventory-only',action='store_true');p.add_argument('--no-ocr',action='store_true');p.add_argument('--preview',action='store_true');args=p.parse_args()
 CACHE.mkdir(parents=True,exist_ok=True);entries,skips=inventory()
 if args.sha256:entries=[x for x in entries if x['sha256']==args.sha256]
 if args.limit is not None:entries=entries[:args.limit]
 state={'started_at':now(),'stage':'inventory','total_files':len(entries),'files_processed':0,'results':[],'inventory_skips':skips,'complete':False,'no_pdf_mutation':True};atomic(PROGRESS,state);atomic(CACHE/'inventory.json',{'entries':entries,'skips':skips})
 if args.inventory_only:print(json.dumps({'total_files':len(entries),'skips':len(skips)}));return
 for entry in entries:
  state['stage']='extracting';state['current_sha256']=entry['sha256'];atomic(PROGRESS,state)
  try:result=extract(entry,not args.no_ocr,args.preview)
  except Exception as e:result={**entry,'complete':False,'error':str(e),'processed_at':now()}
  state['results'].append(result);state['files_processed']+=1;state['updated_at']=now();atomic(PROGRESS,state)
  print(json.dumps({'processed':state['files_processed'],'total':len(entries),'sha256':entry['sha256'],'complete':result.get('complete'),'method':result.get('method'),'seconds':result.get('seconds')},ensure_ascii=False),flush=True)
 state['stage']='finished';state['complete']=True;state['finished_at']=now();atomic(PROGRESS,state)
if __name__=='__main__':main()
