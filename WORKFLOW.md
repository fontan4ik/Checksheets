# Checksheets Workflow & Development Guide

This document describes the development, testing, and deployment procedures for the Checksheets hybrid system (Google Apps Script + local Python sync agents).

---

## 🔄 1. Development & Version Control Workflow

Our source of truth is structured around:
- **Google Apps Script Project:** `"Главные скрипты v2"` — The production cloud environment.
- **Git Repository:** `Checksheets` — The local and version-controlled source code.

### A. Editing and Syncing Google Apps Script (`.js` files)
1. **Always edit locally:** Make code modifications in the local `.js` files inside your Git workspace first. Never make ad-hoc edits directly inside the Google Apps Script browser editor.
2. **Automatic sync:** The LaunchAgent `com.voltmir.checksheets-github-sync` polls GitHub `main` every 120 seconds, fast-forwards the local workspace, commits stable local changes, pushes them to GitHub, and runs `clasp push` when Apps Script files changed.
3. **Scope:** Apps Script upload is controlled by `.claspignore`; local Python, Node helpers, logs, test runtime files, and credentials are not uploaded to the bound Apps Script project.
4. **Verification:** After `clasp push`, the watcher pulls the cloud project into a temporary directory and compares SHA-256 hashes without overwriting the working tree.
5. **Manual execution:** Run `python3 scripts/checksheets_github_sync.py --once --dry-run` for a no-write check or `--once` for one real cycle.
6. **Trigger execution:** Run `runDiagnostics()` or the specific function you modified from the script editor dropdown to verify it behaves correctly.
7. **Inspect Cloud Logs:** Check execution details via the built-in console logs (**View → Logs** or **Executions** tab in Apps Script).

### B. Developing and Running Local Python Scripts (`.py` files)
1. **Virtual Environment:** Ensure Python dependencies (like `requests`, `gspread`, `google-auth`) are activated inside the local virtual environment:
   ```bash
   source .venv-etm-export/bin/activate
   ```
2. **Interface Binding / VPN Bypass:** When running sync scripts from local machines that have active corporate or private VPN clients (which block default API routes), the python scripts must resolve the active Wi-Fi/LAN interface and bind to it natively:
   - Interface resolver logic checks `en0` and `en1` adapters using `ifconfig`.
   - `network_bypass.SourceAddressAdapter` is mounted on the `requests` Session object. On macOS it uses `IP_BOUND_IF`, matching `curl --interface`; binding only the source IP does not work with full-tunnel Network Extension clients such as Happ.
   - Bypass configuration is specified in `config.py` and via environment variables like `CHECKSHEETS_BYPASS_INTERFACE`.
   - The Node CDEK sync follows the macOS system route by default; use `CHECKSHEETS_NODE_SOURCE_BIND=true` only for legacy VPN setups that support source-address binding.
3. **Running the Syncs:** Python synchronization tasks can be executed manually or scheduled via system crons:
   ```bash
   python3 feron_sync_local.py
   python3 rs_sync_local.py
   python3 etm_sync_multi_store.py
   ```

---

## 📁 2. Repository Organization & Strict File Location Rules

To keep the repository pristine, structured, and easy to maintain for both human developers and AI coding agents, we enforce strict folder location policies:

### ⚠️ Strict Rules for File Locations:
1. **Documentation & Reference (.md, .txt, etc.):** 
   - All documentation files, API specifications, task lists, research notes, and architectural markdown reports **MUST** be placed in the **`Docs/`** directory.
   - No new `.md` files should be added directly to the project root, except for the absolute base configurations (`CLAUDE.md`, `AGENTS.md`, and `WORKFLOW.md`).
2. **Testing & Diagnostics (.py, .js, .json, mocks):** 
   - All diagnostic files, local connectivity testers, ad-hoc execution playgrounds, sample response payloads, and mock JSON files **MUST** reside exclusively in the **`test/`** directory.
   - The repository root must be kept clean of temporary logs, data dumps, and debug scripts. It must only contain active production code.
3. **Always Document Modifications:** 
   - If you introduce new script parameters or change column indices in Google Sheet, immediately update the column mapping table in both **`CLAUDE.md`** and **`AGENTS.md`**.
