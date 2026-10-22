"""Fresh, read-only Ozon/WB reconciliation for FERON 01315/22 and 53551/22."""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
import re
import subprocess
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from api_client import BASE, Client, digest, now, save
from network_bypass import SourceAddressAdapter

WORKBOOK = Path("/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron/Сопоставление_артикулов_и_файлов_документов.xlsx")
FERON = WORKBOOK.parent
NUMBERS = {
    "01315": "ЕАЭС RU C-CN.HB85.B.01315/22",
    "53551": "ЕАЭС N RU Д-CN.PA06.B.53551/22",
}
NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
CHAR_MAP = str.maketrans({
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
    "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
    "Ё": "E", "Э": "E", "Д": "D", "П": "P",
})


def norm(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper().translate(CHAR_MAP) if ch.isalnum())


def read_rows() -> dict[str, list[dict[str, str]]]:
    with zipfile.ZipFile(WORKBOOK) as archive:
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = {x.attrib["Id"]: x.attrib["Target"].lstrip("/")
                for x in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        shared = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        strings = ["".join(t.text or "" for t in si.findall(".//a:t", NS))
                   for si in shared.findall("a:si", NS)]
        sheet = next(x for x in book.findall("a:sheets/a:sheet", NS)
                     if x.attrib["name"] == "Артикул-файл")
        root = ET.fromstring(archive.read(rels[sheet.attrib[f"{{{NS['r']}}}id"]]))

    result = {key: [] for key in NUMBERS}
    for row in root.findall("a:sheetData/a:row", NS):
        values: dict[str, str] = {}
        for cell in row.findall("a:c", NS):
            col = "".join(ch for ch in cell.attrib["r"] if ch.isalpha())
            raw = cell.find("a:v", NS)
            value = raw.text if raw is not None else ""
            if cell.attrib.get("t") == "s" and value:
                value = strings[int(value)]
            elif cell.attrib.get("t") == "inlineStr":
                value = "".join(t.text or "" for t in cell.findall(".//a:t", NS))
            values[col] = value
        for key, number in NUMBERS.items():
            if norm(values.get("G")) == norm(number):
                result[key].append({"offer_id": values.get("A", "").strip(),
                                    "feron_article": values.get("B", "").strip(),
                                    "name": values.get("C", "").strip(),
                                    "workbook_product_id": values.get("D", "").strip(),
                                    "workbook_sku": values.get("E", "").strip(),
                                    "number": values.get("G", "").strip(),
                                    "file_in_offer": values.get("H", "").strip(),
                                    "original_name": values.get("R", "").strip(),
                                    "registry_and_scan_dates": values.get("K", "").strip(),
                                    "registry_status": values.get("M", "").strip(),
                                    "applicability": values.get("N", "").strip(),
                                    "manual_check": values.get("O", "").strip(),
                                    "source": values.get("P", "").strip()})
    return result


def wb_session(client: Client):
    config = (BASE.parents[1] / "Shared_Настройки.js").read_text(encoding="utf-8")
    block = config.split("const wbHeaders", 1)[1].split("};", 1)[0]
    token = re.search(r"Authorization\s*:\s*['\"]([^'\"]+)['\"]", block)[1]
    session = requests.Session()
    session.trust_env = False
    for iface in ("en1", "en0"):
        info = subprocess.run(["ifconfig", iface], capture_output=True, text=True).stdout
        ip = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", info)
        if ip and "status: active" in info:
            session.mount("https://", SourceAddressAdapter(ip.group(1), interface_name=iface))
            break
    else:
        raise RuntimeError("Active physical interface unavailable")
    return session, {"Authorization": token, "Content-Type": "application/json"}


def ozon_certificates(client: Client) -> list[dict]:
    all_items: list[dict] = []
    page = 1
    while page <= 100:
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100})["result"]
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Invalid certificate list page")
        all_items.extend(batch)
        if len(batch) < 100:
            return all_items
        page += 1
    raise RuntimeError("Certificate list pagination limit exceeded")


def ozon_bindings(client: Client, cert_id: int) -> list[dict]:
    all_items: list[dict] = []
    last_id = 0
    count_expected = None
    while True:
        result = client.call("ozon", "/v1/product/certificate/products/list",
                             {"certificate_id": cert_id, "limit": 500,
                              "last_id": last_id})["result"]
        batch, count = result.get("items"), result.get("count")
        if not isinstance(batch, list) or not isinstance(count, int):
            raise RuntimeError("Invalid certificate binding page")
        if count_expected is None:
            count_expected = count
        elif count != count_expected:
            raise RuntimeError("Binding count changed during read")
        all_items.extend(batch)
        if len(all_items) == count_expected:
            if len({str(x.get("sku")) for x in all_items}) != len(all_items):
                raise RuntimeError("Duplicate Ozon SKU binding")
            return all_items
        if not batch or len(all_items) > count_expected:
            raise RuntimeError("Incomplete Ozon binding read")
        cursor = int(batch[-1].get("product_id", 0))
        if cursor <= last_id:
            raise RuntimeError("Ozon binding cursor failed to advance")
        last_id = cursor


