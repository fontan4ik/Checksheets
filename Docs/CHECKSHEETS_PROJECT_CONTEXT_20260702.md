# Checksheets project context — 2026-07-02

## Назначение проекта

`Checksheets` — гибридная система Voltmir для синхронизации маркетплейс-данных в Google Sheets и обратно на маркетплейсы.

Главные контуры:

1. **Google Sheet** — операционная таблица `ТЗ Контент`.
2. **Google Apps Script** — облачные `.gs`-скрипты, привязанные к таблице, обновляют колонки, агрегируют аналитику и управляют ручными/триггерными функциями внутри Google.
3. **Локальные Python sync scripts** — тяжёлые синхронизации поставщиков и рекламной статистики через локальный macOS runtime, Google Sheets API и внешние API.
4. **Локальные Node.js sync scripts** — выгрузка рассчитанных остатков из Google Sheets в Ozon/Wildberries FBS-остатки.
5. **macOS launchd** — расписание ежедневных запусков через `~/Library/LaunchAgents/com.checksheets.*.plist`.

## Базовые идентификаторы

| Объект | Значение |
| --- | --- |
| Рабочая папка | `/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets` |
| Google Spreadsheet ID | `15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI` |
| Таблица в UI | `ТЗ Контент` |
| Основной рабочий лист | `тест` / также в URL был `gid=185334916` |
| Apps Script project | `Главные скрипты v2` |
| Apps Script script ID | `13r5qTN_nb0F9yM47t5PmrXMtCvqGz0CoedPxrv8AMatMJCgdSxYw4dSl` |
| Service account key file | `nomadic-bedrock-485314-b0-d7624dedd83c.json` |
| Baseline Apps Script sync report | `Docs/APPS_SCRIPT_SYNC_20260701.md` |

## Важные правила безопасности

- В проекте есть live credentials в `config.py`, `settings.gs`, `.env`, service account JSON и, возможно, в отдельных `.gs`/`.js` файлах.
- Не печатать значения API keys, OAuth tokens, service account private key, marketplace tokens, auth headers и полные request/response dumps.
- Любые действия, которые пишут в маркетплейсы или Google Apps Script cloud, требуют явного подтверждения:
  - `clasp push`;
  - Apps Script API `projects.updateContent`;
  - Ozon/WB stock/price updates;
  - массовые обнуления остатков;
  - изменение launchd/расписаний;
  - включение/выключение OAuth/API в Google Cloud.

## Структура репозитория

Инвентаризация без `.git`, `node_modules`, `.venv-etm-export`, `__pycache__`, `.brv`, `.claude`, `.zed`:

| Тип | Кол-во |
| --- | ---: |
| Всего файлов без dependency/runtime папок | 492 |
| `.py` | 185 |
| `.gs` | 109 |
| `.log` | 55 |
| `.js` | 54 |
| `.md` | 36 |
| `.txt` | 18 |
| `.json` | 13 |
| `.csv` | 7 |
| `.err` | 5 |
| `.xlsx` | 3 |
| `.sh` | 2 |

Основные зоны:

| Путь | Роль |
| --- | --- |
| root `*.gs` | локальные копии Apps Script файлов; 49 совпадают с cloud export, 13 — локальные/legacy/черновики |
| root `*.py` | production/local sync scripts и вспомогательные утилиты |
| root `*.js` | Node.js синхронизация рассчитанных остатков в Ozon/WB |
| `Docs/` | проектная документация, API notes, отчёты |
| `logs/` | ежедневные launchd/runtime логи |
| `test/` | диагностика, fixtures, локальные test/debug scripts |
| `scratch/` | ad-hoc исследования и проверки |
| `test/tmp/` | временные export/backup/verification артефакты |

## Зависимости

### Node.js

`package.json`:

```json
{
  "axios": "^1.15.0",
  "dotenv": "^17.4.2",
  "googleapis": "^171.4.0"
}
```

`package-lock.json`:

- `lockfileVersion`: 3
- dependency packages: 58

Runtime, который использует `run_with_lock.sh`:

