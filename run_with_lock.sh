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
        (
            FIRST_EXIT_CODE=0
            SECOND_EXIT_CODE=0

            echo "[$(date)] Starting sync-cdek-stocks.js"
            /opt/homebrew/bin/node sync-cdek-stocks.js
            FIRST_EXIT_CODE=$?
            echo "[$(date)] sync-cdek-stocks.js finished with exit code $FIRST_EXIT_CODE"

            echo "[$(date)] Waiting 60 seconds before sync-cdek-ozon-stocks.js"
            /bin/sleep 60

            echo "[$(date)] Starting sync-cdek-ozon-stocks.js"
            /opt/homebrew/bin/node sync-cdek-ozon-stocks.js
            SECOND_EXIT_CODE=$?
            echo "[$(date)] sync-cdek-ozon-stocks.js finished with exit code $SECOND_EXIT_CODE"

            if [ "$FIRST_EXIT_CODE" -ne 0 ] || [ "$SECOND_EXIT_CODE" -ne 0 ]; then
                exit 1
            fi
        ) >> "$LOG_FILE" 2>&1
        ;;
    *)
        echo "[$(date)] Unknown script: $SCRIPT_NAME" >> "$LOG_FILE"
        rm -f "$LOCK_FILE"
        exit 1
        ;;
esac

EXIT_CODE=$?
echo "[$(date)] $SCRIPT_NAME finished with exit code $EXIT_CODE" >> "$LOG_FILE"

# Remove lock file
rm -f "$LOCK_FILE"

exit $EXIT_CODE
