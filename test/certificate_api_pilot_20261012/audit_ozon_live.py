import datetime,json,re,sys,time,subprocess
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from network_bypass import SourceAddressAdapter
source=(ROOT/'Shared_Настройки.js').read_text()
client=re.search(r"const clientId\s*=\s*'([^']+)'",source)[1]
key=re.search(r"const apiKey\s*=\s*'([^']+)'",source)[1]
session=requests.Session();session.trust_env=False
for iface in ('en1','en0'):
 p=subprocess.run(['ifconfig',iface],capture_output=True,text=True)
 match=re.search(r'inet (\d+\.\d+\.\d+\.\d+)',p.stdout)
 if match and 'status: active' in p.stdout:
  session.mount('https://',SourceAddressAdapter(match[1],interface_name=iface)); break
headers={'Client-Id':client,'Api-Key':key,'Content-Type':'application/json'}
def call(path,payload):
 for attempt in range(4):
  r=session.post('https://api-seller.ozon.ru'+path,json=payload,headers=headers,timeout=45)
  if r.status_code in (429,500,502,503) and attempt<3:time.sleep(2**attempt);continue
  
  if r.status_code>=400:print('API error',path,r.status_code,r.text[:1200],flush=True)
  r.raise_for_status();time.sleep(.15);return r.json()
out={'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'certificate_statuses':call('/v1/product/certificate/status/list',{}),'product_statuses':call('/v1/product/certificate/product_status/list',{}),'certificates':[],'complete':False}
page=1
while True:
 data=call('/v1/product/certificate/list',{'page':page,'page_size':100})['result']
 out['certificates'].extend(data['certificates'])
 if page>=data['page_count']:break
 page+=1
for i,c in enumerate(out['certificates']):
 items=[];page=1
 while True:
  result=call('/v1/product/certificate/products/list',{'certificate_id':c['certificate_id'],'offset':len(items),'limit':1000})['result']
  items.extend(result['items'])
  if len(items)>=result['count']:break
  if not result['items']:raise RuntimeError('Incomplete binding pagination')
  page+=1
 c['live_bindings']=items;c['live_binding_count']=len(items)
 print(json.dumps({'index':i+1,'id':c['certificate_id'],'status':c['status_code'],'bindings':len(items)},ensure_ascii=False),flush=True)
 outpath=Path(__file__).with_name('ozon_live.json');outpath.write_text(json.dumps(out,ensure_ascii=False,indent=2))
out['complete']=True;outpath.write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({'complete':True,'certificates':len(out['certificates']),'bindings':sum(c['live_binding_count'] for c in out['certificates'])}))