def wb_body(session, headers, path: str, payload: dict) -> dict:
    response = session.post("https://content-api.wildberries.ru" + path,
                            headers=headers, json=payload, timeout=(15, 120))
    if response.status_code != 200:
        raise RuntimeError(f"WB {path}: HTTP {response.status_code}")
    body = response.json()
    if body.get("error"):
        raise RuntimeError(f"WB {path}: API error")
    return body


def main() -> None:
    started = now()
    rows = read_rows()
    targets = {key: {r["offer_id"]: r for r in group} for key, group in rows.items()}
    if any(len(group) != 289 or len(targets[key]) != 289 for key, group in rows.items()):
        raise RuntimeError("Workbook document rows/offer IDs changed; stop for review")
    common = set(targets["01315"]) & set(targets["53551"])
    if common != set(targets["01315"]) or set(targets["01315"]) != set(targets["53551"]):
        raise RuntimeError("01315 and 53551 workbook targets differ; stop for review")

    client = Client()
    offer_ids = sorted(common)
    live_products: dict[str, dict] = {}
    for offset in range(0, len(offer_ids), 100):
        batch = offer_ids[offset:offset + 100]
        response = client.call("ozon", "/v3/product/info/list", {"offer_id": batch})
        items = response.get("items") or response.get("result", {}).get("items")
        if not isinstance(items, list):
            raise RuntimeError(f"Unexpected product info response at {offset}")
        for item in items:
            offer = str(item.get("offer_id", ""))
            if not offer or offer in live_products:
                raise RuntimeError("Missing/duplicate live Ozon offer identity")
            live_products[offer] = {"product_id": str(item.get("id", "")),
                                    "sku": str(item.get("sku", "")),
                                    "is_archived": item.get("is_archived"),
                                    "name": item.get("name")}
    missing_products = sorted(set(offer_ids) - set(live_products))
    mismatches = {}
    for offer in offer_ids:
        if offer not in live_products:
            continue
        expected = targets["01315"][offer]
        actual = live_products[offer]
        if (expected["workbook_product_id"] != actual["product_id"] or
                expected["workbook_sku"] != actual["sku"]):
            mismatches[offer] = {"workbook": expected, "live": actual}

    certificates = ozon_certificates(client)
    matches = {}
    binding_evidence = {}
    for key, number in NUMBERS.items():
        exact = [c for c in certificates if norm(c.get("certificate_number")) == norm(number)]
        substring = [c for c in certificates if norm(number) in norm(c.get("certificate_number"))]
        matches[key] = {"exact_count": len(exact), "substring_count": len(substring),
                        "records": exact or substring}
        if len(exact) == 1:
            binding_evidence[key] = ozon_bindings(client, int(exact[0]["certificate_id"]))

    session, headers = wb_session(client)
    wb_cards: dict[str, list[dict]] = collections.defaultdict(list)
    all_nmids: set[str] = set()
    duplicate_nmids = 0
    pages = 0
    cursor = {"limit": 100}
    wb_started = now()
    while True:
        body = wb_body(session, headers, "/content/v2/get/cards/list",
                       {"settings": {"sort": {"ascending": True}, "cursor": cursor,
                                      "filter": {"withPhoto": -1}}})
        batch = body.get("cards")
        returned = body.get("cursor", {})
        if not isinstance(batch, list) or returned.get("total") != len(batch):
            raise RuntimeError("WB card-list page/cursor mismatch")
        pages += 1
        for card in batch:
            nm_id = str(card.get("nmID", ""))
            offer = str(card.get("vendorCode", ""))
            if not nm_id or not offer:
                raise RuntimeError("WB card identity missing")
            if nm_id in all_nmids:
                duplicate_nmids += 1
            all_nmids.add(nm_id)
            if offer in common:
                wb_cards[offer].append(card)
        if len(batch) < 100:
            break
        nxt = {k: returned.get(k) for k in ("updatedAt", "nmID")}
        if not all(nxt.values()):
            raise RuntimeError("WB cursor incomplete")
        cursor = {"limit": 100, **nxt}
        if pages % 50 == 0:
            save("feron_01315_53551_live_preflight_partial.json", {
                "started_at": started, "wb_started_at": wb_started, "wb_pages": pages,
                "wb_target_offers_seen": len(wb_cards), "complete": False})
        time.sleep(0.58)
    if duplicate_nmids:
        raise RuntimeError("Duplicate WB nmID in full catalog")

    trash_cards: list[dict] = []
    trash_pages = 0
    trash_cursor = {"limit": 100}
    while True:
        body = wb_body(session, headers, "/content/v2/get/cards/trash",
                       {"settings": {"sort": {"ascending": True}, "cursor": trash_cursor}})
        data = body.get("data", body)
        items = (data.get("cards") or data.get("items") or []) if isinstance(data, dict) else []
        cursor_data = data.get("cursor", {}) if isinstance(data, dict) else {}
        if not isinstance(items, list):
            raise RuntimeError("WB trash response missing items")
        trash_cards.extend(items)
        trash_pages += 1
        if len(items) < 100:
            break
        nxt = {k: cursor_data.get(k) for k in ("trashedAt", "nmID")}
        if not all(nxt.values()):
            raise RuntimeError("WB trash cursor incomplete")
        trash_cursor = {"limit": 100, **nxt}
        time.sleep(0.58)

    card_results = {}
    for offer in offer_ids:
        exact_cards = wb_cards.get(offer, [])
        card_results[offer] = []
        for card in exact_cards:
            docs = card.get("documents") or {}
            items = docs.get("items") or []
            per_number = {}
            for key, number in NUMBERS.items():
                exact_docs = [x for x in items if norm(x.get("number")) == norm(number)]
                per_number[key] = [{"type": x.get("type"), "number": x.get("number"),
                                    "startDate": x.get("startDate"), "endDate": x.get("endDate"),
                                    "verdict": x.get("verdict")} for x in exact_docs]
            card_results[offer].append({"nmID": str(card.get("nmID")), "imtID": card.get("imtID"),
                                        "brand": card.get("brand"), "title": card.get("title"),
                                        "documents_excluded": docs.get("excludeDocuments"),
                                        "overallVerdict": docs.get("overallVerdict"),
                                        "documents": per_number})
    trash_matches = [c for c in trash_cards if str(c.get("vendorCode", "")) in common]

    output = {
        "started_at": started, "checked_at": now(), "workbook": str(WORKBOOK),
        "workbook_targets": {key: {"number": NUMBERS[key], "rows": len(rows[key]),
                                   "offers": sorted(targets[key]),
                                   "manual_check_values": sorted({r["manual_check"] for r in rows[key]}),
                                   "registry_and_scan_dates": sorted({r["registry_and_scan_dates"] for r in rows[key]}),
                                   "status_values": sorted({r["registry_status"] for r in rows[key]}),
                                   "source_values": sorted({r["source"] for r in rows[key]}),
                                   "offer_copies": [{"offer": r["offer_id"], "file": r["file_in_offer"],
                                                     "original_name": r["original_name"]} for r in rows[key]]}
                             for key in NUMBERS},
        "ozon": {"product_offer_count": len(live_products), "product_missing_offers": missing_products,
                 "identity_mismatches": mismatches, "archived_count": sum(bool(x.get("is_archived")) for x in live_products.values()),
                 "certificates_list_count": len(certificates), "matching_certificates": matches,
                 "binding_readbacks": {key: {"count": len(items), "statuses": dict(collections.Counter(
                     str(x.get("product_status_code")) for x in items)),
                     "skus": sorted(str(x.get("sku")) for x in items),
                     "product_ids": sorted(str(x.get("product_id")) for x in items)}
                     for key, items in binding_evidence.items()}},
        "wildberries": {"catalog_started_at": wb_started, "catalog_checked_at": now(),
                        "complete_catalog_read": True, "pages": pages, "catalog_cards": len(all_nmids),
                        "duplicate_nmids": duplicate_nmids,
                        "target_offers_found": len(wb_cards),
                        "target_offers_missing": sorted(set(offer_ids) - set(wb_cards)),
                        "target_offers_multiple_cards": sorted(o for o, c in wb_cards.items() if len(c) != 1),
                        "target_cards": card_results,
                        "trash_complete": True, "trash_pages": trash_pages,
                        "cards_in_trash": len(trash_cards),
                        "target_offers_in_trash": sorted({str(c.get("vendorCode")) for c in trash_matches})},
    }
    save("feron_01315_53551_live_preflight.json", output)
    summary = {"checked_at": output["checked_at"],
               "workbook_targets": {k: len(v) for k, v in targets.items()},
               "ozon_products": len(live_products), "ozon_identity_mismatches": len(mismatches),
               "ozon_records": {k: {"exact": v["exact_count"], "substring": v["substring_count"]}
                                for k, v in matches.items()},
               "wb_pages": pages, "wb_catalog_cards": len(all_nmids),
               "wb_target_offers_found": len(wb_cards),
               "wb_target_offers_missing": len(output["wildberries"]["target_offers_missing"]),
               "wb_target_offers_in_trash": len(output["wildberries"]["target_offers_in_trash"]),
               "path": str(BASE / "feron_01315_53551_live_preflight.json")}
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
