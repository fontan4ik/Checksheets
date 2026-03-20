import json

creds_path = "gsheets_creds.json"
with open(creds_path, "r", encoding="utf-8") as f:
    data = json.load(f)

# Fix double-escaped newlines if they exist
if "\\n" in data["private_key"]:
    print("Fixing literal \\n in private_key...")
    data["private_key"] = data["private_key"].replace("\\n", "\n")

# Also ensure no trailing/leading whitespace that might mess up PEM
data["private_key"] = data["private_key"].strip()

with open(creds_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)

print("gsheets_creds.json has been fixed and saved.")
