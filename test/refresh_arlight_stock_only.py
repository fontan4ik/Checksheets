"""Refresh the existing ARL TR stock source without writing prices."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import arlight_sync_local as arl
import gsheets_utils as sheets


def main():
    stocks = arl.fetch_arlight_stocks()
    ws = sheets.get_worksheet(arl.SHEET_NAME)
    columns = sheets.get_header_columns(
        ws, {"article": arl.ARTICLE_HEADER, "stock": arl.STOCK_HEADER}, arl.SHEET_NAME
    )
    if columns != {"article": arl.ARTICLE_COLUMN, "stock": arl.STOCK_COLUMN}:
        raise RuntimeError(f"Unexpected ARL TR schema: {columns}")
    cells = ws.get(f"B2:B{ws.row_count}", value_render_option="UNFORMATTED_VALUE")
    articles = [row[0] if row else "" for row in cells]
    articles.extend([""] * (ws.row_count - 1 - len(articles)))
    values, stats = arl.build_stock_values(articles, stocks)
    if (not stats.nonempty_articles or stats.match_rate < arl.MIN_MATCH_RATE
            or not stats.positive_stock):
        raise RuntimeError(f"Unsafe Arlight snapshot: {stats}")
    mask = [bool(str(a or "").strip()) and str(a or "").strip() in stocks for a in articles]
    before = ws.get(f"F2:F{ws.row_count}", value_render_option="UNFORMATTED_VALUE")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "test" / f"arlight_stock_before_{stamp}.json"
    backup.write_text(json.dumps({"sheet": ws.title, "range": f"F2:F{ws.row_count}",
                                 "values": before}, ensure_ascii=False))
    written = sheets.update_column_masked(ws, columns["stock"], values, mask)
    after = ws.get(f"F2:F{ws.row_count}", value_render_option="UNFORMATTED_VALUE")
    for index, enabled in enumerate(mask):
        if enabled:
            actual = after[index][0] if index < len(after) and after[index] else ""
            if actual != values[index][0]:
                raise RuntimeError(f"Arlight readback mismatch at row {index + 2}")
    print(f"ARL TR stock updated and verified: written={written}, stats={stats}, backup={backup}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        arl.send_telegram_alert("arlight stock refresh", exc)
        raise
