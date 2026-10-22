"""Review-only registry-ready entries from filtered ETM responses."""
import json,collections,urllib.parse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];T=ROOT/'test'
filtered=json.loads((T/'etm_filtered_catalog_remaining_20261016.json').read_text())
source={r['offer_id']:r for r in json.loads((T/'etm_codes_remaining_candidate_plan_20261016.json').read_text())['rows']}
primary={r['offer_id']:r for r in json.loads((T/'etm_navigator_primary_evidence_20261016.json').read_text())['rows']}
makers={'Arlight':2010,'Navigator':953,'ОНЛАЙТ':953,'Stekker':2042,'Feron':964}
manufacturer_names={2010:{'arlight'},953:{'navigator group','navigator'},2042:{'stekker'},964:{'feron'}}
confirmed=[];decisions=[]
for r in filtered['rows']:
 original=source[r['offer_id']];expected={original['model'].strip().casefold()};p=primary.get(r['offer_id'])
 if p:expected.add(str(p['official_ean']).strip().casefold())
 matches=[]
 for key in r['query_keys']:
  q=filtered['queries'][key]
  if q.get('api_status')!=200:continue
  try:complete=int(q.get('records',0))<=len(q.get('rows',[]))
  except (ValueError,TypeError):complete=False
  for row in q.get('rows',[]):
   article=str(row.get('art')or row.get('vendorCode')or'').strip();vendor=row.get('vendor');name=str(row.get('vendorName')or'').strip()
   if article.casefold()not in expected or vendor!=makers.get(original['brand'])or name.casefold()not in manufacturer_names.get(vendor,set())or not complete:continue
   code=str(row.get('offerId')or row.get('code')or'').replace('ETM','').strip()
   if not code.isdigit():continue
   url='https://ipro.etm.ru/api/m1/catalog?'+urllib.parse.urlencode({'val':q['term'],'type':'code','mnf':q['maker'],'page':1,'rows':100})
   evidence=[{'source':'ETM filtered catalog API','url':url,'note':f"Exact manufacturer article {article}; vendor={vendor}/{name}; ETM title: {row.get('name','')}. Complete result set ({q.get('records')} records). Ozon title: {r['marketplace_name']}"}]
   if p:evidence.append({'source':'Official Navigator/ONLIGHT catalog','url':p['primary_source_url'],'note':f"Official manufacturer article {p['manufacturer_article']}, EAN {p['official_ean']}, model {p['official_model']} corroborate seller identity. No EAN-to-ETM-code inference without matching ETM row."})
   matches.append({'offer_id':original['offer_id'],'model':original['model'],'brand':original['brand'],'etm_code':code,'etm_article':article,'etm_manufacturer':name,'evidence':evidence,'raw_sanitized_m1_row':row})
 unique={m['etm_code']:m for m in matches}
 decision='confirmed'if len(unique)==1 else'conflicting_exact_identity'if len(unique)>1 else'no_exact_identity'
 chosen=next(iter(unique.values()))if len(unique)==1 else None
 if chosen:confirmed.append({k:v for k,v in chosen.items()if k!='raw_sanitized_m1_row'})
 decisions.append({'offer_id':r['offer_id'],'model':r['model'],'brand':r['brand'],'decision':decision,'confirmed_entry':chosen,'queries':{k:filtered['queries'][k]for k in r['query_keys']}})
# Exact composite manufacturer article explicitly contains both the source model
# DH101 and source article 48099, with matching manufacturer and specifications.
for decision in decisions:
 if decision['offer_id']!='48099' or decision['decision']=='confirmed':continue
 original=source['48099']
 for q in decision['queries'].values():
  for row in q.get('rows',[]):
   if row.get('art')=='DH101 48099' and row.get('vendor')==964 and row.get('offerId')==5321311 and row.get('vendorName')=='FERON':
    entry={'offer_id':'48099','model':'48099','brand':'Feron','etm_code':'5321311','etm_article':'DH101 48099','etm_manufacturer':'FERON','evidence':[{'source':'ETM filtered catalog API','url':'https://ipro.etm.ru/api/m1/catalog?val=48099&type=code&mnf=964&page=1&rows=100','note':f"Exact composite manufacturer article DH101 48099 contains source model DH101 and numeric article 48099; manufacturer964/FERON. Both names identify outdoor up/down6x1W,3000K,white DH101. ETM title: {row.get('name')}; Ozon title: {original['marketplace']['name']}. This is an explicit model+article identity, not a fuzzy name match."}]}
    confirmed.append(entry);decision['decision']='confirmed_composite_article';decision['confirmed_entry']={**entry,'raw_sanitized_m1_row':row}
# Explicit alternate manufacturer article in the marketplace source name.
r=source['DIS4133267S-1'];alternative=json.loads((T/'etm_remaining_alternates_api_20261016.json').read_text())['queries']['DIS4133267']['product']
if alternative.get('gdsCode')=='3749009'and alternative.get('gdsArt')=='DIS4133267'and alternative.get('gdsMnfName')=='DKC':
 confirmed.append({'offer_id':r['offer_id'],'model':r['model'],'brand':r['brand'],'etm_code':'3749009','etm_article':'DIS4133267','etm_manufacturer':'DKC','evidence':[{'source':'ETM Goods API','url':'https://ipro.etm.ru/api/v1/goods/DIS4133267?type=mnf','note':'Exact manufacturer article DIS4133267 is explicitly written in Ozon product name; ETM manufacturer DKC and angled panel socket IP44,32A,3P+E+N,400V match all source electrical specifications. Seller offer/model has additional S, but source product name states unsuffixed manufacturer article.'},{'source':'Fresh Ozon Seller API product identity','url':'https://api-seller.ozon.ru/v3/product/info/list','note':f"Offer {r['offer_id']}; Ozon title: {r['marketplace']['name']}"}]})
report={'read_only':True,'registry_changed':False,'scope_offers':len(filtered['rows']),'scope_complete':bool(filtered.get('finished_at')),'confirmed_count':len(confirmed),'by_brand':dict(collections.Counter(r['brand']for r in confirmed)),'controls':filtered['controls'],'confirmed':confirmed,'decisions':decisions}
(T/'etm_codes_supplement_plan_20261016.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print({k:report[k]for k in ['scope_offers','scope_complete','confirmed_count','by_brand']})
