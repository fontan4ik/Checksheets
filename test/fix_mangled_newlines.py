import json

creds_path = "gsheets_creds.json"
with open(creds_path, "r", encoding="utf-8") as f:
    data = json.load(f)
    pk = data["private_key"]

# If there are backslashes that are NOT part of a newline sequence \n, 
# then they are likely mangled newlines from the copy-paste.

# In the current string, \n are real newlines (value 10). 
# But search_pk_backslash found a backslash (value 92).

print("Indices of backslash characters (ord 92):")
for i, char in enumerate(pk):
    if char == "\\":
        context = pk[max(0, i-5) : min(len(pk), i+6)]
        print(f"Index {i}: {char!r} context: {context!r}")

# Base64 should not have backslashes. 
# If we find one, and it's not followed by 'n' as part of an escaped sequence (which shouldn't be here anyway since it's decoded),
# then it's a mangled newline.

# Wait, if I'm reading with json.load, a backslash in the string is a literal backslash.
# If I see \h, it's a backslash and an h.

# Recommendation: Replace all backslashes with newlines if they appear in the middle of Base64?
# Or maybe they are just extra?

# Let's try to replace ALL backslashes with actual newlines.
fixed_pk = pk.replace("\\", "\n")

with open("gsheets_creds_fixed.json", "w", encoding="utf-8") as f:
    data["private_key"] = fixed_pk
    json.dump(data, f, indent=2)

print("Created gsheets_creds_fixed.json with all backslashes replaced by newlines.")
