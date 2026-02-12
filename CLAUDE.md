# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Google Apps Script** project for synchronizing product data from **Ozon** and **Wildberries** (ВБ) marketplaces into a Google Sheet. The sheet tracks inventory, prices, orders, and analytics for ~10,000+ products.

**Target Spreadsheet:** Sheet named `тест` in the active spreadsheet
**Main Entry Point:** [Главные функции.gs](Главные%20функции.gs) contains trigger-compatible functions

---

## 🚀 WORKFLOW WITH THIS PROJECT

### Phase 1: Problem Analysis

When user reports an issue:
1. **Ask for specific symptoms** - which columns are empty/wrong?
2. **Check diagnostic logs** - user runs `runDiagnostics()`
3. **Identify root cause** - API errors, wrong column mapping, missing functions

### Phase 2: Create/Update .gs Files

**Local Development:**
- All `.gs` files are in the project root directory
- **NEVER modify Apps Script directly** - always edit local files first
- After fixing, provide file to user for upload

**File Creation Rules:**
1. **New functionality** → Create new `.gs` file (e.g., `WB Артикулы.gs`)
2. **Bug fixes** → Update existing file
3. **Breaking changes** → Create `V2` version (preserve original)

### Phase 3: Provide Upload Instructions

**ALWAYS include this information after modifying files:**

```
📋 ФАЙЛЫ ДЛЯ ЗАГРУЗКИ В APPS SCRIPT:

ЗАМЕНИТЬ:
1. ИмяФайла.gs - описание изменения

НОВЫЕ ФАЙЛЫ:
2. НовыйФайл.gs - описание

ВЫПОЛНИТЬ ПОСЛЕ ЗАГРУЗКИ:
functionName() - описание
```

**User uploads files:**
1. Open Google Sheet → Extensions → Apps Script
2. Create/Update file with same name
3. Copy-paste code from local file
4. Save (Ctrl+S)

### Phase 4: Verify & Test

After user uploads:
1. Run `runDiagnostics()` - check API keys and functions
2. Run specific functions with logging
3. Check results in sheet columns
4. View logs: **View → Logs** in Apps Script

---

## 📁 PROJECT STRUCTURE

### Local Files (.gs)
```
project-root/
├── settings.gs              # API keys, URLs, rate limits
├── utils.gs                 # Helper functions
├── fetchapp.gs              # HTTP library
├── Главные функции.gs       # Main entry points
├── Ozon *.gs               # Ozon-specific functions (7 files)
├── ВБ *.gs / WB *.gs      # Wildberries functions (5 files)
└── test/                   # Local testing only
    ├── test_*.js           # Node.js tests
    └── *.json             # Mock API responses
```

### Column Mapping Reference
```
A (1)   - Артикул (primary key)
T (20)  - Артикул ВБ (nmId)
U (21)  - Product_id Ozon
```

---

## 🔧 DIAGNOSTIC FUNCTIONS

**Always use these for troubleshooting:**

```javascript
// Full system diagnostics
function runDiagnostics() {
  checkSheetData();      // Check row counts, filled columns
  checkAPIKeys();        // Verify API keys are set
  checkFunctionsExist(); // Verify functions are loaded
  testAPIConnections();  // Test actual API calls
}

// Quick API test
function testAPIConnections() {
  // Tests Ozon and WB API with actual requests
  // Shows 200/401/403 errors
}

// Run with logging
function runUpdateWithLogs() {
  console.log('1. syncOfferIdWithProductId()...');
  syncOfferIdWithProductId();
  // ... other functions
}
```

---

## 🐛 COMMON ISSUES & SOLUTIONS

### Issue: "Function executed but data didn't change"

**Diagnosis:**
1. Check if API keys are set: `runDiagnostics()`
2. Check API response codes: `testAPIConnections()`
3. Check logs for errors

**Common causes:**
- ❌ WB Token expired (error 401) → Update in `settings.gs`
- ❌ Wrong column mapping → Check file reads/writes correct column
- ❌ Functions not loaded → Verify file exists in Apps Script
- ❌ Empty data source → Check API returns data

### Issue: "Columns are empty"