- `/opt/homebrew/bin/node` → Node `v25.6.1`
- `/opt/homebrew/bin/npm` → npm `11.9.0`

### Python

В проекте есть venv:

`/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets/.venv-etm-export/bin/python`

Пакеты в venv на момент проверки:

| Package | Version |
| --- | --- |
| certifi | 2026.4.22 |
| cffi | 2.0.0 |
| charset-normalizer | 3.4.7 |
| cryptography | 48.0.0 |
| et_xmlfile | 2.0.0 |
| google-auth | 2.53.0 |
| google-auth-oauthlib | 1.4.0 |
| gspread | 6.2.1 |
| hermes-agent | 0.17.0 |
| idna | 3.15 |
| oauthlib | 3.3.1 |
| openpyxl | 3.1.5 |
| pyasn1 | 0.6.3 |
| pyasn1_modules | 0.4.2 |
| pycparser | 3.0 |
| requests | 2.34.2 |
| requests-oauthlib | 2.0.0 |
| urllib3 | 2.7.0 |

Важно: launchd wrapper сейчас запускает **не venv**, а `/opt/homebrew/bin/python3`.

Runtime `/opt/homebrew/bin/python3`:

| Module | Status |
| --- | --- |
| Python | 3.14.4 |
| requests | 2.32.5 |
| gspread | 6.2.1 |
| google.oauth2.service_account | installed |
| urllib3 | 2.6.3 |
| openpyxl | **missing** |

Вывод: production launchd sync scripts, которые запускаются через `run_with_lock.sh`, зависят от Homebrew Python окружения. `openpyxl` в Homebrew Python не установлен, поэтому скрипты, использующие Excel/XLSX обработку (`etm_export_codes.py`, часть Ozon report tooling), надо запускать через venv или доустановить зависимость в runtime после отдельного согласования.

## Google Sheets client layer

`gsheets_utils.py` — общий thin wrapper:

- `get_gsheet_client()` — авторизация через service account file и scopes:
  - `https://www.googleapis.com/auth/spreadsheets`
  - `https://www.googleapis.com/auth/drive`
- `get_worksheet(sheet_name)` — открывает spreadsheet по `SPREADSHEET_ID` и лист по имени.
- `update_column_by_header(...)` — ищет колонку по заголовку и обновляет диапазон.
- `clear_column(...)` — чистит колонку с `start_row`.
- `update_column(...)` — обновляет колонку по номеру.

## Основные локальные Python scripts

| Файл | Роль | Пишет в Google Sheets | Особенности |
| --- | --- | --- | --- |
| `etm_sync_multi_store.py` | ETM multi-store остатки/коды/маппинг | Да | Самый большой локальный sync; использует `SourceAddressAdapter`, login ETM, store lookups, direct stock fetch, validation/brand matching; пишет в ETM-related columns/sheets. |
| `rs_sync_local.py` | Russvet/RS остатки и цены | Да через `gsheets_utils` | Basic auth/header generation, RS stock/price fetch, обновление листа `РуСВ TR`. |
| `feron_sync_local.py` | Feron bulk stock sync | Да через `gsheets_utils` | Защитная логика: если API отдаёт 0 складов, sync aborts to avoid overwriting Sheet with zeros. |
| `feron_mic_sync_local.py` | Feron MIC prices | Да/обновляет колонку BF | Получает MIC prices и пишет в `ТЕСТ` column BF. |
| `ozon_perf_sync.py` | Ozon Performance Ads sync | Да через `gsheets_utils` | Interface-bound Performance API session, campaigns/report generation/download/parse, period logic. |
| `ozon_ad_sync_to_gs.py` | Ozon ads report to Google Sheets | Да | OAuth/token, campaigns, report parse, direct gspread writes. |
| `ozon_ad_sync_final.py` | Финальная/альтернативная Ozon ads sync | Да | Requests report, waits, parses zipped report, writes to Google Sheet. |
| `ozon_json_sync.py` | Ozon performance JSON processor | Нет/не детектировано | Получение token и processing JSON. |
| `ozon_copy_cards.py` | Копирование Ozon карточек | Нет к Sheets | Seller API import flow; может создавать/импортировать карточки — live marketplace write risk. |
| `etm_export_codes.py` | ETM export codes / XLSX | Да | Требует `openpyxl`; venv подходит, Homebrew Python сейчас без `openpyxl`. |
| `vpn_guard.py` | VPN guard helper | Нет | Управляет/проверяет VPN state через macOS tooling; сейчас scripts в основном используют direct interface binding. |
| `config.py` | Runtime config/credentials/constants | Нет | Содержит live credentials. Не печатать значения. |

