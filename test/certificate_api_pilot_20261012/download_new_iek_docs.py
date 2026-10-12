"""Download and SHA-check official IEK PDFs for genuinely missing Ozon records."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
DEST = BASE / "iek_new_docs"
OUT = BASE / "iek_new_docs_download_audit.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    plan = json.loads((BASE / "iek_new_offer_document_plan.json").read_text())
    if not plan.get("official_iek_feed_sha256") or not plan.get("summary"):
        raise RuntimeError("Reviewed official IEK feed plan required")
    docs = {}
    for row in plan["document_assignments"]:
        if row["ozon_outcome"] != "new_upload_requires_pdf_validation":
            continue
        key = (row["ozon_type_code"], row["number"])
        item = docs.setdefault(key, {"type": row["document_type"], "type_code": row["ozon_type_code"],
                                     "number": row["number"], "issue_date": row["issue_date"],
                                     "expire_date": row["expire_date"], "source_url": row["source_url"],
                                     "offers": []})
        if (item["source_url"] != row["source_url"] or item["issue_date"] != row["issue_date"]
                or item["expire_date"] != row["expire_date"]):
            raise RuntimeError(f"Conflicting official file/date mapping for {row['number']}")
        item["offers"].append({"offer_id": row["offer_id"], "product_id": row["product_id"], "sku": row["sku"]})

    DEST.mkdir(parents=True, exist_ok=True)
    results = []
    for index, (key, item) in enumerate(sorted(docs.items()), 1):
        match = re.search(r"/([0-9a-fA-F]{64})\.pdf(?:$|\?)", item["source_url"])
        if not match:
            item.update({"download_status": "blocked_no_sha_in_official_url"})
            results.append(item)
            continue
        expected = match.group(1).lower()
        path = DEST / f"{expected}.pdf"
        if path.exists() and sha256(path) != expected:
            raise RuntimeError(f"Cached file hash mismatch for {path}")
        if not path.exists():
            request = urllib.request.Request(item["source_url"], headers={
                "User-Agent": "Checksheets-Certificate-Audit/1.0", "Accept-Encoding": "identity"})
            with urllib.request.urlopen(request, timeout=120) as response:
                data = response.read()
                if response.status != 200 or not data.startswith(b"%PDF-"):
                    raise RuntimeError(f"Official source did not return a PDF for {item['number']}")
                path.write_bytes(data)
            time.sleep(0.15)
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(f"PDF hash differs from official content-addressed URL for {item['number']}")
        info = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True)
        if info.returncode:
            raise RuntimeError(f"pdfinfo failed for {path.name}")
        pages = None
        for line in info.stdout.splitlines():
            if line.startswith("Pages:"):
                pages = int(line.split(":", 1)[1].strip())
                break
        if not pages:
            raise RuntimeError(f"Could not determine PDF page count for {path.name}")
        result = {**item, "file": str(path), "file_size": path.stat().st_size,
                  "sha256_expected_from_url": expected, "sha256_actual": actual, "page_count": pages,
                  "document_content_review": "pending embedded-text and visual inspection",
                  "download_status": "sha_verified"}
        results.append(result)
        print(json.dumps({"index": index, "total": len(docs), "number": item["number"],
                          "sha_ok": True, "pages": pages},
                         ensure_ascii=False), flush=True)
    audit = {"checked_at": datetime.now(timezone.utc).isoformat(),
             "official_feed_sha256": plan["official_iek_feed_sha256"],
             "documents": results, "complete": len(results) == len(docs)
             and all(x.get("download_status") == "sha_verified" for x in results)}
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    tmp.replace(OUT)
    print(json.dumps({"complete": audit["complete"], "documents": len(results),
                      "sha_verified": sum(x.get("download_status") == "sha_verified" for x in results),
                      "content_review_pending": sum(x.get("document_content_review") != "" for x in results)},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
