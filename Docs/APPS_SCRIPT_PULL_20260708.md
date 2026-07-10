# Apps Script pull — 2026-07-08

Время: 2026-07-08 12:49:23 +04

## Цель

Подтянуть текущие файлы bound Google Apps Script проекта `Главные скрипты v2` в локальную папку Checksheets.

## Проект

- Local project: `/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets`
- Script ID: `13r5qTN_nb0F9yM47t5PmrXMtCvqGz0CoedPxrv8AMatMJCgdSxYw4dSl`
- Command: `npx -y @google/clasp pull`

## Перед pull

- Проверен `git status --short --untracked-files=no`: рабочее дерево уже было dirty, это не создавалось текущим pull.
- Проверена авторизация clasp: `loggedIn: true`.
- Проверена привязка `.clasp.json` к нужному Script ID.
- Создан backup текущих локальных Apps Script файлов:
  `/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets/test/tmp/apps-script-local-backup-20260708-124608`

Backup содержит:

- 63 `.gs` файла;
- `appsscript.json`;
- `.clasp.json`;
- `.claspignore`;
- manifest и pre-pull git status.

## Pull result

`clasp pull` завершился успешно и вывел:

- `Pulled 51 files.`

В текущей версии `clasp` серверные Apps Script файлы были выгружены как `.js`, поэтому после pull выполнено локальное зеркалирование свежих `.js` файлов обратно в существующие `.gs` файлы проекта, чтобы сохранить текущий рабочий формат репозитория и `.claspignore`.

## Verification

Проверено после pull:

- fresh `.js` → `.gs` sync: 50 файлов;
- mismatches после копирования: 0;
- local `.js` files: 55;
- local `.gs` files: 63;
- `appsscript.json`: есть;
- `npx -y @google/clasp status`: exit code 0;
- tracked by clasp: 64 файла.

## Notes

- Extra local `.gs` файлы, которых нет в cloud pull, не удалялись.
- `clasp pull --deleteUnusedFiles` не запускался.
- Секреты, credentials, `.env`, service account JSON и marketplace keys не печатались и не переносились.
- Rollback локального Apps Script состояния: восстановить файлы из backup-папки `test/tmp/apps-script-local-backup-20260708-124608`.
