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


def test_legacy_apps_script_supplier_writers_are_removed():
    for legacy_path in (
        "Flow_ARL_TR__Остатки_Маркетплейсы.js",
        "Flow_StreamSupps__Остатки_RS_Маркетплейсы.js",
        "Flow_StreamSupps__Обнуление_RS_Ozon.js",
        "scripts/com.checksheets.sync_rs_stocks.plist",
    ):
        assert not (PROJECT_ROOT / legacy_path).exists(), legacy_path


def test_local_rs_writer_uses_wb_total():
    local_rs = (PROJECT_ROOT / "sync-rs-stocks.js").read_text(encoding="utf-8")
    assert 'wb_stock: STREAM_SUPPS_HEADERS.wbVoltmirTotal' in local_rs
    assert '"AB:WB ВОЛЬТМИР ИТОГ"' in local_rs


def test_main_flow_does_not_call_removed_external_api_writer():
    source = (PROJECT_ROOT / "Flow_Триггеры__Основные.js").read_text(encoding="utf-8")
    for removed_entrypoint in (
        "updateExternalAPIStocks(",
        "syncRSStocks(",
        "syncARLStocks(",
    ):
        assert removed_entrypoint not in source, removed_entrypoint
