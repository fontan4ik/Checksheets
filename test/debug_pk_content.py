import json

with open("google_credentials.json", "r", encoding="utf-8") as f:
    data = json.load(f)
    pk = data["private_key"]
    
    # Let's find index of 'nnjsaNQdIs4Ka7Dp' in the string
    search_str = "nnjsaNQdIs4Ka7Dp"
    idx = pk.find(search_str)
    if idx != -1:
        print(f"Found '{search_str}' at index {idx}")
        # Show preceding 10 and succeeding 10 chars
        print(f"Context: {pk[max(0, idx-10) : idx+len(search_str)+10]!r}")
    else:
        print(f"String '{search_str}' NOT found in private_key")
        
    print(f"Character at 1620: {pk[1620]!r} (ord: {ord(pk[1620])})")
    print(f"Context at 1620: {pk[1610:1630]!r}")
