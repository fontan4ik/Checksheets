"""Preflight, create once, and bind the verified FERON 01854/22 certificate."""
from __future__ import annotations

import base64
import collections
import datetime as dt
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from pypdf import PdfReader

from api_client import BASE, Client, digest, now, save

FERON = Path("/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron")
PILOT = Path(__file__).resolve().parent
WORKBOOK = FERON / "Сопоставление_артикулов_и_файлов_документов.xlsx"
SOURCE = FERON / "00_Оригиналы_файлов" / (
    "Сертификат__01854_Светильники_втраиваемые_Feron_серии_CD,_GS-M,_DL,_DLT._1__c00260c039.jpg"
)
UPLOAD = PILOT / "feron_01854_upload_files/feron_01854_22.pdf"
PLAN = PILOT / "feron_01854_ozon_plan.json"
EXECUTION = PILOT / "feron_01854_ozon_execution.json"
VERIFICATION = PILOT / "feron_01854_ozon_verification.json"

# FSA displays Cyrillic lookalikes; the source scan and workbook use Latin ones.
NUMBER = "ЕАЭС RU С-CN.НА83.В.01854/22"
SCAN_NUMBER = "ЕАЭС RU C-CN.HA83.B.01854/22"
ISSUE_DATE = "2022-04-11"
EXPIRY_DATE = "2027-04-10"
FSA_URL = "https://pub.fsa.gov.ru/rss/certificate/view/3074630/product"
FSA_RECORD_ID = 3074630
EXPECTED_SOURCE_SHA256 = "c00260c039d1f1c73d43ca1f4374312553641001d0810f3f7b68fd1a0ddf8fbf"
EXPECTED_ROWS = 188
MAX_REQUEST_BYTES = 15_000_000

CHAR_MAP = str.maketrans({
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
    "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
    "Ё": "E", "Э": "E", "Д": "D", "П": "P",
})
NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
MODEL_RE = re.compile(r"(?<![A-Z0-9])(?:CD|GS[ -]?M|DLT?\d{1,5})(?![A-Z0-9])", re.I)


def normalize(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper().translate(CHAR_MAP) if ch.isalnum())


def read_workbook_rows() -> list[dict[str, str]]:
    with zipfile.ZipFile(WORKBOOK) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = {
            item.attrib["Id"]: item.attrib["Target"].lstrip("/")
            for item in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }
        strings_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        shared = [
            "".join(text.text or "" for text in item.findall(".//a:t", NS))
            for item in strings_root.findall("a:si", NS)
        ]
        sheet = next(
            item for item in workbook.findall("a:sheets/a:sheet", NS)
            if item.attrib["name"] == "Артикул-файл"
        )
        root = ET.fromstring(archive.read(rels[sheet.attrib[f"{{{NS['r']}}}id"]]))

    rows: list[dict[str, str]] = []
    for row in root.findall("a:sheetData/a:row", NS):
        values: dict[str, str] = {}
        for cell in row.findall("a:c", NS):
            col = "".join(ch for ch in cell.attrib["r"] if ch.isalpha())
            value_node = cell.find("a:v", NS)
            value = value_node.text if value_node is not None else ""
            if cell.attrib.get("t") == "s" and value:
                value = shared[int(value)]
            elif cell.attrib.get("t") == "inlineStr":
                value = "".join(text.text or "" for text in cell.findall(".//a:t", NS))
            values[col] = (value or "").strip()
        if values.get("A") and normalize(values.get("G")) == normalize(SCAN_NUMBER):
            rows.append({
                "offer_id": values.get("A", ""),
                "article": values.get("B", ""),
                "name": values.get("C", ""),
                "product_id": values.get("D", ""),
                "sku": values.get("E", ""),
                "workbook_number": values.get("G", ""),
                "file_in_offer": values.get("H", ""),
                "registry_status": values.get("K", ""),
                "official_status": values.get("M", ""),
                "applicability": values.get("N", ""),
                "manual_flag": values.get("O", ""),
                "source_reference": values.get("P", ""),
            })
    return rows


