#!/bin/bash
set -u

ROOT="/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets"
LOCK_DIR="$ROOT/logs/ozon-reviews.lock"
NODE_BIN="/opt/homebrew/bin/node"
SCRIPT="$ROOT/ozon_reviews_local.js"

mkdir -p "$ROOT/logs"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  PID_FILE="$LOCK_DIR/pid"
  PID=""
  [ -f "$PID_FILE" ] && PID=$(<"$PID_FILE")
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    printf '%s Ozon reviews: уже выполняется (PID %s), новый запуск пропущен\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$PID"
    exit 0
  fi
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR" || exit 0
fi

printf '%s\n' "$$" > "$LOCK_DIR/pid"
cleanup() {
  rm -rf "$LOCK_DIR"
}
trap cleanup EXIT INT TERM

cd "$ROOT" || exit 1
printf '%s Ozon reviews: старт\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
"$NODE_BIN" "$SCRIPT"
EXIT_CODE=$?
printf '%s Ozon reviews: завершение с кодом %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$EXIT_CODE"
exit "$EXIT_CODE"
