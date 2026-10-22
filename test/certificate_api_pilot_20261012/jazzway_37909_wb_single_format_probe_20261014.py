"""Probe one exact, freshly approved Jazzway row with RFC3339 dates."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import Counter
from pathlib import Path

from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import (
    UPDATE_CARD_FIELDS, comparable_card, doc_key, norm_number,
)

BASE_DIR = Path(__file__).resolve().parent
SOURCE = BASE_DIR / "jazzway_37909_approved_ozon_to_wb_preflight_20261014.json"
RUN = BASE_DIR / "jazzway_37909_wb_single_rfc3339_probe_20261014.json"
NUMBER = "ЕАЭС N RU Д-HK.РА08.В.37909/22"
TNVED = "8539520009"


def card_documents(card: dict) -> list[dict]:
    return [{k: item[k] for k in (
        "id", "type", "number", "productNumber", "tradeName", "applicant",
        "startDate", "endDate", "isEndless",
    ) if k in item} for item in ((card.get("documents") or {}).get("items") or [])]


def tnved_values(card: dict) -> list[str]:
    result = []
    for ch in card.get("characteristics") or []:
        if "тнвэд" in str(ch.get("name") or "").lower().replace("ё", "е"):
            raw = ch.get("value")
            result.extend(str(v).strip() for v in (raw if isinstance(raw, list) else [raw])
                          if v not in (None, ""))
    return sorted(set(result))


def doc_signatures(docs: list[dict]) -> Counter:
    return Counter((doc_key(d), str(d.get("startDate") or "")[:10],
                    str(d.get("endDate") or "")[:10]) for d in docs)


def wb_datetime(value: str) -> str:
    value = str(value or "")
    return value if "T" in value else f"{value}T00:00:00Z"


def main() -> None:
    if RUN.exists():
        raise RuntimeError("Probe marker exists; reconcile before any retry")
    source = json.loads(SOURCE.read_text())
    checked = dt.datetime.fromisoformat(source["checked_at"].replace("Z", "+00:00"))
    if (dt.datetime.now(dt.timezone.utc) - checked).total_seconds() > 1200:
        raise RuntimeError("Ozon approval snapshot is stale")
    candidates = source.get("wb_candidates") or []
    if len(candidates) != 140 or source.get("declined_targets") != 18:
        raise RuntimeError("Ozon final status counts changed; stop and re-audit")
    row = candidates[0]
    document = source["certificate"]
    issue, expiry = str(document.get("issue_date") or "")[:10], str(document.get("expire_date") or "")[:10]
    if (document.get("status_code") != "approved" or not issue or not expiry
            or expiry < dt.datetime.now(dt.timezone.utc).date().isoformat()):
        raise RuntimeError("Document status or dates are not current")

    client = Client()
    cards = client.wb_cards(row["offer_id"])
    if len(cards) != 1:
        raise RuntimeError("Exact WB card is missing or ambiguous")
    before = cards[0]
    if (before.get("vendorCode") != row["offer_id"] or not before.get("nmID")
            or before.get("brand") != "Jazzway" or tnved_values(before) != [TNVED]):
        raise RuntimeError("Fresh WB identity, brand, or TNVED scope check failed")
    desired = {"type": 2, "number": NUMBER, "startDate": wb_datetime(issue),
               "endDate": wb_datetime(expiry), "isEndless": False}
    number_key = norm_number(NUMBER)
    same_number = [d for d in card_documents(before)
                   if norm_number(d.get("number", "")) == number_key]
    if same_number:
        raise RuntimeError("Document number already exists; reconcile current WB card")

    payload = {k: before[k] for k in UPDATE_CARD_FIELDS if k in before}
    payload["nmID"] = before["nmID"]
    payload["vendorCode"] = row["offer_id"]
    payload["documents"] = {
        "items": card_documents(before) + [desired],
        "excludeDocuments": False,
    }
    encoded = json.dumps([payload], ensure_ascii=False, separators=(",", ":")).encode()
    RUN.write_text(json.dumps({
        "started_at": now(), "state": "submitting_once", "offer_id": row["offer_id"],
        "nmID": before["nmID"], "request_sha256": hashlib.sha256(encoded).hexdigest(),
        "request_bytes": len(encoded), "document": desired,
    }, ensure_ascii=False, indent=2))
    response = None
    error = None
    try:
        response = client.call("wb", "/content/v2/cards/update", [payload], mutation=True)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    # Reconcile immediately even when the API call raised; never retry here.
    after_cards = client.wb_cards(row["offer_id"])
    readback = {"state": "missing_or_ambiguous", "matches": len(after_cards)}
    if len(after_cards) == 1:
        after = after_cards[0]
        docs = card_documents(after)
        matches = [d for d in docs if doc_key(d) == doc_key(desired)
                   and str(d.get("startDate") or "")[:10] == issue
                   and str(d.get("endDate") or "")[:10] == expiry]
        readback = {
            "state": "visible" if len(matches) == 1 else "missing_or_duplicate",
            "matches": len(matches), "verdict": matches[0].get("verdict") if len(matches) == 1 else None,
            "unrelated_fields_preserved": comparable_card(before) == comparable_card(after),
            "preexisting_documents_preserved": not bool(
                doc_signatures(card_documents(before)) - doc_signatures(docs)),
            "overallVerdict": (after.get("documents") or {}).get("overallVerdict"),
        }
    output = {
        "finished_at": now(), "state": "reconciled", "offer_id": row["offer_id"],
        "nmID": before["nmID"], "http_error": error, "response": response,
        "readback": readback,
    }
    RUN.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps(output, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
