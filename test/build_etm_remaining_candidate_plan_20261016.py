"""Build reviewable evidence from read-only marketplace and ETM snapshots."""
import json,re,collections
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];T=ROOT/'test'
rows=json.loads((T/'etm_codes_remaining_normalized_20261016.json').read_text())['rows']
market={r['offer_id']:r['marketplace']for r in json.loads((T/'etm_remaining_marketplace_identity_20261016.json').read_text())['rows']}
dictionary_references=collections.defaultdict(list)
for source_row in rows:
 if source_row['brand'] and source_row['brand']!='Нет бренда' and not source_row['offer_id'].startswith(('IEK-PROBE','IEK-VAT','QZA-READONLY','TEST-')):
  for attr in market[source_row['offer_id']].get('selected_attributes',{}).get('85',[]):
   dictionary_references[attr.get('dictionary_value_id')].append({'offer_id':source_row['offer_id'],'brand':source_row['brand']})
api=json.loads((T/'etm_codes_remaining_api_20261016.json').read_text()).get('queries',{})
alternates=json.loads((T/'etm_remaining_alternates_api_20261016.json').read_text()).get('queries',{}) if (T/'etm_remaining_alternates_api_20261016.json').exists() else {}
baseline=json.loads((T/'etm_identity_before_20261016.json').read_text())['values']
baseline_code_col=baseline[0].index('CODES')
baseline_codes={str(r[0]):str(r[baseline_code_col]) for r in baseline[1:] if r and r[0] and len(r)>baseline_code_col and r[baseline_code_col]}
def norm(s):
 s=str(s or '').casefold().translate(str.maketrans('авекмнорстух','abekmhopctyx'));return re.sub(r'[^a-zа-яё0-9]','',s).lstrip('0')or'0'
