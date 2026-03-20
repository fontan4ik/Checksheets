import json

with open("gsheets_creds.json", "r", encoding="utf-8") as f:
    data = json.load(f)
    pk = data["private_key"]
    if "\\" in pk:
        print(f"Found backslash at index {pk.find('\\')}")
        print(f"Context: {pk[pk.find('\\')-5 : pk.find('\\')+5]!r}")
    else:
        print("No backslashes found in private_key string.")
