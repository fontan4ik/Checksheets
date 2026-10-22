"""Build a fresh Ozon plan for FSA-verified FERON declaration 87126/22."""
from __future__ import annotations

import collections
import hashlib
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from api_client import Client, digest, now, save
from audit_feron_01315_53551 import FERON, norm

BASE = Path(__file__).resolve().parent
WORKBOOK = FERON / "Сопоставление_артикулов_и_файлов_документов.xlsx"
SOURCE = FERON / "00_Оригиналы_файлов" / "Декларация__87126_Светильники_встраиваемые,_тм_Feron,_серии_CD,_GS-M,_DL,_DLT_Декларация_по_037_1__5fec5515c7.jpg"
UPLOAD = BASE / "feron_87126_upload_files/decl_87126_22.pdf"
REGISTRY_NUMBER = "ЕАЭС N RU Д-CN.РА02.В.87126/22"
WORKBOOK_NUMBER_SUFFIX = "87126/22"
REGISTRY_URL = "https://pub.fsa.gov.ru/rds/declaration/view/16650422"
ISSUE_DATE = "2022-04-05"
REGISTRY_EXPIRY = "2027-04-03"
SCAN_EXPIRY = "2027-04-04"
NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def read_target_rows() -> list[dict[str, str]]:
    with zipfile.ZipFile(WORKBOOK) as archive:
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = {x.attrib["Id"]: x.attrib["Target"].lstrip("/")
                for x in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        shared = ["".join(t.text or "" for t in item.findall(".//a:t", NS))
                  for item in shared_root.findall("a:si", NS)]
        sheet = next(x for x in book.findall("a:sheets/a:sheet", NS)
                     if x.attrib["name"] == "Артикул-файл")
        root = ET.fromstring(archive.read(rels[sheet.attrib[f"{{{NS['r']}}}id"]]))
    out = []
    for row in root.findall("a:sheetData/a:row", NS):
        values: dict[str, str] = {}
        for cell in row.findall("a:c", NS):
            col = "".join(ch for ch in cell.attrib["r"] if ch.isalpha())
            v = cell.find("a:v", NS)
            value = v.text if v is not None else ""
            if cell.attrib.get("t") == "s" and value:
                value = shared[int(value)]
            elif cell.attrib.get("t") == "inlineStr":
                value = "".join(t.text or "" for t in cell.findall(".//a:t", NS))
            values[col] = value.strip()
        if (values.get("A") and values.get("B") and values.get("C") and
                values.get("G", "").endswith(WORKBOOK_NUMBER_SUFFIX)):
            out.append({"offer_id": values.get("A", ""), "feron_article": values.get("B", ""),
                        "name": values.get("C", ""), "workbook_product_id": values.get("D", ""),
                        "workbook_sku": values.get("E", ""), "workbook_number": values.get("G", ""),
                        "file_in_offer": values.get("H", ""), "original_name": values.get("R", ""),
                        "registry_state": values.get("K", ""), "official_status": values.get("M", ""),
                        "applicability": values.get("N", ""), "manual_flag": values.get("O", "")})
    return out


def list_certificates(client: Client) -> list[dict]:
    out: list[dict] = []
    page = 1
    while page <= 100:
        batch = client.call("ozon", "/v1/product/certificate/list",
                            {"page": page, "page_size": 100})["result"].get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Invalid Ozon certificate list page")
        out.extend(batch)
        if len(batch) < 100:
            return out
        page += 1
    raise RuntimeError("Ozon certificate pagination limit exceeded")


def read_wb_trash(client: Client) -> tuple[list[dict], int]:
    out: list[dict] = []
    cursor = {"limit": 100}
    pages = 0
    while True:
        body = client.call("wb", "/content/v2/get/cards/trash",
                           {"settings": {"sort": {"ascending": True}, "cursor": cursor}})
        data = body.get("data", body)
        batch = (data.get("cards") or data.get("items") or []) if isinstance(data, dict) else []
        cursor_data = (data.get("cursor") or body.get("cursor") or {}) if isinstance(data, dict) else {}
        if not isinstance(batch, list):
            raise RuntimeError("Invalid WB trash list page")
        pages += 1
        out.extend(batch)
        if len(batch) < 100:
            return out, pages
        next_cursor = {k: cursor_data.get(k) for k in ("trashedAt", "nmID")}
        if not all(next_cursor.values()):
            raise RuntimeError("WB trash cursor incomplete")
        cursor = {"limit": 100, **next_cursor}


def main() -> None:
    if not SOURCE.is_file() or not UPLOAD.is_file():
        raise RuntimeError("Original scan or upload PDF is missing")
    if digest(SOURCE) != "5fec5515c7525a48df5a15a98b749dd3a56a0a9c9b6c6215f1d347e8bf341588":
        raise RuntimeError("Original declaration scan changed")
    preflight = json.loads((BASE / "feron_full_wb_snapshot.json").read_text())
    coverage = json.loads((BASE / "feron_full_wb_document_coverage_audit.json").read_text())
    if not preflight.get("complete") or preflight.get("target_offer_count") != 4232:
        raise RuntimeError("Complete fresh WB full-catalog read is required")
    rows = read_target_rows()
    offers = {row["offer_id"] for row in rows}
    if len(rows) != 221 or len(offers) != 221:
        raise RuntimeError(f"Expected 221 unique workbook offers, got {len(rows)} rows/{len(offers)} offers")
    workbook_number = rows[0]["workbook_number"]
    coverage_row = next((x for x in coverage["documents"]
                         if x["number"] == workbook_number), None)
    if not coverage_row or coverage_row["counts"].get("suffix_number_variant") != 214:
        raise RuntimeError("Fresh WB declaration coverage is not the expected 214 cards")
    if coverage_row["counts"].get("wb_card_missing") != 7 or coverage_row["counts"].get("wb_document_missing", 0):
        raise RuntimeError("WB coverage changed; rebuild plan before continuing")

    local_copies = []
    for row in rows:
        path = FERON / row["file_in_offer"]
        if not path.is_file() or digest(path) != digest(SOURCE):
            raise RuntimeError("Missing or changed per-offer copy: " + str(path))
        local_copies.append({"path": str(path), "size": path.stat().st_size, "sha256": digest(path)})
    if any(row["manual_flag"] for row in rows):
        raise RuntimeError("Workbook requires manual evidence review")

    client = Client()
    offer_ids = sorted(offers)
    live: dict[str, dict] = {}
    for offset in range(0, len(offer_ids), 100):
        result = client.call("ozon", "/v3/product/info/list",
                             {"offer_id": offer_ids[offset:offset + 100]})
        items = result.get("items") or result.get("result", {}).get("items")
        if not isinstance(items, list):
            raise RuntimeError("Invalid Ozon product info page")
        for item in items:
            offer = str(item.get("offer_id", ""))
            if not offer or offer in live:
                raise RuntimeError("Duplicate/missing live Ozon offer identity")
            live[offer] = {"product_id": str(item.get("id", "")), "sku": str(item.get("sku", "")),
                           "is_archived": item.get("is_archived")}
    mismatches = {}
    targets = []
    for row in rows:
        actual = live.get(row["offer_id"])
        if not actual or actual["product_id"] != row["workbook_product_id"] or actual["sku"] != row["workbook_sku"]:
            mismatches[row["offer_id"]] = {"workbook": row, "live": actual}
            continue
        targets.append({"offer_id": row["offer_id"], **actual})
    if mismatches or len(live) != 221 or len(targets) != 221 or len({x["sku"] for x in targets}) != 221:
        raise RuntimeError("Ozon target identity mismatch; do not create/bind")

    records = list_certificates(client)
    expected = norm(REGISTRY_NUMBER)
    suffix = "8712622"
    exact = [c for c in records if norm(c.get("certificate_number")) == expected]
    same_suffix = [c for c in records if norm(c.get("certificate_number", "")).endswith(suffix)
                   and c.get("type_code") == "declaration"]
    if exact or same_suffix:
        raise RuntimeError("Ozon already has exact/suffix-matching declaration; reconcile instead of creating")

    trash_cards, trash_pages = read_wb_trash(client)
    trash_target_offers = sorted({str(card.get("vendorCode", "")) for card in trash_cards} & offers)
    if trash_target_offers:
        raise RuntimeError("WB has target cards in trash; stop and reconcile instead of creating/recovering cards")

    wb_cards = preflight["cards_by_offer"]
    wb_verified = []
    for offer in sorted(offers):
        card = wb_cards.get(offer)
        if not card:
            continue
        docs = (card.get("documents") or {}).get("items") or []
        related = [d for d in docs if re.sub(r"\D", "", str(d.get("number", ""))).endswith(suffix)
                   and int(d.get("type") or 0) == 2]
        if len(related) != 1:
            raise RuntimeError("WB exact declaration row missing/duplicated for " + offer)
        d = related[0]
        verdict = d.get("verdict") or {}
        if (str(d.get("startDate", ""))[:10] != ISSUE_DATE or
                str(d.get("endDate", ""))[:10] != REGISTRY_EXPIRY or
                verdict.get("verified") is not True or verdict.get("status") != 1):
            raise RuntimeError("WB 87126 declaration not finally verified for " + offer)
        wb_verified.append({"offer_id": offer, "nmID": str(card.get("nmID")),
                            "document": {k: d.get(k) for k in ("id", "type", "number", "startDate", "endDate", "verdict")},
                            "overallVerdict": (card.get("documents") or {}).get("overallVerdict")})
    if len(wb_verified) != 214:
        raise RuntimeError(f"Expected 214 current WB declaration rows, got {len(wb_verified)}")
    missing_wb = sorted(offers - set(wb_cards))
    if len(missing_wb) != 7:
        raise RuntimeError(f"Expected 7 WB cards absent, got {len(missing_wb)}")

    plan = {
        "planned_at": now(), "number": REGISTRY_NUMBER, "workbook_number": workbook_number,
        "document_type": "DECLARATION", "country": "RU", "accordance_type": "EAEU",
        "issue_date": ISSUE_DATE, "expire_date": REGISTRY_EXPIRY,
        "date_note": ("The signed scan says validity through 2027-04-04 inclusive; the QR resolves to the live "
                      "FSA record 16650422, which is active through 2027-04-03. Existing verified WB rows also "
                      "use 2027-04-03. Use the live registry date and preserve the one-day discrepancy."),
        "number_note": ("Workbook text begins 'A-CN'; the signed original and QR-linked FSA record both read "
                        "'Д-CN.РА02.В.87126/22', and existing WB rows contain the same declaration number."),
        "product_scope": "Embedded general-purpose Feron luminaires, series/types CD, GS-M, DL, DLT; TR EAEU 037/2016.",
        "registry_url": REGISTRY_URL,
        "registry_evidence": {"record_id": 16650422, "checked_at": now(), "status": "Действует",
                              "registration_date": ISSUE_DATE, "valid_until": REGISTRY_EXPIRY,
                              "applicant_registration": True, "product_scope": "Feron CD, GS-M, DL, DLT"},
        "source_file": {"path": str(SOURCE), "sha256": digest(SOURCE), "size": SOURCE.stat().st_size},
        "upload_file": {"path": str(UPLOAD.resolve()), "sha256": digest(UPLOAD),
                        "size": UPLOAD.stat().st_size, "pages": 1},
        "source_workbook": {"path": str(WORKBOOK), "sha256": digest(WORKBOOK)},
        "target_count": len(targets), "local_offer_copies": local_copies,
        "ozon_preflight": {"checked_at": now(), "certificate_list_count": len(records),
                           "exact_matches": len(exact), "same_suffix_declaration_matches": len(same_suffix),
                           "identity_count": len(live), "identity_mismatches": 0,
                           "archived_target_count": sum(bool(x.get("is_archived")) for x in live.values())},
        "wb_snapshot": {"checked_at": preflight["checked_at"], "catalog_pages": preflight["pages"],
                        "catalog_cards": preflight["catalog_card_count"],
                        "cards_with_verified_document": len(wb_verified),
                        "missing_target_offers": missing_wb,
                        "trash_snapshot_checked_at": now(), "trash_pages": trash_pages,
                        "trash_complete": True, "cards_in_trash": len(trash_cards),
                        "target_offers_in_trash": trash_target_offers},
        "wb_verified_rows": wb_verified, "targets": targets,
        "seed_offer": targets[0]["offer_id"], "seed_product_id": targets[0]["product_id"],
        "seed_sku": targets[0]["sku"],
    }
    save("feron_87126_ozon_plan.json", plan)
    print(json.dumps({"plan": str(BASE / "feron_87126_ozon_plan.json"),
                      "number": REGISTRY_NUMBER, "targets": len(targets),
                      "ozon_existing_exact_or_suffix": 0, "wb_verified_cards": len(wb_verified),
                      "wb_missing_cards": len(missing_wb), "seed": targets[0]["offer_id"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
