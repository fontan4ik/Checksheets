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
        # Exact match for SKU column
        sku_col = None
        for col in df.columns:
            if str(col).strip() == 'SKU':
                sku_col = col
                break
        
        if sku_col is None:
             sku_col = 'SKU'

        # Convert SKU to string and strip
        df[sku_col] = df[sku_col].astype(str).str.strip()
        res = df[df[sku_col] == target_sku]
        
        print(f"--- Analysis for SKU {target_sku} ---")
        print(f"Total rows found: {len(res)}")
        
        # Columns found
        print(f"Columns: {list(df.columns)}")
        
        # Try to find relevant columns
        qty_col = next((c for c in df.columns if 'Количество' in str(c)), None)
        price_col = next((c for c in df.columns if 'Стоимость, ₽' in str(c)), None)
        spend_col = next((c for c in df.columns if 'Расход, ₽' in str(c)), None)
        
        if qty_col:
            total_qty = pd.to_numeric(res[qty_col], errors='coerce').sum()
            print(f"Total Orders ({qty_col}): {total_qty}")
        
        if price_col:
            total_price = pd.to_numeric(res[price_col], errors='coerce').sum()
            print(f"Total Revenue ({price_col}): {total_price}")
            
        if spend_col:
            total_spend = pd.to_numeric(res[spend_col], errors='coerce').sum()
            print(f"Total Spend ({spend_col}): {total_spend}")
            
        # Date range
        if 'Дата' in df.columns:
            # Convert values to date if they are strings in format DD.MM.YYYY
            dates = pd.to_datetime(df['Дата'], format='%d.%m.%Y', errors='coerce')
            if dates.isna().all():
                 # try auto
                 dates = pd.to_datetime(df['Дата'], errors='coerce')
            
            print(f"Excel Date Range: {dates.min()} to {dates.max()}")
            
        # If not found by name, print first match columns values
        if len(res) > 0:
            print("\nFirst row values for SKU:")
            print(res.iloc[0].to_dict())

    else:
        print("\nCould not find 'SKU' header.")

except Exception as e:
    print(f"Error: {e}")
