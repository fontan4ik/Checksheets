import pandas as pd
file = r"C:\Users\jilig\Downloads\Оплата за заказ (все товары)_Отчёт по заказам_15.04.2026.xlsx"
df = pd.read_excel(file, header=None)

# Find column with SKU
for col in range(len(df.columns)):
    col_vals = df.iloc[1:100, col].dropna()
    numeric_count = 0
    for val in col_vals:
        try:
            int(float(str(val)))
            numeric_count += 1
        except:
            pass
    if numeric_count > 50:
        print(f"Column {col} has {numeric_count} numeric values")
        # Print first 5 rows of this column
        for i in range(1, 6):
            val = df.iloc[i, col] if i < len(df) else None
            if val is not None:
                print(f"  Row {i}: {val}")