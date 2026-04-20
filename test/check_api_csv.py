import pandas as pd

# Read API CSV
api_file = "C:/AI/Checksheets/test/ozon_ad_stats.csv"
df = pd.read_csv(api_file)

# Find the SKU
row = df[df['sku'] == 1644174248]
if len(row) > 0:
    print("API CSV row:")
    print(row)
else:
    # Try as string
    df['sku'] = df['sku'].astype(str)
    row = df[df['sku'] == '1644174248']
    if len(row) > 0:
        print("API CSV row (as string):")
        print(row)
    else:
        print("SKU not found in API CSV")
        print("First 5 SKUs:", df['sku'].head())