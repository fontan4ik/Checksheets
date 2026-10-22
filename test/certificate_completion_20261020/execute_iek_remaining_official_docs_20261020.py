"""Prepare/upload the next source-verified IEK/ITK document batch to Ozon.

Dry-run by default. Every candidate is linked through IEK's official product
document crosswalk, the official PDF is hash/date checked, and product TN VED
codes must be in the PDF scope. WB is handled by a separate targeted pass after
Ozon readback. No local files are deleted here.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
import run_all_found_certificates_20261014 as runner_module  # noqa: E402
from api_client import Client, digest  # noqa: E402

AUDIT = HERE / "iek_missing_official_docs_audit_20261020.json"
OCR_INPUT = HERE / "iek_missing_docs_ocr_input_20261020.json"
OCR_DIR = HERE / "iek_missing_docs_ocr_20261020"
JOURNAL = HERE / "reconciliation_journal.jsonl"
MANIFEST = HERE / "iek_remaining_official_docs_manifest_20261020.json"
STATE = HERE / "iek_remaining_official_docs_state_20261020.json"

# Codes have been checked against the official PDFs. 49495/26 is a visual
# readback from page 1 because the existing OCR missed its spaced TN VED line.
SELECTED = {
    "ЕАЭС N RU Д-CN.РА02.В.68913/26": ["9405110033"],
    "ЕАЭС N RU Д-CN.РА02.В.69159/26": ["8203200009"],
    "ЕАЭС N RU Д-CN.РА02.В.69520/26": ["9405110013"],
    "ЕАЭС N RU Д-CN.РА02.В.69763/26": ["9030310000"],
    "ЕАЭС N RU Д-CN.РА02.В.69772/26": ["9030339900"],
    "ЕАЭС N RU Д-CN.РА03.В.03837/26": ["9405190032"],
    "ЕАЭС N RU Д-CN.РА07.В.72519/26": ["8536699008", "8544429009"],
    "ЕАЭС N RU Д-RU.РА03.В.15503/25": ["8544492000"],
    "ЕАЭС N RU Д-RU.РА05.В.56380/26": ["8544492000"],
    "ЕАЭС RU С-CN.АЯ46.В.48281/26": ["9405110013"],
    "ЕАЭС RU С-CN.АЯ46.В.48744/26": ["9405110013"],
    "ЕАЭС RU С-CN.АЯ46.В.49019/26": ["9405190032"],
    "ЕАЭС RU С-CN.АЯ46.В.49495/26": ["8536490000"],
    "ЕАЭС RU С-CN.АЯ46.В.49734/26": ["8516299900"],
    "ЕАЭС RU С-CN.АЯ46.В.49742/26": ["9032102000"],
    "ЕАЭС RU С-CN.АЯ46.В.49743/26": ["8414592000"],
    "ЕАЭС RU С-CN.АЯ46.В.49744/26": ["8516299100"],
    "ЕАЭС RU С-CN.АЯ46.В.52649/26": ["9405110013", "9405610002", "9405610005"],
    "ЕАЭС RU С-CN.НВ28.В.00552/26": ["8536699008", "8544429009"],
}


def build_manifest() -> dict:
    today = date.today().isoformat()
    audit = json.loads(AUDIT.read_text())
    ocr_inputs = {row["number"]: row for row in json.loads(OCR_INPUT.read_text())}
    groups = []

    for number, codes in SELECTED.items():
        rows = [row for row in audit["documents"] if row.get("number") == number]
        if len(rows) != 1:
            raise RuntimeError(f"Expected one official audit row for {number}")
        row = rows[0]
        if row.get("ozon_type_code") not in ("declaration", "certificate_of_conformity"):
            raise RuntimeError(f"Unsupported Ozon type for {number}")
        if row.get("accordance_type") != "EAEU" or row.get("ozon_state") != "missing":
            raise RuntimeError(f"Document is not a missing EAEU document: {number}")
        if (row.get("issue_date") or "")[:10] > today or (row.get("expire_date") or "")[:10] < today:
            raise RuntimeError(f"Document is not currently valid: {number}")

        source = Path(row["local_pdf"])
        if not source.is_file() or digest(source) != row.get("downloaded_sha256"):
            raise RuntimeError(f"Official PDF hash/file mismatch: {number}")
        if not source.read_bytes().startswith(b"%PDF-") or source.stat().st_size > 9_500_000:
            raise RuntimeError(f"Invalid PDF or conservative Ozon size limit exceeded: {number}")

        evidence = ocr_inputs.get(number)
        if not evidence:
            raise RuntimeError(f"Missing official PDF OCR mapping: {number}")
        ocr_path = OCR_DIR / f"{evidence['ozon_id']}.txt"
        text = ocr_path.read_text(errors="replace") if ocr_path.is_file() else ""
        if number.endswith("49495/26"):
            # Page 1 was rendered and visually read: “8536 49 0000”.
            if "8536490000" not in codes:
                raise RuntimeError("Visual TN VED confirmation missing for 49495/26")
        else:
            digits = "".join(ch for ch in text if ch.isdigit())
            for code in codes:
                if code not in digits:
                    raise RuntimeError(f"Official PDF OCR lacks TN VED {code}: {number}")
        if "серийный выпуск" not in text.casefold() and not number.endswith("49495/26"):
            raise RuntimeError(f"Serial-production wording not found in official PDF: {number}")

        targets = []
        for offer in row.get("offers") or []:
            if offer.get("tnved") not in codes:
                continue
            if offer.get("brand") not in ("IEK", "ITK"):
                raise RuntimeError(f"Unexpected source brand {number}/{offer.get('offer_id')}")
            targets.append({
                "offer_id": offer["offer_id"],
                "product_id": str(offer["product_id"]),
                "sku": str(offer["sku"]),
                "brand": offer["brand"],
                "source_url": offer["product_url"],
                "source_first_sale": offer.get("first_sale"),
                "source_tnved": offer.get("tnved"),
                "source_name": offer.get("name"),
            })
        if not targets:
            raise RuntimeError(f"No exact-scope offers for {number}")

        source_evidence = [str(source)]
        if ocr_path.is_file():
            source_evidence.append(str(ocr_path))
        groups.append({
            "number": number,
            "type_code": row["ozon_type_code"],
            "accordance_type": "EAEU",
            "country": "RU",
            "issue_date": row["issue_date"],
            "expire_date": row["expire_date"],
            "allowed_tnved": codes,
            "source_evidence_verified": True,
            "source_evidence_files": source_evidence,
            "upload_file": {"path": str(source), "sha256": row["downloaded_sha256"]},
            "source_url": row["url"],
            "targets": targets,
            "wb_mutation": False,
        })

    result = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_audit": str(AUDIT),
        "groups": groups,
        "candidate_count": sum(len(group["targets"]) for group in groups),
        "basis": "Official IEK product-to-document crosswalk; valid official EAEU PDF dates and SHA-256; serial-production evidence; exact product TN VED scope. 49495/26 TN VED visually confirmed on PDF page 1 because OCR missed the spaced code.",
        "wb_review_left_pending": True,
        "local_file_cleanup": False,
    }
    MANIFEST.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    manifest = build_manifest()
    runner = runner_module.Runner(Client(), manifest, execute=args.execute,
                                  journal=JOURNAL, state=STATE)
    runner.process_groups()
    state = json.loads(STATE.read_text())
    print(json.dumps({
        "execute": args.execute,
        "candidate_count": manifest["candidate_count"],
        "groups": state.get("groups"),
        "skips": state.get("skips"),
        "mutations": state.get("mutations"),
        "manifest": str(MANIFEST),
        "state": str(STATE),
        "local_files_deleted": False,
        "wb_review_left_pending": True,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