### Interface binding / VPN bypass pattern

`etm_sync_multi_store.py`, `rs_sync_local.py`, `feron_sync_local.py`, `feron_mic_sync_local.py`, `ozon_perf_sync.py` используют вариант `SourceAddressAdapter`:

- выбирается активный LAN/Wi-Fi IP (`en0`/`en1` или похожий интерфейс);
- `requests.Session` монтирует адаптер на `http://` и `https://`;
- это обходит проблемы маршрутизации через VPN/split tunnel.

## Основные Node.js scripts

| Файл | Роль | Основные зависимости | Live write риск |
| --- | --- | --- | --- |
| `sync-etm-stocks.js` | Читает ETM TR остатки из Google Sheets, обновляет Ozon/WB FBS остатки, проверяет и repair mismatches | `axios`, `googleapis`, `crypto`, `path` | Да: пишет Ozon/WB stock endpoints |
| `sync-feron-stocks.js` | Читает FERON TR остатки из Google Sheets, обновляет Ozon/WB FBS остатки, проверяет Ozon warehouse stocks | `axios`, `googleapis`, `fs`, `path` | Да: пишет Ozon/WB stock endpoints |
| `zero-etm-stocks.js` | Обнуление ETM остатков в Ozon/WB | `axios`, `googleapis`, `path` | Высокий риск: массовое обнуление |
| `ozon_fbs_warehouse_api.js` | Проверка/работа с Ozon FBS warehouse API | `dotenv`, `https` | Потенциальный write/read зависит от режима |

Главные endpoints в Node flow:

- Ozon stocks read/write:
  - `/v2/products/stocks`
  - `/v2/product/info/stocks-by-warehouse/fbs`
- WB marketplace stock write/read:
  - `/api/v3/stocks/{warehouseId}`
- Google Sheets API:
  - `https://www.googleapis.com/auth/spreadsheets`

## Google Apps Script baseline

См. `Docs/APPS_SCRIPT_SYNC_20260701.md`.

Текущее состояние после baseline sync:

- Cloud Apps Script файлов: 49.
- Все 49 cloud файлов существуют локально и byte-for-byte совпадают с export.
- `.clasp.json` привязан к script ID `13r5qTN_nb0F9yM47t5PmrXMtCvqGz0CoedPxrv8AMatMJCgdSxYw4dSl`.
- `.claspignore` ограничивает потенциальный upload только `*.gs` и `appsscript.json`.
- Есть 13 локальных `.gs`, которых нет в cloud project — их нельзя удалять без отдельного review:
  - `Feron API.gs`
  - `Ozon FBO FBS продажи.gs`
  - `Ozon реклама V2.gs`
  - `Ozon реклама V3.gs`
  - `WB FBO FBS продажи.gs`
  - `ВБ продажа FBO FBS.gs`
  - `Диагностика RS.gs`
  - `Новые колонки Продаж.gs`
  - `Новые колонки итог.gs`
  - `Синхронизация остатков ETM TR.gs`
  - `Синхронизация остатков Feron.gs`
  - `Синхронизация остатков ODC.gs`
  - `Синхронизация остатков.gs`

### Ключевые Apps Script группы

