# ETM Sync Issues Analysis

## Problems Identified

### 1. **Rate Limiting Issues**
- **Current implementation**: Only handles 429 with a single 5-second retry
- **ETM API limits**: 1 request per second for remains/prices
- **Problem**: With 5 parallel workers and 50-item chunks, the script can send 5 requests simultaneously, exceeding the 1 req/sec limit
- **Solution**: Reduce parallelism and add proper rate limiting between requests

### 2. **Incorrect Stock Extraction Logic**
The `_extract_samara_stock()` function has several issues:

**Issue A: Priority Logic Flaw**
```python
if rc_stock > 0:
    return rc_stock
elif op_stock_sum > 0:
    return op_stock_sum
return aggregate_stock
```
- Returns RC stock even if it's less than OP or aggregate
- Should return the MAXIMUM available stock, not just the first non-zero value

**Issue B: Missing Store Types**
- Only checks for "rc", "op", "all", "rc2sum"
- ETM API also returns "crs" (Логистический центр) which may contain stock
- Missing stores means missing inventory

**Issue C: Samara Detection**
- Only looks for "стройкерамика" or "самар" in store name
- May miss variations or when RequestStoreName indicates Samara but individual stores don't

### 3. **Article Variant Logic**
- Currently only strips "-{digit}" suffixes
- May need to handle other article formats from the sheet

### 4. **Session Expiry Handling**
- Returns 0 on 403 (session expired)
- Should attempt to renew session and retry

### 5. **Config Path Issue**
- Credentials path uses Windows format: `C:/AI/Checksheets/...`
- Should use relative path for cross-platform compatibility

## Recommended Fixes

### Priority 1: Rate Limiting
- Reduce `max_workers` from 5 to 1 (sequential processing)
- Add 1.1 second delay between requests (slightly above 1 req/sec limit)
- Keep chunk-based processing for progress tracking

### Priority 2: Stock Extraction
- Return maximum stock across all Samara stores
- Add support for "crs" store type
- Better aggregate handling

### Priority 3: Retry Logic
- Implement exponential backoff for 429 errors
- Add session renewal on 403 errors

### Priority 4: Config
- Fix credentials path to use relative path
