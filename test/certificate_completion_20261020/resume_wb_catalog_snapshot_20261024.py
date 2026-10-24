from __future__ import annotations
import json, sys, time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client
OUT=HERE/'live_marketplaces_snapshot_resume_20261024.json'
PATH='/content/v2/get/cards/list'
ALLOWED={('wb',PATH)}
def stamp():return datetime.now(timezone.utc).isoformat()
def identity(card):return (str(card.get('vendorCode') or ''),str(card.get('brand') or ''),str(card.get('subjectID') or ''),str(card.get('subjectName') or ''),card.get('documents') or {})
def codes(card):
 out=set()
 for x in card.get('characteristics') or []:
  label=''.join(str(x.get('name') or '').casefold().split()).replace('ё','е')
  if 'тнвэд' not in label and 'тнвед' not in label:continue
  v=x.get('value'); out.update(str(y).split(' - ',1)[0].strip() for y in (v if isinstance(v,list) else [v]) if y not in (None,''))
 return tuple(sorted(out))
def call(client,payload):
 if ('wb',PATH) not in ALLOWED:raise RuntimeError('endpoint outside read-only allowlist')
 return client.call('wb',PATH,payload,mutation=False)
def save(state):
 state['updated_at']=stamp();tmp=OUT.with_suffix('.resume.tmp');tmp.write_text(json.dumps(state,ensure_ascii=False));tmp.replace(OUT)
def main():
 state=json.loads(OUT.read_text()); section=state['wb_catalog']
 if section.get('complete'):print(json.dumps({'already_complete':True,'cards':len(section['cards'])}));return
 if not state['ozon_products'].get('complete') or not state['ozon_certificates'].get('complete'):raise RuntimeError('Ozon snapshots must remain complete')
 cards=list(section.get('cards') or []); by_id={str(x.get('nmID')):x for x in cards}
 if len(cards)!=len(by_id) or 'None' in by_id:raise RuntimeError('checkpoint has duplicate/missing nmID')
 cursor=dict(section.get('cursor') or {'limit':100}); pages=int(section.get('pages') or 0); replay=True; new_pages=0; client=Client();seen=set();
 while True:
  body=call(client,{'settings':{'sort':{'ascending':True},'cursor':cursor,'filter':{'withPhoto':-1}}})
  data=body.get('data',body);batch=(data.get('cards') or data.get('items') or []) if isinstance(data,dict) else []
  returned=(data.get('cursor') or body.get('cursor') or {}) if isinstance(data,dict) else {}
  if body.get('error') or not isinstance(batch,list) or returned.get('total')!=len(batch):raise RuntimeError('invalid WB page/cursor')
  ids=[str(x.get('nmID') or '') for x in batch]
  if any(not i for i in ids) or len(ids)!=len(set(ids)):raise RuntimeError('duplicate/missing nmID inside page')
  overlaps=0
  for card in batch:
   nid=str(card['nmID']);old=by_id.get(nid)
   if old:
    overlaps+=1
    if identity(card)!=identity(old) or codes(card)!=codes(old):raise RuntimeError('checkpoint overlap changed identity/document/TN VED: '+nid)
   else:
    by_id[nid]=card;cards.append(card)
  if replay:
   if overlaps!=len(batch):raise RuntimeError('saved cursor did not replay exact last page; stop for investigation')
   replay=False
  else:
   pages+=1;new_pages+=1
  if new_pages%10==0 or len(batch)<100:
   section.update(pages=pages,cards_read=len(cards),cursor=cursor,cards=cards)
   save(state)
   print(json.dumps({'phase':'wb_catalog_resume','pages':pages,'cards':len(cards),'new_pages':new_pages},ensure_ascii=False),flush=True)
  if len(batch)<100:break
  sig=(returned.get('updatedAt'),returned.get('nmID'))
  if None in sig or sig in seen:raise RuntimeError('WB cursor repeated or incomplete')
  seen.add(sig);cursor={'limit':100,'updatedAt':sig[0],'nmID':sig[1]};time.sleep(.65)
 nmids=[str(x.get('nmID') or '') for x in cards]
 if len(nmids)!=len(set(nmids)) or any(not x for x in nmids):raise RuntimeError('final WB nmID set not unique')
 section.update(complete=True,checked_at=stamp(),pages=pages,cards_read=len(cards),cards=cards,unique_nmids=True)
 state['finished_at']=stamp();state['complete']=bool(state['ozon_products'].get('complete') and state['ozon_certificates'].get('complete') and section['complete'])
 save(state)
 print(json.dumps({'complete':state['complete'],'ozon_products':len(state['ozon_products']['products']),'ozon_certificates':len(state['ozon_certificates']['certificates']),'ozon_bindings':state['ozon_certificates']['total_bindings'],'wb_cards':len(cards),'wb_pages':pages,'snapshot':str(OUT)},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
