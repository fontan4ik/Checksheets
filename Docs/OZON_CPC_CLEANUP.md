# Ozon CPC cleanup: лист `СРС`

## Назначение

`ozon_cpc_cleanup.py` читает лист `СРС`, получает актуальные клики из Ozon Performance API и формирует кандидатов на удаление SKU из CPC-кампаний.

Связка листа:

- `SKU OZON` — SKU товара;
- `CAMPAIN ID` — ID кампании;
- `Клики` — значение из Performance-отчёта;
- `Статус` — результат обработки при включённой записи в таблицу.

Текущая read-only сверка показала 4 товарные строки и 4 активные кампании; API вернул по одному соответствующему SKU в каждой кампании.

## Поток

1. Получить running SKU-кампании.
2. Оставить только CPC-кампании, связанные с `СРС`.
3. Проверить состав товаров через `/api/client/campaign/{campaignId}/v2/products`.
4. Создать отчёт `/api/client/statistics` за текущий день по московскому времени.
5. Дождаться `GET /api/client/statistics/{UUID}` со `state=OK`.
6. Скачать CSV/ZIP через `/api/client/statistics/report?UUID=...`.
7. Извлечь SKU и `Клики`.
8. Для `Клики >= 10` подготовить удаление только если SKU всё ещё есть в кампании.

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
