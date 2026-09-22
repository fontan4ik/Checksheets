# План: ошибки Telegram, сводки остатков и удаление Apps Script-дублей

## Requirements Summary

- Собрать единый реестр ошибок из Telegram, локальных журналов и Google Apps Script Executions.
- Исправить устранимые сбои Apps Script, прежде всего лимиты времени, квоты/429/5xx, дублирующие триггеры и устаревшие точки входа.
- Сделать сводку трансляции честной: различать исходный остаток в таблице, попытку отправки, принятые API позиции и фактический post-check маркетплейса.
- Стабилизировать локальные RS/«Русский свет» синхронизации и не считать частичный результат успешным.
- Удалить Apps Script-пути, которые уже полностью обслуживаются локальными Python/Node заданиями, не затронув отчётные чтения остатков и Telegram-привязку.

## Evidence and preliminary findings

1. Полная история Telegram недоступна из текущего окружения: Telegram-клиента нет среди доступных приложений. До исполнения плана нужен экспорт/пересылка сообщений за выбранный период и выгрузка Apps Script Executions. Локальные логи и ранее сохранённые разборы уже дают достаточную основу для проектирования.
2. Формулировка `Транслировалось` берёт `activeSku`, то есть положительные остатки источника, а не подтверждённые остатки маркетплейса: `telegram_notifier.js:239-258`. Поэтому «транслировалось N», а ниже фактически `0`, может быть логически допустимым для текущего кода, но вводящим в заблуждение.
3. ETM/WB 21.09 оставил 21 расхождение, включая 10 transport errors, но скрипт и worker завершились кодом `0`: `logs/marketplace_wb_20260921.log:2640-2729`. Это делает итоговую сводку и статус процесса ложноположительными.
4. RS/Ozon 19.09 сначала упал на 1 224 расхождения: `logs/marketplace_ozon_20260919.log:630-647`; поздний повторный запуск после классификации недоступных товаров прошёл без расхождений: `logs/marketplace_ozon_20260919.log:3360-3717`. Нужна явная граница между terminal product errors, eventual consistency и настоящим сбоем.
5. Дайджест Telegram имеет повторяющиеся HTTP 400, единичные 401 и TLS disconnect: `logs/fbs_broadcast_summary_launchd.log:21-49`, `logs/fbs_broadcast_summary_launchd.err:1-16`. Node-нотификатор не экранирует динамические HTML-поля и не пишет тело ответа Telegram: `telegram_notifier.js:18-44,50-69`.
6. Очередь сводок — один JSON-файл с read/append/write и последующим unlink: `telegram_notifier.js:215-276`. Параллельные Ozon/WB процессы могут перетереть записи, а digest может удалить отчёт, дописанный между чтением и unlink. При сообщении длиннее 4 000 символов текст обрезается, но удаляется вся очередь.
7. Apps Script RS содержит полный старый маршрут API → Sheet → Ozon/WB (`Flow_StreamSupps__Остатки_RS_Маркетплейсы.js:52-808`), хотя экспортируемый `syncRSStocks()` уже только сообщает о локальном LaunchAgent (`:810-815`). Локальные владельцы маршрута — `rs_sync_local.py` и `sync-rs-stocks.js:1-10`.
8. Apps Script ARL продолжает иметь запись Ozon-остатков (`Flow_ARL_TR__Остатки_Маркетплейсы.js:197-350,886-947`), а тот же склад обслуживает локальный `sync-feron-stocks.js:15-40`. Прямая WB-запись в Apps Script уже отключена (`Flow_ARL_TR__Остатки_Маркетплейсы.js:25-30,501-505`). В файле также лежат отдельные ценовые функции, поэтому удалять файл целиком без разделения нельзя.
9. `updateExternalAPIStocks()` вызывает отсутствующие в production Apps Script функции `updateFeronStocks()` и `updateETMStocksTrigger()`: `Flow_Триггеры__Основные.js:237-252`; он также включён в `all()` на строке 207. Это вероятный источник `ReferenceError` и лишних Telegram-сбоев.
10. Старый локальный `com.checksheets.sync_rs_stocks.plist` всё ещё лежит в `scripts/` и `~/Library/LaunchAgents`, но не загружен; фактический RS upload уже запускают marketplace workers через `run_marketplace_worker.sh:35-46`. Его следует вывести из эксплуатации, чтобы случайная повторная загрузка не создала второго writer.
11. Исторически Apps Script уже страдал от шестиминутных таймаутов и 100% ошибок нескольких тяжёлых триггеров; текущая стратегия переноса тяжёлых работ локально описана в `Docs/timeout_remediation_2026-09-17.md:5-21`.

