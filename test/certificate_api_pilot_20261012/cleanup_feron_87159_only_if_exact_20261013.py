"""Move Feron 87159/22 local copies to macOS Trash only after exact live checks."""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from api_client import Client, now  # noqa: E402
from group4_wb import norm  # noqa: E402

FERON = Path("/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron")
WORKBOOK = FERON / "Сопоставление_артикулов_и_файлов_документов.xlsx"
ORIGINAL_DIR = FERON / "00_Оригиналы_файлов"
NUMBER = "ЕАЭС N RU Д-CN.РА02.В.87159/22"
CERTIFICATE_ID = 5423280
SUFFIX = "87159/22"
NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
PLAN_PATH = BASE / "feron_87159_strict_cleanup_plan_20261013.json"
RESULT_PATH = BASE / "feron_87159_strict_cleanup_result_20261013.json"
JOURNAL_PATH = BASE / "feron_87159_strict_cleanup_journal_20261013.jsonl"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save(path: Path, value: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def workbook_rows() -> list[dict[str, str]]:
    with zipfile.ZipFile(WORKBOOK) as archive:
        wb = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = {x.attrib["Id"]: x.attrib["Target"].lstrip("/")
                for x in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        ss_xml = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        strings = ["".join(t.text or "" for t in x.findall(".//a:t", NS))
                   for x in ss_xml.findall("a:si", NS)]
        sheet = next(x for x in wb.findall("a:sheets/a:sheet", NS) if x.attrib["name"] == "Артикул-файл")
        root = ET.fromstring(archive.read(rels[sheet.attrib[f"{{{NS['r']}}}id"]]))
    result = []
    for row in root.findall("a:sheetData/a:row", NS):
        values = {}
        for cell in row.findall("a:c", NS):
            column = "".join(ch for ch in cell.attrib["r"] if ch.isalpha())
            node = cell.find("a:v", NS)
            value = node.text if node is not None else ""
            if cell.attrib.get("t") == "s" and value:
                value = strings[int(value)]
            elif cell.attrib.get("t") == "inlineStr":
                value = "".join(t.text or "" for t in cell.findall(".//a:t", NS))
            values[column] = value
        if SUFFIX in values.get("G", "") and values.get("A"):
            result.append({"offer_id": values["A"], "product_id": values.get("D", ""),
                           "sku": values.get("E", ""), "product_name": values.get("C", ""),
                           "copy_path": str(FERON / values.get("H", "")),
                           "workbook_number": values.get("G", ""), "source_name": values.get("I", "")})
    if len(result) != 7 or len({x["offer_id"] for x in result}) != 7:
        raise RuntimeError(f"Workbook target set mismatch: expected 7 unique offers, got {len(result)}")
    return result


def collect_proof() -> dict:
    targets = workbook_rows()
    source_candidates = list(ORIGINAL_DIR.glob("*87159*"))
    if len(source_candidates) != 1:
        raise RuntimeError(f"Expected one local original, found {len(source_candidates)}")
    original = source_candidates[0]
    source_hash = sha256(original)
    if source_hash != "1f5253002f217e259ca4bb9926c2331ea39254dc1575c72cb48490b316921fc0":
        raise RuntimeError("Local original SHA does not match the known 87159 source proof")
    files = [original] + [Path(x["copy_path"]) for x in targets]
    if len(set(files)) != 8 or not all(path.is_file() for path in files):
        raise RuntimeError("Expected original plus seven exact offer copies")
    file_info = [{"path": str(path.resolve()), "size": path.stat().st_size, "sha256": sha256(path)} for path in files]
    if any(x["sha256"] != source_hash for x in file_info) or len({x["size"] for x in file_info}) != 1:
        raise RuntimeError("One or more local copies differ from the original hash/size")
    # Check every file with the source size under the quality-documents tree so no
    # unlisted local copy is moved or silently left behind.
    same_hash_paths = []
    for root, _, names in os.walk(FERON):
        for name in names:
            path = Path(root) / name
            try:
                if path.stat().st_size == file_info[0]["size"] and sha256(path) == source_hash:
                    same_hash_paths.append(str(path.resolve()))
            except OSError:
                continue
    if set(same_hash_paths) != {x["path"] for x in file_info}:
        raise RuntimeError("The set of local files sharing this source hash changed or includes extra copies")

    client = Client()
    info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER}).get("result")
    if not isinstance(info, dict) or str(info.get("certificate_id")) != str(CERTIFICATE_ID):
        raise RuntimeError("Ozon certificate ID mismatch")
    if (info.get("status_code") != "approved" or info.get("type_code") != "declaration"
            or str(info.get("expire_date", ""))[:10] != "2027-04-03"):
        raise RuntimeError("Ozon certificate is not finally approved with expected type/expiry")
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": [x["offer_id"] for x in targets]})
    items = products.get("items") or products.get("result", {}).get("items")
    if not isinstance(items, list) or len(items) != len(targets):
        raise RuntimeError("Ozon live product-info set incomplete")
    live_by_offer = {str(x.get("offer_id")): {"product_id": str(x.get("id")), "sku": str(x.get("sku"))} for x in items}
    identity_errors = [x["offer_id"] for x in targets
                       if live_by_offer.get(x["offer_id"], {}).get("product_id") != x["product_id"]
                       or live_by_offer.get(x["offer_id"], {}).get("sku") != x["sku"]]
    if identity_errors:
        raise RuntimeError("Ozon live product identity differs from workbook: " + ",".join(identity_errors))
    bindings = client.ozon_bindings(CERTIFICATE_ID)
    required_pairs = {(x["product_id"], x["sku"]) for x in targets}
    live_pairs = [(str(x.get("product_id")), str(x.get("sku"))) for x in bindings]
    binding_statuses = collections.Counter(str(x.get("product_status_code")) for x in bindings)
    if (len(bindings) != len(targets) or len(set(live_pairs)) != len(live_pairs)
            or set(live_pairs) != required_pairs or binding_statuses != {"approved": len(targets)}):
        raise RuntimeError("Ozon live binding set is incomplete, unexpected, duplicated, or not approved")

    wb_rows = []
    for target in targets:
        cards = client.wb_cards(target["offer_id"])
        if len(cards) != 1:
            raise RuntimeError(f"WB card count is not exactly one for {target['offer_id']}")
        card = cards[0]
        docs = card.get("documents") or {}
        if card.get("vendorCode") != target["offer_id"] or card.get("brand") != "Feron":
            raise RuntimeError(f"WB card identity/brand mismatch for {target['offer_id']}")
        matches = [d for d in docs.get("items") or [] if int(d.get("type", -1)) == 2
                   and norm(d.get("number", "")) == norm(NUMBER)]
        if len(matches) != 1:
            raise RuntimeError(f"WB exact document row is missing or duplicated for {target['offer_id']}")
        doc = matches[0]
        overall = docs.get("overallVerdict") or {}
        if (str(doc.get("startDate", ""))[:10] != str(info.get("issue_date", ""))[:10]
                or str(doc.get("endDate", ""))[:10] != str(info.get("expire_date", ""))[:10]
                or (doc.get("verdict") or {}).get("verified") is not True
                or (doc.get("verdict") or {}).get("status") != 1
                or (doc.get("verdict") or {}).get("reason") != "valid"
                or docs.get("excludeDocuments") is not False
                or overall.get("isFullyChecked") is not True or overall.get("status") != 1):
            raise RuntimeError(f"WB doc/card is not finally valid for {target['offer_id']}")
        wb_rows.append({"offer_id": target["offer_id"], "nmID": str(card.get("nmID")),
                        "title": card.get("title"), "document": doc,
                        "overallVerdict": overall})

    status_file = FERON / "По_артикулам" / "48424-1" / "00_Проверка_актуальности_документов.txt"
    status_text = status_file.read_text(encoding="utf-8")
    if ("87159/22" not in status_text or "Действует в ФСА до 2027-04-03" not in status_text
            or "16650469" not in status_text):
        raise RuntimeError("Recent official-register status note is absent or does not match 87159/22")
    return {
        "checked_at_utc": now(), "number": NUMBER, "certificate_id": CERTIFICATE_ID,
        "source": {"path": str(original), "sha256": source_hash, "size": file_info[0]["size"],
                   "printed_scope": "Настольные светильники торговой марки Feron, серия DE; TR EAEU 037/2016",
                   "printed_registration_date": "2022-04-04", "printed_valid_until": "2027-04-03",
                   "official_registry_reference": "https://pub.fsa.gov.ru/rds/declaration/view/16650469/common",
                   "official_registry_status_last_checked": "2026-09-23", "registry_status": "Действует"},
        "source_platform_date_difference": {"scan_registration_date": "2022-04-04",
                                            "ozon_and_wb_start_date": str(info.get("issue_date", ""))[:10],
                                            "note": "Recorded and retained for review; both marketplace records currently approve the exact document and target. The source files will be moved to recoverable Trash, not permanently deleted."},
        "workbook_target_count": len(targets), "workbook_targets": targets,
        "ozon": {"number": info.get("certificate_number"), "status": info.get("status_code"),
                 "type": info.get("type_code"), "issue_date": info.get("issue_date"),
                 "expire_date": info.get("expire_date"), "binding_count": len(bindings),
                 "binding_status_counts": dict(binding_statuses), "product_identity_errors": identity_errors,
                 "exact_target_set_matches": True},
        "wb": {"exact_card_count": len(wb_rows), "exact_valid_document_rows": len(wb_rows),
               "document_status_counts": {"1:valid": len(wb_rows)}, "cards": wb_rows},
        "local_files": file_info, "all_same_hash_copies_found": same_hash_paths,
    }


