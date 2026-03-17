import json

with open("gsheets_creds.json", "r", encoding="utf-8") as f:
    data = json.load(f)
    pk = data["private_key"]
    
    pos = 1472
    start = max(0, pos - 20)
    end = min(len(pk), pos + 20)
    print(f"Context at {pos}: {pk[start:end]!r}")
    
    all_backslashes = [i for i, char in enumerate(pk) if char == "\\"]
    print(f"All backslash indices: {all_backslashes}")
