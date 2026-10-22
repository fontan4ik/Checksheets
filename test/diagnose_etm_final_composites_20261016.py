"""Read-only exact source-series and official-EAN final probes."""
import sys,json,time,re,subprocess
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));import config
from network_bypass import SourceAddressAdapter
http=requests.Session();http.trust_env=False
for iface in ['en1','en0']:
 m=re.search(r'inet (\d+\.\d+\.\d+\.\d+)',subprocess.run(['/sbin/ifconfig',iface],capture_output=True,text=True).stdout)
 if m:http.mount('https://',SourceAddressAdapter(m.group(1),interface_name=iface));break
out=ROOT/'test/etm_final_composite_probes_20261016.json';results={}
try:
 sid=http.post('https://ipro.etm.ru/api/v1/user/login',params={'log':config.ETM_LOGIN,'pwd':config.ETM_PASSWORD},timeout=(10,25)).json()['data']['session'];time.sleep(1.05)
 for term,maker in [('LL-980',0),('LL-981',0),('LL-982',0),('STD02-11-50',0),('STD02-41-30',0),('STD02-41-50',0),('4650074619460',0),('4670004716885',0),('E-381',964)]:
  try:
   params={'val':term,'type':'code','page':1,'rows':100}
   if maker:params['mnf']=maker
   r=http.get('https://ipro.etm.ru/api/m1/catalog',params=params,headers={'session-id':sid},timeout=(10,25));p=r.json();d=p.get('data',{});res={'http_status':r.status_code,'api_status':p.get('status',{}).get('code'),'records':d.get('records'),'total':d.get('total'),'rows':[{k:c[k]for k in ['code','offerId','name','art','vendorName','vendor']if k in c}for c in d.get('rows',[])]};results[f'{maker}:{term}']=res;print(term,res,flush=True)
  except Exception as exc:results[f'{maker}:{term}']={'error_type':type(exc).__name__};print(term,type(exc).__name__,flush=True)
  out.write_text(json.dumps({'read_only':True,'queries':results},ensure_ascii=False,indent=2)+'\n');time.sleep(1.05)
except Exception as exc:print('safe_error',type(exc).__name__,flush=True);sys.exit(1)
