# CLAUDE.md

This file provides guidance to Claude Code (`claude.ai/code`) and developer agents when working with code in this repository.

## Project Overview

This project consists of a hybrid integration environment designed to synchronize product data, inventory, prices, orders, and marketing analytics from **Ozon** and **Wildberries** (ВБ) marketplaces into Google Sheets. The sheet tracks ~10,000+ active product positions.

### The Hybrid Architecture:
1. **Google Apps Script (.js):** Handles the main spreadsheets-bound workflows, cell population, data enrichment, price updates, and analytic aggregations directly inside Google Spreadsheet.
2. **Local Python Scripts (.py):** Handles heavy stock inventory synchronization for suppliers (ETM, Feron, Russvet/RS) and Ozon Performance Ad statistics. These local scripts bypass local VPN/split-tunnel guards on macOS by binding requests directly to active LAN/Wi-Fi adapters using network interface binding.

**Target Spreadsheet ID:** `15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI` (Sheet `тест`)
**Google Service Account Key:** `nomadic-bedrock-485314-b0-d7624dedd83c.json`

---

## 📁 REPOSITORY STRUCTURE & INVENTORY

### ⚠️ STRICT RULES FOR FILE LOCATIONS (MUST OBEY):
1. **Documentation & Reference (.md, .txt, etc.):** 
   - All documentation files, API references, research logs, and markdown files **MUST** be placed in the **`Docs/`** directory.
   - No new `.md` files should be added directly to the project root, except for the absolute base configurations (`CLAUDE.md`, `AGENTS.md`, and `WORKFLOW.md`).
2. **Testing & Diagnostics (.py, .js, .json, mocks):** 
   - All diagnostic scripts, local connectivity testers, playground executions, response payload logs, and mock JSON files **MUST** reside exclusively in the **`test/`** directory.
   - The repository root must be kept clean of temporary logs, data dumps, and debug scripts. It must only contain active production code.

### 1. Production Google Apps Script Files (.js)
These are uploaded to the Google Spreadsheet Script Editor environment:

*   **`Flow_Триггеры__Основные.js`** — Main entry points for automated time-driven and manual triggers.
*   **`Shared_Настройки.js`** — Common configurations, API keys, endpoints, and custom rate limits (RPS).
*   **`Shared_HTTP.js`** — Core HTTP fetcher, rate limiting, and exponential retry logic.
*   **`Diagnostic_Система.js`** — Full system diagnostic routines (`runDiagnostics()`).
*   **`List_ТЕСТ__C_E_V_X_Y__Товары_Ozon.js`** — Updates brand, model, and item categories from Ozon Seller API.
*   **`List_ТЕСТ__A_U__ProductId_Ozon.js`** — Synchronizes Seller Offer IDs with Ozon Product IDs.
*   **`List_ТЕСТ__F_G__Остатки_Ozon.js`** & **`List_ТЕСТ__H__Склад_Москва_Ozon.js`** — Updates Ozon FBO & FBS inventory stocks.
*   **`List_ТЕСТ__AQ_AT__Продажи_Ozon.js`** — Analytical month/quarter sales reporting via Analytics API.
*   **`List_ТЕСТ__K_BR__Цена_Ozon.js`** — Updates active Ozon prices and discounts.
*   **`Flow_ТЕСТ_ARL_TR__Цены_Huckster.js`** — Read-only выгрузка текущей и рекомендуемой цены Huckster в BN:BO и ручная запись цен из `ARL TR` в Huckster.
*   **`List_ТЕСТ__I_J_L_AO__Заказы_Ozon.js`** — Pulls orders and performance metrics from Ozon Seller API.
*   **`List_ТЕСТ__BA_BC__Реклама_Ozon_Performance.js`** — Final optimized Ozon Performance Ads sync (Quantity, Revenue, Spend).
*   **`List_ТЕСТ__T__Артикулы_WB.js`** — Fills Wildberries nmId columns based on catalog mapping.
*   **`List_ТЕСТ__R_S__Аналитика_WB.js`** — Fills WB month/quarter analytics columns.
*   **`WB Склады.js`** & **`List_ТЕСТ__O__Остатки_WB_FBList_UNIT_API__РасчетныеПоля__Ozon.js`** — Handles Wildberries warehouse mapping and stocks.
*   **`List_ТЕСТ__P_Q__Остатки_WB_FBS.js`** & **`List_ТЕСТ__N_AP__Заказы_WB.js`** — Main Wildberries stock updates and order synchronizations.
*   **`List_ТЕСТ__M__Цена_WB.js`** — Manages Wildberries catalog pricing.
*   **`Синхронизация остатков *.js`** — Specific inventory synchronizations for ETM TR, Feron, RS, ARL, ODC, and gaus sheets.

