"""Read-only exact Ozon identity reconciliation for four previously bound Feron docs."""
from __future__ import annotations

import collections
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
FERON = Path("/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron")
WORKBOOK = FERON / "Сопоставление_артикулов_и_файлов_документов.xlsx"
NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
sys.path.insert(0, str(BASE))
from api_client import Client, now, save  # noqa: E402

CASES = {
    "04998/22": {"certificate_id": 5609331, "number": "ЕАЭС RU С-CN.НА46.В.04998/22", "expected_count": 300},
    "53525/22": {"certificate_id": 5423327, "number": "ЕАЭС N RU Д-CN.РА06.В.53525/22", "expected_count": 254},
    "87137/22": {"certificate_id": 5608768, "number": "ЕАЭС N RU Д-CN.РА02.В.87137/22", "expected_count": 1210},
    "87180/22": {"certificate_id": 5609253, "number": "ЕАЭС N RU Д-CN.РА02.В.87180/22", "expected_count": 301},
}


def cell_column(cell_ref: str) -> str:
    return "".join(ch for ch in cell_ref if ch.isalpha())


def workbook_targets() -> tuple[dict[str, list[dict[str, str]]], list[dict[str, str]]]:
    with zipfile.ZipFile(WORKBOOK) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = {
            item.attrib["Id"]: item.attrib["Target"].lstrip("/")
            for item in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }
        shared = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        strings = ["".join(part.text or "" for part in item.findall(".//a:t", NS))
                   for item in shared.findall("a:si", NS)]
        sheet = next(item for item in workbook.findall("a:sheets/a:sheet", NS)
                     if item.attrib["name"] == "Артикул-файл")
        sheet_path = rels[sheet.attrib[f"{{{NS['r']}}}id"]]
        root = ET.fromstring(archive.read(sheet_path))

    result = {suffix: [] for suffix in CASES}
    excluded_candidates: list[dict[str, str]] = []
    for row in root.findall("a:sheetData/a:row", NS):
        values: dict[str, str] = {}
        for cell in row.findall("a:c", NS):
            column = cell_column(cell.attrib["r"])
            node = cell.find("a:v", NS)
            value = node.text if node is not None else ""
            if cell.attrib.get("t") == "s" and value:
                value = strings[int(value)]
            elif cell.attrib.get("t") == "inlineStr":
                value = "".join(part.text or "" for part in cell.findall(".//a:t", NS))
            values[column] = value
        number = values.get("G", "")
        for suffix in result:
            if suffix in number:
                offer, product_id, sku = (values.get(col, "").strip() for col in ("A", "D", "E"))
                if offer and product_id and sku and "Кандидат" in values.get("H", ""):
                    excluded_candidates.append({"suffix": suffix, "offer_id": offer,
                                                "product_id": product_id, "sku": sku,
                                                "basis": values.get("H", "")})
                elif offer and product_id and sku:
                    result[suffix].append({"offer_id": offer, "product_id": product_id, "sku": sku})

    for suffix, case in CASES.items():
        rows = result[suffix]
        if len(rows) != case["expected_count"]:
            raise RuntimeError(f"Workbook target count for {suffix}: expected {case['expected_count']}, got {len(rows)}")
        for key in ("offer_id", "product_id", "sku"):
            if len({item[key] for item in rows}) != len(rows):
                raise RuntimeError(f"Duplicate workbook {key} for {suffix}")
    return result, excluded_candidates


