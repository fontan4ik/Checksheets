"""Read the full current Ozon identity for articles in the FERON workbook."""
from __future__ import annotations

import json
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
WORKBOOK = Path(
    "/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron/"
    "Сопоставление_артикулов_и_файлов_документов.xlsx"
)
NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
sys.path.insert(0, str(BASE))
from api_client import Client, save  # noqa: E402


def read_workbook_offers() -> dict[str, dict[str, str]]:
    with zipfile.ZipFile(WORKBOOK) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relations = {
            item.attrib["Id"]: item.attrib["Target"].lstrip("/")
            for item in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }
        shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        strings = [
            "".join(text.text or "" for text in item.findall(".//a:t", NS))
            for item in shared_root.findall("a:si", NS)
        ]
        sheet = next(
            item
            for item in workbook.findall("a:sheets/a:sheet", NS)
            if item.attrib["name"] == "Артикул-файл"
        )
        xml = ET.fromstring(archive.read(relations[sheet.attrib[f"{{{NS['r']}}}id"]]))

    offers: dict[str, dict[str, str]] = {}
    conflicting: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for row in xml.findall("a:sheetData/a:row", NS):
        values: dict[str, str] = {}
        for cell in row.findall("a:c", NS):
            column = "".join(char for char in cell.attrib["r"] if char.isalpha())
            value = cell.find("a:v", NS)
            text = value.text if value is not None else ""
            if cell.attrib.get("t") == "s" and text:
                text = strings[int(text)]
            elif cell.attrib.get("t") == "inlineStr":
                text = "".join(part.text or "" for part in cell.findall(".//a:t", NS))
            values[column] = text
        offer = values.get("A", "").strip()
        if not offer or offer == "Артикул продавца" or not values.get("D") or not values.get("E"):
            continue
        pair = (values["D"].strip(), values["E"].strip())
        conflicting[offer].add(pair)
        offers.setdefault(offer, {"workbook_product_id": pair[0], "workbook_sku": pair[1]})
    conflicts = {offer: sorted(pairs) for offer, pairs in conflicting.items() if len(pairs) != 1}
    if conflicts:
        raise RuntimeError(f"Conflicting product identity in workbook: {len(conflicts)} offers")
    return offers


def main() -> None:
    offers = read_workbook_offers()
    api = Client()
    live: dict[str, dict] = {}
    ids = sorted(offers)
    for offset in range(0, len(ids), 100):
        batch = ids[offset : offset + 100]
        response = api.call("ozon", "/v3/product/info/list", {"offer_id": batch})
        items = response.get("items") or response.get("result", {}).get("items")
        if not isinstance(items, list):
            raise RuntimeError(f"Unexpected product info response at offset {offset}")
        for item in items:
            offer = str(item.get("offer_id", ""))
            if not offer or offer in live:
                raise RuntimeError(f"Missing or duplicate Ozon offer_id {offer!r}")
            live[offer] = {
                "product_id": str(item.get("id", "")),
                "sku": str(item.get("sku", "")),
                "name": item.get("name"),
                "is_archived": item.get("is_archived"),
            }
        if (offset // 100 + 1) % 10 == 0 or offset + len(batch) == len(ids):
            print(
                json.dumps(
                    {"queried": min(offset + len(batch), len(ids)), "expected": len(ids)},
                    ensure_ascii=False,
                ),
                flush=True,
            )

    missing = sorted(set(ids) - set(live))
    extras = sorted(set(live) - set(ids))
    mismatches = {
        offer: {
            "workbook": offers[offer],
            "live": live[offer],
        }
        for offer in set(ids) & set(live)
        if offers[offer]["workbook_product_id"] != live[offer]["product_id"]
        or offers[offer]["workbook_sku"] != live[offer]["sku"]
    }
    state = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "workbook": str(WORKBOOK),
        "workbook_offer_count": len(offers),
        "live_offer_count": len(live),
        "missing_offers": missing,
        "unexpected_offers": extras,
        "identity_mismatches": mismatches,
        "offers": {
            offer: {**offers[offer], **live.get(offer, {})} for offer in ids
        },
        "complete": not missing and not extras and len(live) == len(offers),
    }
    save("feron_ozon_identity_audit.json", state)
    print(
        json.dumps(
            {
                "complete": state["complete"],
                "workbook_offers": len(offers),
                "live_offers": len(live),
                "missing": len(missing),
                "identity_mismatches": len(mismatches),
                "archived": sum(bool(item.get("is_archived")) for item in live.values()),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
