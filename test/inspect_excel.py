import pandas as pd
import sys

# Set encoding for output to UTF-8
sys.stdout.reconfigure(encoding='utf-8')

file_path = 'Оплата за заказ (все товары)_Отчёт по заказам_15.04.2026.xlsx'
try:
    df = pd.read_excel(file_path, header=None)
    
    # Try to find header row
    header_row_index = -1
    for i, row in df.iterrows():
        if 'SKU' in [str(x) for x in row.values]:
            header_row_index = i
            break
    
    if header_row_index != -1:
        df.columns = df.iloc[header_row_index]
        df = df.iloc[header_row_index+1:]
        
        target_sku = "1644174248"
        sku_mask = df.astype(str).apply(lambda x: x.str.contains(target_sku)).any(axis=1)
        res = df[sku_mask]
        
        qty_col = None
        for col in df.columns:
            if 'Количество' in str(col):
                qty_col = col
                break
        
        if qty_col:
            total_qty = pd.to_numeric(res[qty_col], errors='coerce').sum()
            print(f"Sum of '{qty_col}' for SKU {target_sku}: {total_qty}")
        else:
            print("Could not find 'Количество' column.")

        print(f"Total rows matching SKU {target_sku}: {len(res)}")
        print("\nFirst 5 rows:")
        print(res.head(5).to_string())
    else:
        print("\nCould not find 'SKU' header.")

except Exception as e:
    print(f"Error: {e}")