def live_products(client: Client, targets: list[dict[str, str]]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    offers = [x["offer_id"] for x in targets]
    for start in range(0, len(offers), 100):
        body = client.call("ozon", "/v3/product/info/list", {"offer_id": offers[start:start + 100]})
        items = body.get("items") or body.get("result", {}).get("items")
        if not isinstance(items, list):
            raise RuntimeError("Unexpected Ozon product-info response")
        for item in items:
            offer = str(item.get("offer_id", ""))
            if not offer or offer in result:
                raise RuntimeError("Ozon product-info returned a missing or repeated offer")
            result[offer] = {"product_id": str(item.get("id", "")),
                             "sku": str(item.get("sku", "")),
                             "is_archived": bool(item.get("is_archived"))}
    if set(result) != set(offers):
        raise RuntimeError(f"Live product-info offer set mismatch: {len(set(offers)-set(result))} missing, {len(set(result)-set(offers))} extra")
    return result


def main() -> None:
    targets_by_case, excluded_candidates = workbook_targets()
    client = Client()
    audit = {"checked_at_utc": now(), "read_only": True,
             "source_workbook": str(WORKBOOK),
             "excluded_candidate_rows": excluded_candidates, "cases": []}
    for suffix, case in CASES.items():
        targets = targets_by_case[suffix]
        products = live_products(client, targets)
        identity_mismatches = [
            {"offer_id": target["offer_id"], "workbook_product_id": target["product_id"],
             "live_product_id": products[target["offer_id"]]["product_id"],
             "workbook_sku": target["sku"], "live_sku": products[target["offer_id"]]["sku"]}
            for target in targets
            if target["product_id"] != products[target["offer_id"]]["product_id"]
            or target["sku"] != products[target["offer_id"]]["sku"]
        ]
        info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": case["number"]}).get("result")
        if not isinstance(info, dict) or str(info.get("certificate_id")) != str(case["certificate_id"]):
            raise RuntimeError(f"Ozon certificate identity mismatch for {suffix}")
        bindings = client.ozon_bindings(case["certificate_id"])
        target_by_pair = {(x["sku"], x["product_id"]): x["offer_id"] for x in targets}
        live_by_pair: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
        for binding in bindings:
            live_by_pair[(str(binding.get("sku", "")), str(binding.get("product_id", "")))].append(binding)
        missing_pairs = sorted(set(target_by_pair) - set(live_by_pair))
        unexpected_pairs = sorted(set(live_by_pair) - set(target_by_pair))
        duplicate_pairs = [pair for pair, rows in live_by_pair.items() if len(rows) != 1]
        statuses = collections.Counter(str(x.get("product_status_code") or "MISSING") for x in bindings)
        audit["cases"].append({
            "suffix": suffix, "certificate_id": case["certificate_id"],
            "number_queried": case["number"], "stored_number": info.get("certificate_number"),
            "record_status": info.get("status_code"), "type_code": info.get("type_code"),
            "issue_date": info.get("issue_date"), "expire_date": info.get("expire_date"),
            "workbook_target_count": len(targets), "live_product_info_count": len(products),
            "live_product_identity_mismatch_count": len(identity_mismatches),
            "live_product_identity_mismatches": identity_mismatches,
            "binding_count": len(bindings), "binding_status_counts": dict(statuses),
            "missing_target_pairs": [{"offer_id": target_by_pair[pair], "sku": pair[0], "product_id": pair[1]}
                                      for pair in missing_pairs],
            "unexpected_live_pairs": [{"sku": pair[0], "product_id": pair[1],
                                        "binding_count": len(live_by_pair[pair])}
                                       for pair in unexpected_pairs],
            "duplicate_live_pairs": [{"sku": pair[0], "product_id": pair[1]}
                                     for pair in duplicate_pairs],
            "exact_target_set_matches": not identity_mismatches and not missing_pairs
                and not unexpected_pairs and not duplicate_pairs and len(bindings) == len(targets),
            "bindings": [{"sku": str(x.get("sku")), "product_id": str(x.get("product_id")),
                          "status": x.get("product_status_code")} for x in bindings],
        })
        save("fresh_exact_ozon_identity_audit_20261013.json", audit)
        last = audit["cases"][-1]
        print(json.dumps({k: v for k, v in last.items() if k != "bindings"}, ensure_ascii=False), flush=True)
    save("fresh_exact_ozon_identity_audit_20261013.json", audit)
    print("SAVED", BASE / "fresh_exact_ozon_identity_audit_20261013.json", flush=True)


if __name__ == "__main__":
    main()
