"""Fresh, three-card-only WB attachment for the already bound MOONLIGHT declaration."""
from __future__ import annotations

import collections
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    comparable_card, copy_documents, doc_key, norm_number, wb_datetime,
)
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402

SNAPSHOT = HERE / "live_marketplaces_snapshot_resume_20261022.json"
OZON_STATE = HERE / "arlight_moonlight_87392_execution_20261022.json"
BEFORE = HERE / "arlight_moonlight_87392_wb_before_20261022.json"
JOURNAL = HERE / "arlight_moonlight_87392_wb_journal_20261022.jsonl"
READBACK = HERE / "arlight_moonlight_87392_wb_readback_20261022.json"
NUMBER = "ЕАЭС N RU Д-CN.РА08.В.87392/22"
ISSUE = "2022-12-07"
EXPIRY = "2027-12-06"
TYPE = 2
TARGETS = [
    {"offer_id": "025550-1", "product_id": "6345705737", "sku": "5803567812", "nmID": "1605076424"},
    {"offer_id": "031017-1", "product_id": "6345705568", "sku": "5803568172", "nmID": "1605076425"},
    {"offer_id": "031117-1", "product_id": "6345705339", "sku": "5803568222", "nmID": "1605076423"},
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic(path: Path, value) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def signature(doc: dict) -> tuple:
    return (doc_key(doc), str(doc.get("startDate", ""))[:10],
            str(doc.get("endDate", ""))[:10], bool(doc.get("isEndless")))


def main() -> None:
    if any(p.exists() for p in (BEFORE, JOURNAL, READBACK)):
        raise RuntimeError("WB targeted execution artifacts exist; reconcile before retry")
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    prior_state = json.loads(OZON_STATE.read_text(encoding="utf-8"))
    if not snap.get("wb_catalog", {}).get("complete"):
        raise RuntimeError("Complete current WB catalog snapshot required")
    processed = [g for g in prior_state.get("groups", []) if g.get("number") == NUMBER and g.get("status") == "processed"]
    if len(processed) != 1 or not processed[0].get("certificate_id"):
        raise RuntimeError("No verified Ozon processing record; reconcile it before WB upload")
    cid = str(processed[0]["certificate_id"])
    desired = {"type": TYPE, "number": NUMBER, "startDate": wb_datetime(ISSUE),
               "endDate": wb_datetime(EXPIRY), "isEndless": False}
    client = Client()

    # Recheck the exact Ozon record and all three live product bindings.
    ozon_records = []
    for page in range(1, 101):
        data = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = data.get("certificates") or []
        ozon_records.extend(batch)
        if page >= int(data.get("page_count") or page):
            break
    exact_records = [c for c in ozon_records if norm_number(c.get("certificate_number")) == norm_number(NUMBER)]
    if len(exact_records) != 1 or str(exact_records[0].get("certificate_id")) != cid:
        raise RuntimeError("Ozon record missing/duplicated/changed before WB write")
    record = exact_records[0]
    if (record.get("type_code") != "declaration" or record.get("accordance_type_code") != "EAEU"
            or str(record.get("issue_date", ""))[:10] != ISSUE
            or str(record.get("expire_date", ""))[:10] != EXPIRY
            or record.get("status_code") not in ("approved", "pending", "checking", "in_review", "awaiting_verification")):
        raise RuntimeError("Ozon document type, dates, or status changed before WB write")
    bindings = client.ozon_bindings(cid)
    by_product = {str(b.get("product_id")): b for b in bindings}
    binding_evidence = []
    for t in TARGETS:
        b = by_product.get(t["product_id"])
        ok = bool(b and str(b.get("sku")) == t["sku"] and b.get("product_status_code") != "declined")
        binding_evidence.append({"offer_id": t["offer_id"], "product_id": t["product_id"],
                                 "sku": t["sku"], "bound": ok,
                                 "product_status_code": b.get("product_status_code") if b else None})
    if not all(x["bound"] for x in binding_evidence):
        raise RuntimeError("Ozon does not yet confirm every exact binding; WB write withheld")

    # Preflight only the three named WB cards; no other offer is eligible for mutation here.
    rows = []
    for t in TARGETS:
        cards = client.wb_cards(t["offer_id"])
        if len(cards) != 1:
            raise RuntimeError(f"WB exact card missing/duplicated: {t['offer_id']} ({len(cards)})")
        card = cards[0]
        if (str(card.get("nmID")) != t["nmID"] or card.get("vendorCode") != t["offer_id"]
                or str(card.get("brand", "")).strip().casefold() != "arlight"
                or "MOONLIGHT" not in (str(card.get("title") or "") + " " + str(card.get("description") or "")).upper()):
            raise RuntimeError("WB exact card identity, brand, or product series changed: " + t["offer_id"])
        matches = [d for d in copy_documents(card) if norm_number(d.get("number")) == norm_number(NUMBER)]
        if matches:
            exact = [d for d in matches if doc_key(d) == doc_key(desired)
                     and str(d.get("startDate", ""))[:10] == ISSUE
                     and str(d.get("endDate", ""))[:10] == EXPIRY
                     and d.get("isEndless") is False]
            if len(matches) != 1 or len(exact) != 1:
                raise RuntimeError("WB already has conflicting metadata for the same declaration: " + t["offer_id"])
            rows.append({"target": t, "before": card, "payload": None,
                         "already_exact": True, "prior_signatures": [signature(x) for x in copy_documents(card)]})
            continue
        payload = merge_wb(card, [desired])
        if not payload or payload.get("nmID") != card.get("nmID"):
            raise RuntimeError("WB update payload could not be safely prepared: " + t["offer_id"])
        rows.append({"target": t, "before": card, "payload": payload,
                     "already_exact": False, "prior_signatures": [signature(x) for x in copy_documents(card)]})

    writes = [r for r in rows if r["payload"] is not None]
    atomic(BEFORE, {"checked_at": now(), "certificate_id": cid,
                    "source_evidence": "FSA 17278483, active through 2027-12-06; exact MOONLIGHT series and Arlight brand",
                    "ozon_bindings": binding_evidence,
                    "cards": [{"offer_id": r["target"]["offer_id"], "before": r["before"],
                               "prior_signatures": r["prior_signatures"], "already_exact": r["already_exact"]}
                              for r in rows], "write_count": len(writes)})

    if writes:
        payloads = [r["payload"] for r in writes]
        encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode()
        if len(payloads) > 100 or len(encoded) > 9_000_000:
            raise RuntimeError("WB update payload exceeds safe limit")
        marker = hashlib.sha256(encoded).hexdigest()
        with JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"phase": "prepared", "at": now(), "endpoint": "/content/v2/cards/update",
                                "offers": [r["target"]["offer_id"] for r in writes],
                                "sha256": marker, "bytes": len(encoded)}, ensure_ascii=False) + "\n")
            f.flush()
        try:
            response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
        except Exception as exc:
            with JOURNAL.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"phase": "uncertain", "at": now(), "error_type": type(exc).__name__,
                                    "sha256": marker}, ensure_ascii=False) + "\n")
            raise RuntimeError("WB write outcome uncertain; live-read these three cards before any retry") from None
        with JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"phase": "response", "at": now(), "response": response,
                                "sha256": marker}, ensure_ascii=False) + "\n")
        if response.get("error") is not False or response.get("additionalErrors"):
            raise RuntimeError("WB rejected the targeted update; reconcile live cards before retry")
    else:
        response = {"skipped_write": True, "reason": "all exact documents already present"}

    # Read back only the same three cards. Never repeat an uncertain mutation.
    results = []
    for row in rows:
        t = row["target"]
        final = None
        for attempt in range(8):
            cards = client.wb_cards(t["offer_id"])
            if len(cards) == 1:
                card = cards[0]
                docs = ((card.get("documents") or {}).get("items") or [])
                same = [d for d in docs if norm_number(d.get("number")) == norm_number(NUMBER)]
                exact = [d for d in same if int(d.get("type") or 0) == TYPE
                         and str(d.get("startDate", ""))[:10] == ISSUE
                         and str(d.get("endDate", ""))[:10] == EXPIRY
                         and d.get("isEndless") is False]
                prior = collections.Counter(row["prior_signatures"])
                actual = collections.Counter(signature(d) for d in copy_documents(card))
                preserved = all(actual[k] >= n for k, n in prior.items())
                unrelated = comparable_card(card) == comparable_card(row["before"])
                if len(same) == 1 and len(exact) == 1 and preserved and unrelated:
                    final = {"offer_id": t["offer_id"], "nmID": str(card.get("nmID")),
                             "exact_document_visible": True, "prior_documents_preserved": preserved,
                             "other_card_fields_preserved": unrelated,
                             "excludeDocuments": (card.get("documents") or {}).get("excludeDocuments"),
                             "verdict": exact[0].get("verdict"), "review_left_to_wb": True}
                    break
            time.sleep(5)
        if final is None:
            final = {"offer_id": t["offer_id"], "nmID": t["nmID"],
                     "exact_document_visible": False, "reason": "readback_incomplete_after_8_checks",
                     "review_left_to_wb": True}
        results.append(final)
    report = {"checked_at": now(), "certificate_id": cid, "number": NUMBER,
              "ozon_status": record.get("status_code"), "ozon_bindings": binding_evidence,
              "wb_write_response": response, "wb_updated_cards": len(writes),
              "wb_cards": results, "complete": all(x.get("exact_document_visible") for x in results),
              "wb_review_left_pending": True, "local_source_pdf_deleted": False}
    atomic(READBACK, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["complete"]:
        raise RuntimeError("WB exact readback is incomplete; reconcile live cards before any retry")


if __name__ == "__main__":
    main()
