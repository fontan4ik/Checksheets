import json

with open("gsheets_creds.json", "r", encoding="utf-8") as f:
    data = json.load(f)
    pk = data["private_key"]
    print(f"PK start: {pk[:20]!r}")
    print(f"PK bytes start: {pk[:10].encode('utf-8')}")
    print(f"First char: {pk[0]} (ord: {ord(pk[0])})")
