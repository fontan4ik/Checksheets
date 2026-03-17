import json

with open("google_credentials.json", "r", encoding="utf-8") as f:
    orig_data = json.load(f)

# Re-dump with literal \n instead of actual newlines
# Most APIs expect the JSON to have "\n" as a two-character sequence in the string
orig_data["private_key"] = orig_data["private_key"].replace("\n", "\\n")

with open("google_credentials_fixed.json", "w", encoding="utf-8") as f:
    json.dump(orig_data, f, indent=2)

print("Created google_credentials_fixed.json with escaped newlines.")
