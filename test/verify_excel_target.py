import pandas as pd
import sys

sys.stdout.reconfigure(encoding='utf-8')

FILE_NAME = "Оплата за заказ (все товары)_Отчёт по заказам_15.04.2026.xlsx"
TARGET_SKU = 1644174248

def main():
    try:
        # Load starting from row 2 as header
        df = pd.read_excel(FILE_NAME, header=2)
        
        # Check target SKU in 'SKU' and 'SKU продвигаемого товара'
        mask_sku = df['SKU'].astype(str) == str(TARGET_SKU)
        mask_promo = df['SKU продвигаемого товара'].astype(str) == str(TARGET_SKU)
        
        combined_mask = mask_sku | mask_promo
        target_df = df[combined_mask]
        
        if not target_df.empty:
            print(f"Found {len(target_df)} records for SKU {TARGET_SKU}")
            total_qty = target_df['Количество'].sum()
            total_rev = target_df['Стоимость, ₽'].sum()
            total_spend = target_df['Расход, ₽'].sum()
            
            print(f"Total Quantity: {total_qty}")
            print(f"Total Revenue: {total_rev}")
            print(f"Total Spend: {total_spend}")
            
            # Show sources
            # print(target_df[['Дата', 'Номер заказа', 'SKU', 'SKU продвигаемого товара', 'Количество', 'Расход, ₽']].head(10))
        else:
            print(f"SKU {TARGET_SKU} not found.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