### 2. Local Python Synchronization Scripts (.py)
These run on local servers or machines to update Google Sheets via the API:

*   **`etm_sync_multi_store.py`** — Synchronizes ETM stocks across multiple warehouses.
*   **`feron_sync_local.py`** — Performs bulk stock updates for Feron warehouses.
*   **`rs_sync_local.py`** — Updates Russvet (RS) stock levels sequentially.
*   **`ozon_perf_sync.py`** — Local counterpart for Ozon Performance Ads sync.
*   **`config.py`** — Holds ETM, Russvet, Feron API credentials, sheet names, and local configurations.
*   **`gsheets_utils.py`** — A wrapper client around the `google-auth` / `gspread` libraries.
*   **`vpn_guard.py`** — Interface adapter fallback checking local VPN routing statuses.

---

## 🚀 DEVELOPMENT & DEPLOYMENT WORKFLOW

### Google Apps Script Workflow:
1. **Never edit Apps Script directly** in the browser. Codex edits the local `.js` files, verifies the changes, and uploads them to the bound project with `clasp push`; the user does not manually replace script files.
2. Before pushing, inspect `clasp status` and `.claspignore`, preserve a backup, and verify the uploaded project by pulling it into a temporary directory and comparing the tracked files. Report the push and verification result to the user.
3. The autonomous LaunchAgent `com.voltmir.checksheets-github-sync` still synchronizes the checkout with GitHub `main` and can perform an automatic `clasp push`. Coordinate with its lock/state so a direct push and a watcher run do not race.
4. `.claspignore` is the upload boundary: local Python, Node helpers, tests/runtime files, logs, service-account files, and unrelated credentials must not be uploaded to Apps Script. Keys used by this Google Sheets/Apps Script project may be part of the agreed Apps Script source/configuration and may be passed or tested there.
5. When delivering changes, list the files changed and the functions that need a manual run, if any. Do not give the user manual file replacement instructions.
6. Test changed behavior with a focused execution in the Google Apps Script IDE when safe, and inspect **Executions** or **View → Logs**.
7. Name Apps Script files `List_<sheet>__<columns-or-field>__<purpose>.js` for direct sheet writers; use `Flow_`, `Shared_`, or `Diagnostic_` for cross-sheet processes, shared code, and diagnostics. Keep existing trigger function names unless their triggers are migrated.
8. Resolve write destinations by visible header with `columnByHeader_()` (or the sheet's strict header resolver). Missing or duplicate headers must raise an error. Fixed service layouts and columns with missing or duplicate headers are documented exceptions; never silently fall back to a column number.
9. Wrap trigger entrypoints and their scheduled continuations in `runWithTelegramAlertGAS_()`, keeping the current Telegram bot token and chat binding. Terminal failures caught inside a function must be rethrown or explicitly alerted; expected transient retries should not send alerts.

### Python Stock Synchronization Workflow:
1. Python dependencies should be maintained in a virtual environment (`.venv-etm-export`).
2. Use `SourceAddressAdapter` from `network_bypass.py` inside local Python scripts. On macOS it binds sockets with `IP_BOUND_IF`; a source-address-only bind is incompatible with full-tunnel Network Extension clients such as Happ.
3. The Node CDEK sync uses the macOS system route by default. `CHECKSHEETS_NODE_SOURCE_BIND=true` restores the legacy source-address mode for non-Network-Extension VPN setups.
4. Local WB stock writers (`sync-etm-stocks.js`, `sync-feron-stocks.js`) MUST use `wb_stock_audit.js`. Do not remove or bypass the payload audit when changing batching, source columns, warehouse mappings, retries, or fallback behavior.
5. Test execution locally:
    ```bash
    python3 rs_sync_local.py
    python3 feron_sync_local.py
    ```

---

## 📊 GOOGLE SHEET COLUMN STRUCTURE (Sheet: `тест`)

| Column Index | Column Letter | Data Field | Source Function / Script | Status |
| :---: | :---: | :--- | :--- | :---: |
| **1** | **A** | Артикул (offer_id) | **Primary Key** | ✅ |
| **2** | **B** | Модель | Manual Formula — *DO NOT TOUCH* | ✅ |
| **3** | **C** | Бренд | `updateProductsV2()` in `List_ТЕСТ__C_E_V_X_Y__Товары_Ozon.js` | ✅ |
| **4** | **D** | Связка (model_name) | `updateProductsV2()` in `List_ТЕСТ__C_E_V_X_Y__Товары_Ozon.js` | ✅ |
| **5** | **E** | Картинка | `updateProductsV2()` in `List_ТЕСТ__C_E_V_X_Y__Товары_Ozon.js` | ✅ |
| **6** | **F** | Остаток ФБО ОЗОН | `updateStockFBO()` in `List_ТЕСТ__F_G__Остатки_Ozon.js` | ✅ |
| **7** | **G** | Остаток ФБС ОЗОН | `updateAllFBSStocks()` in `List_ТЕСТ__F_G__Остатки_Ozon.js` | ✅ |
| **8** | **H** | ОСТ ФБС МСК ОЗОН | `getStocksByWarehouseFBS()` in `List_ТЕСТ__H__Склад_Москва_Ozon.js` | ✅ |
| **9** | **I** | Уход Мес ОЗОН | `fetchAndWriteAnalytics()` in `List_ТЕСТ__I_J_L_AO__Заказы_Ozon.js` | ✅ |
| **10** | **J** | Уход КВ | `fetchAndWriteAnalytics()` in `List_ТЕСТ__I_J_L_AO__Заказы_Ozon.js` | ✅ |
| **11** | **K** | ЦЕНА ОЗОН | `getOzonPricesOptimized()` in `List_ТЕСТ__K_BR__Цена_Ozon.js` | ✅ |
| **12** | **L** | Сумма заказов Мес ОЗОН | `fetchAndWriteAnalytics()` in `List_ТЕСТ__I_J_L_AO__Заказы_Ozon.js` | ✅ |
| **13** | **M** | ЦЕНА ВБ | `updatePricesAndImages()` in `List_ТЕСТ__M__Цена_WB.js` | ✅ |
| **14** | **N** | Сумма заказов Мес ВБ | `updateOrdersSummaryV2()` in `List_ТЕСТ__N_AP__Заказы_WB.js` | ✅ |
| **15** | **O** | Остаток ФБО ВБ | `main()` in `List_ТЕСТ__P_Q__Остатки_WB_FBS.js` | ✅ |
| **16** | **P** | Остаток ФБС ВБ | `main()` in `List_ТЕСТ__P_Q__Остатки_WB_FBS.js` | ✅ |
| **17** | **Q** | ОСТ ФБС МСК ВБ | *NOT CURRENTLY IN USE* | ✅ |
| **18** | **R** | Уход Мес ВБ | `updateWBAnalytics()` in `List_ТЕСТ__R_S__Аналитика_WB.js` | ✅ |
| **19** | **S** | Уход КВ ВБ | `updateWBAnalytics()` in `List_ТЕСТ__R_S__Аналитика_WB.js` | ✅ |
| **20** | **T** | Артикул ВБ | `updateWBArticles()` in `List_ТЕСТ__T__Артикулы_WB.js` | ✅ |
| **21** | **U** | Product_id Ozon | `syncOfferIdWithProductId()` in `List_ТЕСТ__A_U__ProductId_Ozon.js` | ✅ |
| **22** | **V** | SKU Ozon | `updateProductsV2()` in `List_ТЕСТ__C_E_V_X_Y__Товары_Ozon.js` | ✅ |
| **24** | **X** | Название модели | `updateProductsV2()` in `List_ТЕСТ__C_E_V_X_Y__Товары_Ozon.js` | ✅ |
| **25** | **Y** | Категория товара | `updateProductsV2()` in `List_ТЕСТ__C_E_V_X_Y__Товары_Ozon.js` | ✅ |
| **53** | **BA** | Реклама Количество | `updateOzonAdPerfFinal()` in `List_ТЕСТ__BA_BC__Реклама_Ozon_Performance.js` | ✅ |
| **54** | **BB** | Реклама Стоимость | `updateOzonAdPerfFinal()` in `List_ТЕСТ__BA_BC__Реклама_Ozon_Performance.js` | ✅ |
| **55** | **BC** | Реклама Расход | `updateOzonAdPerfFinal()` in `List_ТЕСТ__BA_BC__Реклама_Ozon_Performance.js` | ✅ |
| **66** | **BN** | Текущая выставленная цена (Huckster `upload_price`) | `updateHucksterPrices()` in `Flow_ТЕСТ_ARL_TR__Цены_Huckster.js` | ✅ |
| **67** | **BO** | Цена по карте / РЦ для удержания (Huckster `market_card_price`) | `updateHucksterPrices()` in `Flow_ТЕСТ_ARL_TR__Цены_Huckster.js` | ✅ |
| **по заголовку** | — | Цена на витрине с картой Х (Huckster `market_card_price`) | `updateHucksterPrices()` in `Flow_ТЕСТ_ARL_TR__Цены_Huckster.js` | ✅ |
| **по заголовку** | — | Мин. цена продажи (или исторический заголовок Мин цена продажи Х) (Huckster `min_price`) | `updateHucksterPrices()` in `Flow_ТЕСТ_ARL_TR__Цены_Huckster.js` | ✅ |

### ARL TR: Huckster price source columns

| Column | Header | Huckster target | Function |
|---|---|---|---|
| U (21) | `МИНИМАЛЬНАЯ ХАКСТЕР` | `min_price` via `repricer/items/set` — единственная запись | `syncHucksterPricesFromArlTr()` |
| W (23) | `ВЫСТАВЛЯЕМАЯ ХАКСТЕР` | не записывается | — |
| X (24) | `РЦ ХАКСТЕР` | не записывается | — |

### FERON TR: source stock columns

| Column | Header | Source | Warehouse |
|---|---|---|---|
| J (10) | `stocks SMR` | `feron_sync_local.py` | Самара |
| K (11) | `stocks MSK` | `feron_sync_local.py` | Внуково |
| L (12) | `stocks NSB` | `feron_sync_local.py` | Новосибирск |
| M (13) | `stocks EKB` | `feron_sync_local.py` | Екатеринбург |

Фаза `получение остатков` обновляет только J:M в `FERON TR`; колонки FR и финальные marketplace-остатки не являются целью этого запуска.

---

## 🔧 RATE LIMITING & DIAGNOSTICS

### WB Stock Payload Audit

- The authoritative forensic log for local WB stock writes is `logs/wb_stock_payload_audit_YYYYMMDD.jsonl`.
- Every prepared batch must record `runId`, script, spreadsheet tab, source snapshot timestamp, snapshot age, source column/header, WB warehouse ID/name, batch number, checksum, and every `offerId`/`chrtId`/`amount` sent.
- Batch results must reference the prepared-payload checksum. When a `409` batch is split into individual requests, record the result of every individual `chrtId`.
- Treat `WB STALE SNAPSHOT` as a material warning. The default threshold is 15 minutes and can be changed with `WB_STOCK_AUDIT_STALE_MS`; do not silently suppress this warning.
- For an unexplained WB stock, inspect the audit before changing mappings or manually zeroing again:
  ```bash
  rg 'АРТИКУЛ_ИЛИ_CHRTID' logs/wb_stock_payload_audit_*.jsonl
  ```
- Distinguish the source-read time from the WB-send time. A long-running process can resend an old in-memory value after the sheet and Ozon have already changed.
- `StreamSupps` mapping for WB must remain explicit: `AB = N + S + V → WB 798761 (ВольтМир)`; `AC = M + X → WB 1449484 (ФБС ФЕРОН МОСКВА)`. `M` already combines Feron Moscow with Arlight from `ARL TR`; `X` adds «РУССКИЙ СВЕТ МОСКВА». Warehouse 1449484 must have a single regular writer: `sync-feron-stocks.js` reading `AC`; direct ARL→WB writes are disabled.

### Diagnostic Suite
Use the functions inside **`Diagnostic_Система.js`** to verify system stability:
*   `checkSheetData()` — Scans sheet columns, verifying populated ranges.
*   `checkAPIKeys()` — Checks credentials availability.
*   `testAPIConnections()` — Validates network and authentication states for both Ozon and WB endpoints.

### API Rate Limits
*   **Ozon Seller API:** Hard throttle limit at 50 RPS. Shared queries are configured at **20 RPS** (`RPS()` in `Shared_Настройки.js`).
*   **Ozon Analytics API:** Strict limit at ~1 query per 7 seconds. Uses custom wait times.
*   **Wildberries API:** Configured at **2 RPS** (`WB_RPS()` in `Shared_Настройки.js`).

---

## ⚠️ COMMON PITFALLS & DEVELOPMENT RULES

1.  **Product ID Filtering:** Ozon `product_id` (Column U / 21) contains zeros and placeholder elements. Always filter them out:
    ```javascript
    const productIds = values.filter(id =>
      id !== '' && id !== null && id !== undefined && id > 0 && !isNaN(id)
    );
    ```
2.  **Ozon Attributes API Format (v4):** Requires an explicit `filter` wrapper around batch lists:
    ```json
    { "filter": { "offer_id": ["ART-1", "ART-2"] }, "limit": 2 }
    ```
3.  **VPN Guard in Local Scripts:** The local Python modules use native binding blocks in the network stack:
    ```python
    # Mounts a SourceAddressAdapter to requests.Session to bypass active VPN gateways
    session.mount("http://", SourceAddressAdapter(active_ip))
    session.mount("https://", SourceAddressAdapter(active_ip))
    ```
4.  **Google Apps Script Execution Quotas:** Triggers are subject to a **6-minute execution window**. Heavy processing tasks (like full analytical syncs) are split into batches or executed as separate time-driven triggers.
