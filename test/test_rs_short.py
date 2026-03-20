import rs_sync_local
import gsheets_utils
import config

def test_rs():
    print("Testing RS sync for 5 articles...")
    ws = gsheets_utils.get_worksheet(config.RS_SHEET_NAME)
    headers = ws.row_values(1)
    col_model = headers.index("Модель") + 1
    models = ws.col_values(col_model)[1:6]
    print(f"Test models: {models}")
    
    # We need the code map
    code_map = rs_sync_local.fetch_rs_code_map(config.RS_WAREHOUSE_ID)
    
    for m in models:
        rs_code = code_map.get(m)
        if rs_code:
            stock = rs_sync_local.fetch_rs_stock(rs_code, config.RS_WAREHOUSE_ID)
            print(f"  {m} (RS:{rs_code}): {stock}")
        else:
            print(f"  {m}: Code not found")

if __name__ == "__main__":
    test_rs()