**Check list:**
- [ ] Are functions loaded in Apps Script?
- [ ] Are API keys valid?
- [ ] Is there data in column A (offer_id)?
- [ ] Do functions execute without errors?

**Solution:**
```javascript
// 1. Test single function
syncOfferIdWithProductId();

// 2. Check logs
View → Logs

// 3. Check specific column
=COUNTA(U2:U10000) // Should show >0 if Product_id is filled
```

### Issue: "updateWBArticles returns 0 updated"

**Probable cause:** WB stocks API doesn't have data for these articles

**Solution:**
- Verify articles exist in WB
- Check WB stocks API manually
- Articles may not be synced yet

---

## 📊 CRITICAL COLUMNS & FUNCTIONS

| Column | Letter | Function | File | Status |
|--------|--------|----------|------|--------|
| Product_id Ozon | 21 | U | `syncOfferIdWithProductId()` | Ozon Получить товары.gs | ✅ |
| Артикул ВБ | 20 | T | `updateWBArticles()` | WB Артикулы.gs | ✅ |
| Уход Мес ВБ | 18 | R | `updateWBAnalytics()` | WB Аналитика.gs | ✅ |
| Уход КВ ВБ | 19 | S | `updateWBAnalytics()` | WB Аналитика.gs | ✅ |
| Остаток ФБО ВБ | 15 | O | `main()` | ВБ.gs | ⚠️ Check warehouse_id |
| Остаток ФБС ВБ | 16 | P | `main()` | ВБ.gs | ⚠️ Check warehouse_id |

---

## ✅ DEVELOPMENT CHECKLIST

Before providing files to user:

- [ ] Tested logic locally with mock data (in `/test` folder)
- [ ] Verified column numbers are correct
- [ ] Added proper error handling
- [ ] Included logging for debugging
- [ ] Checked for API rate limiting
- [ ] Updated `CLAUDE.md` if adding new functionality
- [ ] Provided clear upload instructions

---

## 🔄 UPDATE PROCESS EXAMPLE

**Scenario:** User reports "Артикул ВБ column is empty"

**Step 1: Analyze**
```
Read WB Артикулы.gs → Check logic
Check column mapping → T (20) correct?
```

**Step 2: Fix**
```javascript
// Update file if needed
// Create test case in test/
// Verify locally
```

**Step 3: Provide**
```
📋 ЗАГРУЗИТЕ:
WB Артикулы.gs (ИСПРАВЛЕНО)

ВЫПОЛНИТЕ:
updateWBArticles()
```

**Step 4: Verify**
```
User runs: runDiagnostics()
Check: T (20) column has values?
```

---

### Entry Points for Testing/Execution

```javascript
testAll();              // Test all functions sequentially
all();                  // Run Ozon + WB + Analytics
OzonMain();             // Ozon products, stocks, prices, SKU, FBS
WbMain();               // WB stocks, orders, prices
OzonSKUAndAnalytic();   // Ozon analytics (heavy, runs separately)
maintainArticleColumn(); // Validate article/offer_id column
```

---

## Critical Recent Fixes (February 2026)

### 1. Column Mapping Corrections (FIXED)

Multiple files were writing to **wrong columns**, causing data conflicts. Fixed files:

| File | What Was Fixed | Correct Column |
|------|----------------|----------------|
| [Ozon остатки FBO.gs](Ozon%20остатки%20FBO.gs) | Was writing to C (3) | F (6) - Остаток ФБО ОЗОН |
| [Ozon склад Москва.gs](Ozon%20склад%20Москва.gs) | Was writing to D (4), E (5) | G (7), H (8) - - FBS stocks |
| [Ozon заказы.gs](Ozon%20заказы.gs) | Was writing to F (6), G (7) | I (9), J (10), L (12) - Analytics |
| [Цены ВБ.gs](Цены%20ВБ.gs) | Was writing to J (10) | M (13) - ЦЕНА ВБ |
| [ВБ заказы.gs](ВБ%20заказы.gs) | Was writing to wrong cols | N (14), O (15), P (16) |
| [Ozon цена.gs](Ozon%20цена.gs) | Was writing to H (8) | K (11) - ЦЕНА ОЗОН |
| [ВБ.gs](ВБ.gs) | Was writing to M (13), N (14) | O (15), P (16) - WB stocks |
| [ВБ.gs](ВБ.gs) | Reading from column Q (17) | **FIXED:** Now reads from A (1) |

