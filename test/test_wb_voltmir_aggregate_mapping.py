from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_local_etm_reads_wb_voltmir_total_by_header():
    source = (PROJECT_ROOT / "sync-etm-stocks.js").read_text(encoding="utf-8")
    assert 'wbStock: STREAM_SUPPS_HEADERS.wbVoltmirTotal' in source
    assert '"AB:WB ВОЛЬТМИР ИТОГ"' in source
    assert "const colWbStock = colStock" not in source


def test_local_feron_uses_wb_total_for_voltmir():
    source = (PROJECT_ROOT / "sync-feron-stocks.js").read_text(encoding="utf-8")
    assert 'wb_voltmir_stock: STREAM_SUPPS_HEADERS.wbVoltmirTotal' in source
    assert 'id: FERON_TR_WB_WAREHOUSE.SMR' in source
    assert 'col: "stock_wb_voltmir"' in source


def test_local_feron_uses_ac_total_for_feron_moscow():
    source = (PROJECT_ROOT / "sync-feron-stocks.js").read_text(encoding="utf-8")
    assert 'wb_feron_moscow_stock: STREAM_SUPPS_HEADERS.wbFeronMoscowTotal' in source
    assert 'id: FERON_TR_WB_WAREHOUSE.MSK' in source
    assert 'col: "stock_wb_feron_moscow"' in source


def test_direct_arl_wb_stock_writer_is_disabled():
    source = (PROJECT_ROOT / "Flow_ARL_TR__Остатки_Маркетплейсы.js").read_text(encoding="utf-8")
    assert "const ARL_DIRECT_WB_STOCK_UPLOAD_ENABLED = false" in source
    assert "if (!ARL_DIRECT_WB_STOCK_UPLOAD_ENABLED)" in source


def test_rs_writers_use_wb_total():
    local_rs = (PROJECT_ROOT / "sync-rs-stocks.js").read_text(encoding="utf-8")
    rs = (PROJECT_ROOT / "Flow_StreamSupps__Остатки_RS_Маркетплейсы.js").read_text(encoding="utf-8")
    assert 'wb_stock: STREAM_SUPPS_HEADERS.wbVoltmirTotal' in local_rs
    assert '"AB:WB ВОЛЬТМИР ИТОГ"' in local_rs
    assert 'wbStock: "WB ВОЛЬТМИР ИТОГ"' in rs
    assert rs.count("amount: item.wb_stock") >= 2
