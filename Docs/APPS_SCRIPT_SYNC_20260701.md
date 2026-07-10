# Apps Script sync baseline — 2026-07-01

## Scope

Связал локальный проект Checksheets с текущим Google Apps Script проектом таблицы **«ТЗ Контент»**.

- Spreadsheet ID: `15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI`
- Apps Script project name in UI: `Главные скрипты v2`
- Apps Script script ID: `13r5qTN_nb0F9yM47t5PmrXMtCvqGz0CoedPxrv8AMatMJCgdSxYw4dSl`
- Local project: `/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets`

## Official docs checked

- Google Apps Script clasp guide: `https://developers.google.com/apps-script/guides/clasp`
- Apps Script API `projects.getContent`: `https://developers.google.com/apps-script/api/reference/rest/v1/projects/getContent`
- Apps Script API `projects.updateContent`: `https://developers.google.com/apps-script/api/reference/rest/v1/projects/updateContent`

## What was done

1. Открыл связанную Apps Script IDE из Google Sheets.
2. Извлёк из Monaco editor все загруженные файлы проекта Apps Script.
3. Сохранил raw cloud export в `test/tmp/apps-script-cloud-export-20260701T083830Z.json`.
4. Перед перезаписью сделал backup локальных `.gs` и clasp-конфигов:
   `test/tmp/apps-script-local-backup-20260701T083830Z/`.
5. Скопировал cloud-версии `.gs` файлов в корень проекта.
6. Создал локальную привязку для будущей работы через `clasp`:
   - `.clasp.json`
   - `.claspignore`

## Verification

Проверка после записи:

- Cloud files exported: `49`
- Local files matching cloud export byte-for-byte: `49`
- Missing cloud files locally: `0`
- Mismatched cloud files locally: `0`

Команды/проверки:

```bash
npx -y @google/clasp --version
npx -y @google/clasp pull --help
python3 <local compare script>
```

`clasp` доступен через `npx`; глобально устанавливать не стал.

## Files created from cloud that were absent locally

- `Без названия 2.gs`
- `Без названия 3.gs`
- `Обнуление.gs`
- `Без названия.gs`
- `feron_sync.gs`
- `Синхронизайия остатков Feron.gs.gs`
- `Ozon цена по карте.gs`
- `Зануление RS OZON.gs`
- `Ozon возвраты и отмены\.gs`
- `Ozon платное хранение.gs`
- `O.gs`
- `O квартал.gs`
- `Ozon индекс.gs`
- `Ozon отзывы.gs`
- `WB Unit.gs`

Также приведён к cloud-регистру файл:

- `WB Склады.gs` → `WB склады.gs`

## Local `.gs` files not present in Google Apps Script project

Эти файлы оставлены на месте и **не удалялись**, чтобы не потерять локальную историю/черновики:

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

## Current limitation

Полноценный CLI push/pull через Apps Script API ещё требует OAuth/`clasp login` под Google-аккаунтом, потому что сервисный аккаунт проекта умеет работать с Google Sheets/Drive, но Apps Script API для него сейчас отвечает, что API не включён для связанного Google Cloud project. Я не включал API и не выдавал OAuth-доступ без отдельного подтверждения.

До OAuth-настройки рабочий read-only способ синхронизации из облака — экспорт из открытой Apps Script IDE через Monaco editor в браузере. Push в Google Apps Script без подтверждения не выполнять.

## Rollback

Чтобы откатить локальную Apps Script часть к состоянию до синхронизации, скопировать `.gs`, `.clasp.json`, `.claspignore` из:

`test/tmp/apps-script-local-backup-20260701T083830Z/`

обратно в корень проекта.