def read_certificates(client: Client) -> list[dict]:
    items: list[dict] = []
    seen_ids: set[str] = set()
    page = 1
    while page <= 100:
        result = client.call("ozon", "/v1/product/certificate/list", {
            "page": page, "page_size": 100,
        }).get("result", {})
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list returned an invalid page")
        ids = [str(item.get("certificate_id", "")) for item in batch]
        if any(not value for value in ids) or len(ids) != len(set(ids)) or seen_ids.intersection(ids):
            raise RuntimeError("Ozon certificate pagination contains missing or duplicate IDs")
        seen_ids.update(ids)
        items.extend(batch)
        if len(batch) < 100:
            return items
        page += 1
    raise RuntimeError("Ozon certificate list exceeded the 100-page safety limit")


def read_live_products(client: Client, rows: list[dict[str, str]]) -> dict[str, dict[str, str | bool]]:
    offers = sorted({row["offer_id"] for row in rows})
    live: dict[str, dict[str, str | bool]] = {}
    for offset in range(0, len(offers), 100):
        body = client.call("ozon", "/v3/product/info/list", {
            "offer_id": offers[offset:offset + 100],
        })
        items = body.get("items") or body.get("result", {}).get("items")
        if not isinstance(items, list):
            raise RuntimeError("Ozon product info response has no items list")
        for item in items:
            offer = str(item.get("offer_id", ""))
            if not offer or offer in live:
                raise RuntimeError("Ozon product response contains a missing or repeated offer_id")
            live[offer] = {
                "product_id": str(item.get("id", "")),
                "sku": str(item.get("sku", "")),
                "is_archived": item.get("is_archived"),
                "name": str(item.get("name", "")),
            }
    if set(live) != set(offers):
        raise RuntimeError("Ozon did not return the complete target offer set")
    return live