## Apps Script cleanup list

### Удалить после проверки/миграции зависимостей

| Объект | Почему неактуален | Перед удалением |
| --- | --- | --- |
| `Flow_StreamSupps__Остатки_RS_Маркетплейсы.js` | Полностью дублирует `rs_sync_local.py` + `sync-rs-stocks.js`; публичный trigger entrypoint уже заглушка | Удалить trigger `syncRSStocks` у всех владельцев; перенести или вывести из эксплуатации зависимый emergency zero-path |
| Stock-часть `Flow_ARL_TR__Остатки_Маркетплейсы.js` | Ozon ПОДОРОЖНИК и WB 1449484 уже принадлежат `sync-feron-stocks.js`; WB-путь в GAS уже отключён | Вынести реально используемые price-only функции в отдельный корректно названный файл или подтвердить, что они не используются; удалить `syncARLStocks` trigger |
| `updateExternalAPIStocks()` и вызов из `all()` в `Flow_Триггеры__Основные.js` | Вызывает отсутствующие GAS-функции и дублирует локальные ETM/Feron jobs | Проверить и удалить одноимённый trigger, если существует |

### Не удалять автоматически

- `List_ТЕСТ__F_G__Остатки_Ozon.js`, `List_ТЕСТ__H__Склад_Москва_Ozon.js`, `List_ТЕСТ__O__Остатки_WB_FBO.js`, `List_ТЕСТ__P_Q__Остатки_WB_FBS.js`: это чтение marketplace-остатков в отчётные колонки, а не supplier → marketplace writers.
- `Flow_UNIT_YNX__Остатки_поставщиков_Яндекс.js` и `Flow_UNIT_YNX__Остатки_НТЦ_Яндекс.js`: отдельный Yandex/UNIT YNX маршрут; текущий local Yandex worker покрывает только CDEK.
- `Flow_StreamSupps__Обнуление_Ozon.js` и `Flow_StreamSupps__Обнуление_RS_Ozon.js`: аварийные операции, не обычная синхронизация. Их либо оставить как явно ручные инструменты без trigger, либо заменить локальной dry-run-first утилитой и только потом удалить.

## Implementation Steps

### 1. Зафиксировать полный реестр инцидентов

- Экспортировать Telegram-сообщения и Apps Script Executions за последние 14–30 дней.
- Нормализовать события по полям: timestamp, service/function, owner, source (GAS/local), error class, retry outcome, final status, duplicate count.
- Отдельно пометить: Google transient (`429/500/503`, internal error), hard timeout, trigger quota, marketplace terminal product error, network/VPN, notifier delivery error, false-success summary.
- Сопоставить каждое Telegram-сообщение с локальным log/runId либо Apps Script execution ID. События без корреляции не считать доказанными причинами.

### 2. Починить транспорт и очередь Telegram

- В `telegram_notifier.js` добавить единый HTML escape для service/error/details/supplier/warehouse и fallback: при Telegram 400 повторить как plain text.
- Логировать безопасные поля ответа Telegram (`status`, `error_code`, `description`, `retry_after`), не печатая токен.
- Повторять TLS/timeout/429/5xx с bounded exponential backoff; 401 считать конфигурационной ошибкой без бессмысленных retries.
- Заменить общий JSON queue на атомарный spool/claim протокол: один файл на report или locked atomic rename. Digest должен удалять только подтверждённо отправленные элементы.
- Разбивать digest на сообщения до лимита Telegram; не обрезать сообщение с последующим удалением всех неотправленных записей.
- Централизовать один источник bot token/chat ID для Node/Python/shell/GAS, сохранив текущий chat binding; перед переключением сделать `getMe` и тестовую отправку.

