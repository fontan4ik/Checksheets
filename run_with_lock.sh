#!/bin/bash
# Wrapper script to run jobs with lock file protection

SCRIPT_NAME="$1"
LOCK_DIR="/tmp/checksheets_locks"
LOG_DIR="/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets/logs"

mkdir -p "$LOCK_DIR" "$LOG_DIR"

# Clean up logs older than 7 days to keep the directory tidy
find "$LOG_DIR" -type f \( -name "*.log" -o -name "*.err" \) -mtime +7 -delete 2>/dev/null

LOCK_FILE="$LOCK_DIR/${SCRIPT_NAME}.lock"
LOG_FILE="$LOG_DIR/${SCRIPT_NAME}_$(date +%Y%m%d).log"

# Check if already running
if [ -f "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "[$(date)] $SCRIPT_NAME already running (PID $PID), skipping" >> "$LOG_FILE"
        exit 0
    else
        echo "[$(date)] Stale lock file found, removing" >> "$LOG_FILE"
        rm -f "$LOCK_FILE"
    fi
fi

# Create lock file
echo $$ > "$LOCK_FILE"

# Run the script
echo "[$(date)] Starting $SCRIPT_NAME" >> "$LOG_FILE"
cd /Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets

case "$SCRIPT_NAME" in
    rs_sync)
        /opt/homebrew/bin/python3 rs_sync_local.py >> "$LOG_FILE" 2>&1
        ;;
    feron_sync)
        /opt/homebrew/bin/python3 feron_sync_local.py >> "$LOG_FILE" 2>&1
        ;;
    feron_mic_sync)
        /opt/homebrew/bin/python3 feron_mic_sync_local.py >> "$LOG_FILE" 2>&1
        ;;
    etm_sync)
        /opt/homebrew/bin/python3 etm_sync_multi_store.py >> "$LOG_FILE" 2>&1
        EXIT_CODE=$?
        echo "[$(date)] etm_sync finished with exit code $EXIT_CODE. sync_etm_stocks remains on its own hourly launchd schedule." >> "$LOG_FILE"
        ;;
    sync_etm_codes)
        echo "[$(date)] sync_etm_codes disabled: CODES are no longer written" >> "$LOG_FILE"
        EXIT_CODE=0
        ;;
    sync_feron_stocks)
        /opt/homebrew/bin/node sync-feron-stocks.js >> "$LOG_FILE" 2>&1
        ;;
    sync_etm_stocks)
        /opt/homebrew/bin/node sync-etm-stocks.js >> "$LOG_FILE" 2>&1
        ;;
    cdek_hourly_sync)
        echo "[$(date)] cdek_hourly_sync disabled by operator request" >> "$LOG_FILE"
        ;;
    *)
        echo "[$(date)] Unknown script: $SCRIPT_NAME" >> "$LOG_FILE"
        rm -f "$LOCK_FILE"
        exit 1
        ;;
esac

if [ -z "${EXIT_CODE+x}" ]; then
    EXIT_CODE=$?
fi
echo "[$(date)] $SCRIPT_NAME finished with exit code $EXIT_CODE" >> "$LOG_FILE"

# Alert in Telegram if script failed
if [ $EXIT_CODE -ne 0 ]; then
    BOT_TOKEN="8795048754:AAHXbXFhzTHa6ICvwyQ1sE2pBvb-ZgqZIac"
    CHAT_ID="-5299125247"
    DATE_STR=$(date '+%d.%m.%Y')
    TIME_STR=$(date '+%H:%M:%S')
    ERR_TAIL=$(tail -n 15 "$LOG_FILE" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')
    MSG="🚨 <b>Сбой триггера Checksheets: $SCRIPT_NAME</b>
📅 <b>Дата ошибки:</b> <code>$DATE_STR</code>
⏰ <b>Время ошибки:</b> <code>$TIME_STR</code>
❌ <b>Код завершения:</b> <code>$EXIT_CODE</code>

<b>Последние строки лога:</b>
<pre>$ERR_TAIL</pre>"


    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "{\"chat_id\": \"$CHAT_ID\", \"text\": $(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$MSG"), \"parse_mode\": \"HTML\", \"disable_web_page_preview\": true}" > /dev/null 2>&1
fi

# Remove lock file
rm -f "$LOCK_FILE"

exit $EXIT_CODE
