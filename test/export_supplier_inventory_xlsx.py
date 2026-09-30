import json
import math
import os
import sys
from datetime import datetime

import xlsxwriter


PROJECT = "/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets"
THREAD_ID = "01a0f179-fa02-7ac1-8c59-51bb8848e624"
SNAPSHOT_PATH = os.path.join(PROJECT, "test/tmp/supplier_inventory_snapshot.json")
OUTPUT_DIR = os.path.join(PROJECT, "outputs", THREAD_ID)


def as_number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    try:
        parsed = float(str(value).replace(",", ".").strip())
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def write_value(sheet, row, col, value, text_format, number_format):
    if value is None or value == "":
        sheet.write_blank(row, col, None)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        sheet.write_number(row, col, value, number_format)
    else:
        number = as_number(value)
        if number is None:
            text = str(value)
            sheet.write_string(row, col, text[:32767], text_format)
        else:
            sheet.write_number(row, col, number, number_format)


def make_workbook(path, sheet_name, column_count):
    workbook = xlsxwriter.Workbook(
        path,
        {"constant_memory": True, "use_zip64": True, "strings_to_formulas": False},
    )
    sheet = workbook.add_worksheet(sheet_name)
    sheet.hide_gridlines(2)
    sheet.freeze_panes(6, 1)
    sheet.set_zoom(90)
    title_format = workbook.add_format({"bold": True, "font_size": 14, "font_color": "#172B4D"})
    label_format = workbook.add_format({"bold": True, "font_color": "#172B4D"})
    note_format = workbook.add_format({"font_size": 9, "font_color": "#526173", "text_wrap": False})
    header_format = workbook.add_format({
        "bold": True,
        "font_color": "#FFFFFF",
        "bg_color": "#1F4E78",
        "text_wrap": True,
        "valign": "vcenter",
        "border": 1,
        "border_color": "#FFFFFF",
    })
    text_format = workbook.add_format({"num_format": "@"})
    number_format = workbook.add_format({"num_format": "#,##0.##"})
    sheet.set_row(1, 25)
    sheet.set_row(5, 34)
    return workbook, sheet, title_format, label_format, note_format, header_format, text_format, number_format


def write_russvet(snapshot, warehouse_name, fetched_at):
    data = snapshot["russvet"][warehouse_name]
    path = os.path.join(OUTPUT_DIR, f"Русский_свет_{warehouse_name}.xlsx")
    headers = [
        "Артикул производителя (VENDOR_CODE)",
        "Артикул ARTICLE",
        "Код РС",
        "Наименование",
        "Бренд",
        "Категория",
        "Остаток свободный",
    ]
    workbook, sheet, title_fmt, label_fmt, note_fmt, header_fmt, text_fmt, number_fmt = make_workbook(
        path, f"Остатки {warehouse_name}", len(headers)
    )
    sheet.set_column("A:A", 30, text_fmt)
    sheet.set_column("B:B", 22, text_fmt)
    sheet.set_column("C:C", 15, text_fmt)
    sheet.set_column("D:D", 58, text_fmt)
    sheet.set_column("E:E", 24, text_fmt)
    sheet.set_column("F:F", 22, text_fmt)
    sheet.set_column("G:G", 18, number_fmt)
    sheet.write(1, 0, f"Русский Свет — остатки, {warehouse_name}", title_fmt)
    for col, value in enumerate(["Склад", warehouse_name, "ID склада", data["warehouse_id"], "Выгрузка API, UTC", fetched_at]):
        write_value(sheet, 2, col, value, text_fmt, number_fmt)
    for col, value in enumerate([
        "Категории каталога", "instock + custom", "Позиций", data["catalog_count"],
        "Без артикула", data["catalog_without_article"],
    ]):
        write_value(sheet, 3, col, value, text_fmt, number_fmt)
    note = (
        "Источник: cdis.russvet.ru/rs. Ноль означает отсутствие кода в residue/all "
        "(API возвращает только ненулевые остатки); пусто оставлено для "
        f"{data['invalid_stock_rows']} некорректных строк API."
    )
    sheet.write(4, 0, note, note_fmt)
    for col, header in enumerate(headers):
        sheet.write(5, col, header, header_fmt)

    records = data["rows"]
    for row_index, item in enumerate(records, start=6):
        for col, key in enumerate(("vendor_code", "article", "code", "name", "brand", "category")):
            value = item.get(key)
            if value is not None and value != "":
                sheet.write_string(row_index, col, str(value)[:32767], text_fmt)
        stock = as_number(item.get("stock"))
        if stock is not None:
            sheet.write_number(row_index, 6, stock, number_fmt)
        if (row_index - 5) % 100000 == 0 or row_index == len(records) + 5:
            print(f"Русский Свет {warehouse_name}: {row_index - 5}/{len(records)} строк", flush=True)

    sheet.autofilter(5, 0, len(records) + 5, len(headers) - 1)
    workbook.close()
    print(json.dumps({"file": path, "rows": len(records), "catalog_count": data["catalog_count"], "missing_article": data["catalog_without_article"], "invalid_stock_rows": data["invalid_stock_rows"]}, ensure_ascii=False), flush=True)


