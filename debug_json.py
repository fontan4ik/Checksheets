import json

with open(r"c:\AI\Работа Voltmir\Проверка таблицы\gsheets_creds.json", "r", encoding="utf-8") as f:
    content = f.read()

print(f"File length: {len(content)}")
try:
    data = json.loads(content)
    print("JSON is valid!")
except json.JSONDecodeError as e:
    print(f"JSON error: {e}")
    # Print context around the error
    start = max(0, e.pos - 50)
    end = min(len(content), e.pos + 50)
    print(f"Context: ...{content[start:end]}...")
    print(f"Problematic char: {content[e.pos]!r} at pos {e.pos}")
