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

*   **`Главные функции.js`** — Main entry points for automated time-driven and manual triggers.
*   **`settings.js`** — Common configurations, API keys, endpoints, and custom rate limits (RPS).
*   **`utils.js`** & **`fetchapp.js`** — Core utility stack (custom HTTP fetchers, rate limiting, and exponential retry mechanisms).
*   **`DIAGNOSTICS.js`** — Full system diagnostic routines (`runDiagnostics()`).
*   **`Ozon обновить товары V2.js`** — Updates brand, model, and item categories from Ozon Seller API.
*   **`Ozon Получить товары.js`** — Synchronizes Seller Offer IDs with Ozon Product IDs.
*   **`Ozon остатки FBO.js`** & **`Ozon склад Москва.js`** — Updates Ozon FBO & FBS inventory stocks.
*   **`Ozon продажи FBO FBS.js`** — Analytical month/quarter sales reporting via Analytics API.
*   **`Ozon цена.js`** — Updates active Ozon prices and discounts.
*   **`Huckster цены.js`** — Read-only выгрузка текущей и рекомендуемой цены Huckster в BN:BO и ручная запись цен из `ARL TR` в Huckster.
*   **`Ozon заказы.js`** — Pulls orders and performance metrics from Ozon Seller API.
*   **`Ozon реклама V3.js`** — Final optimized Ozon Performance Ads sync (Quantity, Revenue, Spend).
*   **`Ozon Запись SKU.js`** — Maps product details to internal SKU lists.
*   **`WB Артикулы.js`** — Fills Wildberries nmId columns based on catalog mapping.
*   **`WB Аналитика.js`** — Fills WB month/quarter analytics columns.
*   **`WB Склады.js`** & **`ВБ остатки.js`** — Handles Wildberries warehouse mapping and stocks.
*   **`ВБ.js`** & **`ВБ заказы.js`** — Main Wildberries stock updates and order synchronizations.
*   **`Цены ВБ.js`** — Manages Wildberries catalog pricing.
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
1. **Never edit Apps Script directly** in the browser. Always modify the local `.js` file in your repository first.
2. The autonomous LaunchAgent `com.voltmir.checksheets-github-sync` polls GitHub `main` every 120 seconds, synchronizes the local checkout, commits stable local changes, pushes GitHub, and runs `clasp push` when an Apps Script file changed.
3. `.claspignore` is the upload boundary: local Python, Node helpers, tests/runtime files, logs, and credentials must not be uploaded to Apps Script.
4. The watcher verifies every Apps Script push by pulling into a temporary directory and comparing hashes; it does not overwrite the working tree during read-back.
5. Provide upload instructions following this format when delivering changes:
    ```text
    📋 ФАЙЛЫ ДЛЯ ЗАГРУЗКИ В APPS SCRIPT:
    ЗАМЕНИТЬ:
    1. ИмяФайла.js — описание изменения
    ВЫПОЛНИТЬ ПОСЛЕ ЗАГРУЗКИ:
    functionName() — описание
    ```
3. Test your changes by triggering execution directly in the Google Apps Script IDE and monitoring logs under **View → Logs**.

