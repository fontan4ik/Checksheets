"""Point-check WB by official IEK article for all 40 current Ozon targets."""
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client

AUDIT=HERE/'iek_missing_official_docs_audit_20261020.json'
EAEU_MANIFEST=HERE/'iek_missing_new_docs_manifest_20261020.json'
OUT=HERE/'wb_article_recheck_20261020.json'

def read_search(client,text):
    cards=[]; cursor={'limit':100}; seen=set()
    while True:
        data=client.call('wb','/content/v2/get/cards/list',{'settings':{
            'sort':{'ascending':True},'cursor':cursor,
            'filter':{'withPhoto':-1,'textSearch':text}}})
        if data.get('error') or not isinstance(data.get('cards'),list):
            raise RuntimeError('WB card search failed')
        batch=data['cards']; cards.extend(batch); returned=data.get('cursor') or {}
        if returned.get('total')!=len(batch): raise RuntimeError('WB result count mismatch')
        if len(batch)<100:return cards
        signature=(returned.get('updatedAt'),returned.get('nmID'))
        if None in signature or signature in seen: raise RuntimeError('WB cursor repeated or incomplete')
        seen.add(signature); cursor={'limit':100,'updatedAt':signature[0],'nmID':signature[1]}

def main():
    audit={x['number']:x for x in json.loads(AUDIT.read_text())['documents']}
    manifest=json.loads(EAEU_MANIFEST.read_text())
    numbers=[g['number'] for g in manifest['groups']]
    numbers += ['RU С-RU.АЮ64.В.00560/25','RU С-RU.АЮ64.В.00631/26']
    offers={}
    for number in numbers:
        for row in audit[number]['offers']:
            offers[row['offer_id']]={"offer_id":row['offer_id'],"product_article":row['product_article'],
                                     "official_name":row['name'],"source_number":number}
    client=Client(); results=[]
    for item in offers.values():
        article=item['product_article'] or item['offer_id']
        cards=read_search(client,article)
        relevant=[]
        for card in cards:
            vendor=str(card.get('vendorCode') or '')
            title=str(card.get('title') or '')
            if article in vendor or article in title or vendor in article:
                relevant.append({"nmID":card.get('nmID'),"vendorCode":vendor,"brand":card.get('brand'),
                                 "title":title,"documents":(card.get('documents') or {}).get('items') or []})
        results.append({**item,"query":article,"returned_card_count":len(cards),
                        "article_relevant_cards":relevant,"exact_offer_card_count":sum(c.get('vendorCode')==item['offer_id'] for c in relevant)})
    out={"checked_at":datetime.now(timezone.utc).isoformat(),"read_only":True,
         "unique_offers":len(results),"offers_with_article_relevant_wb_cards":sum(bool(x['article_relevant_cards']) for x in results),
         "exact_offer_cards":sum(x['exact_offer_card_count'] for x in results),"results":results}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in out.items() if k!='results'},ensure_ascii=False))
    for row in results:
        if row['article_relevant_cards']:
            print(json.dumps({k:row[k] for k in ('offer_id','product_article','article_relevant_cards')},ensure_ascii=False))

if __name__=='__main__':main()
