"""Build a fresh, exact Ozon bind plan for FERON certificate 01381/22."""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path(__file__).resolve().parent
FERON = Path("/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron")
WORKBOOK = FERON / "Сопоставление_артикулов_и_файлов_документов.xlsx"
ORIGINALS = FERON / "00_Оригиналы_файлов"
NUMBER = "ЕАЭС RU C-CN.HB85.B.01381/22"
FILE_NAME = "Сертификат__01381_Лампы_светодиодные_тм_Feron,_серия_LB._Сертификат_по_004_и_020_1__0022cee06f.pdf"
FILE_SHA256 = "0022cee06f811dfc5f32f69ecc042b00a10f7c7eb8e64930bcd66ce725ee60ce"
REGISTRY_URL = "https://pub.fsa.gov.ru/rss/certificate/view/3139470/baseInfo"
NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
sys.path.insert(0, str(BASE))
from api_client import Client, digest, now, save  # noqa: E402


def norm(value: object) -> str:
    tr = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
                       "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
                       "Ё": "E", "Э": "E", "Д": "D", "П": "P"})
    return "".join(ch for ch in str(value or "").upper().translate(tr) if ch.isalnum())


def read_rows() -> list[dict[str, str]]:
    with zipfile.ZipFile(WORKBOOK) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = {
            item.attrib["Id"]: item.attrib["Target"].lstrip("/")
            for item in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }
        strings = [
            "".join(part.text or "" for part in item.findall(".//a:t", NS))
            for item in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("a:si", NS)
        ]
        sheet = next(item for item in workbook.findall("a:sheets/a:sheet", NS)
                     if item.attrib["name"] == "Артикул-файл")
        root = ET.fromstring(archive.read(rels[sheet.attrib[f"{{{NS['r']}}}id"]]))
    out = []
    for row in root.findall("a:sheetData/a:row", NS):
        values: dict[str, str] = {}
        for cell in row.findall("a:c", NS):
            column = "".join(ch for ch in cell.attrib["r"] if ch.isalpha())
            node = cell.find("a:v", NS)
            value = node.text if node is not None else ""
            if cell.attrib.get("t") == "s" and value:
                value = strings[int(value)]
            elif cell.attrib.get("t") == "inlineStr":
                value = "".join(part.text or "" for part in cell.findall(".//a:t", NS))
            values[column] = value
        if norm(NUMBER) == norm(values.get("G", "")) or "01381" in values.get("G", ""):
            out.append(values)
    return out


def live_products(client: Client, rows: list[dict[str, str]]) -> dict[str, dict]:
    expected = {row["A"]: row for row in rows}
    actual: dict[str, dict] = {}
    offers = sorted(expected)
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        body = client.call("ozon", "/v3/product/info/list", {"offer_id": batch})
        items = body.get("items") or body.get("result", {}).get("items")
        if not isinstance(items, list):
            raise RuntimeError(f"Unexpected Ozon info response at batch {start // 100 + 1}")
        for item in items:
            offer = str(item.get("offer_id", ""))
            if not offer or offer in actual:
                raise RuntimeError(f"Missing or duplicate live offer {offer!r}")
            actual[offer] = {
                "product_id": str(item.get("id", "")),
                "sku": str(item.get("sku", "")),
                "is_archived": bool(item.get("is_archived")),
                "name": item.get("name"),
            }
    if set(actual) != set(expected):
        raise RuntimeError(f"Live offer set mismatch: missing={len(set(expected)-set(actual))}, extra={len(set(actual)-set(expected))}")
    for offer, row in expected.items():
        got = actual[offer]
        if got["product_id"] != row["D"] or got["sku"] != row["E"] or got["is_archived"]:
            raise RuntimeError(f"Ozon identity/archive mismatch for {offer}: workbook {row['D']}/{row['E']}, live {got}")
    return actual


