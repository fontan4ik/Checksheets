import csv
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sync_etm_codes import _source_columns, normalize, normalize_code

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = json.loads(Path("/tmp/etm_candidate_source_rows.json").read_text(encoding="utf-8"))
SOURCES = [
    ("13", ROOT / "test/tmp/etm_ftp_downloads/from_etm/13/price.csv"),
    ("14", ROOT / "test/tmp/etm_ftp_downloads/from_etm/14/price.csv"),
]


def source_encoding(sample: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "windows-1251", "koi8-r"):
        try:
            sample.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            pass
    return "utf-8"


def read_relevant_pairs(path: Path, wanted: set[tuple[str, str]]):
    with path.open("rb") as stream:
        sample = stream.read(65536)
    encoding = source_encoding(sample)
    sample_text = sample.decode(encoding, errors="replace")
    try:
        dialect = csv.Sniffer().sniff(sample_text[:4096], delimiters=";\t,|")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"

    found: dict[tuple[str, str], set[str]] = {}
    with path.open("r", encoding=encoding, newline="") as stream:
        reader = csv.reader(stream, dialect)
        headers = next(reader, None)
        columns = _source_columns(headers)
        for row in reader:
            if len(row) <= max(columns.values()):
                continue
            key = (
                normalize(row[columns["article"]]),
                normalize(row[columns["brand"]]),
            )
            if key not in wanted:
                continue
            code = normalize_code(row[columns["code"]])
            if code:
                found.setdefault(key, set()).add(code)
    return found


def read_unbranded_matches(path: Path, candidates: list[dict]):
    wanted: dict[str, list[dict]] = {}
    for item in candidates:
        for field in ("model", "article"):
            key = normalize(item.get(field))
            if key:
                wanted.setdefault(key, []).append(item)

    with path.open("rb") as stream:
        sample = stream.read(65536)
    encoding = source_encoding(sample)
    sample_text = sample.decode(encoding, errors="replace")
    try:
        dialect = csv.Sniffer().sniff(sample_text[:4096], delimiters=";\t,|")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"

    result: dict[str, set[tuple[str, str, str]]] = {}
    with path.open("r", encoding=encoding, newline="") as stream:
        reader = csv.reader(stream, dialect)
        headers = next(reader, None)
        columns = _source_columns(headers)
        name_col = next((i for i, header in enumerate(headers or []) if normalize(header) == normalize("Полное наименование")), None)
        for row in reader:
            if len(row) <= max(columns.values()):
                continue
            article = normalize(row[columns["article"]])
            matches = wanted.get(article, [])
            if not matches:
                continue
            code = normalize_code(row[columns["code"]])
            producer = normalize(row[columns["brand"]])
            name = str(row[name_col]).strip() if name_col is not None and len(row) > name_col else ""
            if not code:
                continue
            for item in matches:
                result.setdefault(item["article"], set()).add((code, producer, name))
    return result


def unique_code(mapping, key):
    values = mapping.get(key, set())
    return next(iter(values)) if len(values) == 1 else None


keys = set()
for item in CANDIDATES:
    brand = normalize(item.get("brand"))
    for field in ("model", "article"):
        value = normalize(item.get(field))
        if brand and value:
            keys.add((value, brand))

source_maps = []
for label, path in SOURCES:
    source_maps.append((label, read_relevant_pairs(path, keys) if path.is_file() else {}))

mapped = []
unmatched = []
ambiguous = []
for item in CANDIDATES:
    brand = normalize(item.get("brand"))
    candidate_keys = [(field, normalize(item.get(field))) for field in ("model", "article")]
    selected = None
    for label, mapping in source_maps:
        found = [
            (field, unique_code(mapping, (value, brand)))
            for field, value in candidate_keys
            if value and unique_code(mapping, (value, brand))
        ]
        codes = {code for _, code in found}
        if len(codes) > 1:
            ambiguous.append({"article": item["article"], "source": label})
            selected = "ambiguous"
            break
        if found:
            selected = {"article": item["article"], "code": found[0][1], "source": label}
            break
    if isinstance(selected, dict):
        mapped.append(selected)
    elif selected != "ambiguous":
        unmatched.append(item["article"])

output = {"mapped": mapped, "unmatched": unmatched, "ambiguous": ambiguous}
Path("/tmp/etm_candidate_codes.json").write_text(json.dumps(output), encoding="utf-8")
weak_matches = {}
needs_review = [item for item in CANDIDATES if item["article"] in set(unmatched) | {x["article"] for x in ambiguous}]
for label, path in SOURCES:
    if path.is_file():
        weak_matches[label] = read_unbranded_matches(path, needs_review)
review = {
    item["article"]: {
        "model": item.get("model"),
        "brand": item.get("brand"),
        "sources": {
            label: sorted([list(x) for x in mapping.get(item["article"], set())])
            for label, mapping in weak_matches.items()
            if mapping.get(item["article"])
        },
    }
    for item in needs_review
}
print(json.dumps({
    "candidate_count": len(CANDIDATES),
    "mapped_count": len(mapped),
    "source_13": sum(item["source"] == "13" for item in mapped),
    "source_14": sum(item["source"] == "14" for item in mapped),
    "unmatched_count": len(unmatched),
    "ambiguous_count": len(ambiguous),
    "unmatched_examples": unmatched[:12],
    "ambiguous_examples": ambiguous[:8],
    "unbranded_matches": review,
}, ensure_ascii=False))
