"""Read-only full WB seller card/document snapshot for certificate cleanup."""
from pathlib import Path
import json, re, sys, time, subprocess
from datetime import datetime, timezone
import requests
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from network_bypass import SourceAddressAdapter
OUT=Path(__file__).with_name('wb_live.json')
config=(ROOT/'Shared_Настройки.js').read_text()
block=config.split('const wbHeaders',1)[1].split('};',1)[0]
m=re.search(r"Authorization\s*:\s*['\"]([^'\"]+)['\"]",block)
if not m: raise RuntimeError('WB authorization unavailable')
http=requests.Session(); http.trust_env=False
for interface in ('en1','en0'):
    r=subprocess.run(['ifconfig',interface],capture_output=True,text=True)
    match=re.search(r'inet (\d+\.\d+\.\d+\.\d+)',r.stdout)
    if 'status: active' in r.stdout and match:
        http.mount('https://',SourceAddressAdapter(match.group(1),interface_name=interface)); break
else: raise RuntimeError('Active physical interface unavailable')
headers={'Authorization':m.group(1),'Content-Type':'application/json'}
started=datetime.now(timezone.utc).isoformat()
rows={}; cursor={'limit':100}; page=0; duplicates=0; seen=set(); complete=False

def save(error=None):
    result={'started_at':started,'checked_at':datetime.now(timezone.utc).isoformat(),'complete':complete,'pages':page,'unique_cards':len(rows),'duplicate_nmids':duplicates,'cursor':cursor,'cards':list(rows.values())}
    if error: result['error']=error
    tmp=OUT.with_suffix('.tmp'); tmp.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':'))); tmp.replace(OUT)
try:
    while True:
        payload={'settings':{'sort':{'ascending':True},'cursor':cursor,'filter':{'withPhoto':-1}}}
        for attempt in range(8):
            response=http.post('https://content-api.wildberries.ru/content/v2/get/cards/list',headers=headers,json=payload,timeout=90)
            if response.status_code==429:
                time.sleep(min(60,5*(attempt+1))); continue
            response.raise_for_status(); break
        else: raise RuntimeError('WB rate limit retry exhausted')
        data=response.json()
        if data.get('error'): raise RuntimeError('WB API error')
        cards=data.get('cards')
        if not isinstance(cards,list): raise RuntimeError('WB cards list missing')
        page+=1
        for card in cards:
            nm=card.get('nmID')
            if not nm: raise RuntimeError('WB card nmID missing')
            if nm in rows: duplicates+=1
            rows[nm]={'vendorCode':card.get('vendorCode'),'nmID':nm,'documents':card.get('documents')}
        returned=data.get('cursor',{})
        total=returned.get('total')
        if total is None: raise RuntimeError('WB returned cursor total missing')
        if total!=len(cards): raise RuntimeError('WB cursor total/card count mismatch')
        if total<100:
            complete=True; save(); break
        nxt={k:returned[k] for k in ('updatedAt','nmID') if k in returned}
        if len(nxt)!=2: raise RuntimeError('WB pagination cursor missing')
        signature=(nxt['updatedAt'],nxt['nmID'])
        if signature in seen: raise RuntimeError('WB cursor repeated')
        seen.add(signature); cursor={'limit':100,**nxt}
        if page%50==0:
            save(); print(json.dumps({'pages':page,'cards':len(rows),'documents':sum(bool(x['documents']) for x in rows.values())}),flush=True)
        time.sleep(.55)
    print(json.dumps({'complete':complete,'pages':page,'cards':len(rows),'documents':sum(bool(x['documents']) for x in rows.values()),'duplicates':duplicates,'path':str(OUT)}),flush=True)
except Exception as exc:
    save(type(exc).__name__)
    print(json.dumps({'complete':False,'pages':page,'cards':len(rows),'error_type':type(exc).__name__}),flush=True)
    raise
