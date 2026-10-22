"""Read-only exact Ozon and WB coverage check for Feron 53577/22."""
from __future__ import annotations

import collections
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE))
from api_client import Client, now, save  # noqa: E402

WORKBOOK = Path("/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron/Сопоставление_артикулов_и_файлов_документов.xlsx")
DOC_NUMBER = "ЕАЭС N RU Д-CN.РА06.В.53577/22"
CERTIFICATE_ID = 5423304
NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def targets() -> list[dict[str, str]]:
    with zipfile.ZipFile(WORKBOOK) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = {x.attrib["Id"]: x.attrib["Target"].lstrip("/")
                for x in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        shared_xml = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        shared = ["".join(t.text or "" for t in item.findall(".//a:t", NS))
                  for item in shared_xml.findall("a:si", NS)]
        sheet = next(x for x in workbook.findall("a:sheets/a:sheet", NS)
                     if x.attrib["name"] == "Артикул-файл")
        root = ET.fromstring(archive.read(rels[sheet.attrib[f"{{{NS['r']}}}id"]]))
    result = []
    for row in root.findall("a:sheetData/a:row", NS):
        values = {}
        for cell in row.findall("a:c", NS):
            col = "".join(ch for ch in cell.attrib["r"] if ch.isalpha())
            node = cell.find("a:v", NS)
            value = node.text if node is not None else ""
            if cell.attrib.get("t") == "s" and value:
                value = shared[int(value)]
            elif cell.attrib.get("t") == "inlineStr":
                value = "".join(t.text or "" for t in cell.findall(".//a:t", NS))
            values[col] = value
        if "53577" in values.get("G", "") and values.get("A"):
            result.append({"offer_id": values["A"], "product_id": values.get("D", ""),
                           "sku": values.get("E", ""), "name": values.get("C", ""),
                           "source_file": values.get("H", "")})
    if len(result) != 10 or len({x["offer_id"] for x in result}) != 10:
        raise RuntimeError(f"Workbook 53577 target mismatch: {len(result)}")
    return result


def main() -> None:
    target_rows = targets()
    client = Client()
    audit = {"checked_at_utc": now(), "read_only": True, "document_number": DOC_NUMBER,
             "certificate_id": CERTIFICATE_ID, "workbook_target_count": len(target_rows),
             "workbook_source_sha256": __import__("hashlib").sha256(WORKBOOK.read_bytes()).hexdigest(),
             "local_original_exists": (ROOT / "00_Оригиналы_файлов" / "not-present-53577").exists(),
             "targets": [], "wb_failures": []}

    live_products = {}
    response = client.call("ozon", "/v3/product/info/list",
                           {"offer_id": [x["offer_id"] for x in target_rows]})
    products = response.get("items") or response.get("result", {}).get("items")
    if not isinstance(products, list):
        raise RuntimeError("Unexpected Ozon info/list response")
    live_products = {str(x.get("offer_id")): {"product_id": str(x.get("id")), "sku": str(x.get("sku"))}
                     for x in products}
    identity_mismatches = [
        {"offer_id": row["offer_id"], "expected_product_id": row["product_id"],
         "live_product_id": live_products.get(row["offer_id"], {}).get("product_id"),
         "expected_sku": row["sku"], "live_sku": live_products.get(row["offer_id"], {}).get("sku")}
        for row in target_rows if live_products.get(row["offer_id"], {}).get("product_id") != row["product_id"]
        or live_products.get(row["offer_id"], {}).get("sku") != row["sku"]]
    info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": DOC_NUMBER}).get("result")
    if not isinstance(info, dict) or str(info.get("certificate_id")) != str(CERTIFICATE_ID):
        raise RuntimeError("Ozon 53577 certificate identity mismatch")
    bindings = client.ozon_bindings(CERTIFICATE_ID)
    expected_pairs = {(x["sku"], x["product_id"]): x["offer_id"] for x in target_rows}
    live_pairs = collections.defaultdict(list)
    for row in bindings:
        live_pairs[(str(row.get("sku", "")), str(row.get("product_id", "")))].append(row)
    missing = set(expected_pairs) - set(live_pairs)
    extra = set(live_pairs) - set(expected_pairs)
    audit["ozon"] = {
        "stored_number": info.get("certificate_number"), "record_status": info.get("status_code"),
        "type_code": info.get("type_code"), "issue_date": info.get("issue_date"),
        "expire_date": info.get("expire_date"), "live_binding_count": len(bindings),
        "binding_status_counts": dict(collections.Counter(str(x.get("product_status_code")) for x in bindings)),
        "live_product_count": len(live_products), "product_identity_mismatches": identity_mismatches,
        "missing_target_pairs": [{"offer_id": expected_pairs[p], "sku": p[0], "product_id": p[1]} for p in sorted(missing)],
        "unexpected_live_pairs": [{"sku": p[0], "product_id": p[1]} for p in sorted(extra)],
        "exact_target_set_matches": not identity_mismatches and not missing and not extra
            and len(bindings) == len(target_rows),
    }
    audit["targets"] = [{**row, "wb_cards": []} for row in target_rows]
    for index, row in enumerate(target_rows, start=1):
        try:
            cards = client.wb_cards(row["offer_id"])
        except RuntimeError as exc:
            audit["wb_failures"].append({"offer_id": row["offer_id"], "error": str(exc)})
            continue
        exact_docs = []
        for card in cards:
            for doc in (card.get("documents") or {}).get("items") or []:
                if "53577/22" in str(doc.get("number", "")) and int(doc.get("type", -1)) == 2:
                    exact_docs.append({"nmID": str(card.get("nmID")), "number": doc.get("number"),
                                       "type": doc.get("type"), "startDate": doc.get("startDate"),
                                       "endDate": doc.get("endDate"), "verdict": doc.get("verdict"),
                                       "overallVerdict": card.get("overallVerdict")})
        audit["targets"][index - 1]["wb_cards"] = [
            {"nmID": str(card.get("nmID")), "brand": card.get("brand"),
             "subjectName": card.get("subjectName"), "exact_53577_rows": [
                 {"number": doc.get("number"), "type": doc.get("type"),
                  "startDate": doc.get("startDate"), "endDate": doc.get("endDate"),
                  "verdict": doc.get("verdict")} for doc in (card.get("documents") or {}).get("items") or []
                 if "53577/22" in str(doc.get("number", "")) and int(doc.get("type", -1)) == 2
             ]} for card in cards]
        if index % 5 == 0:
            save("feron_53577_live_recheck_20261013.json", audit)
            print(json.dumps({"wb_offers_checked": index, "target_count": len(target_rows)}, ensure_ascii=False), flush=True)
    audit["wb_summary"] = {
        "offers_with_one_exact_card": sum(len(x["wb_cards"]) == 1 for x in audit["targets"]),
        "offers_without_exact_card": [x["offer_id"] for x in audit["targets"] if not x["wb_cards"]],
        "offers_with_multiple_exact_cards": [x["offer_id"] for x in audit["targets"] if len(x["wb_cards"]) > 1],
        "offers_with_53577_document_row": [x["offer_id"] for x in audit["targets"]
                                            if any(c["exact_53577_rows"] for c in x["wb_cards"])],
        "wb_failures": len(audit["wb_failures"]),
    }
    audit["local_original_exists"] = any(
        Path("/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron")
        .joinpath(row["source_file"]).is_file() for row in target_rows if row.get("source_file"))
    save("feron_53577_live_recheck_20261013.json", audit)
    print("SAVED", json.dumps({"ozon": audit["ozon"], "wb": audit["wb_summary"],
                                "local_original_exists": audit["local_original_exists"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
