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
    assert FERON_TR_STOCK_HEADERS["Екатеринбург"] == "FER EKB"


def test_stream_supps_feron_source_columns_are_h_to_k():
    headers = [
        "Артикул продавца", "Артикул производителя", "PIC", "brand",
        "SKU OZON", "Х", "chrlid", "FER MSK", "FER SMR", "FER NSB", "FER EKB",
    ]
    columns = resolve_header_columns(headers, FERON_TR_SCHEMA, "StreamSupps")
    assert columns["model"] == 2
    assert columns["stock_vnukovo"] == 8
    assert columns["stock_samara"] == 9
    assert columns["stock_ekaterinburg"] == 11


def test_missing_stream_supps_feron_source_header_is_rejected():
    headers = [
        "Артикул продавца", "Артикул производителя", "PIC", "brand",
        "SKU OZON", "Х", "chrlid", "FER MSK", "FER SMR", "WRONG", "FER EKB",
    ]
    try:
        resolve_header_columns(headers, FERON_TR_SCHEMA, "StreamSupps")
    except ValueError as exc:
        assert "FER NSB" in str(exc)
    else:
        raise AssertionError("missing FERON TR source header must be rejected")


def test_etm_writer_no_longer_targets_legacy_feron_column():
    source = ETM_SYNC_PY.read_text(encoding="utf-8")
    assert '"etm_code": "CODES"' in source
    assert '"stock_smr": "ETM SMR"' in source
    assert '"stock_nsb": "ETM NSB"' in source
    assert "stock_etm" not in source


def test_wb_ekb_target_is_configured_for_feron_translation():
    source = SYNC_FERON_JS.read_text(encoding="utf-8")
    assert "EKB: 1860503" in source
    assert 'name: "Екатеринбург"' in source
    assert 'col: "stock_ekb"' in source
    assert "WB FBS (4 склада)" in source
