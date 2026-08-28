# Актуализация кодов ETM в ETM TR

## Назначение

`sync_etm_codes.py` ежедневно читает последнюю выгрузку `price.csv` из FTP-каталога `/from_etm/13` и актуализирует колонку **W** (`Коды ЭТМ`) листа **ETM TR**.

## Сопоставление

1. Бренд берётся из колонки **C** (`brand`).
2. Сначала проверяется пара `model + brand` (модель из **B**).
3. Если она не найдена, проверяется пара `art + brand` (артикул из **A**).
4. Если модель и артикул дают разные коды, строка пропускается как неоднозначная.
5. Несовпавшие строки и текущие значения не очищаются.

Источник ETM: `Код ЭТМ`, `Артикул`, `Производитель`; поддерживается кодировка CP1251.

## Запуск

```bash
# Только расчёт, без записи
./.venv-etm-export/bin/python sync_etm_codes.py

# Повторная обработка файла и запись в ETM TR
./.venv-etm-export/bin/python sync_etm_codes.py --force --write

# Проверка на локальном файле
./.venv-etm-export/bin/python sync_etm_codes.py --csv test/tmp/etm_ftp_downloads/from_etm/13/price.csv
```

Файл состояния: `test/tmp/etm_codes_ftp_state.json`. Логи: `logs/sync_etm_codes.log` и `logs/sync_etm_codes_launchd.log`.

## Расписание

LaunchAgent `com.voltmir.checksheets-etm-codes` запускается ежедневно в **08:30 по локальному времени Mac**. Конфигурация хранится в `Docs/com.voltmir.checksheets-etm-codes.plist`, а запуск идёт через `run_with_lock.sh sync_etm_codes`.
