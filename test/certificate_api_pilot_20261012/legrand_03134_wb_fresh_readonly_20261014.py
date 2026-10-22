"""Fresh read-only WB full-card check for the ten Legrand 03134 targets."""
from __future__ import annotations
import collections, csv, json
from pathlib import Path
from api_client import BASE, Client, now, save
ROOT=BASE.parents[1]
NUMBER='ЕАЭС KG 417/032.FR.02.03134'
OLD='EAC KG 417/032.FR.02.03134'
CSV_PATH=ROOT/'output_to_user/certificates/document_assignments.csv'
PREFLIGHT=BASE/'legrand_remaining_preflight_20261013.json'
TARGETS={x['offer']:x for x in json.loads(PREFLIGHT.read_text())['documents']['EAC-FR.02.03134']['targets']}

def main():
 with CSV_PATH.open(newline='',encoding='utf-8-sig') as f:
  rows=[r for r in csv.DictReader(f) if 'EAC-FR.02.03134' in r.get('Номер/название документа','')]
 offers=sorted({r['Артикул продавца'] for r in rows})
 if len(offers)!=10: raise RuntimeError(f'expected 10 offers, found {len(offers)}')
 c=Client(); cards_by_offer={}
 for offer in offers:
  cards=c.wb_cards(offer)
  if len(cards)!=1 or cards[0].get('vendorCode')!=offer: raise RuntimeError(f'WB exact card missing/duplicate: {offer}')
  card=cards[0]
  if str(card.get('nmID') or '')!=str(TARGETS[offer]['nmID']): raise RuntimeError(f'nmID changed for {offer}')
  docs=card.get('documents') or card.get('docs') or {}
  items=docs.get('items') or []
  matched=[d for d in items if int(d.get('type') or 0)==1 and d.get('number') in (NUMBER,OLD)]
  cards_by_offer[offer]={
   'vendorCode':card.get('vendorCode'),'nmID':str(card.get('nmID') or ''),'brand':card.get('brand'),
   'updatedAt':card.get('updatedAt'),'excludeDocuments':docs.get('excludeDocuments'),
   'documents_count':len(items),'document_matches':matched,
   'overallVerdict':docs.get('overallVerdict'),
  }
 result={'checked_at_utc':now(),'read_only':True,'document_number':NUMBER,'old_number':OLD,
         'target_count':len(offers),'cards':cards_by_offer}
 save('legrand_03134_wb_fresh_readonly_20261014.json',result)
 print(json.dumps({'output':'legrand_03134_wb_fresh_readonly_20261014.json','checked_at_utc':result['checked_at_utc'],
  'cards':len(cards_by_offer),'vendor_code_exact':sum(x['vendorCode']==o for o,x in cards_by_offer.items()),
  'exact_document_rows':sum(len(x['document_matches']) for x in cards_by_offer.values()),
  'valid_rows':sum(len(x['document_matches'])==1 and (x['document_matches'][0].get('verdict') or {}).get('verified') is True and (x['document_matches'][0].get('verdict') or {}).get('reason')=='valid' for x in cards_by_offer.values()),
  'overall_reasons':dict(collections.Counter(str((x.get('overallVerdict') or {}).get('reason') or '') for x in cards_by_offer.values())),
  'nmids':{o:x['nmID'] for o,x in cards_by_offer.items()}},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