def list_certificates(client: Client) -> list[dict]:
    items = []
    page = 1
    seen = set()
    while page <= 100:
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})["result"]
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError(f"Missing certificate list page {page}")
        ids = [str(item.get("certificate_id")) for item in batch]
        if any(identifier in seen for identifier in ids):
            raise RuntimeError(f"Duplicate certificate ID on page {page}")
        seen.update(ids)
        items.extend(batch)
        if len(batch) < 100:
            return items
        page += 1
    raise RuntimeError("Certificate list page limit exceeded")


def bindings(client: Client, certificate_id: int) -> list[dict]:
    result = []
    last_id = 0
    page_size = 500
    expected_count = None
    while True:
        page = client.call("ozon", "/v1/product/certificate/products/list", {
            "certificate_id": certificate_id, "limit": page_size, "last_id": last_id,
        })["result"]
        batch = page.get("items")
        count = page.get("count")
        if not isinstance(batch, list) or not isinstance(count, int):
            raise RuntimeError(f"Invalid binding list for certificate {certificate_id}")
        if expected_count is None:
            expected_count = count
        elif count != expected_count:
            raise RuntimeError(f"Ozon binding count changed during pagination for certificate {certificate_id}")
        result.extend(batch)
        if len(result) == expected_count:
            if len({str(item.get("sku")) for item in result}) != len(result):
                raise RuntimeError(f"Duplicate SKU bindings on certificate {certificate_id}")
            return result
        if not batch or len(result) > expected_count:
            raise RuntimeError(f"Incomplete binding list for certificate {certificate_id}")
        next_last_id = int(batch[-1].get("product_id", 0))
        if next_last_id <= last_id:
            raise RuntimeError(f"Ozon last_id did not advance for certificate {certificate_id}")
        last_id = next_last_id


