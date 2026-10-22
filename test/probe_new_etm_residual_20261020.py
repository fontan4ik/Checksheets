import sys,json,time,re,subprocess,collections
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import quote
import requests
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import config
from network_bypass import SourceAddressAdapter
rows=json.loads((ROOT/'test/new_etm_residual_identity_20261020.json').read_text())['residual']
http=requests.Session();http.trust_env=False
for iface in ['en1','en0']:
 p=subprocess.run(['/sbin/ifconfig',iface],capture_output=True,text=True);m=re.search(r'inet (\d+\.\d+\.\d+\.\d+)',p.stdout)
 if m:
  ad=SourceAddressAdapter(m.group(1),interface_name=iface);http.mount('https://',ad);http.mount('http://',ad);break
login=http.post('https://ipro.etm.ru/api/v1/user/login',params={'log':config.ETM_LOGIN,'pwd':config.ETM_PASSWORD},timeout=(10,30)).json();sid=login.get('data',{}).get('session')
if not sid:raise RuntimeError('ETM authentication failed')
out={'at':datetime.now(timezone.utc).isoformat(),'read_only':True,'queries':{}}
fields=['gdsCode','gdsArt','gdsExtArt','gdsMnfName','gdsMnfCode','gdsNameTitle','gdsNameInMnf','gdsUnitName','barcodes']
for i,x in enumerate(rows):
 model=x['model']
 try:
  r=http.get('https://ipro.etm.ru/api/v1/goods/'+quote(model,safe=''),params={'type':'mnf','session-id':sid},timeout=(10,25));p=r.json();d=p.get('data',{})
  out['queries'][model]={'http_status':r.status_code,'api_status':p.get('status',{}).get('code'),'product':{k:d[k] for k in fields if k in d} if isinstance(d,dict) else None}
 except Exception as e:out['queries'][model]={'error_type':type(e).__name__}
 (ROOT/'test/new_etm_residual_api_20261020.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
 if (i+1)%10==0:print('ETM queried',i+1,'of',len(rows),flush=True)
 time.sleep(1.05)
print('done',len(out['queries']),flush=True)
