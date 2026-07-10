# Checksheets Sync Jobs Status

## Installed Jobs

All 5 launchd jobs have been created and loaded:

1. **rs_sync** - 07:00 and 18:30 daily
2. **feron_sync** - 12:00 and 19:00 daily  
3. **etm_sync** - 12:00 and 19:00 daily
4. **sync_feron_stocks** - 12:30 and 19:30 daily
5. **sync_etm_stocks** - 13:00 and 20:00 daily

## Configuration

- **Lock files**: `/tmp/checksheets_locks/` - prevents overlapping runs
- **Logs**: `/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets/logs/`
- **VPN**: V2Box stays connected, split routing handles domain access
- **Python**: `/opt/homebrew/bin/python3`
- **Node**: `/opt/homebrew/bin/node`

## Network Status

✓ RS (russvet.ru) - reachable
✓ ETM (ipro.etm.ru) - reachable
✓ Feron (api.feron.ru) - reachable
✓ Ozon (api-seller.ozon.ru) - reachable
✓ WB (marketplace-api.wildberries.ru) - reachable
✓ Google Sheets - reachable

## Next Steps

1. Monitor the live launchd windows and logs
2. Keep the lock-file wrapper in place to avoid overlap
3. Revisit timings only if the business schedule changes

## Manual Testing

Test any job immediately:
```bash
launchctl start com.checksheets.rs_sync
launchctl start com.checksheets.feron_sync
launchctl start com.checksheets.etm_sync
launchctl start com.checksheets.sync_feron_stocks
launchctl start com.checksheets.sync_etm_stocks
```

Check logs:
```bash
tail -f ~/Code/Checksheets_Project/Checksheets/logs/*.log
```

Unload a job:
```bash
launchctl unload ~/Library/LaunchAgents/com.checksheets.rs_sync.plist
```