def build_plan(client: Client) -> dict:
    if not WORKBOOK.is_file() or not SOURCE.is_file() or not UPLOAD.is_file():
        raise RuntimeError("Workbook, original scan, or prepared PDF is missing")
    workbook_hash = digest(WORKBOOK)
    source_hash = digest(SOURCE)
    upload_hash = digest(UPLOAD)
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("Original certificate scan changed")
    if UPLOAD.stat().st_size > 5_000_000:
        raise RuntimeError("Prepared upload PDF exceeds the conservative size guard")
    if len(PdfReader(str(UPLOAD)).pages) != 1:
        raise RuntimeError("Prepared certificate upload must be a one-page PDF")

    rows = read_workbook_rows()
    if len(rows) != EXPECTED_ROWS:
        raise RuntimeError(f"Expected {EXPECTED_ROWS} workbook rows, got {len(rows)}")
    for key in ("offer_id", "product_id", "sku"):
        values = [row[key] for row in rows]
        if any(not value for value in values) or len(values) != len(set(values)):
            raise RuntimeError(f"Workbook {key} values are missing or duplicated")
    if any(normalize(row["workbook_number"]) != normalize(SCAN_NUMBER) for row in rows):
        raise RuntimeError("Workbook number differs from the certificate scan")
    if any(row["applicability"] != "карточка Feron" for row in rows):
        raise RuntimeError("Workbook applicability basis changed")
    if any(row["manual_flag"].strip().casefold() != "да" for row in rows):
        raise RuntimeError("Expected an explicit manual-review 'да' flag on every applicable workbook row")
    if any(not MODEL_RE.search(row["name"]) for row in rows):
        raise RuntimeError("At least one product name does not identify a certified series")

    copy_hashes: collections.Counter[str] = collections.Counter()
    missing_copies: list[str] = []
    mismatched_copies: list[str] = []
    for row in rows:
        path = FERON / row["file_in_offer"]
        if not path.is_file():
            missing_copies.append(str(path))
            continue
        file_hash = digest(path)
        copy_hashes[file_hash] += 1
        if file_hash != source_hash:
            mismatched_copies.append(str(path))
    if missing_copies or mismatched_copies or copy_hashes != {source_hash: EXPECTED_ROWS}:
        raise RuntimeError("Local target copies are missing or differ from the verified original")

    live = read_live_products(client, rows)
    target_products: list[dict[str, str]] = []
    for row in rows:
        current = live[row["offer_id"]]
        if (current["product_id"] != row["product_id"] or current["sku"] != row["sku"]
                or current["is_archived"] is not False):
            raise RuntimeError("Ozon offer/product/SKU identity changed or is archived: " + row["offer_id"])
        target_products.append({
            "offer_id": row["offer_id"],
            "article": row["article"],
            "product_id": row["product_id"],
            "sku": row["sku"],
            "name": row["name"],
            "is_archived": False,
        })

    records = read_certificates(client)
    exact = [item for item in records if normalize(item.get("certificate_number")) == normalize(NUMBER)]
    suffix = [item for item in records if normalize(item.get("certificate_number", "")).endswith("0185422")]
    if exact:
        raise RuntimeError("An Ozon certificate with the exact normalized number already exists; reconcile it")

    seed = min(target_products, key=lambda item: item["sku"])
    request_params_bytes = len(json.dumps({
        "number": NUMBER,
        "file_content": base64.b64encode(UPLOAD.read_bytes()).decode("ascii"),
        "skus": [seed["sku"]],
    }, ensure_ascii=False).encode("utf-8"))
    if request_params_bytes > MAX_REQUEST_BYTES:
        raise RuntimeError("Ozon create request exceeds the conservative 15 MB request guard")

    return {
        "planned_at": now(),
        "number": NUMBER,
        "scan_number": SCAN_NUMBER,
        "document_type": "CERTIFICATE_OF_CONFORMITY",
        "country": "RU",
        "accordance_type": "EAEU",
        "issue_date": ISSUE_DATE,
        "expire_date": EXPIRY_DATE,
        "product_scope": "Feron embedded general-purpose luminaires, series CD, GS-M, DL, DLT; TR TS 004/2011.",
        "fsa_record": {
            "id": FSA_RECORD_ID,
            "url": FSA_URL,
            "status": "Действует",
            "registration_date": ISSUE_DATE,
            "expiry_date": EXPIRY_DATE,
            "applicant": "ООО СИЛА СВЕТА",
            "manufacturer": "Ningbo Yusing Electronics Co., Ltd.; Ningbo Yusing Lighting Co., Ltd.; Zhejiang MEKA Electric Co., Ltd.; Hangzhou Junction Imp. and Exp. Co., Ltd.",
            "regulation": "ТР ТС 004/2011",
            "product_tab_scope": "Оборудование световое общего назначения: светильники встраиваемые, торговая марка Feron, серии CD, GS-M, DL, DLT",
            "ui_rechecked_at": "2026-10-12T09:56Z",
        },
        "manual_review_resolution": "All 188 workbook rows were flagged because the scan expiry had not been OCR-read. The original scan visibly states 11.04.2022–10.04.2027 inclusive; the live FSA record 3074630 confirms the same dates and product scope.",
        "workbook": {"path": str(WORKBOOK), "sha256": workbook_hash, "target_rows": len(rows)},
        "original_file": {"path": str(SOURCE), "sha256": source_hash, "size": SOURCE.stat().st_size},
        "upload_file": {"path": str(UPLOAD.resolve()), "sha256": upload_hash, "size": UPLOAD.stat().st_size, "pages": 1},
        "local_copy_audit": {"target_copy_count": sum(copy_hashes.values()), "unique_sha256_count": len(copy_hashes), "all_match_original": True},
        "ozon_preflight": {
            "products_returned": len(live),
            "active_product_count": sum(item["is_archived"] is False for item in live.values()),
            "archived_product_count": sum(item["is_archived"] is True for item in live.values()),
            "certificate_record_count": len(records),
            "exact_normalized_record_count": len(exact),
            "same_numeric_suffix_records": [
                {"certificate_id": str(item.get("certificate_id")),
                 "certificate_number": item.get("certificate_number"),
                 "type_code": item.get("type_code"), "status_code": item.get("status_code")}
                for item in suffix
            ],
            "existing_exact_info_endpoint": "404/code=5 confirmed read-only by separate live audit before this plan",
        },
        "seed": seed,
        "targets": target_products,
        "target_sku_to_product_id": {item["sku"]: item["product_id"] for item in target_products},
        "estimated_create_request_bytes": request_params_bytes,
    }


