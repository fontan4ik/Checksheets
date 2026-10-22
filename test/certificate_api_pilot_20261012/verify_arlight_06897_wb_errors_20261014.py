"""Read-only WB error-list reconciliation for the Arlight 06897 bulk update."""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from api_client import Client, now  # noqa: E402

EXEC = BASE / "arlight_06897_source_map_execution_20261014.json"
READBACK = BASE / "arlight_06897_source_map_wb_readback_20261014.json"
OUT = BASE / "arlight_06897_source_map_wb_errors_20261014.json"


def post(client: Client, path: str, payload: dict) -> dict:
    for attempt in range(7):
        response = client.http.post("https://content-api.wildberries.ru" + path, json=payload,
                                    headers=client.wb_headers, timeout=(15, 120))
        try:
            body = response.json()
        except ValueError:
            body = {"non_json_response": True}
        if response.status_code == 429 or response.status_code in (500, 502, 503, 504):
            if attempt == 6:
                raise RuntimeError(f"WB error-list read failed after bounded retries: HTTP {response.status_code}")
            retry_after = response.headers.get("Retry-After")
            try:
                delay = max(float(retry_after), 1.0) if retry_after else min(60, 2 ** (attempt + 1))
            except ValueError:
                delay = min(60, 2 ** (attempt + 1))
            time.sleep(delay)
            continue
        time.sleep(1.05)
        if response.status_code != 200 or body.get("error"):
            raise RuntimeError(f"WB error-list read returned HTTP {response.status_code}")
        return body
    raise RuntimeError("Unreachable error-list retry state")


def main() -> None:
    execution, readback = json.loads(EXEC.read_text()), json.loads(READBACK.read_text())
    if execution.get("phase") not in {"wb_update_response_received", "both_marketplaces_bound_wb_review_pending",
                                      "wb_readback_needs_reconciliation"}:
        raise RuntimeError("WB update acceptance/readback is not present")
    if not readback.get("complete") or len(readback.get("results") or []) != 491:
        raise RuntimeError("Complete 491-card readback is required")
    started = dt.datetime.fromisoformat(execution["wb_update_sent_at_utc"])
    target_offers = {x["offer_id"] for x in execution["wb_before"]}
    client = Client()
    batches = []
    cursor = {"limit": 100}
    for _ in range(100):
        body = post(client, "/content/v2/cards/error/list", {"cursor": cursor,
                                                              "order": {"ascending": True}})
        data = body.get("data") or {}
        items = data.get("items") or []
        batches.extend(items)
        cur = data.get("cursor") or {}
        if cur.get("next") is not True:
            break
        if not cur.get("updatedAt") or not cur.get("batchUUID"):
            raise RuntimeError("WB error-list cursor is incomplete")
        cursor = {"limit": 100, "updatedAt": cur["updatedAt"], "batchUUID": cur["batchUUID"]}
    else:
        raise RuntimeError("WB error-list pagination exceeded 100 batches")

    relevant = []
    for batch in batches:
        try:
            updated = dt.datetime.fromisoformat(str(batch.get("updatedAt") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        errors = batch.get("errors") or {}
        affected = target_offers & (set(batch.get("vendorCodes") or []) | set(errors))
        if updated >= started and affected:
            relevant.append({"batchUUID": batch.get("batchUUID"), "updatedAt": batch.get("updatedAt"),
                             "vendor_codes": sorted(affected),
                             "errors": {k: errors[k] for k in affected if k in errors}})

    missing = [x for x in readback["results"] if not x["declaration_visible"]]
    result = {"checked_at_utc": now(), "read_only": True, "target_count": len(target_offers),
              "wb_error_batches_total": len(batches), "post_update_error_batches_for_targets": len(relevant),
              "relevant_batches": relevant,
              "missing_targets": [{"offer_id": x["offer_id"], "nmID": x["nmID"],
                                   "excludeDocuments": x["excludeDocuments"],
                                   "documents": x["document_rows"]} for x in missing],
              "local_cleanup_allowed": False}
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(OUT)
    print(json.dumps({k: v for k, v in result.items() if k not in ("relevant_batches", "missing_targets")},
                     ensure_ascii=False, indent=2))
    print("RELEVANT", json.dumps(relevant, ensure_ascii=False, indent=2))
    print("MISSING", json.dumps(result["missing_targets"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
