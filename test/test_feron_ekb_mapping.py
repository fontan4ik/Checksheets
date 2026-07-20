import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from feron_sync_local import (  # noqa: E402
    FERON_TR_STOCK_COLUMNS,
    FERON_TR_STOCK_HEADERS,
    FERON_WAREHOUSE_IDS,
    validate_feron_tr_headers,
)


def test_ekb_warehouse_and_source_column_mapping():
    assert FERON_WAREHOUSE_IDS["Екатеринбург"] == "9a521a77-6e27-11ef-96b6-a4bf0186f0c7"
    assert FERON_TR_STOCK_COLUMNS["Екатеринбург"] == 13
    assert FERON_TR_STOCK_HEADERS["Екатеринбург"] == "stocks EKB"


def test_feron_tr_source_columns_are_j_to_m():
    headers = ["art", "model", "brand", "pic", "SKU OZON", "SKU WB", "pr ozon", "pr wb", "bar"]
    headers.extend(["stocks SMR", "stocks MSK", "stocks NSB", "stocks EKB"])
    validate_feron_tr_headers(headers)


def test_shifted_feron_tr_column_is_rejected():
    headers = ["art", "model", "brand", "pic", "SKU OZON", "SKU WB", "pr ozon", "pr wb", "bar"]
    headers.extend(["stocks SMR", "stocks MSK", "WRONG", "stocks EKB"])
    try:
        validate_feron_tr_headers(headers)
    except RuntimeError as exc:
        assert "column 12" in str(exc)
        assert "stocks NSB" in str(exc)
    else:
        raise AssertionError("shifted FERON TR source column must be rejected")
