"""Resolve WB cursor-overlap duplicates with exact readbacks; read-only."""
from __future__ import annotations
import json, sys, time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client
PARTIAL=HERE/'live_marketplaces_snapshot_resume_20261020.json'
PRIOR=HERE/'live_marketplaces_snapshot_complete_20261020.json'
OUT=HERE/'live_marketplaces_snapshot_final_20261020.json'
RESOLUTION=HERE/'wb_duplicate_card_resolution_20261020.json'
d=json.loads(PARTIAL.read_text()); prior=json.loads(PRIOR.read_text())
if not d['ozon_products'].get('complete') or not d['ozon_certificates'].get('complete'):
    raise RuntimeError('Ozon portions are incomplete')
raw=d['wb_catalog'].get('cards') or []
by_id=defaultdict(list)
for c in raw: by_id[str(c.get('nmID') or '')].append(c)
duplicates={k:v for k,v in by_id.items() if not k or len(v)!=1}
if '' in duplicates: raise RuntimeError('Missing nmID in WB pages')
prior_by={str(c['nmID']):c for c in prior['wb_catalog']['cards']}
if set(k for k in by_id)!=set(prior_by):
    raise RuntimeError('WB nmID set differs from previous complete read; quarantine current snapshot')
client=Client(); rereads=[]

def doc_signature(card):
    return sorted((int(x.get('type') or 0),str(x.get('number') or '').strip().upper(),
                   str(x.get('startDate') or '')[:10],str(x.get('endDate') or '')[:10],
                   (x.get('verdict') or {}).get('verified'),(x.get('verdict') or {}).get('status'),
                   (x.get('verdict') or {}).get('reason'))
                  for x in ((card.get('documents') or {}).get('items') or []))

for nm_id, versions in sorted(duplicates.items()):
    offers={str(x.get('vendorCode') or '') for x in versions}
    brands={str(x.get('brand') or '') for x in versions}
    if len(offers)!=1 or len(brands)!=1 or len({json.dumps(doc_signature(x),sort_keys=True) for x in versions})!=1:
        raise RuntimeError(f'Conflicting WB duplicate payloads for nmID {nm_id}; exact re-read required before reconciliation')
    offer=next(iter(offers))
    live=client.wb_cards(offer)
    if len(live)!=1 or str(live[0].get('nmID'))!=nm_id or str(live[0].get('vendorCode'))!=offer:
        raise RuntimeError(f'Exact WB card lookup did not resolve nmID {nm_id}')
    by_id[nm_id]=[live[0]]
    rereads.append({'nmID':nm_id,'offer_id':offer,'brand':next(iter(brands)),
                    'pages_versions':len(versions),'exact_readback_count':len(live),
                    'current_document_signature':doc_signature(live[0]),
                    'readback_updated_at':live[0].get('updatedAt')})

cards=[rows[0] for rows in by_id.values()]
if len(cards)!=len(prior_by) or len({str(c['nmID']) for c in cards})!=len(cards):
    raise RuntimeError('WB catalog is not uniquely identified after exact readbacks')

def tnved(card):
    out=set()
    for ch in card.get('characteristics') or []:
        label=''.join(str(ch.get('name') or '').casefold().split()).replace('ё','е')
        if 'тнвэд' not in label and 'тнвед' not in label: continue
        raw=ch.get('value'); vals=raw if isinstance(raw,list) else [raw]
        for v in vals:
            code=str(v or '').split(' - ',1)[0].strip()
            if code:out.add(code)
    return out
identity_changes=[];tnved_changes=[];document_changes=[]
for c in cards:
    old=prior_by[str(c['nmID'])]
    if (str(old.get('vendorCode')),str(old.get('brand')))!=(str(c.get('vendorCode')),str(c.get('brand'))):
        identity_changes.append(str(c['nmID']))
    if tnved(old)!=tnved(c): tnved_changes.append(str(c['nmID']))
    if doc_signature(old)!=doc_signature(c): document_changes.append(str(c['nmID']))
if identity_changes: raise RuntimeError(f'WB card identities changed for {len(identity_changes)} IDs')

# Fresh, paginated read of WB trash. It is read-only and held separately from active cards.
trash=[];cursor={'limit':100};seen=set();pages=0
while True:
    body=client.call('wb','/content/v2/get/cards/trash',{'settings':{'sort':{'ascending':True},'cursor':cursor}},mutation=False)
    data=body.get('data',body);batch=(data.get('cards') or data.get('items') or []) if isinstance(data,dict) else []
    returned=(data.get('cursor') or body.get('cursor') or {}) if isinstance(data,dict) else {}
    if body.get('error') or not isinstance(batch,list) or returned.get('total')!=len(batch):
        raise RuntimeError('WB trash page or cursor is incomplete')
    pages+=1;trash.extend(batch)
    if len(batch)<100:break
    fields=('trashedAt','nmID');sig=tuple(returned.get(k) for k in fields)
    if None in sig or sig in seen:raise RuntimeError('WB trash cursor repeated or incomplete')
    seen.add(sig);cursor={'limit':100,**dict(zip(fields,sig))};time.sleep(.65)
ids=[str(c.get('nmID') or '') for c in trash]
if any(not x for x in ids) or len(set(ids))!=len(ids):raise RuntimeError('WB trash contains missing/duplicate nmID')

now=datetime.now(timezone.utc).isoformat()
d['wb_catalog'].update({'complete':True,'checked_at':now,'cards':cards,'cards_read':len(cards),
    'raw_rows':len(raw),'duplicate_rows_resolved_by_exact_readback':len(rereads),
    'duplicate_nmids_seen':len(duplicates),'id_set_matches_previous_complete_read':True,
    'card_identity_stable_vs_previous_complete_read':True,
    'tnved_changed_nmids_since_previous_complete_read':tnved_changes,
    'document_changed_nmids_since_previous_complete_read':document_changes})
d['wb_trash']={'complete':True,'checked_at':now,'pages':pages,'cards':trash}
d['complete']=True;d['finished_at']=now;d['updated_at']=now
OUT.write_text(json.dumps(d,ensure_ascii=False,indent=2))
RESOLUTION.write_text(json.dumps({'checked_at':now,'read_only':True,'raw_rows':len(raw),
    'unique_nmids':len(cards),'duplicate_nmids_resolved':rereads,'identity_changes':identity_changes,
    'tnved_changed_count':len(tnved_changes),'tnved_changed_examples':tnved_changes[:25],
    'documents_changed_count':len(document_changes),'trash_pages':pages,'trash_cards':len(trash),
    'snapshot':str(OUT)},ensure_ascii=False,indent=2))
print(json.dumps({'complete':True,'snapshot':str(OUT),'ozon_active':d['ozon_products'].get('active_products'),
 'ozon_certificates':d['ozon_certificates'].get('records'),'ozon_bindings':d['ozon_certificates'].get('total_bindings'),
 'wb_cards':len(cards),'wb_raw_rows':len(raw),'wb_duplicates_resolved':len(rereads),
 'wb_tnved_changed_count':len(tnved_changes),'wb_document_changed_count':len(document_changes),
 'wb_trash_cards':len(trash)},ensure_ascii=False,indent=2))
