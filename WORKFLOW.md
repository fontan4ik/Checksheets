# Checksheets Workflow

## Source of truth
- Google Apps Script project: **"Главные скрипты v2"**
- GitHub repo mirror: **Checksheets**

## How we work

### `.gs` scripts
1. Edit the script.
2. Sync the updated version to **Главные скрипты v2**.
3. Sync the same version to **GitHub / Checksheets**.
4. Test by running the relevant Apps Script function against the real Google Sheet/project.

### `python`, `js`, `java`
1. Edit locally in the repository.
2. Run and test locally.
3. Sync the final version to **GitHub / Checksheets**.

## Repository organization
- Tests, debug scripts, temporary verification helpers → `test/`
- Documentation and reference materials → `Docs/`
- Production `.gs` scripts stay in the repository root unless a different structure is agreed explicitly.
