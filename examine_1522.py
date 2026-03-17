import json

with open("gsheets_creds.json", "r", encoding="utf-8") as f:
    data = json.load(f)
    pk = data["private_key"]
    
    pos = 1522
    start = max(0, pos - 10)
    end = min(len(pk), pos + 10)
    print(f"Char at {pos}: {pk[pos]!r} (ord: {ord(pk[pos])})")
    print(f"Context: {pk[start:end]!r}")
