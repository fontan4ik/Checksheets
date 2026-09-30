import math
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
import iek_stock_sync_local as iek
import rs_sync_local as rs


OUT = Path("outputs/01a0f179-fa02-7ac1-8c59-51bb8848e624")
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def read_cell(cell):
    if cell.attrib.get("t") == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//" + NS + "t"))
    value = cell.find(NS + "v")
    return value.text if value is not None else ""


def row_values(row):
    result = {}
    for cell in row.findall(NS + "c"):
        match = re.match(r"([A-Z]+)", cell.attrib.get("r", ""))
        if match:
            result[match.group(1)] = read_cell(cell)
    return result


def rows_from_xlsx(name):
    with zipfile.ZipFile(OUT / name) as archive, archive.open("xl/worksheets/sheet1.xml") as source:
        for _, row in ET.iterparse(source, events=("end",)):
            if row.tag == NS + "row" and int(row.attrib.get("r", "0")) >= 7:
                yield row_values(row)
            row.clear()


def positive_number(value):
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def read_rs_candidates(name, limit=1):
    result = []
    for row in rows_from_xlsx(name):
        if row.get("C") and (row.get("A") or row.get("B")) and positive_number(row.get("G")):
            result.append(row)
            if len(result) == limit:
                break
    return result


def rs_residue(session, warehouse_id, code):
    url = f"{config.RS_BASE_URL}/residue/{warehouse_id}/{quote(code, safe='')}"
    response = rs.rs_get_with_retry(session, url, rs.get_rs_headers(), timeout=30, label="RS item residue check")
    if response.status_code != 200:
        raise RuntimeError(f"RS point query returned HTTP {response.status_code} for warehouse {warehouse_id}")
    payload = response.json()
    value = payload.get("Residue", payload.get("residue"))
    return float(value) if value is not None else None


def main():
    rs_examples = [
        ("Москва", 14030, read_rs_candidates("Русский_свет_Москва.xlsx")),
        ("Самара", 287, read_rs_candidates("Русский_свет_Самара.xlsx")),
    ]
    if any(not rows for _, _, rows in rs_examples):
        raise RuntimeError("Could not find a positive-stock RS item in each exported warehouse file")
    session = rs.create_rs_session()
    for warehouse_name, warehouse_id, rows in rs_examples:
        item = rows[0]
        api_value = rs_residue(session, warehouse_id, item["C"])
        file_value = float(item["G"])
        print({
            "supplier": "Русский Свет",
            "warehouse": warehouse_name,
            "article": item["B"] or item["A"],
            "rs_code": item["C"],
            "xlsx": file_value,
            "fresh_api": api_value,
            "match": math.isclose(file_value, api_value, rel_tol=0, abs_tol=1e-9),
        })

    iek_row = next((row for row in rows_from_xlsx("IEK_остатки_по_складам.xlsx") if row.get("A") and positive_number(row.get("C"))), None)
    if not iek_row:
        raise RuntimeError("Could not find an IEK item with positive stock in the workbook")
    session = iek.create_session()
    iek.login(session, iek.get_api_key())
    url = f"{iek.BASE_URL}/api/catalog/v1/client/products/{quote(iek_row['A'], safe='')}"
    detail = iek.request_json(session, "GET", url, allow_not_found=True)
    if not detail:
        raise RuntimeError("IEK item detail endpoint returned no product")
    if iek.normalize_article(detail.get("article")) != iek.normalize_article(iek_row["A"]):
        raise RuntimeError("IEK item detail endpoint returned a different article")
    api_available = iek.validate_stock(detail.get("available"), iek_row["A"])
    xlsx_available = float(iek_row["C"])
    balances = detail.get("warehouseData")
    warehouse_checks = []
    if isinstance(balances, list):
        api_by_name = {
            item.get("warehouseName"): item.get("availableAmount")
            for item in balances if isinstance(item, dict)
        }
        for col, header in zip([chr(ord("D") + index) for index in range(11)], [
            "Балабаново", "Владивосток", "Екатеринбург", "Казань склад", "Кувекино",
            "Новосибирск", "Ростов-на-Дону", "Склад временного хранения", "Чехов", "Щербинка", "Ясногорский",
        ]):
            api_value = api_by_name.get(header)
            file_value = iek_row.get(col, "")
            if api_value is not None and file_value != "":
                warehouse_checks.append({"warehouse": header, "xlsx": float(file_value), "fresh_api": float(api_value), "match": math.isclose(float(file_value), float(api_value), rel_tol=0, abs_tol=1e-9)})
    print({
        "supplier": "IEK",
        "article": iek_row["A"],
        "available": {"xlsx": xlsx_available, "fresh_api": api_available, "match": math.isclose(xlsx_available, float(api_available), rel_tol=0, abs_tol=1e-9)},
        "warehouse_checks": warehouse_checks,
        "detail_fields_include_warehouseData": isinstance(balances, list),
    })


if __name__ == "__main__":
    main()
