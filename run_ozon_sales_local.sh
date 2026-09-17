#!/bin/bash
set -u
ROOT="/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets"
LOCK_DIR="$ROOT/logs/ozon-sales.lock"
mkdir -p "$ROOT/logs"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  PID_FILE="$LOCK_DIR/pid"
  PID=""
  [ -f "$PID_FILE" ] && PID=$(<"$PID_FILE")
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    printf 'Ozon sales: процесс %s уже выполняется\n' "$PID"
    exit 0
  fi
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR" || exit 1
fi
printf '%s\n' "$$" > "$LOCK_DIR/pid"
trap 'rm -rf "$LOCK_DIR"' EXIT INT TERM
cd "$ROOT" || exit 1
"$ROOT/scripts/run_with_telegram_alert.sh" ozon-fbo-fbs-sales -- /opt/homebrew/bin/node "$ROOT/ozon_fbo_fbs_sales_local.js"
exit $?