def main() -> None:
    if (BASE / "feron_01381_execution.json").exists():
        raise RuntimeError("An execution journal already exists; reconcile it before rebuilding")
    if not WORKBOOK.is_file() or not ORIGINALS.is_dir():
        raise RuntimeError("FERON workbook or original-file folder is unavailable")
    rows = read_rows()
    if any(norm(row.get("G", "").split(";", 1)[0]) != norm(NUMBER) for row in rows):
        raise RuntimeError("Workbook contains a visually similar but non-identical 01381 number; inspect manually")
    # Only active, primary-registry rows with an explicit product-scope evidence level are eligible.
    eligible = [row for row in rows if row.get("J") == "Основной реестр"
                and row.get("K", "").startswith("Действует в ФСА до 2027-09-07")
                and row.get("M", "").startswith("Действует;") and not row.get("O")
                and row.get("N") in {"карточка Feron", "серия/модель",
                                     "серия/модель прямо указана в официальном скане и каталоге Feron"}
                and "Feron" in row.get("P", "") and "01381" in row.get("P", "")]
    excluded = [row for row in rows if row not in eligible]
    if len(rows) != 1183 or len(eligible) != 1182 or len(excluded) != 1:
        raise RuntimeError(f"Unexpected workbook scope: all={len(rows)}, eligible={len(eligible)}, excluded={len(excluded)}")
    if len({row["A"] for row in eligible}) != len(eligible) or len({row["E"] for row in eligible}) != len(eligible):
        raise RuntimeError("Duplicate offer or SKU in exact eligible rows")
    local_file = ORIGINALS / FILE_NAME
    if digest(local_file) != FILE_SHA256:
        raise RuntimeError("Original certificate SHA-256 does not match verified source")
    workbook_hash = digest(WORKBOOK)
    client = Client()
    products = live_products(client, eligible)
    all_certs = list_certificates(client)
    matching = [item for item in all_certs if item.get("type_code") == "certificate_of_conformity"
                and norm(item.get("certificate_number")) == norm(NUMBER)]
    if not matching or any(item.get("status_code") != "approved" for item in matching):
        raise RuntimeError("Matching Ozon records are missing or not all approved; do not create another record")
    if any(item.get("issue_date", "")[:10] != "2022-09-08" or item.get("expire_date", "")[:10] != "2027-09-07"
           for item in matching):
        raise RuntimeError("Ozon record dates conflict with the verified certificate")
    full_bindings = {str(item["certificate_id"]): bindings(client, int(item["certificate_id"])) for item in matching}
    targets = {str(row["E"]): str(row["D"]) for row in eligible}
    existing: dict[str, dict] = {}
    for cert in matching:
        for item in full_bindings[str(cert["certificate_id"])]:
            sku = str(item.get("sku", ""))
            if sku in targets:
                existing.setdefault(sku, {"certificate_id": str(cert["certificate_id"]),
                                          "product_id": str(item.get("product_id", "")),
                                          "product_status_code": item.get("product_status_code")})
                if str(item.get("product_id", "")) != targets[sku]:
                    raise RuntimeError(f"Existing certificate binding identity conflict for SKU {sku}")
    missing = sorted(set(targets) - set(existing))
    target_products = {str(v["product_id"]): v for v in products.values()}
    by_id = {str(row["D"]): row for row in eligible}
    if set(target_products) != set(by_id):
        raise RuntimeError("Product identity map is not one-to-one")
    best = max(matching, key=lambda item: (sum(
        1 for b in full_bindings[str(item["certificate_id"])] if str(b.get("sku")) in targets
    ), int(item["certificate_id"])))
    plan = {
        "planned_at": now(),
        "number": NUMBER,
        "type": "certificate_of_conformity",
        "issue_date": "2022-09-08",
        "expire_date": "2027-09-07",
        "registry_url": REGISTRY_URL,
        "registry_state_evidence": "Active in FSA; application lists Feron LED light sources, trademark Feron, series/type LB; verified in prior live registry review on 2026-10-12.",
        "workbook": str(WORKBOOK),
        "workbook_sha256": workbook_hash,
        "workbook_rows_for_document": len(rows),
        "eligible_offer_count": len(eligible),
        "excluded_rows": [{"offer": row.get("A"), "feron_article": row.get("B"),
                           "product_id": row.get("D"), "sku": row.get("E"),
                           "reason": row.get("K"), "link_level": row.get("J"),
                           "scope_level": row.get("N"), "manual_review": row.get("O")}
                          for row in excluded],
        "original_file": str(local_file),
        "original_file_sha256": FILE_SHA256,
        "original_file_size": local_file.stat().st_size,
        "source_url": "https://feron.ru/postup/certificate/01381",
        "offer_to_identity": {offer: {"product_id": data["product_id"], "sku": data["sku"],
                                        "is_archived": data["is_archived"], "name": data["name"]}
                              for offer, data in products.items()},
        "target_offer_to_sku": {row["A"]: str(row["E"]) for row in eligible},
        "target_sku_to_product_id": targets,
        "matching_existing_records": [{"certificate_id": str(item["certificate_id"]),
                                        "status_code": item["status_code"],
                                        "issue_date": item["issue_date"], "expire_date": item["expire_date"],
                                        "live_binding_count": len(full_bindings[str(item["certificate_id"])])}
                                       for item in matching],
        "existing_target_bindings": existing,
        "existing_target_binding_count": len(existing),
        "already_approved_target_bindings": sum(v["product_status_code"] == "approved" for v in existing.values()),
        "missing_skus": missing,
        "selected_certificate_id": str(best["certificate_id"]),
        "fresh_product_info_checked_at": now(),
        "fresh_certificate_listing_checked_at": now(),
    }
    save("feron_01381_plan.json", plan)
    print(json.dumps({"eligible": len(eligible), "excluded": len(excluded), "existing_records": len(matching),
                      "already_linked": len(existing), "already_approved": plan["already_approved_target_bindings"],
                      "missing_to_bind": len(missing), "certificate_id": plan["selected_certificate_id"],
                      "file_sha256": FILE_SHA256}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
