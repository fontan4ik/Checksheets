"""Prepare or upload current official IEK documents missing from Ozon.

Dry-run unless --execute. The selected groups were crosswalked from official
IEK product pages and PDF scope/date checks. WB is read-only here; no local
source files are deleted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
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
SNAPSHOT = HERE / "live_marketplaces_snapshot_complete_20261020.json"
MANIFEST = HERE / "iek_missing_new_docs_manifest_20261020.json"
JOURNAL = HERE / "reconciliation_journal.jsonl"

# Exact TN VED codes verified in the official declaration/certificate PDFs.
SELECTED = {
    "ЕАЭС N RU Д-CN.РА02.В.66453/26": {"codes": ["8544429009"]},
    "ЕАЭС N RU Д-CN.РА02.В.66507/26": {"codes": ["8544492000"]},
    "ЕАЭС N RU Д-CN.РА02.В.68171/26": {"codes": ["9405110033"]},
    "ЕАЭС N RU Д-CN.РА02.В.68364/26": {"codes": ["8536901000"]},
    "ЕАЭС N RU Д-CN.РА02.В.71161/26": {"codes": ["8203200009", "8203400000"]},
    "ЕАЭС N RU Д-RU.РА04.В.27073/26": {"codes": ["8544492000"], "sample_month": "2023-09"},
    "ЕАЭС RU С-CN.АЯ46.В.47749/26": {"codes": ["8536490000"]},
    "ЕАЭС RU С-CN.АЯ46.В.48571/26": {"codes": ["8536490000", "8536699008"]},
}


def build_manifest() -> dict:
    today = date.today().isoformat()
    audit = json.loads(AUDIT.read_text())
    ocr_inputs = {row["number"]: row for row in json.loads(OCR_INPUT.read_text())}
    snapshot = json.loads(SNAPSHOT.read_text())
    if snapshot.get("complete") is not True:
        raise RuntimeError("Marketplace snapshot is incomplete")

    groups = []
    for number, policy in SELECTED.items():
        rows = [row for row in audit["documents"] if row.get("number") == number]
        if len(rows) != 1:
            raise RuntimeError(f"Expected exactly one official audit row for {number}")
        row = rows[0]
        if row.get("ozon_type_code") not in ("declaration", "certificate_of_conformity"):
            raise RuntimeError(f"Unsupported Ozon document type for {number}")
        if row.get("accordance_type") != "EAEU":
            raise RuntimeError(f"Not an EAEU document: {number}")
        if (row.get("issue_date") or "")[:10] > today or (row.get("expire_date") or "")[:10] < today:
            raise RuntimeError(f"Document is not currently valid: {number}")

        file = Path(row["local_pdf"])
        if not file.is_file() or digest(file) != row.get("downloaded_sha256"):
            raise RuntimeError(f"Official PDF hash/file check failed: {number}")
        if file.stat().st_size > 9_500_000:
            raise RuntimeError(f"PDF exceeds the conservative Ozon request limit: {number}")
        if not file.read_bytes()[:5] == b"%PDF-":
            raise RuntimeError(f"Downloaded file is not a PDF: {number}")

        ocr_row = ocr_inputs.get(number)
        if not ocr_row:
            raise RuntimeError(f"Missing OCR mapping: {number}")
        ocr_path = OCR_DIR / f"{ocr_row['ozon_id']}.txt"
        if not ocr_path.is_file():
            raise RuntimeError(f"Missing OCR evidence: {number}")
        text = ocr_path.read_text(errors="replace")
        digits = "".join(ch for ch in text if ch.isdigit())
        for code in policy["codes"]:
            if code not in digits:
                raise RuntimeError(f"Expected scope code {code} not present in OCR: {number}")

        targets = []
        for offer in row.get("offers") or []:
            if offer.get("tnved") not in policy["codes"]:
                continue
            if offer.get("brand") not in ("IEK", "ITK"):
                raise RuntimeError(f"Unexpected source brand for {number}/{offer.get('offer_id')}")
            first_sale = (offer.get("first_sale") or "")[:10]
            sample_month = policy.get("sample_month")
            if sample_month and (not first_sale or first_sale[:7] <= sample_month):
                continue
            target = {
                "offer_id": offer["offer_id"],
                "product_id": str(offer["product_id"]),
                "sku": str(offer["sku"]),
                "brand": offer["brand"],
                "source_url": offer["product_url"],
                "source_first_sale": offer.get("first_sale"),
                "source_tnved": offer.get("tnved"),
                "source_name": offer.get("name"),
            }
            targets.append(target)
        if not targets:
            raise RuntimeError(f"No products remain after exact scope/date checks: {number}")

        groups.append({
            "number": number,
            "type_code": row["ozon_type_code"],
            "accordance_type": "EAEU",
            "country": "RU",
            "issue_date": row["issue_date"],
            "expire_date": row["expire_date"],
            "allowed_tnved": policy["codes"],
            "source_evidence_verified": True,
            "source_evidence_files": [str(ocr_path), str(file)],
            "sample_month": policy.get("sample_month"),
            "upload_file": {"path": str(file), "sha256": row["downloaded_sha256"]},
            "source_url": row["url"],
            "targets": targets,
            "wb_mutation": False,
        })

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_audit": str(AUDIT),
        "snapshot": str(SNAPSHOT),
        "groups": groups,
        "blocked_document_keys": [],
        "candidate_count": sum(len(group["targets"]) for group in groups),
        "basis": (
            "Exact official IEK product-page document crosswalk; current PDF dates; "
            "PDF OCR TN VED scope; first-sale cutoff where sample date is stated; "
            "live Ozon product identity, brand, TN VED and binding state rechecked by runner."
        ),
        "wb_review_left_pending": True,
        "local_file_cleanup": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    manifest = build_manifest()
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    state = HERE / ("iek_missing_new_docs_execute_state_20261020.json" if args.execute
                    else "iek_missing_new_docs_dry_run_state_20261020.json")
    runner = runner_module.Runner(Client(), manifest, execute=args.execute,
                                  journal=JOURNAL, state=state)
    runner.process_groups()
    result = {
        "execute": args.execute,
        "candidate_count": manifest["candidate_count"],
        "groups": json.loads(state.read_text()).get("groups"),
        "skips": json.loads(state.read_text()).get("skips"),
        "mutations": json.loads(state.read_text()).get("mutations"),
        "manifest": str(MANIFEST),
        "state": str(state),
    }
    print(json.dumps(result, ensure_ascii=False))
    if args.execute:
        summary = json.loads(state.read_text())
        expected = {g["number"]: len(g["targets"]) for g in manifest["groups"]}
        if any(g.get("status") != "processed" or g.get("eligible") != expected.get(g.get("number"))
               for g in summary.get("groups", [])):
            raise SystemExit("Some groups did not finish cleanly; reconcile live state before retry.")


if __name__ == "__main__":
    main()