| Группа | Файлы / функции | Логика |
| --- | --- | --- |
| Orchestration | `Главные функции.gs` (`OzonMain`, `WbMain`, `all`, `runOzonOnly`, `runWbOnly`, `updateExternalAPIStocks`) | Главные ручные/триггерные entrypoints. |
| Core settings/utils | `settings.gs`, `utils.gs`, `fetchapp.gs` | API config, sheet accessor, retry/rate limit helpers. |
| Ozon product data | `Ozon обновить товары V2.gs`, `Ozon Получить товары.gs`, `Ozon Запись SKU.gs`, `Ozon цена.gs`, `Ozon цена по карте.gs`, `Ozon индекс.gs` | Product IDs/SKU, brand/model/category, prices, price index. |
| Ozon stocks/orders/analytics | `Ozon остатки FBO.gs`, `Ozon склад Москва.gs`, `Ozon заказы.gs`, `Ozon продажи FBO FBS.gs`, `Ozon возвраты и отмены\.gs`, `Ozon отзывы.gs`, `Ozon платное хранение.gs` | Stocks, orders, cancellations/returns, review count, storage cost. |
| Ozon unit economics | `O.gs`, `O квартал.gs` | Large staged UNIT / UNIT API flows, finance/storage/performance clicks; uses triggers/state to bypass Apps Script time limits. |
| Ozon ads | `Ozon реклама.gs` cloud; local legacy `Ozon реклама V2.gs`, `Ozon реклама V3.gs` | Ozon Performance reports: create, wait, download, parse, write stats. |
| Wildberries data | `WB Артикулы.gs`, `WB Аналитика.gs`, `ВБ заказы.gs`, `Цены ВБ.gs`, `WB Тех данные.gs`, `WB Unit.gs` | nmId mapping, analytics, sales funnel, prices, tech data, WB unit economics. |
| Wildberries stocks | `ВБ.gs`, `ВБ остатки.gs`, `WB FBS Москва.gs`, `WB склады.gs`, `Chrlid.gs` | FBO/FBS stocks, warehouse mapping, chrtId-based updates. |
| Supplier sheet sync | `feron_sync.gs`, `ФЕРОН API.gs`, `RS API.gs`, `Синхронизация остатков RS.gs`, `Синхронизация остатков ARL.gs`, `Синхронизация остатков gaus.gs`, `Синхронизайия остатков Feron.gs.gs` | Supplier/brand stock tables and marketplace upload scripts. |
| Diagnostics | `DIAGNOSTICS.gs`, `Без названия*.gs`, `Диагностика RS.gs` | API/token/sales discrepancy diagnostics, some cloud files still have generic names. |
| Dangerous utilities | `Обнуление.gs`, `Зануление RS OZON.gs`, `zero-etm-stocks.js` | Obнуление stock values. Require explicit approval before run. |

## Launchd / launched logic

Project is scheduled through macOS LaunchAgents, not crontab and not PM2.

Checked state:

- `crontab`: no Checksheets refs found.
- `pm2`: no Checksheets refs found.
- `launchctl list`: active `com.checksheets.*` jobs found.

### Wrapper

All active launchd jobs call:

`/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets/run_with_lock.sh <script_name>`

Wrapper behavior:

1. Creates `/tmp/checksheets_locks` and `logs/`.
2. Deletes `*.log`/`*.err` older than 7 days in `logs/`.
3. Uses `/tmp/checksheets_locks/<script_name>.lock` to prevent concurrent duplicate run.
4. Writes daily log: `logs/<script_name>_YYYYMMDD.log`.
5. Runs a case branch for the script name.
6. Removes lock at end.

Case mapping:

| script_name | Command |
| --- | --- |
| `rs_sync` | `/opt/homebrew/bin/python3 rs_sync_local.py` |
| `feron_sync` | `/opt/homebrew/bin/python3 feron_sync_local.py` |
| `feron_mic_sync` | `/opt/homebrew/bin/python3 feron_mic_sync_local.py` |
| `etm_sync` | `/opt/homebrew/bin/python3 etm_sync_multi_store.py` |
| `sync_feron_stocks` | `/opt/homebrew/bin/node sync-feron-stocks.js` |
| `sync_etm_stocks` | `/opt/homebrew/bin/node sync-etm-stocks.js` |

Special ETM chain:

