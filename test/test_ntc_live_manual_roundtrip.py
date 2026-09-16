"""One-off live manual-K check; restores the edited cell and physical F."""

import subprocess
import time
from pathlib import Path

import gspread


ROOT = Path(__file__).resolve().parents[1]
SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI"


def run_sync():
    command = [str(ROOT / ".venv-etm-export/bin/python"), str(ROOT / "ntc_live_local.py"), "--apply"]
    for _ in range(8):
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=45)
        if result.returncode == 0:
            return result.stdout.strip()
        if "already running" not in result.stderr:
            raise RuntimeError(result.stderr or result.stdout)
        time.sleep(2)
    raise RuntimeError("NTC local sync stayed locked")


def main():
    client = gspread.service_account(filename=str(ROOT / "nomadic-bedrock-485314-b0-d7624dedd83c.json"))
    stock = client.open_by_key(SPREADSHEET_ID).worksheet("НТЦ списания")
    row = 3  # 2851987-5; no tracked order in the local journal.
    original_k = stock.acell(f"K{row}").value or ""
    original_f = int(stock.acell(f"F{row}").value)
    if stock.acell(f"A{row}").value != "2851987-5" or original_k or original_f != 100:
        raise RuntimeError("manual test row changed; refusing to edit")
    try:
        stock.update(range_name=f"K{row}", values=[[1]], value_input_option="RAW")
        run_sync()
        after = int(stock.acell(f"F{row}").value)
        if after != 95:
            raise AssertionError(f"K=1 at H=5 should make F=95, got {after}")
        print("manual K=1 at H=5: F 100→95")
    finally:
        stock.update(range_name=f"K{row}", values=[[original_k]], value_input_option="RAW")
        run_sync()
        restored = int(stock.acell(f"F{row}").value)
        if restored != original_f:
            raise AssertionError(f"manual test did not restore F: {restored}")
        print("manual K cleared: F 95→100; restored")


if __name__ == "__main__":
    main()