**Reference:** See [ОТЧЕТ_ОШИБОК_КОЛОНКИ.md](ОТЧЕТ_ОШИБОК_КОЛОНКИ.md) for complete column mapping.

### 2. New Files Created

| File | Purpose | Status |
|------|---------|--------|
| [WB Артикулы.gs](WB%20Артикулы.gs) | Fill T (20) with nmId from WB API | ✅ Ready |
| [WB Аналитика.gs](WB%20Аналитика.gs) | Fill R (18), S (19) with order counts | ✅ Ready |
| [DIAGNOSTICS.gs](DIAGNOSTICS.gs) | System diagnostics | ✅ Ready |

### 3. Invalid Product ID Filtering

**CRITICAL:** Column R (18) contains `product_id` values including zeros and invalid entries. Files reading from this column MUST filter:

```javascript
// CORRECT - filters out zeros, null, undefined, negative
const productIds = values.filter(id =>
  id !== '' && id !== null && id !== undefined && id > 0 && !isNaN(id)
);

// WRONG - causes API 400 errors
const productIds = values.filter(id => id && !isNaN(id));
```

**Files with this fix:**
- [Ozon остатки FBO.gs](Ozon%20остатки%20FBO.gs):9
- [Ozon цена.gs](Ozon%20цена.gs):5
- [Ozon Запись SKU.gs](Ozon%20Запись%20SKU.gs):17

---

## Sheet Column Structure (Sheet: `тест`)

| Column | Letter | Data | Source File | Status |
|--------|--------|------|-------------|--------|
| 1 | A | Артикул (offer_id) | Primary key | ✅ |
| 2 | B | Модель | Manual - DO NOT TOUCH | ✅ |
| 3 | C | Бренд | updateProductsV2() | ✅ |
| 4 | D | Связка (model_name) | updateProductsV2() | ✅ |
| 5 | E | Картинка | updateProductsV2() | ✅ |
| 6 | F | Остаток ФБО ОЗОН | updateStockFBO() | ✅ Fixed |
| 7 | G | Остаток ФБС ОЗОН | getStocksByWarehouseFBS() | ✅ Fixed |
| 8 | H | ОСТ ФБС МСК ОЗОН | getStocksByWarehouseFBS() | ✅ Fixed |
| 9 | I | Уход Мес ОЗОН | fetchAndWriteAnalytics() | ✅ Fixed |
| 10 | J | Уход КВ | fetchAndWriteAnalytics() | ✅ Fixed |
| 11 | K | ЦЕНА ОЗОН | getOzonPricesOptimized() | ✅ Fixed |
| 12 | L | Сумма заказов Мес ОЗОН | fetchAndWriteAnalytics() | ✅ Fixed |
| 13 | M | ЦЕНА ВБ | updatePricesAndImages() | ✅ Fixed |
| 14 | N | Сумма заказов Мес ВБ | updateOrdersSummaryV2() | ✅ Fixed |
| 15 | O | Остаток ФБО ВБ | main() in ВБ.gs | ⚠️ Verify warehouse ID |
| 16 | P | Остаток ФБС ВБ | main() in ВБ.gs | ⚠️ Verify warehouse ID |
| 17 | Q | ОСТ ФБС МСК ВБ | NOT USED | ✅ |
| 18 | R | Уход Мес ВБ | updateWBAnalytics() | ✅ NEW |
| 19 | S | Уход КВ ВБ | updateWBAnalytics() | ✅ NEW |
| 20 | T | Артикул ВБ | updateWBArticles() | ✅ NEW |
| 21 | U | Product_id Ozon | syncOfferIdWithProductId() | ✅ |
| 22 | V | SKU Ozon | updateSkuByProductId() | ✅ |
| 24 | X | Название модели | updateProductsV2() | ✅ |
| 25 | Y | Категория товара | updateProductsV2() | ✅ |

---

## Architecture Patterns

### Core Utilities