### Python Stock Synchronization Workflow:
1. Python dependencies should be maintained in a virtual environment (`.venv-etm-export`).
2. Use `SourceAddressAdapter` from `network_bypass.py` inside local Python scripts. On macOS it binds sockets with `IP_BOUND_IF`; a source-address-only bind is incompatible with full-tunnel Network Extension clients such as Happ.
3. The Node CDEK sync uses the macOS system route by default. `CHECKSHEETS_NODE_SOURCE_BIND=true` restores the legacy source-address mode for non-Network-Extension VPN setups.
4. Test execution locally:
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
| **3** | **C** | Бренд | `updateProductsV2()` in `Ozon обновить товары V2.js` | ✅ |
| **4** | **D** | Связка (model_name) | `updateProductsV2()` in `Ozon обновить товары V2.js` | ✅ |
| **5** | **E** | Картинка | `updateProductsV2()` in `Ozon обновить товары V2.js` | ✅ |
| **6** | **F** | Остаток ФБО ОЗОН | `updateStockFBO()` in `Ozon остатки FBO.js` | ✅ |
| **7** | **G** | Остаток ФБС ОЗОН | `getStocksByWarehouseFBS()` in `Ozon склад Москва.js` | ✅ |
| **8** | **H** | ОСТ ФБС МСК ОЗОН | `getStocksByWarehouseFBS()` in `Ozon склад Москва.js` | ✅ |
| **9** | **I** | Уход Мес ОЗОН | `fetchAndWriteAnalytics()` in `Ozon заказы.js` | ✅ |
| **10** | **J** | Уход КВ | `fetchAndWriteAnalytics()` in `Ozon заказы.js` | ✅ |
| **11** | **K** | ЦЕНА ОЗОН | `getOzonPricesOptimized()` in `Ozon цена.js` | ✅ |
| **12** | **L** | Сумма заказов Мес ОЗОН | `fetchAndWriteAnalytics()` in `Ozon заказы.js` | ✅ |
| **13** | **M** | ЦЕНА ВБ | `updatePricesAndImages()` in `Цены ВБ.js` | ✅ |
| **14** | **N** | Сумма заказов Мес ВБ | `updateOrdersSummaryV2()` in `ВБ заказы.js` | ✅ |
| **15** | **O** | Остаток ФБО ВБ | `main()` in `ВБ.js` | ✅ |
| **16** | **P** | Остаток ФБС ВБ | `main()` in `ВБ.js` | ✅ |
| **17** | **Q** | ОСТ ФБС МСК ВБ | *NOT CURRENTLY IN USE* | ✅ |
| **18** | **R** | Уход Мес ВБ | `updateWBAnalytics()` in `WB Аналитика.js` | ✅ |
| **19** | **S** | Уход КВ ВБ | `updateWBAnalytics()` in `WB Аналитика.js` | ✅ |
| **20** | **T** | Артикул ВБ | `updateWBArticles()` in `WB Артикулы.js` | ✅ |
| **21** | **U** | Product_id Ozon | `syncOfferIdWithProductId()` in `Ozon Получить товары.js` | ✅ |
| **22** | **V** | SKU Ozon | `updateSkuByProductId()` in `Ozon Запись SKU.js` | ✅ |
| **24** | **X** | Название модели | `updateProductsV2()` in `Ozon обновить товары V2.js` | ✅ |
| **25** | **Y** | Категория товара | `updateProductsV2()` in `Ozon обновить товары V2.js` | ✅ |
| **53** | **BA** | Реклама Количество | `updateOzonAdPerfFinal()` in `Ozon реклама V3.js` | ✅ |
| **54** | **BB** | Реклама Стоимость | `updateOzonAdPerfFinal()` in `Ozon реклама V3.js` | ✅ |
| **55** | **BC** | Реклама Расход | `updateOzonAdPerfFinal()` in `Ozon реклама V3.js` | ✅ |
| **66** | **BN** | Текущая выставленная цена (Huckster `upload_price`) | `updateHucksterPrices()` in `Huckster цены.js` | ✅ |
| **67** | **BO** | Цена по карте / РЦ для удержания (Huckster `market_card_price`) | `updateHucksterPrices()` in `Huckster цены.js` | ✅ |
| **по заголовку** | — | Цена на витрине с картой Х (Huckster `market_card_price`) | `updateHucksterPrices()` in `Huckster цены.js` | ✅ |
| **по заголовку** | — | Мин цена продажи Х (Huckster `min_price`) | `updateHucksterPrices()` in `Huckster цены.js` | ✅ |

### ARL TR: Huckster price source columns

| Column | Header | Huckster target | Function |
|---|---|---|---|
| U (21) | `МИНИМАЛЬНАЯ ХАКСТЕР` | `min_price` via `repricer/items/set` | `syncHucksterPricesFromArlTr()` |
| W (23) | `ВЫСТАВЛЯЕМАЯ ХАКСТЕР` | `retail_price` via `catalog_updatePrice` | `syncHucksterPricesFromArlTr()` |
| X (24) | `РЦ ХАКСТЕР` | additional type `РЦ Озон` via `markets/items/prices/update` | `syncHucksterPricesFromArlTr()` |

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

### Diagnostic Suite
Use the functions inside **`DIAGNOSTICS.js`** to verify system stability:
*   `checkSheetData()` — Scans sheet columns, verifying populated ranges.
*   `checkAPIKeys()` — Checks credentials availability.
*   `testAPIConnections()` — Validates network and authentication states for both Ozon and WB endpoints.

### API Rate Limits
*   **Ozon Seller API:** Hard throttle limit at 50 RPS. Shared queries are configured at **20 RPS** (`RPS()` in `settings.js`).
*   **Ozon Analytics API:** Strict limit at ~1 query per 7 seconds. Uses custom wait times.
*   **Wildberries API:** Configured at **2 RPS** (`WB_RPS()` in `settings.js`).

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
