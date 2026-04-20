import pandas as pd
import sys

sys.stdout.reconfigure(encoding='utf-8')

FILE_NAME = "Оплата за заказ (все товары)_Отчёт по заказам_15.04.2026.xlsx"

def main():
    try:
        df = pd.read_excel(FILE_NAME, header=None)
        # Print first 5 rows to see structure
        for i, row in df.head(10).iterrows():
            print(f"Row {i}: {row.tolist()[:13]}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
