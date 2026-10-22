"""Reconcile Feron workbook number variants to approved Ozon records on both platforms."""
from __future__ import annotations

import collections
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from api_client import Client, now, save  # noqa: E402

WORKBOOK = Path("/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron/Сопоставление_артикулов_и_файлов_документов.xlsx")
NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
CASES = {
    "02586/26": {"certificate_id": 5423319, "number": "ЕАЭС N RU Д-CN.РА08.В.02586/26", "target_count": 5, "type": 2},
    "87159/22": {"certificate_id": 5423280, "number": "ЕАЭС N RU Д-CN.РА02.В.87159/22", "target_count": 7, "type": 2},
    "78189/24": {"certificate_id": 5423331, "number": "ЕАЭС N RU Д-RU.РА02.В.78189/24", "target_count": 24, "type": 2},
    "33655/22": {"certificate_id": 5423333, "number": "ЕАЭС N RU Д-RU.РА05.В.33655/22", "target_count": 2, "type": 2},
}


def workbook_targets() -> dict[str, list[dict[str, str]]]:
    with zipfile.ZipFile(WORKBOOK) as archive:
        wb = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = {x.attrib["Id"]: x.attrib["Target"].lstrip("/")
                for x in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        ss_xml = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        strings = ["".join(t.text or "" for t in x.findall(".//a:t", NS))
                   for x in ss_xml.findall("a:si", NS)]
        sheet = next(x for x in wb.findall("a:sheets/a:sheet", NS) if x.attrib["name"] == "Артикул-файл")
        root = ET.fromstring(archive.read(rels[sheet.attrib[f"{{{NS['r']}}}id"]]))
    result = {suffix: [] for suffix in CASES}
    for row in root.findall("a:sheetData/a:row", NS):
        values = {}
        for cell in row.findall("a:c", NS):
            col = "".join(ch for ch in cell.attrib["r"] if ch.isalpha())
            node = cell.find("a:v", NS)
            value = node.text if node is not None else ""
            if cell.attrib.get("t") == "s" and value:
                value = strings[int(value)]
            elif cell.attrib.get("t") == "inlineStr":
                value = "".join(t.text or "" for t in cell.findall(".//a:t", NS))
            values[col] = value
        for suffix in result:
            if suffix in values.get("G", "") and values.get("A"):
                result[suffix].append({"offer_id": values["A"], "product_id": values.get("D", ""),
                                       "sku": values.get("E", ""), "name": values.get("C", ""),
                                       "workbook_number": values.get("G", "")})
    for suffix, case in CASES.items():
        rows = result[suffix]
        if len(rows) != case["target_count"] or len({x["offer_id"] for x in rows}) != len(rows):
            raise RuntimeError(f"Workbook target scope mismatch for {suffix}: {len(rows)}")
    return result


def main() -> None:
    target_groups = workbook_targets()
    client = Client()
    result = {"checked_at_utc": now(), "read_only": True,
              "source_workbook": str(WORKBOOK), "groups": []}
    for suffix, case in CASES.items():
        targets = target_groups[suffix]
        offers = [x["offer_id"] for x in targets]
        product_info = client.call("ozon", "/v3/product/info/list", {"offer_id": offers})
        products = product_info.get("items") or product_info.get("result", {}).get("items")
        if not isinstance(products, list):
            raise RuntimeError(f"Unexpected Ozon product info response for {suffix}")
        live_products = {str(x.get("offer_id")): {"product_id": str(x.get("id")), "sku": str(x.get("sku"))}
                         for x in products}
        identity_errors = [{"offer_id": x["offer_id"], "workbook_product_id": x["product_id"],
                            "live_product_id": live_products.get(x["offer_id"], {}).get("product_id"),
                            "workbook_sku": x["sku"], "live_sku": live_products.get(x["offer_id"], {}).get("sku")}
                           for x in targets if live_products.get(x["offer_id"], {}).get("product_id") != x["product_id"]
                           or live_products.get(x["offer_id"], {}).get("sku") != x["sku"]]
        info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": case["number"]}).get("result")
        if not isinstance(info, dict) or str(info.get("certificate_id")) != str(case["certificate_id"]):
            raise RuntimeError(f"Certificate identity mismatch for {suffix}")
        bindings = client.ozon_bindings(case["certificate_id"])
        target_pairs = {(x["sku"], x["product_id"]): x["offer_id"] for x in targets}
        live_pairs: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
        for row in bindings:
            live_pairs[(str(row.get("sku", "")), str(row.get("product_id", "")))].append(row)
        missing_pairs = set(target_pairs) - set(live_pairs)
        extra_pairs = set(live_pairs) - set(target_pairs)
        wb_rows = []
        for target in targets:
            cards = client.wb_cards(target["offer_id"])
            matches = []
            for card in cards:
                if card.get("vendorCode") != target["offer_id"]:
                    continue
                docs = (card.get("documents") or {}).get("items") or []
                matching_docs = [doc for doc in docs if str(case["number"].split("/")[-1]) in str(doc.get("number", ""))
                                 and int(doc.get("type", -1)) == case["type"]]
                matches.append({"nmID": str(card.get("nmID")), "brand": card.get("brand"),
                                "title": card.get("title"), "documents": matching_docs,
                                "document_count": len(matching_docs),
                                "card_fully_checked": (card.get("documents") or {}).get("overallVerdict", {}).get("isFullyChecked"),
                                "card_status": (card.get("documents") or {}).get("overallVerdict", {}).get("status")})
            wb_rows.append({"offer_id": target["offer_id"], "exact_card_count": len(matches), "cards": matches})
        status_counts = collections.Counter(str(x.get("product_status_code") or "MISSING") for x in bindings)
        wb_doc_statuses = collections.Counter(
            f"{doc.get('verdict', {}).get('status')}:{doc.get('verdict', {}).get('reason')}"
            for row in wb_rows for card in row["cards"] for doc in card["documents"])
        group = {
            "suffix": suffix, "certificate_id": case["certificate_id"],
            "workbook_target_count": len(targets), "ozon_number": info.get("certificate_number"),
            "ozon_record_status": info.get("status_code"), "ozon_type": info.get("type_code"),
            "ozon_issue_date": info.get("issue_date"), "ozon_expire_date": info.get("expire_date"),
            "ozon_live_product_count": len(live_products), "ozon_identity_errors": identity_errors,
            "ozon_binding_count": len(bindings), "ozon_binding_status_counts": dict(status_counts),
            "ozon_missing_pairs": [{"offer_id": target_pairs[p], "sku": p[0], "product_id": p[1]}
                                   for p in sorted(missing_pairs)],
            "ozon_unexpected_pairs": [{"sku": p[0], "product_id": p[1]} for p in sorted(extra_pairs)],
            "ozon_exact_target_set_matches": not identity_errors and not missing_pairs and not extra_pairs
                and len(bindings) == len(targets),
            "wb_exact_card_count": sum(x["exact_card_count"] == 1 for x in wb_rows),
            "wb_missing_cards": [x["offer_id"] for x in wb_rows if x["exact_card_count"] == 0],
            "wb_duplicate_cards": [{"offer_id": x["offer_id"], "nmIDs": [c["nmID"] for c in x["cards"]]}
                                   for x in wb_rows if x["exact_card_count"] > 1],
            "wb_doc_row_count": sum(x["document_count"] for row in wb_rows for x in row["cards"]),
            "wb_doc_verdict_counts": dict(wb_doc_statuses),
            "wb_targets": wb_rows,
        }
        result["groups"].append(group)
        save("near_match_ozon_wb_recheck_20261013.json", result)
        print(json.dumps({k: v for k, v in group.items() if k != "wb_targets"}, ensure_ascii=False), flush=True)
    save("near_match_ozon_wb_recheck_20261013.json", result)
    print("SAVED", BASE / "near_match_ozon_wb_recheck_20261013.json", flush=True)


if __name__ == "__main__":
    main()
