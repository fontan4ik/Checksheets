"""Read the complete current WB catalog and retain only offers in the FERON workbook."""
from __future__ import annotations

import datetime as dt
import json
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from api_client import BASE, Client, now, save

WORKBOOK = Path("/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron/Сопоставление_артикулов_и_файлов_документов.xlsx")
NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def workbook_offers() -> set[str]:
    with zipfile.ZipFile(WORKBOOK) as archive:
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        shared = ["".join(t.text or "" for t in item.findall(".//a:t", NS))
                  for item in shared_root.findall("a:si", NS)]
        rels = {x.attrib["Id"]: x.attrib["Target"].lstrip("/")
                for x in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        sheet = next(x for x in book.findall("a:sheets/a:sheet", NS) if x.attrib["name"] == "Артикул-файл")
        root = ET.fromstring(archive.read(rels[sheet.attrib[f"{{{NS['r']}}}id"]]))
    offers = set()
    for row in root.findall("a:sheetData/a:row", NS):
        cells = {"".join(ch for ch in c.attrib["r"] if ch.isalpha()): c
                 for c in row.findall("a:c", NS)}
        if not all(col in cells for col in ("A", "B", "C")):
            continue
        def read(cell):
            value = cell.find("a:v", NS)
            text = value.text if value is not None else ""
            if cell.attrib.get("t") == "s" and text:
                text = shared[int(text)]
            elif cell.attrib.get("t") == "inlineStr":
                text = "".join(t.text or "" for t in cell.findall(".//a:t", NS))
            return text.strip()
        offer, article, title = (read(cells[col]) for col in ("A", "B", "C"))
        if offer and article and title and offer != "Артикул продавца":
            offers.add(offer.strip())
    return offers


def main() -> None:
    targets = workbook_offers()
    if len(targets) != 4232:
        raise RuntimeError(f"Expected 4,232 unique FERON workbook offers, got {len(targets)}")
    client = Client()
    rows: dict[str, dict] = {}
    seen_nmids: set[str] = set()
    duplicates = 0
    pages = 0
    cursor = {"limit": 100}
    started = now()
    complete = False

    def checkpoint(error: str | None = None) -> None:
        payload = {"started_at": started, "checked_at": now(), "complete": complete,
                   "pages": pages, "catalog_card_count": len(seen_nmids),
                   "duplicate_nmids": duplicates, "target_offer_count": len(targets),
                   "target_offers_found": len(rows), "cursor": cursor,
                   "cards_by_offer": rows}
        if error:
            payload["error"] = error
        save("feron_full_wb_snapshot_partial.json", payload)

    try:
        while True:
            response = None
            for attempt in range(8):
                response = client.http.post(
                    "https://content-api.wildberries.ru/content/v2/get/cards/list",
                    data=json.dumps({"settings": {"sort": {"ascending": True},
                                                   "cursor": cursor,
                                                   "filter": {"withPhoto": -1}}},
                                    ensure_ascii=False).encode(),
                    headers=client.wb_headers, timeout=(15, 120))
                if response.status_code not in (429, 500, 502, 503, 504):
                    break
                if attempt == 7:
                    raise RuntimeError(f"WB catalog retry limit exhausted ({response.status_code})")
                time.sleep(min(2 ** (attempt + 1), 30))
            if response is None or response.status_code != 200:
                raise RuntimeError(f"WB catalog HTTP {response.status_code if response else 'no response'}")
            body = response.json()
            batch = body.get("cards")
            page_cursor = body.get("cursor", {})
            if body.get("error") or not isinstance(batch, list) or page_cursor.get("total") != len(batch):
                raise RuntimeError("WB catalog page/cursor mismatch")
            pages += 1
            for card in batch:
                nm = str(card.get("nmID", ""))
                offer = str(card.get("vendorCode", ""))
                if not nm or not offer:
                    raise RuntimeError("WB card identity missing")
                if nm in seen_nmids:
                    duplicates += 1
                seen_nmids.add(nm)
                if offer in targets:
                    if offer in rows:
                        rows[offer]["duplicate_card_count"] = rows[offer].get("duplicate_card_count", 1) + 1
                        rows[offer].setdefault("duplicate_cards", []).append(card)
                    else:
                        rows[offer] = card
            if pages % 50 == 0:
                checkpoint()
                print(json.dumps({"pages": pages, "catalog_cards": len(seen_nmids),
                                  "target_offers_found": len(rows), "target_count": len(targets)},
                                 ensure_ascii=False), flush=True)
            if len(batch) < 100:
                complete = True
                break
            nxt = {k: page_cursor.get(k) for k in ("updatedAt", "nmID")}
            if not all(nxt.values()):
                raise RuntimeError("WB catalog cursor incomplete")
            cursor = {"limit": 100, **nxt}
            time.sleep(0.58)
    except Exception as exc:
        checkpoint(type(exc).__name__)
        raise

    if duplicates:
        raise RuntimeError(f"Duplicate nmID in full WB catalog: {duplicates}")
    missing = sorted(targets - set(rows))
    result = {"started_at": started, "checked_at": now(), "complete": True,
              "pages": pages, "catalog_card_count": len(seen_nmids), "duplicate_nmids": 0,
              "target_offer_count": len(targets), "target_offers_found": len(rows),
              "target_offers_missing": missing,
              "multiple_card_offers": sorted(k for k, v in rows.items() if v.get("duplicate_cards")),
              "cards_by_offer": rows}
    save("feron_full_wb_snapshot.json", result)
    print(json.dumps({"complete": True, "pages": pages, "catalog_cards": len(seen_nmids),
                      "feron_target_offers": len(targets), "found": len(rows),
                      "missing": len(missing), "multiple": len(result["multiple_card_offers"]),
                      "path": str(BASE / "feron_full_wb_snapshot.json")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
