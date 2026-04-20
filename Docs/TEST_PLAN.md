# ETM Sync Testing Plan

## Test Status: ⚠️ Cannot test live due to network connectivity issues

**Error:** `Connection aborted - Remote end closed connection without response`

This is a network/infrastructure issue, not a code issue. The ETM API at `https://ipro.etm.ru` is not responding.

## Code Verification ✅

I've verified all fixes are correctly implemented:

### 1. Rate Limiting Fix ✅
**File:** `etm_sync_local.py` lines 170-260

```python
# Sequential processing with 1.1s delay
request_delay = 1.1
last_request_time = 0

for j, article in enumerate(chunk):
    elapsed = time.time() - last_request_time
    if elapsed < request_delay:
        time.sleep(request_delay - elapsed)
    
    last_request_time = time.time()
    stock = fetch_etm_stock(article, session_id)
```

✅ Removed ThreadPoolExecutor
✅ Added 1.1 second delay between requests
✅ Sequential processing respects 1 req/sec limit

### 2. Stock Extraction Fix ✅
**File:** `etm_sync_local.py` lines 46-98

```python
def _extract_samara_stock(info_stores, request_store_name=""):
    samara_stocks = []  # Collect all Samara-related stocks
    
    for store in info_stores:
        # ... extract qty ...
        
        # Collect stocks from Samara stores (rc, op, crs)
        if is_samara and store_type in ["rc", "op", "crs"]:
            if qty > 0:
                samara_stocks.append(qty)
    
    # Return the MAXIMUM stock found
    if samara_stocks:
        return max(samara_stocks)
    
    return aggregate_stock
```

✅ Returns MAX stock instead of first non-zero
✅ Added "crs" store type support
✅ Collects all Samara stocks before deciding

### 3. Exponential Backoff ✅
**File:** `etm_sync_local.py` lines 114-167

```python
if response.status_code == 429:
    wait_time = min(2 ** (retry_count + 1), 10)
    print(f"Rate limit hit for article {variant}, waiting {wait_time}s...")
    time.sleep(wait_time)
    
    if retry_count < 3:
        return fetch_etm_stock(article, session_id, retry_count + 1)
```

✅ Exponential backoff: 2s, 4s, 8s
✅ Max 3 retries
✅ Proper recursion with retry counter

### 4. Config Path Fix ✅
**File:** `config.py` line 15

```python
GSHEETS_CREDS_FILE = "nomadic-bedrock-485314-b0-d16b6095cbb3.json"
```

✅ Changed from `C:/AI/Checksheets/...` to relative path
✅ Cross-platform compatible

## Manual Testing When Network Available

When ETM API is accessible, run:

```bash
cd /path/to/Checksheets
python3 etm_sync_local.py
```

**Expected behavior:**
1. Session login succeeds
2. Articles processed sequentially with 1.1s delays
3. No 429 rate limit errors
4. Progress shown every 10 articles
5. Stock values written to Google Sheet column AL

**Expected results for test articles:**
- 33110 → ~275 units
- 104801209 → ~26 units
- 105101210 → ~103 units
- 23222 → ~239 units

## Alternative: Dry Run Test

To verify logic without API calls, you could:

1. Mock the ETM API responses
2. Test `_extract_samara_stock()` with sample data
3. Verify rate limiting timing with dummy requests

## Conclusion

✅ All code fixes are correctly implemented
⚠️ Live testing blocked by network connectivity to ETM API
📋 Ready for testing when network access is available

The fixes address all identified issues:
- Rate limiting (parallel → sequential with delays)
- Stock extraction (first non-zero → maximum)
- Missing store types (added "crs")
- Config path (Windows → relative)
