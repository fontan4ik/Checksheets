"""Reconcile the WB 429 batch and submit only still-missing 52132/25 links."""
from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))

from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    OZON_TO_WB_TYPE, copy_documents, doc_key, norm_number, wb_datetime,
)
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА09.В.52132/25"
ALLOWED = {"9405110013", "9405110033", "9405110039",
           "9405420012", "9405420032", "9405420039"}
STATE = HERE / "arlight_52132_wb_execution_state_20261020.json"
BEFORE = HERE / "arlight_52132_wb_before_cards_20261020.json"
OZON = HERE / "arlight_52132_ozon_preflight_live_20261020.json"
OZON_POST = HERE / "arlight_52132_ozon_postwrite_readback_20261020.json"
INITIAL_JOURNAL = HERE / "arlight_52132_wb_execution_journal_20261020.jsonl"
RECOVERY_JOURNAL = HERE / "arlight_52132_wb_recovery_journal_20261020.jsonl"
RECOVERY_BEFORE = HERE / "arlight_52132_wb_recovery_cards_before_20261020.json"


def save(path: pathlib.Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(path)


def record_journal(row: dict) -> None:
    with RECOVERY_JOURNAL.open("a") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()


def fetch_cards(client: Client, wanted: set[str]) -> tuple[dict, int, int]:
    cursor = {"limit": 100}
    seen = set()
    found: dict[str, list[dict]] = collections.defaultdict(list)
    pages = total = 0
    while True:
        body = client.call("wb", "/content/v2/get/cards/list", {
            "settings": {"sort": {"ascending": True}, "cursor": cursor,
                         "filter": {"withPhoto": -1}}
        })
        batch = body.get("cards")
        if body.get("error") or not isinstance(batch, list):
            raise RuntimeError("invalid_wb_full_catalog_read")
        pages += 1
        total += len(batch)
        for card in batch:
            offer = str(card.get("vendorCode") or "")
            if offer in wanted:
                found[offer].append(card)
        if len(batch) < 100:
            break
        c = body.get("cursor") or {}
        signature = (c.get("updatedAt"), c.get("nmID"))
        if None in signature or signature in seen:
            raise RuntimeError("repeated_or_incomplete_wb_cursor")
        seen.add(signature)
        cursor = {"limit": 100, "updatedAt": signature[0], "nmID": signature[1]}
        if pages % 50 == 0:
            print(json.dumps({"phase": "recovery_full_read", "pages": pages,
                              "cards": total,
                              "targets_found": sum(map(len, found.values()))}), flush=True)
    return found, pages, total


def tnved(card: dict) -> list[str]:
    values = []
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        values.extend(str(x or "").split(" - ", 1)[0].strip()
                      for x in (raw if isinstance(raw, list) else [raw]))
    return sorted(set(values))


def main() -> None:
    if RECOVERY_JOURNAL.exists() or RECOVERY_BEFORE.exists():
        raise RuntimeError("recovery_artifacts_exist_read_them_before_any_retry")
    state = json.loads(STATE.read_text())
    baseline = json.loads(BEFORE.read_text())
    ozon = json.loads(OZON.read_text())
    ozon_post = json.loads(OZON_POST.read_text())
    if state.get("phase") != "wb_batch_updates_accepted" or len(state.get("batches", [])) != 6:
        raise RuntimeError("unexpected_initial_wb_batch_state")
    if not ozon_post.get("all_target_links_approved"):
        raise RuntimeError("ozon_links_not_approved")

    source = {row["offer_id"]: row for row in ozon["targets"]}
    old_cards = baseline.get("cards") or {}
    wanted_offers = set(source)
    if set(old_cards) != wanted_offers:
        raise RuntimeError("original_exact_wb_card_snapshot_incomplete")
    client = Client()
    found, pages, total = fetch_cards(client, wanted_offers)
    if set(found) != wanted_offers:
        raise RuntimeError("current_wb_target_set_changed")

    doc = {
        "type": OZON_TO_WB_TYPE["declaration"], "number": NUMBER,
        "startDate": wb_datetime("2025-10-22"),
        "endDate": wb_datetime("2030-10-20"), "isEndless": False,
    }
    missing = []
    already = []
    excluded = []
    applied: list[str] = []
    scope_basis = collections.Counter()
    for offer in sorted(wanted_offers):
        rows = found[offer]
        if len(rows) != 1:
            raise RuntimeError(f"duplicate_or_missing_wb_card:{offer}")
        card = rows[0]
        old = old_cards[offer]
        if (card.get("vendorCode") != offer
                or str(card.get("nmID")) != str(old.get("nmID"))
                or str(card.get("brand") or "").casefold() != "arlight"):
            raise RuntimeError(f"live_wb_identity_changed:{offer}")
        codes = tnved(card)
        if len(codes) == 1 and codes[0] in ALLOWED:
            scope_basis["wb_tnved_allowed"] += 1
        elif not codes and len(source[offer].get("tnved") or []) == 1 \
                and source[offer]["tnved"][0] in ALLOWED:
            scope_basis["exact_ozon_offer_tnved_fallback_for_blank_wb"] += 1
        else:
            excluded.append({"offer_id": offer, "reason": "wb_tnved_out_of_scope_or_unconfirmed",
                             "wb_tnved": codes, "ozon_tnved": source[offer].get("tnved")})
            continue

        items = copy_documents(card)
        same = [item for item in items if norm_number(item.get("number")) == norm_number(NUMBER)]
        if same:
            if all(doc_key(item) == doc_key(doc)
                   and str(item.get("startDate", ""))[:10] == doc["startDate"][:10]
                   and str(item.get("endDate", ""))[:10] == doc["endDate"][:10]
                   for item in same):
                already.append(offer)
                applied.append(offer)
                continue
            raise RuntimeError(f"wb_same_number_conflict:{offer}")
        payload = merge_wb(card, [doc])
        if payload is None:
            already.append(offer)
            applied.append(offer)
        else:
            missing.append({"offer_id": offer, "nmID": card["nmID"], "payload": payload})

    save(RECOVERY_BEFORE, {
        "checked_at": now(), "read_only": True, "pages": pages,
        "full_catalog_cards": total, "cards": {k: v[0] for k, v in found.items()},
    })
    summary = {
        "started_at": now(), "phase": "reconciled_before_retry",
        "number": NUMBER, "pages_read": pages, "catalog_cards_read": total,
        "wb_target_cards": len(wanted_offers), "scope_evidence_basis_counts": dict(scope_basis),
        "exact_document_already_visible": len(already),
        "exact_document_missing": len(missing), "excluded_out_of_scope": excluded,
        "initial_successful_wb_batches": 6,
        "initial_batch_7_was_http_429": True,
        "wb_review_left_pending": True, "local_files_deleted": False,
        "batches": [],
    }
    save(STATE, {**state, "recovery": summary,
                 "phase": "reconciled_after_429_before_recovery_updates"})
    print(json.dumps({k: v for k, v in summary.items() if k != "excluded_out_of_scope"},
                     ensure_ascii=False), flush=True)

    for index, start in enumerate(range(0, len(missing), 100), 1):
        batch = missing[start:start + 100]
        payload = [row["payload"] for row in batch]
        payload_bytes = len(json.dumps(payload, ensure_ascii=False,
                                       separators=(",", ":")).encode())
        if payload_bytes > 9_500_000:
            raise RuntimeError(f"recovery_batch_too_large:{index}")
        marker = hashlib.sha256(json.dumps(payload, sort_keys=True,
                                            ensure_ascii=False).encode()).hexdigest()
        prepared = {
            "key": f"wb:52132:recovery:{marker}", "phase": "prepared", "at": now(),
            "batch": index, "cards": len(batch),
            "offers": [row["offer_id"] for row in batch],
            "request_sha256": marker, "request_bytes": payload_bytes,
        }
        record_journal(prepared)
        response = client.call("wb", "/content/v2/cards/update", payload, mutation=True)
        if response.get("error") is not False:
            record_journal({**prepared, "phase": "response_rejected", "response": response,
                            "finished_at": now()})
            raise RuntimeError(f"recovery_wb_batch_rejected:{index}")
        record_journal({**prepared, "phase": "response", "response": response,
                        "finished_at": now()})
        result = {"batch": index, "cards": len(batch), "response": response,
                  "offers": [row["offer_id"] for row in batch]}
        summary["batches"].append(result)
        summary["phase"] = "recovery_batches_accepted_readback_pending"
        summary["updated_at"] = now()
        save(STATE, {**state, "recovery": summary,
                     "phase": "recovery_batches_accepted_readback_pending"})
        print(json.dumps({"phase": summary["phase"], **result}, ensure_ascii=False), flush=True)
        if start + 100 < len(missing):
            time.sleep(7)

    summary["phase"] = "recovery_complete_full_readback_pending"
    summary["completed_at"] = now()
    save(STATE, {**state, "recovery": summary,
                 "phase": "recovery_complete_full_readback_pending"})
    print(json.dumps({"phase": summary["phase"], "recovery_cards": len(missing),
                      "already_exact": len(already), "full_readback_required": True},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
