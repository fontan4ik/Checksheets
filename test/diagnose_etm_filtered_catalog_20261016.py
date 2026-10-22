"""Read-only filtered m1/catalog review. Never mutates Sheets or catalog."""
import sys,json,time,re,subprocess,collections
from pathlib import Path
from datetime import datetime,timezone
import requests
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));import config
from network_bypass import SourceAddressAdapter
OUT=ROOT/'test/etm_filtered_catalog_remaining_20261016.json'
rows=[r for r in json.loads((ROOT/'test/etm_codes_remaining_candidate_plan_20261016.json').read_text())['rows']if r['decision']=='unresolved_identity']
makers={'Arlight':2010,'Navigator':953,'ОНЛАЙТ':953,'Stekker':2042,'Feron':964}
eans={'14203':'4680043142033','80674':'4660134806747','94064':'4607136940642','94068':'4607136940680','94390':'4607136943902','94391':'4607136943919','95777':'4650230957771','95778':'4650230957788','95783':'4650230957832','95784':'4650230957849','95787':'4650230957870','95788':'4650230957887','95789':'4650230957894','61946':'4650074619460','71688':'4670004716885'}
report={'started_at':datetime.now(timezone.utc).isoformat(),'read_only':True,'endpoint':'https://ipro.etm.ru/api/m1/catalog','manufacturer_ids':makers,'controls':{},'queries':{},'rows':[]}
def save():
 t=OUT.with_suffix('.tmp.json');t.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');t.replace(OUT)
http=requests.Session();http.trust_env=False
for iface in ['en1','en0']:
 m=re.search(r'inet (\d+\.\d+\.\d+\.\d+)',subprocess.run(['/sbin/ifconfig',iface],capture_output=True,text=True).stdout)
 if m:http.mount('https://',SourceAddressAdapter(m.group(1),interface_name=iface));break
last=0
fields=['id','code','offerId','name','art','vendorCode','vendorName','vendor','mnf_name','mnf_code','gdscode','packageName','packAmount','availability']
def query(term,maker):
 global last
 wait=1.05-(time.monotonic()-last)
 if wait>0:time.sleep(wait)
 last=time.monotonic()
 params={'val':term,'type':'code','page':1,'rows':100}
 if maker:params['mnf']=maker
 try:
  response=http.get('https://ipro.etm.ru/api/m1/catalog',params=params,headers={'session-id':sid},timeout=(10,25));payload=response.json();d=payload.get('data',{})
  return {'checked_at':datetime.now(timezone.utc).isoformat(),'http_status':response.status_code,'api_status':payload.get('status',{}).get('code'),'records':d.get('records')if isinstance(d,dict)else None,'total':d.get('total')if isinstance(d,dict)else None,'rows':[{k:r[k]for k in fields if k in r}for r in d.get('rows',[])if isinstance(r,dict)]if isinstance(d,dict)else[]}
 except Exception as exc:return {'error_type':type(exc).__name__}
try:
 sid=http.post('https://ipro.etm.ru/api/v1/user/login',params={'log':config.ETM_LOGIN,'pwd':config.ETM_PASSWORD},timeout=(10,25)).json()['data']['session'];last=time.monotonic()
 for label,term,maker in [('arlight_known_correct','053142',2010),('arlight_known_wrong_manufacturer','053142',953),('nav_known_correct','32022',953),('nav_known_wrong_manufacturer','32022',2010),('arlight_collision_unfiltered','026593',0),('arlight_collision_filtered','026593',2010)]:
  report['controls'][label]={'term':term,'maker':maker,**query(term,maker)};save();print('control',label,'rows',len(report['controls'][label].get('rows',[])),flush=True)
 for i,r in enumerate(rows,1):
  term=r['model'];maker=makers.get(r['brand'],0);key=f'{maker}:{term}';report['queries'][key]={'term':term,'maker':maker,**query(term,maker)}
  if term in eans:
   ekey=f'{maker}:{eans[term]}';report['queries'][ekey]={'term':eans[term],'maker':maker,'official_article':term,**query(eans[term],maker)}
  report['rows'].append({'offer_id':r['offer_id'],'model':term,'brand':r['brand'],'query_keys':[key]+([f'{maker}:{eans[term]}']if term in eans else[]),'marketplace_name':r['marketplace']['name']})
  save()
  if i%10==0:print('reviewed',i,'of',len(rows),flush=True)
 report['finished_at']=datetime.now(timezone.utc).isoformat();save();print('complete',len(rows),'offers',len(report['queries']),'queries',flush=True)
except Exception as exc:save();print('safe_error',type(exc).__name__,flush=True);sys.exit(1)