| File | Purpose |
|------|---------|
| [settings.gs](settings.gs) | API keys, URLs, rate limits (RPS, WB_RPS) |
| [utils.gs](utils.gs) | `rateLimitRPS()`, `retryFetch()`, helpers |
| [fetchapp.gs](fetchapp.gs) | HTTP library with retry logic |
| [Главные функции.gs](Главные%20функции.gs) | Main entry points for triggers |

### Ozon Data Flow

```
Column A (offer_id) → v4/product/info/attributes →
  ├── C (3): Brand (attribute_id=85)
  ├── D (4): Model name (attribute_id=9048)
  ├── E (5): Primary image
  ├── U (21): product_id
  ├── V (22): sku
  ├── X (24): name
  └── Y (25): category_name

Column R (product_id) → Multiple APIs:
  ├── F (6): FBO stocks (v4/product/info/stocks)
  ├── K (11): Prices (v5/product/info/prices)
  └── S (19): SKU (v3/product/info/list)

Column S (sku) → Analytics & FBS:
  ├── I (9), J (10), L (12): Analytics (v1/analytics/data)
  └── G (7), H (8): FBS stocks (v1/product/info/stocks-by-warehouse/fbs)
```

### Critical Ozon API Patterns

**v4 Product Attributes (brand/model):**
```javascript
// Payload format - uses filter wrapper
const payload = {
  filter: { offer_id: batchIds },
  limit: batchIds.length
};

// Response structure
const items = data.result || [];  // NOT data.items!

// Attribute extraction - use numeric IDs
function extractAttribute(item, attributeId) {
  const attr = item.attributes?.find(a => a.id === attributeId);
  return attr?.values[0]?.value || "";
}

// Key attribute IDs
// 85 = Бренд (brand)
// 9048 = Артикул производителя (model for multiplicity)
// 22390 = Additional model field
```

**v5 Prices, v4 Stocks, v3 Product Info:**
- Always filter `product_id > 0` when reading from column R
- Use `JSON.stringify(payload)` in options

---

## Rate Limiting

- **Ozon API:** Max 50 RPS, configured at 20 RPS (`RPS()` in settings)
- **Wildberries API:** Max 5 RPS, configured at 2 RPS (`WB_RPS()`)
- **Ozon Analytics:** Hard limit ~1 request per 7 seconds

```javascript
let lastRequestTime = Date.now() - 1000 / RPS();
for (let i = 0; i < items.length; i += chunkSize) {
  lastRequestTime = rateLimitRPS(lastRequestTime, RPS());
  // ... API call
}
```

---

## Google Apps Script Quotas

- **Triggers:** 20 per user per script
- **Execution:** 6 min/run (personal) or 30 min (Workspace)
- **Daily:** 90 min/day (personal) or 6 hours (Workspace)
- **Concurrent:** 30 simultaneous executions per user

**Current trigger schedule (from existing triggers):**
- `OzonMain`: 03:07, 08:54
- `WbMain`: 03:20, 08:50
- `OzonSKUAndAnalytic`: 03:23, 08:14
- `maintainArticleColumn`: 02:22

---

## Common Pitfalls

1. **Wrong column numbers** → Always verify against the column structure table above
2. **Invalid product_id filtering** → Always filter `id > 0` when reading column R
3. **Ozon v4 API format** → Use `{filter: {offer_id: [...]}}` wrapper
4. **Response structure** → v4 returns `data.result`, v3 returns `data.items`
5. **Attribute IDs** → Use numeric IDs (`a.id === 85`), not names
6. **JSON.stringify** → Always wrap payload in `JSON.stringify()`
7. **WB token expiry** → Error 401 means token expired, refresh in settings.gs

---

## File Naming Conventions

- `V2` suffix = Enhanced version (e.g., `Ozon обновить товары V2.gs`)
- Never modify working originals - create V2 instead
- Files with space in name: use `%20` in URLs/links

---

## Deployment Instructions

To update production Apps Script:

1. Open Google Sheet → Extensions → Apps Script
2. Create new file with `.gs` extension
3. Copy code from local file
4. Update [Главные функции.gs](Главные%20функции.gs) if adding new functions
5. Run `testAll()` to verify
6. Check logs via **View → Logs**

**Note:** Existing triggers will automatically call functions from [Главные функции.gs](Главные%20функции.gs) - no need to recreate triggers unless adding new functions.
