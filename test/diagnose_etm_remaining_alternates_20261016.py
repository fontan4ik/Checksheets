"""Read-only alternate explicit marketplace model identity probes."""
import sys,json,time,re,subprocess
from pathlib import Path
from urllib.parse import quote
import requests
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));import config
from network_bypass import SourceAddressAdapter
out=ROOT/'test/etm_remaining_alternates_api_20261016.json'
queries=['DIS4133267','STD02-11-50','STD02-41-30','STD02-41-50','E-381','LL-980','LL-981','LL-982','NLL-T8-11-230-6.5K-G13','NLL-T8-22-230-6.5K-G13','NLL-T8-11-230-4K-G13','NLL-T8-22-230-4K-G13','NLL-G-T8-10-230-4K-G13','NLL-G-T8-10-230-6.5K-G13','NLL-G-T8-20-230-4K-G13','NLL-G-T8-20-230-6.5K-G13','NFL-01-20-6.5K-LED','NFL-02-100-6.5K-BL-LED','OFL-20-4K-BL-IP65-LED','OFL-10-6K-BL-IP65-LED']
http=requests.Session();http.trust_env=False
for iface in ['en1','en0']:
 m=re.search(r'inet (\d+\.\d+\.\d+\.\d+)',subprocess.run(['/sbin/ifconfig',iface],capture_output=True,text=True).stdout)
 if m:http.mount('https://',SourceAddressAdapter(m.group(1),interface_name=iface));break
try:
 sid=http.post('https://ipro.etm.ru/api/v1/user/login',params={'log':config.ETM_LOGIN,'pwd':config.ETM_PASSWORD},timeout=(10,30)).json()['data']['session']
 results={}
 for model in queries:
  try:
   resp=http.get('https://ipro.etm.ru/api/v1/goods/'+quote(model,safe=''),params={'type':'mnf','session-id':sid},timeout=(10,25));d=resp.json();p=d.get('data',{});results[model]={'http_status':resp.status_code,'api_status':d.get('status',{}).get('code'),'product':{k:p[k]for k in ['gdsCode','gdsArt','gdsExtArt','gdsMnfName','gdsNameTitle','barcodes']if k in p}if isinstance(p,dict)else None}
  except Exception as exc:results[model]={'error_type':type(exc).__name__}
  out.write_text(json.dumps({'read_only':True,'queries':results},ensure_ascii=False,indent=2)+'\n');print(model,results[model],flush=True);time.sleep(1.05)
except Exception as exc:print('safe_error',type(exc).__name__,flush=True);sys.exit(1)
