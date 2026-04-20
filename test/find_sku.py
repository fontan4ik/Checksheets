import pandas as pd
file = r"C:\Users\jilig\Downloads\Оплата за заказ (все товары)_Отчёт по заказам_15.04.2026.xlsx"
df = pd.read_excel(file, header=None)

# Column 3 is SKU
sku_col = 3
# Find row with target SKU
target = 1644174248
for i in range(len(df)):
    val = df.iloc[i, sku_col]
    try:
        if int(float(str(val).replace('.0', ''))) == target:
            print(f"Found at row {i}")
            # Print all columns for this row
            for col in range(len(df.columns)):
                print(f"Col {col}: {df.iloc[i, col]}")
            break
    except:
        pass