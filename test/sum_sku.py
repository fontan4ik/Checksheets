import pandas as pd
file = r"C:\Users\jilig\Downloads\Оплата за заказ (все товары)_Отчёт по заказам_15.04.2026.xlsx"
df = pd.read_excel(file, header=None)

# Find all rows for target SKU
target = 1644174248
matches = []
for i in range(3, min(2000, len(df))):
    try:
        val = df.iloc[i, 3]
        if val == target or (isinstance(val, float) and int(val) == target):
            matches.append(i)
    except:
        pass

print("Found " + str(len(matches)) + " rows for SKU " + str(target))

# Sum all orders (col 11)
total_orders = 0
total_spend = 0
for idx in matches:
    try:
        orders = int(df.iloc[idx, 11]) if df.iloc[idx, 11] else 0
        spend = float(str(df.iloc[idx, 10]).replace(',', '.')) if df.iloc[idx, 10] else 0
        date = df.iloc[idx, 0]
        print("Row " + str(idx) + ": date=" + str(date) + ", orders=" + str(orders) + ", spend=" + str(spend))
        total_orders += orders
        total_spend += spend
    except Exception as e:
        print("Error at " + str(idx) + ": " + str(e))

print("\nTotal orders: " + str(total_orders))
print("Total spend: " + str(total_spend))