### 3. Исправить модель сводки

- Ввести явные метрики: `sourcePositiveSku`, `attemptedSku`, `acceptedSku`, `skippedSku`, `errorSku`, `verifiedPositiveSku`, `verifiedPieces`, `mismatchSku`, `verificationStatus`.
- Заменить `Транслировалось` на:
  - `В источнике > 0` для sheet count;
  - `API принял` для подтверждённых записей;
  - `Фактически на маркетплейсе` только после post-check;
  - `Проверка недоступна` вместо неявного нуля/null.
- Статус сводки: `✅ успешно`, `⚠️ частично`, `❌ сбой`, `ℹ️ без изменений`. Нельзя показывать success, если остались transport errors или неожиданные mismatches.
- Передавать новые поля из `sync-etm-stocks.js`, `sync-feron-stocks.js`, `sync-rs-stocks.js`; не подменять marketplace-факт sheet-значением.
- Добавить runId, timestamp source snapshot и возраст snapshot, чтобы сводка коррелировала с `wb_stock_payload_audit`.

### 4. Устранить false-success и периодические RS/marketplace падения

- Унифицировать policy результата для трёх local writers: terminal product errors → `skipped` с известной причиной; retryable transport/API errors → retry; оставшиеся ошибки/mismatches → non-zero exit или явный degraded exit/status.
- В ETM исправить путь, при котором 10 WB transport errors и 21 mismatch завершаются кодом `0` (`logs/marketplace_wb_20260921.log:2668-2729`).
- В RS сохранить terminal allowlist (`NOT_FOUND_ERROR`, `PRODUCT_IS_NOT_CREATED`, moderation), но включать SKU и причину в сводку; неожиданный массовый mismatch после повторной проверки должен падать один раз, без alert storm.
- Проверить расписания и lock ownership: текущими writers оставить `marketplace_ozon` и `marketplace_wb`; удалить legacy `com.checksheets.sync_rs_stocks` plist после подтверждения, что он не загружен ни в одном bootstrap/install script.
- Добавить health check свежести: RS raw sheet update должен предшествовать marketplace upload, а snapshot старше порога должен останавливать отправку, а не транслировать старое значение.

### 5. Укрепить Apps Script против Google-сбоев

- По реестру Executions убрать все тяжёлые/дублирующие triggers, особенно `syncRSStocks`, `syncARLStocks`, `updateExternalAPIStocks`; учитывать triggers других владельцев.
- Для оставшихся GAS entrypoints использовать lock, cursor/checkpoint и бюджет выполнения 3–4 минуты; не пытаться переждать десятки секунд внутри шестиминутного лимита без сохранения состояния.
- В `Shared_HTTP.js` классифицировать retryable статусы (`408/425/429/5xx` и transport exceptions), уважать `Retry-After`, добавлять jitter и ограничивать суммарный sleep оставшимся execution budget.
- Не алертить на восстановившуюся transient попытку; алертить один раз только после исчерпания retries/continuation budget.
- Для hard timeout, который нельзя поймать `catch`, добавить внешний freshness/watchdog контроль по последнему успешному run marker, а не полагаться только на `runWithTelegramAlertGAS_()`.
- Удалить stale `updateExternalAPIStocks()` и вызов из `all()` после trigger audit.

### 6. Удалить Apps Script-дубли безопасным порядком

1. Снять backup cloud project и получить полный trigger inventory с владельцами.
2. Удалить/отключить triggers `syncRSStocks`, `syncARLStocks`, `updateExternalAPIStocks` до удаления функций.
3. Для ARL вынести только подтверждённо нужные price helpers; stock code удалить.
4. Для RS либо перенести emergency zero в local dry-run-first tool, либо оставить минимальный независимый ручной zero helper; затем удалить основной RS GAS файл.
5. Проверить отсутствие вызовов удалённых symbols статическим тестом.
6. Выполнить `clasp status`, проверить `.claspignore`, сделать backup, `clasp push`, затем pull в temp directory и byte/semantic compare, как требует проектный workflow.
7. Проверить Apps Script Executions после push и отсутствие `Script function not found`.

