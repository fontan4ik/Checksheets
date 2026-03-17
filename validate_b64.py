import json
import base64

with open("google_credentials.json", "r", encoding="utf-8") as f:
    data = json.load(f)
    pk = data["private_key"]

# Extract the base64 part
lines = [l.strip() for l in pk.split('\n') if l.strip() and "PRIVATE KEY" not in l]
b64_content = "".join(lines)

print(f"B64 length: {len(b64_content)}")
print(f"B64 chars (first 50): {b64_content[:50]}")

try:
    decoded = base64.b64decode(b64_content)
    print(f"Decoded success! Length: {len(decoded)}")
except Exception as e:
    print(f"Decoded failed: {e}")
    # Find invalid chars
    invalid = [c for c in b64_content if c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="]
    print(f"Invalid chars found: {set(invalid)}")
