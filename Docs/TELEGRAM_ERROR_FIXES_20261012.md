# Ошибки Telegram: разбор и исправления, 12 октября 2026

Проверен общий журнал `logs/script_errors.jsonl` за 5–12 октября: 1888 записей, включая 1742 повторных сбоя GitHub sync. Причины сверены с ежедневными журналами, WB payload audit и read-only API Ozon/Яндекса.

## Исправления

| Причина | Результат | Файлы |
|---|---|---|
| Git reset каждого runtime-файла гонялся с Git-клиентом за index.lock | Runtime не добавляется в индекс; старые staged runtime снимаются одной операцией. Краткий повтор при contention, затем корректное отложенное выполнение без аварийного Telegram. Чужие lock не удаляются. Грязные файлы вложенного приложения не блокируют root sync; изменения gitlink сохраняются | `scripts/checksheets_github_sync.py` |
| npm exec --offline не находил metadata clasp | Постоянная установка clasp в ChecksheetsSync/tools и запуск без npm-cache; установка сделана | `scripts/checksheets_github_sync.py` |
| WB post-check/repair ETM использовал исходный снимок до Ozon, хотя WB получил более свежий | Проверка и восстановление используют фактически отправленный WB снимок | `sync-etm-stocks.js` |
| Временные WB сетевые/408/5xx ошибки и исчерпанные 429 | Ограниченные повторы; исчерпанные отказы остаются ошибкой. Все repair payloads и результаты, включая individual 409, имеют аудит с checksum | `sync-etm-stocks.js`, `sync-feron-stocks.js`, `wb_stock_audit.js` |
| Ozon response не сверялся с каждым запрошенным товаром/складом; ETM repair считал TOO_MANY_REQUESTS успехом | Сопоставление по offer_id + warehouse_id; неполные/двойные ответы — ошибка; заведомые ограничения не повторяются, но остаются в итоговом alert | `ozon_stock_results.js`, `sync-etm-stocks.js`, `sync-feron-stocks.js`, `sync-rs-stocks.js`, `stock_sync_report.js` |
| Ozon CPC 500, token SSL EOF, обрыв чтения | Ограниченные повторы только GET/получения токена/скачивания, без повторного воспроизведения mutation | `ozon_cpc_cleanup.py` |
| Ozon продажи/выкупы исчерпывали короткие 429 паузы | Увеличены ограниченные cooldown; учтён Retry-After; аналитический интервал увеличен | `ozon_fbo_fbs_sales_local.js`, `ozon_buyout_periods_local.js` |
| Apps Script выкупы исчерпывали 429 и могли выйти за 6 минут | Отложенный повтор исходного периода с ограничением 4 запусков и сохранением старых ячеек. 429/5xx/исчерпанный transport повторяются; окончательные отказы оповещаются. Учтён Retry-After | `List_UNIT_API__УПД__Ozon.js` |
| Недельный кэш скидок падал из-за разных РАЗНИЦА у одного SKU | Конфликтующие SKU исключены из автоодобрения, остальные обновляются; Google read имеет timeout и transient retries включая Gaxios abort | `ozon_discount_auto_approve_local.js` |
| gspread batch_update меняет range перед HTTP; повтор удваивал имя ОБОР | Каждая попытка получает свежую копию payload | `obor_summary_local.py` |
| Яндекс кратковременно возвращал недоступный DBS склад при успешном HTTP | Три проверки доступности; запись разрешается только при AVAILABLE | `sync-cdek-ozon-stocks.js` |
| Новый Node helper мог попасть в Apps Script | Helper исключён из загрузки | `.claspignore` |

Telegram token, chat binding и регулярные warehouse mappings сохранены.

## Применение и проверка

- Apps Script: исправление `List_UNIT_API__УПД__Ozon.js` загружено из отдельного staging на основе текущей облачной версии. Другие параллельные local GAS edits не включались в эту загрузку. 46 облачных файлов сверены обратным `clasp pull`: расхождений нет. До загрузки сохранены cloud backup.
- Первый backup: `test/tmp/telegram-error-fixes-20261012/cloud-before`; окончательный read-back и deployment.json: `test/tmp/telegram-error-fixes-20261012/verified-retry-update/`.
- Node/Python применяются автоматически следующими запусками локальных заданий; сервисы используют исходники из checkout. Временный maintenance lock освобождён.
- Живой ОБОР dry-run прошёл: рассчитано 9589 строк, WB warehouse report прочитан; запись листа не выполнялась.
- Обновление скидочного кэша выполнено успешно: 21174 SKU. Без отправки одобрений проверены 589 NEW заявок (5 подходят правилу, 584 не подходят).
- Проверки Git sync (9), ОБОР (4), CPC cleanup (41), CPC create (6), CPC bids (7), WB recovery (13), Ozon acknowledgement/repair, HTTP recovery, CDEK, отчётов stock, GAS deferred retry и 24 trigger wrappers прошли. `git diff --check` прошёл.
- IDE live-run не подтверждён: управление основным Chrome недоступно. Синтаксис, mock execution и обратное скачивание Apps Script подтверждены.
- Ручного запуска функций пользователем не требуется: существующий daily handler сохранён, retry handler создаётся автоматически при временном отказе API.

## Оставшиеся ограничения данных/маркетплейсов

1. **Ozon: 51 товар** с `OVER_MAX_OVH_NON_KGT`. Read-only API подтверждает крупные габариты и `is_kgt=false` у назначенных складов. Требуется совместимость КГТ или исправление реально неверных размеров. Размеры, остатки и назначения не изменялись. Перечень: `Docs/OZON_WAREHOUSE_RESTRICTIONS_20261012.md`.
2. **WB: 55 товаров** в последнем ETM запуске на складе `798761` отклонены по ODC/CD+. Повторная отправка не устраняет warehouse cargo restriction. Примеры: `55237-1`, `48024-1`, `48027-1`, `38197-10`. Расхождения и alerts сохранены с причиной.
3. **11 SKU с конфликтующими процентами скидки**: 5470616754, 5470633710, 5472376020, 5472378620, 5498302711, 5498352874, 5498350886, 5498353385, 5498359975, 5501735170, 5498356069. Исключены из автоодобрения до исправления связок/процентов в исходных данных; кэш содержит `conflictingSkus`.
4. Исторический ENOSPC 6/8 октября сейчас не воспроизводится: свободно около 19 GiB. Логи не удалены. Единичный CDEK timeout 8 октября сменился успешными запусками 9–12 октября. Read-only Яндекс: «СДЭК МО» 2456454 доступен для DBS.

Сбоев внешнего сервиса нельзя гарантированно избежать повторами; окончательные отказы остаются видимыми. Массовые реальные marketplace-записи для проверки не запускались.
