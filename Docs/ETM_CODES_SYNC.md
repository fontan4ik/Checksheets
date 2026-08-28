# Актуализация кодов ETM в ETM TR

## Назначение

`sync_etm_codes.py` ежедневно читает выгрузки `price.csv` сначала из FTP-каталога `/from_etm/13`, затем `/from_etm/14`, и заполняет только пустые ячейки колонки **W** (`Коды ЭТМ`) листа **ETM TR**.

## Сопоставление и приоритет

1. Бренд берётся из колонки **C** (`brand`).
2. Сначала проверяется пара `model + brand` (модель из **B**) по складу 13.
3. Затем для оставшихся пустых W проверяется пара `art + brand` (артикул из **A**) по складу 13.
4. После этого только оставшиеся пустые W проходят те же проверки по складу 14.
5. Любое уже непустое значение в W не изменяется, даже если код отличается от FTP.
6. Если модель и артикул дают разные коды, строка пропускается как неоднозначная.
7. Несовпавшие строки не очищаются.

Источник ETM: `Код ЭТМ`, `Артикул`, `Производитель`; поддерживается кодировка CP1251.

## Запуск

```bash
# Только расчёт по складам 13 -> 14, без записи
./.venv-etm-export/bin/python sync_etm_codes.py

# Повторная обработка выгрузок и запись только в пустые W
./.venv-etm-export/bin/python sync_etm_codes.py --force --write

# Проверка на локальном файле (один источник)
./.venv-etm-export/bin/python sync_etm_codes.py --csv test/tmp/etm_ftp_downloads/from_etm/13/price.csv
```

Файл состояния: `test/tmp/etm_codes_ftp_state.json`. Логи: `logs/sync_etm_codes.log` и `logs/sync_etm_codes_launchd.log`.

## Расписание

LaunchAgent `com.voltmir.checksheets-etm-codes` запускается ежедневно в **08:30 по локальному времени Mac**. Конфигурация хранится в `Docs/com.voltmir.checksheets-etm-codes.plist`, а запуск идёт через `run_with_lock.sh sync_etm_codes`.
