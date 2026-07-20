# Синхронизация Apps Script из Google в локальный репозиторий — 2026-07-20

## Результат

Актуальные скрипты связанного Google Apps Script-проекта подтянуты в локальный проект Checksheets:

- Локальный проект: `/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets`
- Направление: **Google Apps Script → локальные файлы**
- Команда: `npm exec --offline --yes --package=@google/clasp -- clasp pull`
- Результат команды: `Pulled 65 files.`

## Проверка

- Облачные Apps Script-файлы `.js`: `64`
- Локальные Apps Script-файлы `.js`: `64`
- Отсутствуют локально: `0`
- Расхождения cloud/local по SHA-256: `0`
- Корневые `.gs`: `0`
- Синтаксис проверен через `node --check`: `64/64`, ошибок `0`
- `appsscript.json`: совпадает с облачной копией
- Повторный read-only `clasp pull` в отдельную временную папку: успешен

## Локальные файлы, не являющиеся файлами Apps Script

Сохранены и не удалялись четыре локальных Node-helper-файла, отсутствующие в облачном Apps Script-проекте:

- `ozon_fbs_warehouse_api.js`
- `sync-etm-stocks.js`
- `sync-feron-stocks.js`
- `zero-etm-stocks.js`

Они исключены через `.claspignore` и не должны загружаться в Apps Script.

## Безопасность и откат

- Перед операцией создан backup: `test/tmp/apps-script-local-backup-20260720T054710Z/`
- Локальные `.js`, `appsscript.json`, `.clasp.json` и `.claspignore` сохранены в backup.
- `clasp push` не выполнялся.
- Функции, триггеры и данные Google Sheets не запускались и не изменялись.
- Для отката локальной части можно восстановить файлы из указанного backup.

## Примечание по `clasp status`

В корне репозитория `clasp status` видит большое количество локальных/служебных файлов репозитория, поэтому его код возврата там не является проверкой содержимого облака. Для контроля выполнен чистый read-only pull/status во временной копии: команда завершилась успешно; итоговая проверка файлов дала `0` missing и `0` mismatched.
