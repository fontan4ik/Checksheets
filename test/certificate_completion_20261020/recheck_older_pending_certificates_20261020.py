"""Fresh read-only Ozon verification for certificate groups pending on Oct 16."""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "certificate_api_pilot_20261012"))
from api_client import Client  # noqa: E402

TARGET_IDS = {
    5448185, 5448204, 5448212, 5448220, 5448240,
    5448281, 5448284, 5448305, 5500453,
}
OUT = HERE / "older_pending_certificates_live_recheck_20261020.json"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    client = Client()
    records = []
    page = 1
    page_count = 1
    ids = set()
    while page <= page_count:
        result = client.call(
            "ozon", "/v1/product/certificate/list",
            {"page": page, "page_size": 100}, mutation=False,
        ).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate page omitted certificates")
        for row in batch:
            cid = int(row.get("certificate_id") or 0)
            if not cid or cid in ids:
                raise RuntimeError("Ozon certificate page has missing/duplicate ID")
            ids.add(cid)
        records.extend(batch)
        page_count = int(result.get("page_count") or page)
        page += 1
    by_id = {int(row["certificate_id"]): row for row in records}
    missing = sorted(TARGET_IDS - set(by_id))
    if missing:
        raise RuntimeError(f"Target certificate records missing: {missing}")

    results = []
    for cid in sorted(TARGET_IDS):
        record = by_id[cid]
        bindings = client.ozon_bindings(cid)
        expected = int(record.get("products_count") or 0)
        if len(bindings) != expected:
            raise RuntimeError(
                f"Certificate {cid}: binding count {len(bindings)} != listed count {expected}"
            )
        counts = Counter(str(x.get("product_status_code") or "unknown") for x in bindings)
        results.append({
            "certificate_id": cid,
            "number": record.get("certificate_number"),
            "document_status": record.get("status_code"),
            "type_code": record.get("type_code"),
            "issue_date": record.get("issue_date"),
            "expire_date": record.get("expire_date"),
            "expected_binding_count": expected,
            "read_binding_count": len(bindings),
            "binding_status_counts": dict(counts),
            "bindings": bindings,
        })
    out = {
        "checked_at": stamp(),
        "read_only": True,
        "source": "live Ozon /v1/product/certificate/list + /v1/product/certificate/products/list",
        "target_records_expected": len(TARGET_IDS),
        "target_records_found": len(results),
        "records": results,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({
        "checked_at": out["checked_at"],
        "records": len(results),
        "binding_totals": sum(x["read_binding_count"] for x in results),
        "documents_by_status": dict(Counter(x["document_status"] for x in results)),
        "bindings_by_status": dict(Counter(
            status for x in results
            for status, count in x["binding_status_counts"].items()
            for _ in range(count)
        )),
        "output": str(OUT),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