### 7. Тестирование и наблюдение

- Unit: HTML escaping/fallback; digest chunking; queue concurrency; formatter для `0`, `null`, partial, mismatch; exit policy для terminal/retryable errors.
- Integration: mock Telegram 400/401/429/TLS; mock Ozon/WB accepted-but-not-visible; concurrent Ozon/WB enqueue + digest claim.
- Local dry-run: каждый supplier/marketplace writer формирует одну сводку с согласованными counters и runId.
- GAS: focused manual execution только оставшихся изменённых entrypoints, затем проверка Executions/Logs.
- Production canary: один плановый цикл Ozon и WB, затем минимум 3 полных расписанных цикла без false-success, потерянных queue items, неожиданных GAS alerts и параллельного writer на один warehouse.

## Acceptance Criteria

- В Apps Script нет trigger, ссылающегося на удалённую функцию; нет `syncRSStocks`, `syncARLStocks` и `updateExternalAPIStocks` как активных supplier-stock writers.
- Для каждого supplier/warehouse существует ровно один регулярный writer; warehouse 1449484 остаётся только за `sync-feron-stocks.js`, а 798761 сохраняет согласованную агрегированную схему.
- Сводка никогда не пишет `Транслировалось N`, если N — только source count; actual `0`, unknown и mismatch отображаются раздельно.
- При оставшихся неожиданных mismatch/transport errors job не завершается безусловным success; Telegram получает один actionable alert с runId.
- Telegram 400 из-за HTML покрыт тестом и fallback; очередь не теряет отчёты при двух параллельных writers и digest run.
- Ни одно сообщение длиннее лимита Telegram не приводит к удалению неотправленного хвоста очереди.
- Google transient error, успешно восстановленный retry/continuation, не создаёт ложный incident; исчерпанная ошибка создаёт ровно один alert.
- Три последовательных полных production цикла проходят без hard timeout Apps Script, `Script function not found`, необъяснимого `401`, ложного success и конкурирующих stock writes.

## Risks and Mitigations

- **Удаление чужого trigger недоступно через ScriptApp.** Удалять через Apps Script UI от соответствующего владельца; до этого не удалять function stub.
- **ARL-файл смешивает stock и price функции.** Сначала разнести ответственности и проверить фактические triggers/manual usage.
- **Emergency zero зависит от RS GAS helpers.** Не удалять dependency до локальной замены или независимого минимального helper.
- **Изменение token source может оборвать Telegram.** Сохранять текущий chat ID, переключать поэтапно с тестовой отправкой и rollback.
- **Marketplace eventual consistency создаёт ложные mismatch.** Использовать bounded delayed verification и terminal allowlist, но не маскировать transport/API failure.
- **Два marketplace workers стартуют одновременно и нагружают Google/WB.** Сохранить per-marketplace locks, добавить атомарную очередь отчётов и при необходимости разнести расписание после измерения, не наугад.

## Verification Commands / Evidence

- `rg -n 'syncRSStocks|syncARLStocks|updateExternalAPIStocks' -- *.js`
- `launchctl list | rg 'checksheets|marketplace|sync_rs'`
- `bash -n run_with_lock.sh run_marketplace_worker.sh scripts/run_with_telegram_alert.sh`
- `node --test test/test_fbs_reports.js <новые unit tests>` либо существующий test runner проекта.
- `rg 'runId|prepared_payload|batch_result' logs/wb_stock_payload_audit_*.jsonl`
- `clasp status`, backup, `clasp push`, temp `clasp pull`, compare tracked Apps Script files.
- Apps Script Executions: ноль новых hard timeout/missing-function событий в трёх полных циклах.

## Out of scope for this change

- Изменение бизнес-формул StreamSupps/FERON TR/ETM/RS, кроме исправления метрик и freshness gating.
- Ручное обнуление marketplace stocks без отдельного dry-run и явного подтверждения.
- Удаление отчётных читателей Ozon/WB, которые только заполняют лист `ТЕСТ`.
