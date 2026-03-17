import json

with open("google_credentials.json", "r", encoding="utf-8") as f:
    data = json.load(f)
    pk = data["private_key"]
    print(f"Key starts with: {pk[:30]!r}")
    print(f"Key ends with: {pk[-30:]!r}")
    print(f"Total length: {len(pk)}")
    
    # Check for literal \n (two characters) vs actual newline (one character)
    if "\\n" in pk:
        print("ALERT: Found literal '\\n' sequences in private_key!")
        # Count them
        count = pk.count("\\n")
        print(f"Total '\\n' sequences: {count}")
    else:
        print("No literal '\\n' sequences found.")
        
    # Check for actual newlines
    if "\n" in pk:
        print(f"Total actual newline characters: {pk.count('\n')}")
    else:
        print("No actual newline characters found.")
