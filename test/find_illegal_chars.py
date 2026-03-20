import json

with open("google_credentials.json", "r", encoding="utf-8") as f:
    data = json.load(f)
    pk = data["private_key"]
    
    # Let's count characters
    print(f"Total PK length: {len(pk)}")
    
    # Find all characters that are NOT base64/newline/dash
    illegal = []
    for i, char in enumerate(pk):
        if char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=-\n":
            illegal.append((i, char, ord(char)))
            
    print(f"Illegal characters found: {illegal}")
    
    # If index 1620 is somehow wrong
    if len(pk) > 1620:
        print(f"Char at 1620: {pk[1620]!r} (ord: {ord(pk[1620])})")
