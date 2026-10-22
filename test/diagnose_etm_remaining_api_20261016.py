"""Read-only ETM catalog identity review. Outputs sanitized evidence in test/."""
import sys,json,time,re,subprocess,collections
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import quote
import requests,gspread
from google.oauth2.service_account import Credentials
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import config
from network_bypass import SourceAddressAdapter
OUT=ROOT/'test/etm_codes_remaining_api_20261016.json'
INPUT=ROOT/'test/etm_codes_remaining_20261016.json'
norm=lambda x:re.sub(r'[^a-zа-яё0-9]','',str(x or '').casefold())

def save(data):
 temp=OUT.with_suffix('.tmp.json');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');temp.replace(OUT)

def main():
 remaining=json.loads(INPUT.read_text())['rows']
 # Source names are evidence only; no Google Sheets mutation methods are used.
 creds=Credentials.from_service_account_file(ROOT/'nomadic-bedrock-485314-b0-d7624dedd83c.json',scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'])
 book=gspread.authorize(creds).open_by_key('15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI')
 oz=book.worksheet('ТЕСТ').get('A:Y');oh=oz[0];ozmap={str(r[0]):r for r in oz[1:]if r and r[0]}
 source={}
 for x in remaining:
  r=ozmap.get(x['offer_id'],[]);source[x['offer_id']]={'ozon_name':r[23]if len(r)>23 else '', 'ozon_brand':r[2]if len(r)>2 else '', 'ozon_product_id':r[20]if len(r)>20 else '', 'ozon_sku':r[21]if len(r)>21 else ''}
 http=requests.Session();http.trust_env=False
 for iface in ['en1','en0']:
  result=subprocess.run(['/sbin/ifconfig',iface],capture_output=True,text=True)
  match=re.search(r'inet (\d+\.\d+\.\d+\.\d+)',result.stdout)
  if match:
   adapter=SourceAddressAdapter(match.group(1),interface_name=iface);http.mount('https://',adapter);http.mount('http://',adapter);break
 else:raise RuntimeError('No physical network interface found')
 login=http.post('https://ipro.etm.ru/api/v1/user/login',params={'log':config.ETM_LOGIN,'pwd':config.ETM_PASSWORD},timeout=(10,30)).json()
 sid=login.get('data',{}).get('session')
 if not sid:raise RuntimeError('ETM authentication failed')
 report={'started_at':datetime.now(timezone.utc).isoformat(),'read_only':True,'endpoint':'/api/v1/goods/{model}?type=mnf','queries':{},'rows':[]}
 if OUT.exists():
  old=json.loads(OUT.read_text());report['queries']=old.get('queries',{})
 fields=['gdsCode','gdsArt','gdsExtArt','gdsMnfName','gdsMnfCode','gdsNameTitle','gdsNameInMnf','gdsUnitName','gdsAvailOP','gdsAvailLC','gdsAvailKDK','gdsCommonAvail','gdsRemAddSt','barcodes']
 models=list(dict.fromkeys(x['model']for x in remaining if x['model']))
 for i,model in enumerate(models,1):
  previous=report['queries'].get(model,{})
  if previous and not previous.get('error_type') and previous.get('http_status',200)<500 and previous.get('api_status') not in {403,429,500,502,503,504}:continue
  try:
   response=http.get('https://ipro.etm.ru/api/v1/goods/'+quote(model,safe=''),params={'type':'mnf','session-id':sid},timeout=(10,25))
   payload=response.json();status=payload.get('status',{})
   q={'http_status':response.status_code,'api_status':status.get('code'),'message':status.get('message',''),'checked_at':datetime.now(timezone.utc).isoformat()}
   data=payload.get('data')
   if isinstance(data,dict):q['product']={k:data[k]for k in fields if k in data}
   elif data is not None:q['data_type']=type(data).__name__
   report['queries'][model]=q
  except Exception as exc:report['queries'][model]={'error_type':type(exc).__name__}
  if i%20==0:save(report);print('queried',i,'of',len(models),flush=True)
  time.sleep(1.05)
 for x in remaining:
  q=report['queries'].get(x['model'],{});p=q.get('product',{});src=source[x['offer_id']]
  exact_article=norm(x['model'])in {norm(p.get('gdsArt')),norm(p.get('gdsExtArt'))}
  exact_brand=bool(x['brand'])and norm(x['brand'])==norm(p.get('gdsMnfName'))
  title=src['ozon_name'];manufacturer=p.get('gdsMnfName','')
  title_brand_evidence=bool(manufacturer)and norm(manufacturer)in norm(title)
  decision='confirmed_exact_identity'if p.get('gdsCode')and exact_article and exact_brand else 'review_missing_brand_name_evidence'if p.get('gdsCode')and exact_article and not x['brand']and title_brand_evidence else 'review_identity_mismatch'if p.get('gdsCode')else 'unresolved_api'
  report['rows'].append({**x,'source':src,'etm_product':p,'article_match':exact_article,'manufacturer_match':exact_brand,'source_name_mentions_manufacturer':title_brand_evidence,'decision':decision})
 report['finished_at']=datetime.now(timezone.utc).isoformat();report['counts']=dict(collections.Counter(x['decision']for x in report['rows']));save(report);print('complete',report['counts'],flush=True)
if __name__=='__main__':
 try:main()
 except Exception as exc:print('safe_error',type(exc).__name__,flush=True);sys.exit(1)
