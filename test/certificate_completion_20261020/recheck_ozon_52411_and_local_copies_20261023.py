#!/usr/bin/env python3
"""Fresh read-only Ozon status and exact-source-copy audit for Gauss 52411/23."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402

RECORD_ID = "5966062"
NUMBER = "ЕАЭС N RU Д-CN.РА04.В.52411/23"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/gauss/25aeb2f93ed587f14b19dc21.pdf"
EXPECTED_SHA256 = "b9503157b344ec2ed68fe168f8b7c9f7046d28a1e7734b8a9949589c5b12ad3d"
OUT = HERE / "gauss_52411_ozon_and_local_copy_recheck_20261023.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if OUT.exists():
        raise RuntimeError("readback_artifact_exists_inspect_before_rechecking")
    client = Client()
    matches = []
    for page in range(1, 101):
        response = client.call("ozon", "/v1/product/certificate/list",
                               {"page": page, "page_size": 100}, mutation=False)
        result = response.get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_invalid")
        matches.extend(row for row in batch if str(row.get("certificate_id")) == RECORD_ID)
        if page >= int(result.get("page_count") or page):
            break
    if len(matches) != 1 or str(matches[0].get("certificate_number")) != NUMBER:
        raise RuntimeError(f"ozon_record_identity_ambiguous:{len(matches)}")
    record = matches[0]
    bindings = client.ozon_bindings(RECORD_ID)
    rows = [{
        "product_id": str(binding.get("product_id") or ""),
        "sku": str(binding.get("sku") or ""),
        "product_status_code": binding.get("product_status_code"),
    } for binding in bindings]
    copies = []
    cert_root = ROOT / "output_to_user/certificates"
    if SOURCE.is_file() and sha256(SOURCE) == EXPECTED_SHA256:
        for path in cert_root.rglob("*.pdf"):
            if path.is_file() and path.stat().st_size == SOURCE.stat().st_size and sha256(path) == EXPECTED_SHA256:
                copies.append(str(path))
    report = {
        "checked_at_utc": now(), "read_only": True,
        "document_number": NUMBER, "ozon_record_id": RECORD_ID,
        "ozon_record_status": record.get("status_code"),
        "ozon_binding_count": len(bindings),
        "ozon_binding_status_counts": {
            state: sum(row["product_status_code"] == state for row in rows)
            for state in sorted({row["product_status_code"] for row in rows})
        },
        "ozon_bindings": rows,
        "source_path": str(SOURCE), "source_exists": SOURCE.is_file(),
        "source_sha256_matches": SOURCE.is_file() and sha256(SOURCE) == EXPECTED_SHA256,
        "matching_local_pdf_copies": copies,
        "matching_local_pdf_copy_count": len(copies),
        "local_files_changed": False,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "ozon_bindings"},
                     ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
