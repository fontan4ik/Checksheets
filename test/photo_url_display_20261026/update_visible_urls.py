import io
import os
import posixpath
import tempfile
import zipfile
import xml.etree.ElementTree as ET


WORKBOOK = "/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets/outputs/666042e4-3b0d-4e69-a5e3-116486d11207/Прайс-лист МЮ - ссылки на фото.xlsx"
SOURCE = "/Users/vladimirgrebennikov/Downloads/2026.09.28 Прайс-лист МЮ (1) (2).xlsx"
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"m": MAIN_NS, "r": DOC_REL_NS, "p": PKG_REL_NS}
SHEETS = {
    "Общий прайс-лист", "Светодиодные лампы", "Светильники",
    "Лампы традиционных технологий", "Светильники с БАП", "Декоративный свет",
}


def parse_xml(data):
    for _, (prefix, uri) in ET.iterparse(io.BytesIO(data), events=("start-ns",)):
        if prefix and prefix.startswith("ns") and prefix[2:].isdigit():
            continue
        ET.register_namespace(prefix or "", uri)
    return ET.fromstring(data)


def xml_bytes(root):
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def package_part(target):
    target = target.replace("\\", "/")
    return target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))


def main():
    with zipfile.ZipFile(WORKBOOK) as input_zip:
        infos = input_zip.infolist()
        parts = {info.filename: input_zip.read(info.filename) for info in infos}

    workbook = parse_xml(parts["xl/workbook.xml"])
    workbook_rels = parse_xml(parts["xl/_rels/workbook.xml.rels"])
    rel_targets = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in workbook_rels.findall("p:Relationship", NS)
    }
    sheet_parts = {}
    for sheet in workbook.find("m:sheets", NS):
        name = sheet.attrib["name"]
        if name in SHEETS:
            rid = sheet.attrib["{" + DOC_REL_NS + "}id"]
            sheet_parts[name] = package_part(rel_targets[rid])

    total = 0
    for name, sheet_path in sheet_parts.items():
        sheet = parse_xml(parts[sheet_path])
        rel_path = posixpath.join(posixpath.dirname(sheet_path), "_rels", posixpath.basename(sheet_path) + ".rels")
        sheet_rels = parse_xml(parts[rel_path])
        rel_by_id = {
            rel.attrib["Id"]: rel.attrib
            for rel in sheet_rels.findall("p:Relationship", NS)
        }
        cells = {
            cell.attrib["r"]: cell
            for cell in sheet.findall(".//m:sheetData/m:row/m:c", NS)
        }
        hyperlinks = sheet.find("m:hyperlinks", NS)
        count = 0
        if hyperlinks is not None:
            for link in hyperlinks.findall("m:hyperlink", NS):
                rid = link.attrib.get("{" + DOC_REL_NS + "}id")
                relationship = rel_by_id.get(rid)
                if not relationship or relationship.get("TargetMode") != "External":
                    continue
                url = relationship.get("Target", "")
                if not url.startswith("https://"):
                    continue
                cell = cells[link.attrib["ref"]]
                cell.attrib["t"] = "inlineStr"
                for child in list(cell):
                    cell.remove(child)
                inline = ET.SubElement(cell, "{" + MAIN_NS + "}is")
                text = ET.SubElement(inline, "{" + MAIN_NS + "}t")
                text.text = url
                count += 1
        parts[sheet_path] = xml_bytes(sheet)
        total += count
        print(f"{name}: {count} URL strings")

    if total != 6230:
        raise ValueError(f"Expected 6230 URLs, found {total}")
    folder = os.path.dirname(WORKBOOK)
    fd, temporary = tempfile.mkstemp(prefix="visible_urls_", suffix=".xlsx", dir=folder)
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary, "w") as output_zip:
            for info in infos:
                output_zip.writestr(info, parts[info.filename])
        with zipfile.ZipFile(temporary) as check, zipfile.ZipFile(SOURCE) as original:
            if check.testzip() is not None:
                raise ValueError("The edited workbook package failed its ZIP integrity check")
            original_media = sorted(name for name in original.namelist() if name.startswith("xl/media/"))
            updated_media = sorted(name for name in check.namelist() if name.startswith("xl/media/"))
            if original_media != updated_media or any(original.read(name) != check.read(name) for name in original_media):
                raise ValueError("Embedded images differ from the source workbook")
        os.replace(temporary, WORKBOOK)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    print(f"FINAL: {total} visible URL strings; source images preserved")


if __name__ == "__main__":
    main()
