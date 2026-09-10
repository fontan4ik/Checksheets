from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_local_etm_reads_wb_voltmir_total_from_ac():
    source = (PROJECT_ROOT / "sync-etm-stocks.js").read_text(encoding="utf-8")
    assert 'WB_STOCK: 29' in source
    assert 'WB_VOLTMIR_STOCK_HEADER = "WB ВОЛЬТМИР ИТОГ"' in source
    assert "const colWbStock = colStock" not in source


def test_local_feron_uses_wb_total_for_voltmir():
    source = (PROJECT_ROOT / "sync-feron-stocks.js").read_text(encoding="utf-8")
    assert 'wb_voltmir_stock: "WB ВОЛЬТМИР ИТОГ"' in source
    assert 'id: FERON_TR_WB_WAREHOUSE.SMR' in source
    assert 'col: "stock_wb_voltmir"' in source


def test_apps_script_writers_use_wb_total():
    etm = (PROJECT_ROOT / "Синхронизация остатков ETM TR.js").read_text(encoding="utf-8")
    rs = (PROJECT_ROOT / "Синхронизация остатков RS.js").read_text(encoding="utf-8")
    assert "const ETM_COL_WB_STOCK = 29" in etm
    assert "amount: item.wb_stock" in etm
    assert "const RS_COL_WB_STOCK = 29" in rs
    assert rs.count("amount: item.wb_stock") >= 2