def read_bindings(client: Client, certificate_id: int) -> list[dict]:
    items: list[dict] = []
    last_id = 0
    expected_count: int | None = None
    while True:
        result = client.call("ozon", "/v1/product/certificate/products/list", {
            "certificate_id": certificate_id, "limit": 500, "last_id": last_id,
        }).get("result", {})
        batch = result.get("items")
        count = result.get("count")
        if not isinstance(batch, list) or not isinstance(count, int):
            raise RuntimeError("Ozon bindings response is malformed")
        if expected_count is None:
            expected_count = count
        elif count != expected_count:
            raise RuntimeError("Ozon binding count changed during read")
        items.extend(batch)
        if len(items) == expected_count:
            if len({str(item.get("sku")) for item in items}) != len(items):
                raise RuntimeError("Ozon returned duplicate certificate binding SKUs")
            return items
        if not batch or len(items) > expected_count:
            raise RuntimeError("Ozon certificate binding pagination is incomplete")
        next_id = int(batch[-1].get("product_id", 0))
        if next_id <= last_id:
            raise RuntimeError("Ozon binding pagination cursor did not advance")
        last_id = next_id


def execute(client: Client, saved_plan: dict) -> None:
    if EXECUTION.exists() or VERIFICATION.exists():
        raise RuntimeError("Execution journal already exists; reconcile current Ozon state before any write")

    fresh = build_plan(client)
    stable_fields = ("number", "issue_date", "expire_date", "workbook", "original_file", "upload_file", "targets")
    if any(fresh.get(key) != saved_plan.get(key) for key in stable_fields):
        raise RuntimeError("Fresh Ozon preflight differs from the saved plan; rebuild it before upload")
    if fresh["ozon_preflight"]["exact_normalized_record_count"] != 0:
        raise RuntimeError("Exact Ozon certificate appeared after preflight; do not create")
    save(PLAN.name, fresh)

    target_map = fresh["target_sku_to_product_id"]
    seed = fresh["seed"]
    upload_bytes = UPLOAD.read_bytes()
    params = {
        "name": "Сертификат соответствия № " + NUMBER,
        "certificate_type": "CERTIFICATE_OF_CONFORMITY",
        "certificate_country": "RU",
        "accordance_type": "EAEU",
        "number": NUMBER,
        "issue_date": ISSUE_DATE + "T00:00:00Z",
        "expired_date": {"date": {"day": 10, "month": 4, "year": 2027}},
        "skus": [seed["sku"]],
        "product_type": "UNKNOWN",
        "link_to_registry": FSA_URL,
        "files": [{
            "file_content": base64.b64encode(upload_bytes).decode("ascii"),
            "name": "FERON_certificate_01854_22.pdf",
        }],
    }
    request_size = len(json.dumps({"params": params}, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if request_size > MAX_REQUEST_BYTES:
        raise RuntimeError("Ozon create body exceeds 15 MB; no write sent")

    state = {
        "started_at": now(), "phase": "create_prepared", "number": NUMBER,
        "target_skus": len(target_map), "seed_sku": seed["sku"],
        "source_file_sha256": fresh["original_file"]["sha256"],
        "upload_file_sha256": fresh["upload_file"]["sha256"],
        "estimated_request_bytes": request_size, "bind_batches": [],
    }
    save(EXECUTION.name, state)
    try:
        created = client.call("ozon", "/v2/product/certificate/create", {"params": params}, mutation=True)
    except Exception as exc:
        state.update({"phase": "create_uncertain", "error_type": type(exc).__name__, "updated_at": now()})
        save(EXECUTION.name, state)
        raise RuntimeError("Create outcome is uncertain; reconcile Ozon before any retry") from None
    state["create_response"] = created
    certificate_id = created.get("certificate_id")
    param_states = [item.get("state") for item in created.get("params", []) if isinstance(item, dict)]
    if not certificate_id or created.get("status") != "COMPLETED" or not param_states or set(param_states) != {"VALID"}:
        state.update({"phase": "create_not_fully_validated", "updated_at": now()})
        save(EXECUTION.name, state)
        raise RuntimeError("Ozon create response was not fully valid; do not bind or retry")
    certificate_id = int(certificate_id)
    state.update({"certificate_id": certificate_id, "phase": "created_response_valid", "updated_at": now()})
    save(EXECUTION.name, state)

    records = read_certificates(client)
    by_id = [item for item in records if str(item.get("certificate_id")) == str(certificate_id)]
    by_number = [item for item in records if normalize(item.get("certificate_number")) == normalize(NUMBER)]
    if len(by_id) != 1 or len(by_number) != 1 or str(by_id[0].get("certificate_id")) != str(by_number[0].get("certificate_id")):
        state.update({"phase": "created_not_uniquely_visible", "by_id_count": len(by_id), "by_number_count": len(by_number), "updated_at": now()})
        save(EXECUTION.name, state)
        raise RuntimeError("Created Ozon record is not uniquely visible; stop without binding")
    stored_number = str(by_id[0].get("certificate_number", ""))
    info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": stored_number}).get("result", {})
    if int(info.get("certificate_id", -1)) != certificate_id or info.get("type_code") != "certificate_of_conformity":
        state.update({"phase": "created_record_identity_conflict", "live_info": info, "updated_at": now()})
        save(EXECUTION.name, state)
        raise RuntimeError("Ozon record type or ID conflicts; stop without binding")
    if info.get("status_code") in {"declined", "rejected", "cancelled", "invalid"}:
        state.update({"phase": "certificate_rejected", "live_info": info, "updated_at": now()})
        save(EXECUTION.name, state)
        raise RuntimeError("Ozon rejected the certificate; stop without binding")
    if str(info.get("issue_date", ""))[:10] != ISSUE_DATE or str(info.get("expire_date", ""))[:10] != EXPIRY_DATE:
        state.update({"phase": "live_date_conflict", "live_info": info, "updated_at": now()})
        save(EXECUTION.name, state)
        raise RuntimeError("Ozon stored dates differ from the original and live FSA record")

    before = read_bindings(client, certificate_id)
    grouped: dict[str, list[dict]] = collections.defaultdict(list)
    for item in before:
        grouped[str(item.get("sku", ""))].append(item)
    outside = sorted(set(grouped) - set(target_map))
    duplicates = sorted(sku for sku, values in grouped.items() if len(values) != 1)
    identity_conflicts = [sku for sku, values in grouped.items()
                          if sku in target_map and {str(item.get("product_id")) for item in values} != {target_map[sku]}]
    if outside or duplicates or identity_conflicts:
        state.update({"phase": "initial_binding_conflict", "outside_skus": outside,
                      "duplicate_skus": duplicates, "identity_conflicts": identity_conflicts,
                      "updated_at": now()})
        save(EXECUTION.name, state)
        raise RuntimeError("Initial Ozon bindings contain an outside SKU, duplicate, or product identity conflict")
    missing = sorted(set(target_map) - set(grouped))
    if seed["sku"] not in grouped:
        state.update({"phase": "created_seed_binding_missing", "updated_at": now()})
        save(EXECUTION.name, state)
        raise RuntimeError("Seed SKU is absent after successful create; reconcile before writing")

    for offset in range(0, len(missing), 500):
        batch = missing[offset:offset + 500]
        entry = {"index": len(state["bind_batches"]) + 1, "sku_count": len(batch),
                 "first_sku": batch[0], "last_sku": batch[-1], "phase": "prepared"}
        state["bind_batches"].append(entry)
        state.update({"phase": "binding_missing_only", "updated_at": now()})
        save(EXECUTION.name, state)
        try:
            response = client.call("ozon", "/v1/product/certificate/bind", {
                "certificate_id": certificate_id, "skus": batch,
            }, mutation=True)
        except Exception as exc:
            entry.update({"phase": "uncertain", "error_type": type(exc).__name__})
            state.update({"phase": "bind_uncertain", "updated_at": now()})
            save(EXECUTION.name, state)
            raise RuntimeError("Bind outcome uncertain; reconcile live bindings before retry") from None
        entry["response"] = response
        entry["phase"] = "accepted" if response.get("result") is True else "rejected"
        state.update({"phase": "binding_missing_only", "updated_at": now()})
        save(EXECUTION.name, state)
        if entry["phase"] != "accepted":
            state.update({"phase": "bind_rejected", "updated_at": now()})
            save(EXECUTION.name, state)
            raise RuntimeError("Ozon rejected the missing-SKU bind batch; reconcile before another write")

    final_info = client.call("ozon", "/v1/product/certificate/info", {
        "certificate_number": stored_number,
    }).get("result", {})
    final_bindings = read_bindings(client, certificate_id)
    final_grouped: dict[str, list[dict]] = collections.defaultdict(list)
    for item in final_bindings:
        final_grouped[str(item.get("sku", ""))].append(item)
    missing_after = sorted(set(target_map) - set(final_grouped))
    outside_after = sorted(set(final_grouped) - set(target_map))
    duplicates_after = sorted(sku for sku, values in final_grouped.items() if len(values) != 1)
    identity_after = [
        {"sku": sku, "expected_product_id": target_map[sku],
         "live_product_ids": sorted({str(item.get("product_id")) for item in final_grouped[sku]})}
        for sku in sorted(set(target_map) & set(final_grouped))
        if {str(item.get("product_id")) for item in final_grouped[sku]} != {target_map[sku]}
    ]
    status_counts = collections.Counter(
        str(item.get("product_status_code")) for item in final_bindings
        if str(item.get("sku")) in target_map
    )
    verification = {
        "checked_at": now(), "number": NUMBER, "ozon_stored_number": stored_number,
        "certificate_id": certificate_id, "certificate_info": final_info,
        "target_skus": len(target_map), "live_binding_count": len(final_bindings),
        "covered_target_skus": len(set(target_map) & set(final_grouped)),
        "missing_skus": missing_after, "outside_target_skus": outside_after,
        "duplicate_skus": duplicates_after, "product_identity_mismatches": identity_after,
        "product_status_counts": dict(status_counts),
    }
    verification["all_target_skus_linked"] = not missing_after and not outside_after and not duplicates_after and not identity_after
    verification["all_product_statuses_approved"] = bool(status_counts) and set(status_counts) == {"approved"}
    verification["certificate_approved"] = final_info.get("status_code") == "approved"
    verification["all_verified"] = (
        verification["all_target_skus_linked"]
        and verification["all_product_statuses_approved"]
        and verification["certificate_approved"]
    )
    save(VERIFICATION.name, verification)
    phase = "all_verified" if verification["all_verified"] else (
        "all_links_verified_review_pending" if verification["all_target_skus_linked"] else "links_incomplete"
    )
    state.update({"phase": phase, "finished_at": now(), "verification_path": str(VERIFICATION)})
    save(EXECUTION.name, state)
    print(json.dumps({key: verification[key] for key in (
        "number", "ozon_stored_number", "certificate_id", "target_skus", "live_binding_count",
        "covered_target_skus", "missing_skus", "outside_target_skus", "duplicate_skus",
        "product_identity_mismatches", "product_status_counts", "certificate_approved", "all_verified",
    )}, ensure_ascii=False, indent=2))


def main() -> None:
    client = Client()
    if "--execute" in sys.argv:
        if not PLAN.is_file():
            raise RuntimeError("Saved dry-run plan is missing")
        saved_plan = json.loads(PLAN.read_text(encoding="utf-8"))
        execute(client, saved_plan)
        return
    if PLAN.exists():
        raise RuntimeError("A plan already exists; inspect it or reconcile before rebuilding")
    plan = build_plan(client)
    save(PLAN.name, plan)
    print(json.dumps({
        "ready": True,
        "number": plan["number"],
        "target_offers": len(plan["targets"]),
        "target_skus": len(plan["target_sku_to_product_id"]),
        "active_products": plan["ozon_preflight"]["active_product_count"],
        "existing_exact_records": plan["ozon_preflight"]["exact_normalized_record_count"],
        "local_copies": plan["local_copy_audit"]["target_copy_count"],
        "all_copies_match": plan["local_copy_audit"]["all_match_original"],
        "upload_bytes": plan["upload_file"]["size"],
        "plan_path": str(PLAN),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
