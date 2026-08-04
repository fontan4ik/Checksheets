# Ozon CPC cleanup: лист `СРС`

## Назначение

`ozon_cpc_cleanup.py` читает лист `СРС`, получает актуальные клики из Ozon Performance API и формирует кандидатов на удаление SKU из CPC-кампаний.

Связка листа:

- `SKU OZON` — SKU товара;
- `CAMPAIN ID` — ID кампании;
- `Расход` ← `Расход, ₽, с НДС` из отчёта;
- `Показы` ← `Показы`;
- `Клики` ← `Клики`;
- `CTR, %` ← `CTR, %`;
- `Средняя стоимость клика` ← `Средняя стоимость клика, ₽`;
- `Продано` ← `Продано товаров`;
- `ДРР в продвижении` ← `ДРР в продвижении, %`;
- `Бюджет` ← `budget`, fallback `dailyBudget` из объекта кампании;
- `Корзины` ← `Добавления в корзину`;
- `Статус` ← `state` кампании.

`weeklyBudget` намеренно не используется: у текущих кампаний это технический лимит, а не явный бюджет.

Состав листа и статус кампаний меняются. Перед каждым запуском скрипт заново сопоставляет строки `СРС` с running SKU-кампаниями; только совпавшие пары участвуют в отчёте и могут стать кандидатами на удаление.

## Поток

1. Получить running SKU-кампании.
2. Оставить только CPC-кампании, связанные с `СРС`.
3. Проверить состав товаров через `/api/client/campaign/{campaignId}/v2/products`.
4. Создать отчёт `/api/client/statistics` за текущий день по московскому времени: RFC3339-поля `from`/`to` и `groupBy=DATE`.
5. Дождаться `GET /api/client/statistics/{UUID}` со `state=OK`.
6. Скачать CSV/ZIP через `/api/client/statistics/report?UUID=...`.
7. Извлечь SKU и `Клики`.
8. Для `Клики >= 10` подготовить удаление только если SKU всё ещё есть в кампании.

`SKU` — поле строк CSV, а не значение `groupBy`. Актуальная документация Ozon разрешает для `groupBy` только `NO_GROUP_BY`, `DATE`, `START_OF_WEEK` и `START_OF_MONTH`. Перед live-удалением скрипт повторно читает состав каждой кампании: отчёт может ждать в очереди несколько минут.

Ozon может формировать статистику дольше пяти минут. Скрипт ждёт до 15 минут по умолчанию (`180 × 5 секунд`). Параметры можно изменить через `OZON_CPC_REPORT_MAX_ATTEMPTS` и `OZON_CPC_REPORT_SLEEP_SECONDS`.

## Режимы запуска

Из корня проекта:

```bash
cd /Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets

# Безопасный режим: отчёт, план кандидатов, без записи в Google Sheets и без удаления SKU
./.venv-etm-export/bin/python ozon_cpc_cleanup.py

# Получить метрики и статусы в СРС, но не удалять SKU
./.venv-etm-export/bin/python ozon_cpc_cleanup.py --write-sheet

# Live-режим. Требует явного защитного флага
OZON_CPC_CONFIRM_DELETE=YES \
  ./.venv-etm-export/bin/python ozon_cpc_cleanup.py --write-sheet --apply
```

`--apply` без `OZON_CPC_CONFIRM_DELETE=YES` завершится ошибкой. Без `--apply` всегда выполняется dry-run.

## Планирование каждые 30 минут

Периодический LaunchAgent пока **не включён**. Для включения live-автоматизации требуется отдельное подтверждение, потому что она будет регулярно удалять SKU из рекламных кампаний.

После утверждения запускать с `StartInterval=1800`, блокировкой от параллельных прогонов и логом в `logs/`. Перед включением проверить один dry-run и один ручной запуск с `--write-sheet` без `--apply`.

## Проверки

```bash
./.venv-etm-export/bin/python test/test_ozon_cpc_cleanup.py -v
./.venv-etm-export/bin/python -m py_compile ozon_cpc_cleanup.py test/test_ozon_cpc_cleanup.py
```

Тесты проверяют период, парсинг CSV/ZIP, агрегацию SKU и защиту от удаления SKU, которого уже нет в кампании.
