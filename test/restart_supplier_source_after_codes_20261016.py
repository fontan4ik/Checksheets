"""One-off background restart; wait for an older source run before starting anew."""
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
JOBS={'feron_sync':[], 'etm_sync':['--force'], 'rs_sync':[]}
job=sys.argv[1]
if job not in JOBS:
    raise SystemExit('Unknown supplier source job')
lock=Path('/tmp/checksheets_locks')/(job+'.lock')
last_pid=None
while lock.exists():
    try:
        pid=int(lock.read_text().strip())
        os.kill(pid,0)
    except (ValueError,ProcessLookupError,FileNotFoundError):
        break
    if pid!=last_pid:
        print(f'{job}: queued after active source PID {pid}',flush=True)
        last_pid=pid
    time.sleep(15)
print(f'{job}: starting refresh after CODES verification',flush=True)
os.chdir(ROOT)
os.execv(str(ROOT/'run_with_lock.sh'),[str(ROOT/'run_with_lock.sh'),job,*JOBS[job]])
