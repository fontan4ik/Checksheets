#!/bin/bash
# Preserve the scheduled command's exit status and alert the existing Telegram chat on failure.
set -u

ROOT="/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets"
SERVICE="${1:-}"
if [ -z "$SERVICE" ] || [ "${2:-}" != "--" ] || [ "$#" -lt 3 ]; then
  printf 'Usage: %s service -- command [args...]\n' "$0" >&2
  exit 64
fi
shift 2

OUTPUT_FILE=$(mktemp "${TMPDIR:-/tmp}/checksheets-alert.XXXXXX") || exit 1
trap 'rm -f "$OUTPUT_FILE"' EXIT

"$@" 2>&1 | tee "$OUTPUT_FILE"
EXIT_CODE=${PIPESTATUS[0]}

if [ "$EXIT_CODE" -ne 0 ]; then
  # The existing notifier reads the project's configured bot token and chat ID.
  "$ROOT/.venv-etm-export/bin/python" - "$ROOT" "$SERVICE" "$EXIT_CODE" "$OUTPUT_FILE" <<'PY' >&2
import sys
from pathlib import Path

root, service, exit_code, log_path = sys.argv[1:]
sys.path.insert(0, root)
from telegram_notifier import send_telegram_alert

tail = Path(log_path).read_bytes()[-6000:].decode("utf-8", errors="replace")
if not send_telegram_alert(service, f"код завершения {exit_code}", tail):
    print(f"Telegram alert failed for {service}", file=sys.stderr)
PY
fi

exit "$EXIT_CODE"
