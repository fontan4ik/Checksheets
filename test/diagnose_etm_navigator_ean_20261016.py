"""Read-only alternate explicit marketplace model identity probes."""
import sys,json,time,re,subprocess
from pathlib import Path
from urllib.parse import quote
import requests
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));import config
from network_bypass import SourceAddressAdapter
out=ROOT/'test/etm_navigator_ean_api_20261016.json'
queries=['4680043142033','4660134806747','4607136940642','4607136940680','4607136943902','4607136943919','4650230957771','4650230957788','4650230957832','4650230957849','4650230957870','4650230957887','4650230957894','4650074619460','4670004716885']
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
