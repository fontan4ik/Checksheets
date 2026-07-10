# Checksheets: локальная синхронизация GitHub → Apps Script

## Целевая цепочка

```text
Любой ПК: commit/push в GitHub main
        ↓
Mac: launchd запускает watcher каждые 120 секунд
        ↓
fetch origin/main → fast-forward локалки
        ↓
изменения локалки → commit/push в GitHub
        ↓
если изменились Apps Script-файлы → clasp push
        ↓
clasp pull во временную папку → hash/read-back проверка
```

GitHub `main` — источник совместной версии проекта. Google Apps Script получает только файлы, разрешённые `.claspignore`; Python, локальные helper-файлы, логи и credentials туда не загружаются.

## Автономный watcher

- Скрипт: `scripts/checksheets_github_sync.py`
- LaunchAgent: `com.voltmir.checksheets-github-sync`
- Интервал: 120 секунд
- Lock: `~/Library/Application Support/Voltmir/ChecksheetsSync/sync.lock`
- Состояние: `~/Library/Application Support/Voltmir/ChecksheetsSync/state.json`
- Backup Apps Script перед push: `~/Library/Application Support/Voltmir/ChecksheetsSync/backups/`
- Лог: `~/Library/Logs/Voltmir/checksheets-github-sync.log`

Watcher ждёт 20 секунд после обнаружения локальных изменений, чтобы не закоммитить файл в момент записи. При конфликте Git-веток rebase выполняется только безопасно; неразрешённый конфликт останавливает цикл и оставляет рабочее дерево для ручного разбора.

## Управление

```bash
# Проверить вручную без изменений
python3 scripts/checksheets_github_sync.py --once --dry-run

# Один реальный цикл
python3 scripts/checksheets_github_sync.py --once

# Проверить LaunchAgent
launchctl print gui/$(id -u)/com.voltmir.checksheets-github-sync
```

## Установка/откат LaunchAgent

Установка выполняется копированием plist в `~/Library/LaunchAgents` и загрузкой через `launchctl bootstrap`. Для остановки достаточно выгрузить label и удалить только этот plist; GitHub, Apps Script, существующие Checksheets jobs и Telegram-контур не затрагиваются.

## Безопасность

- `.env` и service-account JSON не отправляются в GitHub.
- Локальный credential-файл сохраняется на Mac и исключён из Git.
- Существующий `.env`, который исторически был tracked, должен быть удалён из Git index без удаления локального файла.
- Перед каждым `clasp push` сохраняется backup локальных Apps Script-файлов.
- `clasp push` выполняется только если изменился Apps Script-файл или watcher запускается впервые.
