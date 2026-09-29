#!/usr/bin/env python3
"""Read-only live Russvet check for supplier article 1025326."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rs_sync_local


ARTICLE = "1025326"

for warehouse_id in (287, 14030):
    code_map = rs_sync_local.fetch_rs_code_map(warehouse_id)
    code = code_map.get(ARTICLE)
    stock_map = rs_sync_local.fetch_all_rs_stocks(warehouse_id)
    print({
        "warehouse_id": warehouse_id,
        "supplier_code": code,
        "stock": stock_map.get(code) if code is not None else None,
        "article_mapped": code is not None,
    })
