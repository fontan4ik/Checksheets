import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

SYNC_FERON_JS = PROJECT_ROOT / "sync-feron-stocks.js"
ETM_SYNC_PY = PROJECT_ROOT / "etm_sync_multi_store.py"

from feron_sync_local import (  # noqa: E402
    FERON_TR_SCHEMA,
    FERON_TR_STOCK_HEADERS,
    FERON_WAREHOUSE_IDS,
)
from gsheets_utils import resolve_header_columns  # noqa: E402


def test_ekb_warehouse_and_source_column_mapping():
    assert FERON_WAREHOUSE_IDS["Екатеринбург"] == "9a521a77-6e27-11ef-96b6-a4bf0186f0c7"
    assert FERON_TR_STOCK_HEADERS["Екатеринбург"] == "stocks EKB"


def test_feron_tr_source_columns_are_j_to_m():
    headers = ["art", "model", "brand", "pic", "SKU OZON", "SKU WB", "pr ozon", "pr wb", "bar"]
    headers.extend(["stocks SMR", "stocks MSK", "stocks NSB", "stocks EKB"])
    columns = resolve_header_columns(headers, FERON_TR_SCHEMA, "FERON TR")
    assert columns["stock_samara"] == 10
    assert columns["stock_ekaterinburg"] == 13


def test_missing_feron_tr_source_header_is_rejected():
    headers = ["art", "model", "brand", "pic", "SKU OZON", "SKU WB", "pr ozon", "pr wb", "bar"]
    headers.extend(["stocks SMR", "stocks MSK", "WRONG", "stocks EKB"])
    try:
        resolve_header_columns(headers, FERON_TR_SCHEMA, "FERON TR")
    except ValueError as exc:
        assert "stocks NSB" in str(exc)
    else:
        raise AssertionError("missing FERON TR source header must be rejected")


def test_etm_writer_targets_etm_header():
    source = ETM_SYNC_PY.read_text(encoding="utf-8")
    assert '"stock_etm": "ЭТМ"' in source
    assert "FERON_TR_STOCK_ETM_COL" not in source


def test_wb_ekb_target_is_configured_for_feron_translation():
    source = SYNC_FERON_JS.read_text(encoding="utf-8")
    assert "EKB: 1860503" in source
    assert 'name: "Екатеринбург"' in source
    assert 'col: "stock_ekb"' in source
    assert "WB FBS (4 склада)" in source
