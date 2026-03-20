import json
import os

creds_path = "gsheets_creds.json"
output_path = "check_creds.txt"

with open(creds_path, "r", encoding="utf-8") as f:
    content = f.read()

with open(output_path, "w", encoding="utf-8") as f:
    f.write(f"Raw content length: {len(content)}\n")
    f.write(f"Raw content start: {content[:100]}\n")
    try:
        data = json.loads(content)
        pk = data.get("private_key", "")
        f.write(f"Private key length: {len(pk)}\n")
        f.write(f"Private key start: {pk[:100].replace('\n', '[N]')}\n")
        f.write(f"Contains literal backslash: {'\\' in pk}\n")
    except Exception as e:
        f.write(f"Error: {e}\n")
