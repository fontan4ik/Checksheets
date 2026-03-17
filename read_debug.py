with open("etm_exhaustive.txt", "rb") as f:
    content = f.read().decode('utf-8', errors='replace')
    print(content)