```text
etm_sync_multi_store.py
  -> checks log segment for "ETM TR values written successfully"
  -> waits 300 seconds for Google Sheets recalculation
  -> run_with_lock.sh sync_etm_stocks
  -> sync-etm-stocks.js pushes ETM stocks to Ozon/WB
```

### LaunchAgents schedule

| Label | Schedule | Command | Logs | launchctl state at check |
| --- | --- | --- | --- | --- |
| `com.checksheets.rs_sync` | 10:30 and 22:30 | `run_with_lock.sh rs_sync` | `rs_sync_launchd.*`, daily `rs_sync_YYYYMMDD.log` | not running, last exit 0, runs 45 |
| `com.checksheets.etm_sync` | 11:10 | `run_with_lock.sh etm_sync` | `etm_sync_launchd.*`, daily `etm_sync_YYYYMMDD.log` | not running, last exit 0, runs 22 |
| `com.checksheets.feron_sync` | 12:00 and 19:00 | `run_with_lock.sh feron_sync` | `feron_sync_launchd.*`, daily `feron_sync_YYYYMMDD.log` | not running, last exit 0, runs 44 |
| `com.checksheets.feron_mic_sync` | 13:30 | `run_with_lock.sh feron_mic_sync` | `feron_mic_sync_launchd.*`, daily `feron_mic_sync_YYYYMMDD.log` | not running, last exit 0, runs 15 |
| `com.checksheets.sync_feron_stocks` | 12:15 and 19:15 | `run_with_lock.sh sync_feron_stocks` | `sync_feron_stocks_launchd.*`, daily `sync_feron_stocks_YYYYMMDD.log` | **running**, PID 94365, last exit 0, runs 42 |
| `com.checksheets.sync_etm_stocks` | 17:30 in `.plist.bak` only | `run_with_lock.sh sync_etm_stocks` | `sync_etm_stocks_launchd.*`, daily `sync_etm_stocks_YYYYMMDD.log` | not loaded from active plist; ETM sync triggers it manually after 300s delay |

### Current live concern found

At the time of analysis (`2026-07-02 01:36 +04`), `com.checksheets.sync_feron_stocks` was still running:

- launchd PID: `94365`
- child Node PID: `94370`
- elapsed: ~1 day 13 hours
- lock file: `/tmp/checksheets_locks/sync_feron_stocks.lock` → `94365`
- Node stdout/stderr is still attached to `logs/sync_feron_stocks_20260630.log`
- that log stops after:
  - `СИНХРОНИЗАЦИЯ ОСТАТКОВ FERON (LOCAL)`
  - `Шаг 1: Чтение данных из листа "FERON TR" (попытка 1/5)...`

This looks like a hung/stuck `sync-feron-stocks.js` run. I did **not** kill or restart it because this is live launchd/process state and requires explicit approval.

## Logs: current operational picture

`logs/` contains daily logs plus launchd stdout/stderr files.

Recent observations:

| Flow | Recent status from logs |
| --- | --- |
| `rs_sync` | Recent daily runs end with `RS Sync completed successfully!`; exit 0. |
| `feron_mic_sync` | Recent daily runs fetched ~4092–4101 articles and updated `ТЕСТ` column BF; exit 0. |
| `feron_sync` | Most historical runs successful; `2026-07-01` aborted safely because Feron quantities API returned 0 warehouses, avoiding overwrite with zeros; wrapper still exited 0. |
| `etm_sync` | Most runs successful and trigger `sync_etm_stocks`; `2026-06-30` had Google Sheets SSL EOF during ETM TR write and did not trigger marketplace sync; `2026-07-01` succeeded. |
| `sync_etm_stocks` | Recent triggered runs complete in ~43–47 minutes with success; writes to Ozon/WB. |
| `sync_feron_stocks` | `2026-06-24` failed exit 1, `2026-06-25..29` success, `2026-06-30` appears stuck and still holds lock/process. |

## Data-flow overview

### Supplier → Google Sheets

```text
ETM API
  -> etm_sync_multi_store.py
  -> Google Sheets / ETM-related columns and ETM TR data
  -> if confirmed write: wait 300s
  -> sync-etm-stocks.js
  -> Ozon/WB stock endpoints
```

