#!/bin/bash
# One independent queue per marketplace. Supplier uploads stay in their existing modules.
set -u

ROOT="/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets"
MARKETPLACE="${1:-}"
case "$MARKETPLACE" in ozon|wb|yandex) ;; *) echo "Usage: $0 ozon|wb|yandex" >&2; exit 2 ;; esac

mkdir -p "$ROOT/logs" /tmp/checksheets_locks
LOCK="/tmp/checksheets_locks/marketplace_${MARKETPLACE}.lock"
LOG="$ROOT/logs/marketplace_${MARKETPLACE}_$(date +%Y%m%d).log"
if ! mkdir "$LOCK" 2>/dev/null; then
  OLD_PID=$(cat "$LOCK/pid" 2>/dev/null || true)
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "[$(date)] $MARKETPLACE worker already running (PID $OLD_PID)" >> "$LOG"
    exit 0
  fi
  rm -f "$LOCK/pid"
  rmdir "$LOCK" 2>/dev/null || { echo "Lock unavailable: $LOCK" >&2; exit 1; }
  mkdir "$LOCK" || exit 1
fi
echo $$ > "$LOCK/pid"
trap 'rm -f "$LOCK/pid"; rmdir "$LOCK" 2>/dev/null || true' EXIT
cd "$ROOT" || exit 1

FAILED=0
run_supplier() {
  echo "[$(date)] $MARKETPLACE: starting $1" >> "$LOG"
  /opt/homebrew/bin/node "$1" "--marketplace=$MARKETPLACE" >> "$LOG" 2>&1
  RESULT=$?
  echo "[$(date)] $MARKETPLACE: $1 finished with code $RESULT" >> "$LOG"
  if [ "$RESULT" -ne 0 ]; then FAILED=1; fi
}

case "$MARKETPLACE" in
  ozon)
    run_supplier sync-rs-stocks.js
    run_supplier sync-feron-stocks.js
    run_supplier sync-etm-stocks.js
    run_supplier sync-cdek-ozon-stocks.js
    ;;
  wb)
    run_supplier sync-rs-stocks.js
    run_supplier sync-feron-stocks.js
    run_supplier sync-etm-stocks.js
    ;;
  yandex)
    run_supplier sync-cdek-ozon-stocks.js
    ;;
esac
echo "[$(date)] $MARKETPLACE worker completed; failed=$FAILED" >> "$LOG"
exit "$FAILED"
