import pandas as pd
import sys

# Set encoding for output
sys.stdout.reconfigure(encoding='utf-8')

TARGET_SKU = 1644174248
FILE_NAME = "Оплата за заказ (все товары)_Отчёт по заказам_15.04.2026.xlsx"

def main():
    try:
        print(f"Reading {FILE_NAME}...", flush=True)
        # We don't know the exact sheet name, let's load the first one
        df = pd.read_excel(FILE_NAME)
        
        print(f"Columns: {df.columns.tolist()}", flush=True)
        
        # Columns in Excel usually have spaces or specific names
        # Let's find columns that matches 'SKU' and 'Количество'
        sku_col = None
        qty_col = None
        rev_col = None
        spend_col = None
        
        for col in df.columns:
            c = str(col).lower()
            if 'sku' in c: sku_col = col
            elif 'количество' in c: qty_col = col
            elif 'стоимость' in c: rev_col = col
            elif 'расход' in c: spend_col = col
            
        print(f"Selected Columns: SKU={sku_col}, Qty={qty_col}, Rev={rev_col}, Spend={spend_col}", flush=True)
        
        if sku_col is not None:
            # Drop rows where SKU is NaN
            df = df.dropna(subset=[sku_col])
            
            # Filter for target SKU
            # Ensure target SKU is compared correctly (it might be numeric or string in df)
            target_df = df[df[sku_col].astype(str).str.contains(str(TARGET_SKU))]
            
            if not target_df.empty:
                total_qty = target_df[qty_col].sum() if qty_col else 0
                total_rev = target_df[rev_col].sum() if rev_col else 0
                total_spend = target_df[spend_col].sum() if spend_col else 0
                
                print("\n" + "="*50)
                print(f"EXCEL DATA FOR SKU {TARGET_SKU}:")
                print(f"Orders: {total_qty}")
                print(f"Revenue: {total_rev}")
                print(f"Spend: {total_spend}")
                print("="*50)
            else:
                print(f"\nSKU {TARGET_SKU} not found in Excel.")
                # Show some sample SKUs
                print(f"Sample SKUs: {df[sku_col].head(10).tolist()}")
        else:
            print("SKU column not found in Excel.")
            
    except Exception as e:
        print(f"Error reading Excel: {e}")

if __name__ == "__main__":
    main()