def main(execute: bool) -> None:
    if execute and (RESULT_PATH.exists() or JOURNAL_PATH.exists()):
        raise RuntimeError("Cleanup was previously attempted; reconcile from result/journal before retry")
    proof = collect_proof()
    save(PLAN_PATH, proof)
    print(json.dumps({"plan": str(PLAN_PATH), "checked_at_utc": proof["checked_at_utc"],
                      "Ozon": proof["ozon"], "WB": {k: v for k, v in proof["wb"].items() if k != "cards"},
                      "local_files": len(proof["local_files"]),
                      "scan_platform_date_difference": proof["source_platform_date_difference"]}, ensure_ascii=False), flush=True)
    if not execute:
        return
    stamp = dt.datetime.now(ZoneInfo("Asia/Dubai")).strftime("%Y%m%dT%H%M%SZ")
    trash = Path.home() / ".Trash" / f"Feron_87159_confirmed_Ozon_WB_{stamp}"
    trash.mkdir(parents=True, exist_ok=False)
    moved = []
    with JOURNAL_PATH.open("x", encoding="utf-8") as journal:
        for file in proof["local_files"]:
            source = Path(file["path"])
            destination = trash / "Feron" / source.relative_to(FERON)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not source.is_file() or source.stat().st_size != file["size"] or sha256(source) != file["sha256"] or destination.exists():
                raise RuntimeError("Source changed or Trash path already exists: " + str(source))
            record = {"source": str(source), "trash_path": str(destination), "number": NUMBER,
                      "sha256": file["sha256"], "size": file["size"], "certificate_id": CERTIFICATE_ID,
                      "ozon_target_count": proof["ozon"]["binding_count"],
                      "wb_nmids": [x["nmID"] for x in proof["wb"]["cards"]]}
            journal.write(json.dumps({**record, "phase": "prepared", "at": now()}, ensure_ascii=False) + "\n")
            journal.flush(); os.fsync(journal.fileno())
            os.rename(source, destination)
            if source.exists() or destination.stat().st_size != file["size"] or sha256(destination) != file["sha256"]:
                raise RuntimeError("Move verification failed; inspect cleanup journal")
            journal.write(json.dumps({**record, "phase": "verified_moved", "at": now()}, ensure_ascii=False) + "\n")
            journal.flush(); os.fsync(journal.fileno())
            moved.append(record)
    result = {"completed_at_utc": now(), "trash_directory": str(trash),
              "number": NUMBER, "verified_moved_files": len(moved),
              "source_paths_absent": all(not Path(x["source"]).exists() for x in moved),
              "all_trash_hashes_verified": all(sha256(Path(x["trash_path"])) == x["sha256"] for x in moved),
              "ozon_approved_pairs": proof["ozon"]["binding_count"],
              "wb_exact_valid_cards": proof["wb"]["exact_valid_document_rows"],
              "date_difference_recorded": proof["source_platform_date_difference"],
              "moved": moved, "proof": proof}
    save(RESULT_PATH, result)
    print(json.dumps({k: result[k] for k in ("completed_at_utc", "trash_directory", "verified_moved_files",
                                             "source_paths_absent", "all_trash_hashes_verified",
                                             "ozon_approved_pairs", "wb_exact_valid_cards")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main("--execute" in sys.argv)
