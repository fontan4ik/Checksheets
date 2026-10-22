"""Reconcile only the delayed WB 06897 residuals, retry absent rows once."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from api_client import Client, now  # noqa: E402
from execute_arlight_06897_source_map_20261014 import (  # noqa: E402
    DOC_FIELDS,
    EXPIRY,
    ISSUE,
    NUMBER,
    TNVED,
    card_docs,
    card_payload,
    comparable_card,
    direct_post,
    norm,
    read_one_wb_card,
    tnv_codes,
)

EXECUTION = BASE / "arlight_06897_source_map_execution_20261014.json"
READBACK = BASE / "arlight_06897_source_map_wb_readback_20261014.json"
OUT = BASE / "arlight_06897_wb_residual_recheck_20261014.json"
WB_HOST = "https://content-api.wildberries.ru"


def save(value: dict) -> None:
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(OUT)


def read_wb_errors(client: Client, target_offers: set[str], sent_at: dt.datetime) -> list[dict]:
    batches, cursor = [], {"limit": 100}
    for _ in range(100):
        response = client.http.post(WB_HOST + "/content/v2/cards/error/list", json={
            "cursor": cursor, "order": {"ascending": True}},
            headers=client.wb_headers, timeout=(15, 120))
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code in (429, 500, 502, 503, 504):
            if _ == 99:
                raise RuntimeError(f"WB error list remained transient: HTTP {response.status_code}")
            retry_after = response.headers.get("Retry-After")
            try:
                delay = max(float(retry_after), 1.0) if retry_after else min(60, 2 ** (_ + 1))
            except ValueError:
                delay = min(60, 2 ** (_ + 1))
            time.sleep(delay)
            continue
        time.sleep(1.05)
        if response.status_code != 200 or body.get("error"):
            raise RuntimeError(f"WB error list failed: HTTP {response.status_code}")
        data = body.get("data") or {}
        batches.extend(data.get("items") or [])
        page = data.get("cursor") or {}
        if page.get("next") is not True:
            break
        if not page.get("updatedAt") or not page.get("batchUUID"):
            raise RuntimeError("WB error-list cursor is incomplete")
        cursor = {"limit": 100, "updatedAt": page["updatedAt"], "batchUUID": page["batchUUID"]}
    else:
        raise RuntimeError("WB error-list pagination exceeded 100 pages")

    relevant = []
    for batch in batches:
        try:
            updated = dt.datetime.fromisoformat(str(batch.get("updatedAt") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        errors = batch.get("errors") or {}
        affected = target_offers & (set(batch.get("vendorCodes") or []) | set(errors))
        if updated >= sent_at and affected:
            relevant.append({"batchUUID": batch.get("batchUUID"), "updatedAt": batch.get("updatedAt"),
                             "vendor_codes": sorted(affected),
                             "errors": {key: errors[key] for key in affected if key in errors}})
    return relevant


def main() -> None:
    execution, prior = json.loads(EXECUTION.read_text()), json.loads(READBACK.read_text())
    if execution.get("phase") not in {"wb_readback_needs_reconciliation", "both_marketplaces_bound_wb_review_pending"}:
        raise RuntimeError("The original 491-card WB update is not in a reconciliable state")
    if prior.get("complete") is not True or prior.get("wb_target_count") != 491:
        raise RuntimeError("A complete prior 491-card readback is required")
    sent_at = dt.datetime.fromisoformat(execution["wb_update_sent_at_utc"])
    elapsed = (dt.datetime.now(dt.timezone.utc) - sent_at).total_seconds()
    if elapsed < 1800:
        raise RuntimeError(f"WB sync window is not complete yet ({int(elapsed)} seconds elapsed)")

    previous = {x["offer_id"]: x for x in prior["results"]}
    candidates = [x for x in prior["results"] if not x["declaration_visible"] or x.get("verdict") is None]
    if not candidates or len(candidates) > 60:
        raise RuntimeError(f"Unexpected residual candidate count: {len(candidates)}")
    client = Client()
    relevant_errors = read_wb_errors(client, {x["offer_id"] for x in candidates}, sent_at)

    current = []
    for index, old in enumerate(candidates, 1):
        card = read_one_wb_card(client, old["offer_id"])
        if str(card.get("vendorCode") or "") != old["offer_id"] or str(card.get("nmID") or "") != old["nmID"]:
            raise RuntimeError(f"WB card identity changed for {old['offer_id']}")
        rows = [d for d in card_docs(card) if norm(d.get("number")) == norm(NUMBER)]
        if len(rows) > 1:
            raise RuntimeError(f"Duplicate 06897 rows appeared for {old['offer_id']}")
        visible = bool(rows and int(rows[0].get("type") or 0) == 2
                       and str(rows[0].get("startDate") or "")[:10] == ISSUE
                       and str(rows[0].get("endDate") or "")[:10] == EXPIRY
                       and rows[0].get("isEndless") is False)
        current.append({"offer_id": old["offer_id"], "nmID": str(card["nmID"]), "card": card,
                        "declaration_visible": visible,
                        "verdict": rows[0].get("verdict") if rows else None,
                        "excludeDocuments": (card.get("documents") or {}).get("excludeDocuments")})
        if index % 10 == 0 or index == len(candidates):
            print(f"Residual WB reread {index}/{len(candidates)}", flush=True)

    absent = [x for x in current if not x["declaration_visible"]]
    result = {"checked_at_utc": now(), "read_only_reconciliation": True,
              "initial_target_count": 491, "residual_count": len(current),
              "visible_after_sync": sum(x["declaration_visible"] for x in current),
              "verdict_counts_after_sync": dict(Counter(
                  str((x.get("verdict") or {}).get("reason") or "NO_VERDICT")
                  for x in current if x["declaration_visible"])),
              "still_absent_count": len(absent), "post_original_update_errors": relevant_errors,
              "retry_attempted": False,
              "results": [{k: v for k, v in x.items() if k != "card"} for x in current],
              "local_cleanup_allowed": False}
    if not absent:
        result["state"] = "all_residual_rows_visible_pending_wb_verdicts"
        save(result)
        print(json.dumps({k: v for k, v in result.items() if k != "results"}, ensure_ascii=False, indent=2))
        return
    if relevant_errors:
        result["state"] = "absent_rows_have_wb_errors_investigate_before_retry"
        save(result)
        print(json.dumps({k: v for k, v in result.items() if k != "results"}, ensure_ascii=False, indent=2))
        return

    payloads, before = [], []
    for row in absent:
        card = row["card"]
        if card.get("brand") != "Arlight" or tnv_codes(card) != [TNVED]:
            raise RuntimeError(f"WB brand/TN VED changed for {row['offer_id']}")
        payload = card_payload(card)
        if any(payload.get(key) != card.get(key) for key in (
                "nmID", "vendorCode", "brand", "title", "description", "dimensions",
                "characteristics", "sizes", "kizMarked", "gtin") if key in card):
            raise RuntimeError(f"Retry payload changes an unrelated field for {row['offer_id']}")
        payloads.append(payload)
        before.append({"offer_id": row["offer_id"], "nmID": row["nmID"], "card": card})
    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode()
    payload_sha = hashlib.sha256(encoded).hexdigest()
    result.update({"retry_attempted": True, "retry_card_count": len(payloads),
                   "retry_payload_bytes": len(encoded), "retry_payload_sha256": payload_sha,
                   "retry_sent_at_utc": now(), "state": "retry_response_pending"})
    save(result)
    status, body, error_type = 0, {}, None
    try:
        status, body = direct_post(client, "wb", "/content/v2/cards/update", payloads, mutation=True)
    except Exception as exc:  # Preserve uncertainty; never blindly repeat a marketplace write.
        error_type = type(exc).__name__
    result["retry_response"] = {"http_status": status, "error": body.get("error"),
                                "errorText": body.get("errorText"),
                                "additionalErrors": body.get("additionalErrors"),
                                "error_type": error_type}
    if status != 200 or body.get("error") is not False:
        result["state"] = "retry_outcome_uncertain_reconcile_only"
        save(result)
        print(json.dumps({k: v for k, v in result.items() if k != "results"}, ensure_ascii=False, indent=2))
        return

    after_rows = []
    for index, old in enumerate(before, 1):
        after = read_one_wb_card(client, old["offer_id"])
        matches = [d for d in card_docs(after) if norm(d.get("number")) == norm(NUMBER)]
        visible = (len(matches) == 1 and int(matches[0].get("type") or 0) == 2
                   and str(matches[0].get("startDate") or "")[:10] == ISSUE
                   and str(matches[0].get("endDate") or "")[:10] == EXPIRY
                   and matches[0].get("isEndless") is False)
        after_rows.append({"offer_id": old["offer_id"], "nmID": str(after.get("nmID") or ""),
                           "declaration_visible": visible,
                           "all_other_card_fields_preserved": comparable_card(old["card"]) == comparable_card(after),
                           "excludeDocuments": (after.get("documents") or {}).get("excludeDocuments"),
                           "verdict": matches[0].get("verdict") if matches else None})
        if index % 10 == 0 or index == len(before):
            print(f"Post-retry WB reread {index}/{len(before)}", flush=True)
    result.update({"retry_readback_complete": True, "retry_readback": after_rows,
                   "retry_visible_count": sum(x["declaration_visible"] for x in after_rows),
                   "retry_other_fields_preserved_count": sum(x["all_other_card_fields_preserved"] for x in after_rows),
                   "state": ("retry_submitted_sync_pending" if any(not x["declaration_visible"] for x in after_rows)
                             else "retry_visible_pending_wb_verdicts")})
    save(result)
    print(json.dumps({k: v for k, v in result.items() if k not in ("results", "retry_readback")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