def brand(s):return re.sub(r'[^a-zа-яё0-9]','',str(s or '').casefold())
# Explicit reviewed identities; these lists are evidence candidates, not runtime matching rules.
stecker_feron={'49326-1','49494-2','49328-1','49308-1','49503-2','49507-10','49509-2','39494-1','39495-1','39496-1','49591-1','49402-1','49400-1','49407-1','49401-1','39171-B'}
missing_review={'48948-1':('FERON','Feron COB LS630 7W/m 12V 4000K IP20 matches ETM title'),'51852-1':('FERON','Feron AL103 track 30W 6400K grey matches ETM title'),'49171-5':('FERON','STEKKER three-key Katrin switch white matches ETM title'),'39592-5':('FERON','STEKKER two-key Katrin switch champagne matches ETM title'),'49425-2':('FERON','Two-place protected grounded Katrin 250V16A graphite socket matches ETM title; KVT candidate is cable tie and rejected'),'51850-1':('FERON','Feron AL169 GU10 black track lamp matches ETM title'),'sq0602-0008':('TDM ELECTRIC','Full seller article SQ0602-0008 and TDM socket135 63A380V IP54 match ETM title; B model is truncated by sheet formula'),'4690612003030-25':('INHOME','Exact 13-digit manufacturer article + SPB-T5 7W4000K230V630lm600mm match ETM title'),'4690612004921-25':('INHOME','Ozon name explicitly IN HOME; exact article + SPB-T5 5W4000K230V450lm300mm match ETM title'),'SNMPSM2-1':('DKC IT','Ozon name explicitly DKC in Cyrillic (ДКС), SNMP adapter for SmallRackmount/SmallTower/TrioTM matches ETM title'),'41161':('FERON','Ozon name explicitly Feron LN013 recessed3W4000KIP65 black; FERON41161* title matches')}
result=[]
for r in rows:
 offer=r['offer_id'];m=market[offer];name=m.get('name','');p=api.get(r['model'],{}).get('product',{});confirmed=[]
 if p.get('gdsCode')and norm(r['model'])in{norm(p.get('gdsArt')),norm(p.get('gdsExtArt'))}and brand(r['brand'])==brand(p.get('gdsMnfName'))and r['brand']:
  confirmed.append({'code':p['gdsCode'],'method':'ETM_API_article_and_manufacturer','evidence':{'requested_model':r['model'],'etm_article':p.get('gdsArt'),'etm_manufacturer':p.get('gdsMnfName'),'etm_name':p.get('gdsNameTitle'),'marketplace_name':name}})
 if offer=='DIS4133267S-1':
  alternative=alternates.get('DIS4133267',{}).get('product',{})
  if alternative.get('gdsCode')=='3749009' and alternative.get('gdsArt')=='DIS4133267' and alternative.get('gdsMnfName')=='DKC' and 'DIS4133267' in name:
   confirmed.append({'code':'3749009','method':'ETM_API_explicit_article_in_marketplace_name','evidence':{'statement':'Ozon name explicitly identifies DIS4133267, and both names agree on angled panel socket IP44,32A,3P+E+N,400V. Seller offer adds S but source name identifies unsuffixed manufacturer article.','etm_article':alternative['gdsArt'],'etm_manufacturer':alternative['gdsMnfName'],'etm_name':alternative['gdsNameTitle'],'marketplace_name':name}})
 for c in r['normalized_candidates']:
  candidate_article=c['Артикул'];candidate_brand=c['Производитель'];evidence=None
  if norm(r['model'])==norm(candidate_article)and brand(r['brand'])==brand(candidate_brand):
   evidence='Same manufacturer and model after reviewed leading-zero/asterisk/Cyrillic-Latin lookalike normalization; names available for reviewer'
  elif r['brand']=='DKC'and candidate_brand=='DKC IT'and r['model'].casefold()==candidate_article.casefold():evidence='Exact DKC manufacturer article; FTP uses DKC IT subdivision'
  elif offer in stecker_feron and candidate_brand=='FERON'and norm(r['model'])==norm(candidate_article):evidence='Exact article plus reviewed STEKKER/Feron socket/switch/extension identity and matching series/model/specifications in both names'
  elif offer in missing_review and candidate_brand==missing_review[offer][0]and(norm(r['model'])==norm(candidate_article)or norm(offer)==norm(candidate_article)):
   evidence=missing_review[offer][1]
  if evidence:confirmed.append({'code':c['Код ЭТМ'],'method':'FTP_metadata_identity_review','evidence':{'statement':evidence,'etm_article':candidate_article,'etm_manufacturer':candidate_brand,'etm_name':c['Полное наименование'],'marketplace_name':name}})
 codes={x['code']for x in confirmed}
 decision='eligible_for_reviewed_registry'if len(codes)==1 else 'conflicting_confirmed_codes'if len(codes)>1 else 'intentional_test_offer'if offer.startswith(('IEK-PROBE','IEK-VAT','QZA-READONLY'))or offer=='TEST-1'else'unresolved_identity'
 recommended=next(iter(codes))if len(codes)==1 else None
 existing=baseline_codes.get(offer)
 dictionary_evidence=[{'dictionary_value_id':attr.get('dictionary_value_id'),'reference_brands':sorted({ref['brand']for ref in dictionary_references.get(attr.get('dictionary_value_id'),[])}),'reference_offers':dictionary_references.get(attr.get('dictionary_value_id'),[])[:5]}for attr in m.get('selected_attributes',{}).get('85',[])]
 result.append({**r,'marketplace':m,'ozon_brand_dictionary_evidence':dictionary_evidence,'direct_api':api.get(r['model'],{}),'reviewed_candidates':confirmed,'recommended_code':recommended,'decision':decision,'code_already_present_in_parent_baseline':existing,'recommended_matches_parent_baseline':recommended==existing if existing and recommended else None})
report={'read_only':True,'warning':'Candidate plan for parent review. No Sheet mutations or production matching rules are applied by this script.','api_queries_available':len(api),'counts':dict(collections.Counter(r['decision']for r in result)),'confirmed_by_brand':dict(collections.Counter(r['brand']or '(empty)'for r in result if r['decision']=='eligible_for_reviewed_registry')),'rows':result}
report['parent_baseline_comparison']={'already_present':sum(bool(r['code_already_present_in_parent_baseline'])for r in result),'recommended_equal':sum(r['recommended_matches_parent_baseline']is True for r in result),'recommended_different':[{'offer_id':r['offer_id'],'existing':r['code_already_present_in_parent_baseline'],'recommended':r['recommended_code']}for r in result if r['recommended_matches_parent_baseline']is False]}
(T/'etm_codes_remaining_candidate_plan_20261016.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print({k:v for k,v in report.items()if k not in['rows','warning']})