```text
Feron API
  -> feron_sync_local.py
  -> Google Sheets / FERON TR or related Feron columns
  -> sync-feron-stocks.js scheduled 15 min later
  -> Ozon/WB stock endpoints
```

```text
Feron API MIC prices
  -> feron_mic_sync_local.py
  -> Google Sheets `ТЕСТ` column BF
```

```text
Russvet/RS API
  -> rs_sync_local.py
  -> Google Sheets `РуСВ TR` / purchase prices / stock columns
  -> Apps Script or manual stock sync can push RS rows to marketplaces
```

### Google Apps Script → Google Sheets

```text
Apps Script functions
  -> Ozon/WB APIs
  -> fill product IDs, prices, stocks, analytics, ad metrics, reviews, storage, unit economics
  -> write directly to spreadsheet cells/sheets
```

### Google Sheets → Marketplaces

```text
Google Sheets supplier stock sheets
  -> sync-etm-stocks.js / sync-feron-stocks.js / Apps Script stock upload functions
  -> Ozon `/v2/products/stocks`
  -> WB `/api/v3/stocks/{warehouseId}`
  -> verification/repair where implemented
```

## Known risks and follow-ups

1. **Hung `sync_feron_stocks` process** — likely needs controlled investigation and maybe kill/restart after approval.
2. **Runtime mismatch** — launchd uses Homebrew Python, not `.venv-etm-export`; currently Homebrew Python misses `openpyxl`.
3. **Secrets in source files** — existing project stores credentials in `config.py`, `settings.gs`, `.env`, service account JSON and possibly scripts. Future hardening should move secrets to env/secret storage, but this requires careful compatibility work and approval.
4. **Many root-level diagnostic/status docs** — root has `COMPLETE_STATUS.md`, `DONE.md`, `FINAL_REPORT.md`, `SETUP_COMPLETE.md`, `SYNC_STATUS.md`; project rules say docs should be in `Docs/`. Do not move without review because git status is already dirty.
5. **Apps Script cloud contains generic file names** — `Без названия*.gs` exist in cloud and are now mirrored locally. Rename only after cloud/local migration plan.
6. **`.gs` extras** — 13 local files not present in cloud may be old versions or useful alternatives. Need separate dedup/reconciliation task before deletion.
7. **Marketplace write scripts are live-risk** — Node sync and zero scripts can modify Ozon/WB stock state; always dry-run/review before execution.

## Recommended next safe steps

1. Ask for approval to inspect and resolve the stuck `sync_feron_stocks` launchd process.
2. Add explicit timeout handling to `run_with_lock.sh` or `sync-feron-stocks.js` so a Google Sheets/API hang cannot hold a lock for days.
3. Standardize launchd Python runtime: either use `.venv-etm-export/bin/python` or document/install required packages into Homebrew Python.
4. Create a `requirements.txt`/`pyproject.toml` from the known runtime dependencies.
5. Create a safe `healthcheck` script that reports:
   - launchd loaded/running state;
   - stale locks;
   - last daily log status;
   - package/runtime mismatch;
   - Apps Script baseline match status.
6. Reconcile local-extra `.gs` files vs cloud `.gs` files.
7. Later, with approval, configure OAuth/`clasp` for first-class cloud pull/push instead of browser Monaco export.

## Verification performed for this context capture

This report is based on read-only inspection:

- `git status --short`
- safe file inventory excluding dependency/runtime dirs
- Python AST/import/function scan of root `.py` files
- regex/function scan of root `.js` and `.gs` files
- `package.json` / `package-lock.json` parsing
- venv `pip freeze`
- Homebrew Python/Node runtime checks
- `launchctl list` / `launchctl print` for `com.checksheets.*`
- launchd plist parsing with `plutil -p`
- log-tail summarization without printing secrets
- process/lock inspection for the currently running `sync_feron_stocks`

No marketplace write, Google Sheet write, `clasp push`, launchd mutation, process kill, service restart, or credential change was performed.
