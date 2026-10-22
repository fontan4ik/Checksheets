#!/bin/bash
set -u
cd /Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets || exit 1
LOCK=/tmp/checksheets_locks/marketplace_wb.lock
mkdir -p /tmp/checksheets_locks
if ! mkdir "$LOCK" 2>/dev/null; then
  echo 'WB queue occupied; no second writer started'
  exit 75
fi
echo $$ > "$LOCK/pid"
trap 'rm -f "$LOCK/pid"; rmdir "$LOCK" 2>/dev/null || true' EXIT
FAILED=0
for SCRIPT in sync-rs-stocks.js sync-etm-stocks.js; do
  echo "[$(date -u)] START $SCRIPT --marketplace=wb"
  /opt/homebrew/bin/node "$SCRIPT" --marketplace=wb
  RESULT=$?
  echo "[$(date -u)] END $SCRIPT code=$RESULT"
  if [ "$RESULT" -ne 0 ]; then FAILED=1; fi
done
echo "[$(date -u)] COMPLETE failed=$FAILED"
exit "$FAILED"