def write_iek(snapshot, fetched_at):
    data = snapshot["iek"]
    warehouses = data["warehouses"]
    counts = {}
    for warehouse in warehouses:
        counts[warehouse["name"]] = counts.get(warehouse["name"], 0) + 1
    warehouse_headers = [
        f"Склад: {w['name']} [{str(w['id'])[-6:]}]" if counts[w["name"]] > 1 else f"Склад: {w['name']}"
        for w in warehouses
    ]
    headers = ["Артикул IEK", "Наименование", "Общий остаток API", *warehouse_headers]
    path = os.path.join(OUTPUT_DIR, "IEK_остатки_по_складам.xlsx")
    workbook, sheet, title_fmt, label_fmt, note_fmt, header_fmt, text_fmt, number_fmt = make_workbook(
        path, "IEK по складам", len(headers)
    )
    sheet.set_column("A:A", 22, text_fmt)
    sheet.set_column("B:B", 58, text_fmt)
    sheet.set_column("C:C", 20, number_fmt)
    for col in range(3, len(headers)):
        sheet.set_column(col, col, 27, number_fmt)
    sheet.write(1, 0, "IEK — остатки по складам", title_fmt)
    meta1 = ["Срез API", ", ".join(data.get("snapshot_dates", [])) or "не указана API", "Выгрузка UTC", fetched_at,
             "Уникальных артикулов", len(data["products"]), "Складов API", len(warehouses)]
    for col, value in enumerate(meta1):
        write_value(sheet, 2, col, value, text_fmt, number_fmt)
    meta2 = ["Записей во всех категориях", data["raw_product_count"], "Категорий API", len(data["categories"]),
             "Артикулы", "Включены все позиции из balances-json", "Остатки по складам", "warehouseData.availableAmount"]
    for col, value in enumerate(meta2):
        write_value(sheet, 3, col, value, text_fmt, number_fmt)
    sheet.write(4, 0,
                "Источник: bp.iek.ru/api/catalog/v1/client/category/{slug}/balances-json. "
                "Общий остаток — поле available; складские значения — availableAmount.", note_fmt)
    for col, header in enumerate(headers):
        sheet.write(5, col, header, header_fmt)

    products = data["products"]
    for row_index, product in enumerate(products, start=6):
        sheet.write_string(row_index, 0, str(product.get("article", ""))[:32767], text_fmt)
        sheet.write_string(row_index, 1, str(product.get("name", ""))[:32767], text_fmt)
        write_value(sheet, row_index, 2, product.get("available"), text_fmt, number_fmt)
        balances = product.get("warehouse_balances") or {}
        for col, warehouse in enumerate(warehouses, start=3):
            if warehouse["id"] in balances:
                write_value(sheet, row_index, col, balances[warehouse["id"]], text_fmt, number_fmt)
        if (row_index - 5) % 20000 == 0 or row_index == len(products) + 5:
            print(f"IEK: {row_index - 5}/{len(products)} строк", flush=True)

    sheet.autofilter(5, 0, len(products) + 5, len(headers) - 1)
    workbook.close()
    print(json.dumps({"file": path, "rows": len(products), "warehouses": [w["name"] for w in warehouses], "snapshot_dates": data.get("snapshot_dates", [])}, ensure_ascii=False), flush=True)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(SNAPSHOT_PATH, "r", encoding="utf-8") as source:
        snapshot = json.load(source)
    fetched_at = snapshot["fetched_at_utc"]
    write_russvet(snapshot, "Москва", fetched_at)
    write_russvet(snapshot, "Самара", fetched_at)
    write_iek(snapshot, fetched_at)


if __name__ == "__main__":
    main()
