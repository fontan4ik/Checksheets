import pandas as pd
file = r"C:\Users\jilig\Downloads\Оплата за заказ (все товары)_Отчёт по заказам_15.04.2026.xlsx"
df = pd.read_excel(file, header=None)

# Print header row indices
print("Headers at row 2:")
for col in range(13):
    print(str(col))

# Find row index for header
target = 1644174248
for i in range(3, min(200, len(df))):
    try:
        val = df.iloc[i, 3]
        if val == target or (isinstance(val, float) and int(val) == target):
            print("Found at row " + str(i))
            for col in range(13):
                print(str(col) + "=" + str(df.iloc[i, col]))
            break
    except Exception as e:
        pass