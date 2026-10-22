import sys,json,hashlib,shutil
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import etm_sync_multi_store as etm
out=Path(__file__).parent
ftp=etm.connect_ftp()
manifest=[]
try:
    for warehouse, folder in [('Самара','13'),('Москва','14')]:
        remote=f'/from_etm/{folder}/price.csv'
        before=etm.mdtm(ftp,remote)
        dest=out/f'price_{folder}.csv'
        state=json.loads(etm.FTP_STATE_PATH.read_text())
        key='smr' if folder=='13' else 'msk'
        cached=etm.FTP_LOCAL_ROOT/'from_etm'/folder/'price.csv'
        cached_date=next((f['modified'] for f in state.get(key,{}).get('files',[]) if f['remote_path']==remote),None)
        if cached.exists() and before and cached_date==before:
            a=cached.stat(); shutil.copyfile(cached,dest); b=cached.stat()
            if (a.st_size,a.st_mtime_ns)!=(b.st_size,b.st_mtime_ns): raise RuntimeError('Cache changed during copy')
        else:
            with dest.open('wb') as stream: ftp.retrbinary('RETR '+remote,stream.write)
        after=etm.mdtm(ftp,remote)
        if before!=after: raise RuntimeError('FTP file changed during retrieval')
        entry=dict(warehouse=warehouse,remote=remote,modified=before,bytes=dest.stat().st_size,sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),snapshot_at=datetime.now(timezone.utc).isoformat(),local=str(dest))
        manifest.append(entry); print(json.dumps(entry,ensure_ascii=False),flush=True)
finally: ftp.quit()
(out/'ftp_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
