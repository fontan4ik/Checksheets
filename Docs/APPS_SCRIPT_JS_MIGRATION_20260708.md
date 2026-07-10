# Apps Script local format migration to `.js` — 2026-07-08

## Goal

Владимир подтвердил, что локальные Apps Script файлы в Checksheets должны храниться как `.js`, а не `.gs`, потому что `clasp pull` выгружает серверные Apps Script файлы именно в `.js`.

Current convention: local Apps Script server files are canonical as `.js`.

## Scope

- Local project: `/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets`
- Bound Apps Script ID: `13r5qTN_nb0F9yM47t5PmrXMtCvqGz0CoedPxrv8AMatMJCgdSxYw4dSl`
- Live cloud push не выполнялся.

## Backup

Перед миграцией создан backup:

```text
/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets/test/tmp/apps-script-js-migration-backup-20260708-125329
```

Backup содержит:

- 63 `.gs` файла;
- 55 `.js` файлов;
- `.clasp.json`, `.claspignore`, `appsscript.json`;
- `PRE_MIGRATION_GIT_STATUS.txt`;
- `manifest.json`.

## Changes

- Все root-level `.gs` файлы Apps Script удалены из рабочей папки после backup.
- Если для `.gs` уже был matching `.js`, оставлен `.js`.
- Если matching `.js` не было, файл был скопирован из `.gs` в `.js`.
- Удалён дубликат `Ozon возвраты и отмены\.js`, потому что он байт-в-байт совпадал с нормальным `Ozon возвраты и отмены.js`.
- `.claspignore` переключён с `!*.gs` на `!*.js`.
- В `.claspignore` явно исключены локальные Node helpers, чтобы будущий `clasp push` не загрузил их в Apps Script:
  - `ozon_fbs_warehouse_api.js`
  - `sync-etm-stocks.js`
  - `sync-feron-stocks.js`
  - `zero-etm-stocks.js`

## Migration metrics

- Deleted root `.gs`: 63
- Existing matching `.js` kept: 50
- Missing `.js` created from `.gs`: 13
- Root `.gs` after migration: 0
- Root `.js` after migration: 67
- `clasp status` tracked files: 64 total = 63 `.js` + `appsscript.json`

Detailed migration JSON:

```text
/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets/test/tmp/apps-script-js-migration-20260708-125354.json
```

## Verification

Focused checks run after migration:

- root `.gs` count = 0;
- root `.js` count = 67;
- normal `Ozon возвраты и отмены.js` exists;
- escaped duplicate `Ozon возвраты и отмены\.js` removed;
- `npx -y @google/clasp status` exits 0;
- `clasp status` sees 64 tracked files;
- tracked `.gs` count = 0;
- tracked `.js` count = 63;
- local Node helper JS files are untracked by clasp.

## Rollback

Restore previous local format from backup if needed:

```text
test/tmp/apps-script-js-migration-backup-20260708-125329
```

No live Google Apps Script push was performed, so cloud rollback is not needed.
