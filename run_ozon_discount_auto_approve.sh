#!/bin/bash
set -euo pipefail

ROOT="/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets"
MODE="${1:---poll}"
case "$MODE" in
  --poll)
    SERVICE="ozon-discount-auto-approve"
    ;;
  --refresh-differences)
    SERVICE="ozon-discount-difference-refresh"
    ;;
  *)
    printf 'Unknown mode: %s\n' "$MODE" >&2
    exit 64
    ;;
esac

cd "$ROOT"
exec "$ROOT/scripts/run_with_telegram_alert.sh" "$SERVICE" -- \
  /opt/homebrew/bin/node "$ROOT/ozon_discount_auto_approve_local.js" "$MODE"
