import pandas as pd
import os

file = r"C:\Users\jilig\Downloads\Оплата за заказ (все товары)_Отчёт по заказам_15.04.2026.xlsx"
df = pd.read_excel(file, header=None)

# Print first 5 rows to see structure
print("=== First 5 rows (all columns) ===")
for i in range(min(5, len(df))):
    row = df.iloc[i]
    vals = [str(row[j])[:30] for j in range(min(13, len(row)))]
    print(f"Row {i}: {vals}")

# Find SKU column - look for numeric values
print("\n=== Looking for numeric SKU column ===")
for col in range(len(df.columns)):
    col_vals = df.iloc[1:, col].dropna()
    numeric_count = 0
    for val in col_vals.head(100):
        try:
            int(float(str(val)))
            numeric_count += 1
        except:
            pass
    if numeric_count > 50:
        print(f"Column {col}: {numeric_count} numeric values")
        # Show sample
        print(f"  Sample: {df.iloc[10:15, col].tolist()}")