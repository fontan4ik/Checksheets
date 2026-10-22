"""Safely add Arlight 52132/25 to exact in-scope WB cards and read it back."""
from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import sys
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))

from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    UPDATE_CARD_FIELDS,
    OZON_TO_WB_TYPE,
    comparable_card,
    copy_documents,
    doc_key,
    norm_number,
    wb_datetime,
)
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА09.В.52132/25"
TYPE_CODE = "declaration"
ALLOWED = {
    "9405110013", "9405110033", "9405110039",
    "9405420012", "9405420032", "9405420039",
}
OZON_PREFLIGHT = HERE / "arlight_52132_ozon_preflight_live_20261020.json"
OZON_POSTREAD = HERE / "arlight_52132_ozon_postwrite_readback_20261020.json"
WB_PREFLIGHT = HERE / "arlight_52132_wb_preflight_live_20261020.json"
STATE_PATH = HERE / "arlight_52132_wb_execution_state_20261020.json"
JOURNAL_PATH = HERE / "arlight_52132_wb_execution_journal_20261020.jsonl"
BEFORE_PATH = HERE / "arlight_52132_wb_before_cards_20261020.json"
READBACK_PATH = HERE / "arlight_52132_wb_postwrite_readback_20261020.json"


def save(path: pathlib.Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(path)


def journal(row: dict) -> None:
    with JOURNAL_PATH.open("a") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()


def current_catalog(client: Client, wanted: set[str]) -> tuple[dict, int, int]:
    cursor = {"limit": 100}
    seen: set[tuple[object, object]] = set()
    matches: dict[str, list[dict]] = collections.defaultdict(list)
    pages = raw_rows = 0
    while True:
        body = client.call("wb", "/content/v2/get/cards/list", {
            "settings": {
                "sort": {"ascending": True},
                "cursor": cursor,
                "filter": {"withPhoto": -1},
            }
        })
        batch = body.get("cards")
        if body.get("error") or not isinstance(batch, list):
            raise RuntimeError("invalid_full_wb_catalog_response")
        pages += 1
        raw_rows += len(batch)
        for card in batch:
            offer = str(card.get("vendorCode") or "")
            if offer in wanted:
                matches[offer].append(card)
        if len(batch) < 100:
            break
        c = body.get("cursor") or {}
        signature = (c.get("updatedAt"), c.get("nmID"))
        if None in signature or signature in seen:
            raise RuntimeError("incomplete_or_repeated_wb_cursor")
        seen.add(signature)
        cursor = {"limit": 100, "updatedAt": signature[0], "nmID": signature[1]}
        if pages % 50 == 0:
            print(json.dumps({"phase": "catalog_read", "pages": pages,
                              "cards_read": raw_rows,
                              "target_cards_found": sum(map(len, matches.values()))}),
                  flush=True)
    return matches, pages, raw_rows


def code_values(card: dict) -> list[str]:
    result = []
    for char in card.get("characteristics") or []:
        name = "".join(str(char.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = char.get("value")
        values = raw if isinstance(raw, list) else [raw]
        result.extend(str(value or "").split(" - ", 1)[0].strip() for value in values)
    return sorted(set(result))


def main() -> None:
    if READBACK_PATH.exists():
        raise RuntimeError("postwrite_readback_already_exists_inspect_before_rerun")
    if JOURNAL_PATH.exists():
        raise RuntimeError("journal_already_exists_reconcile_before_rerun")

    ozon = json.loads(OZON_PREFLIGHT.read_text())
    postread = json.loads(OZON_POSTREAD.read_text())
    wb_preflight = json.loads(WB_PREFLIGHT.read_text())
    if not postread.get("all_target_links_approved"):
        raise RuntimeError("ozon_target_bindings_not_fully_approved")
    if ozon.get("fresh_live_valid_target_count") != 929:
        raise RuntimeError("unexpected_live_ozon_target_count")

    ozon_by_offer = {row["offer_id"]: row for row in ozon["targets"]}
    prior_wb = {row["offer_id"]: row for row in wb_preflight["targets"]}
    if len(ozon_by_offer) != 929 or len(prior_wb) != 929:
        raise RuntimeError("preflight_target_set_changed")
    for offer, source in ozon_by_offer.items():
        if (len(source.get("tnved") or []) != 1
                or source["tnved"][0] not in ALLOWED):
            raise RuntimeError(f"ozon_scope_changed:{offer}")

    wanted_offers = set(ozon_by_offer)
    client = Client()
    cards_by_offer, pages, full_count = current_catalog(client, wanted_offers)
    if set(cards_by_offer) != wanted_offers:
        raise RuntimeError("wb_exact_target_offer_set_changed")

    date_start = wb_datetime("2025-10-22")
    date_end = wb_datetime("2030-10-20")
    desired = {
        "type": OZON_TO_WB_TYPE[TYPE_CODE],
        "number": NUMBER,
        "startDate": date_start,
        "endDate": date_end,
        "isEndless": False,
    }
    before: dict[str, dict] = {}
    updates: list[dict] = []
    excluded: list[dict] = []
    already_exact: list[str] = []
    evidence = collections.Counter()

    for offer in sorted(wanted_offers):
        source = ozon_by_offer[offer]
        rows = cards_by_offer[offer]
        if len(rows) != 1:
            excluded.append({"offer_id": offer, "reason": "duplicate_exact_wb_card"})
            continue
        card = rows[0]
        prior = prior_wb[offer]
        if (card.get("vendorCode") != offer
                or str(card.get("nmID")) != str(prior.get("nmID"))
                or str(card.get("brand") or "").casefold() != "arlight"):
            excluded.append({"offer_id": offer, "reason": "fresh_wb_identity_or_brand_conflict"})
            continue

        wb_codes = code_values(card)
        if len(wb_codes) == 1 and wb_codes[0] in ALLOWED:
            evidence["wb_tnved_allowed"] += 1
        elif not wb_codes and len(source.get("tnved") or []) == 1 \
                and source["tnved"][0] in ALLOWED:
            evidence["exact_ozon_offer_tnved_fallback_for_blank_wb"] += 1
        else:
            excluded.append({"offer_id": offer, "reason": "wb_tnved_out_of_scope_or_unconfirmed",
                             "wb_tnved": wb_codes, "ozon_tnved": source.get("tnved")})
            continue

        same = [doc for doc in copy_documents(card)
                if norm_number(doc.get("number")) == norm_number(NUMBER)]
        if same:
            exact = all(
                doc_key(doc) == doc_key(desired)
                and str(doc.get("startDate", ""))[:10] == date_start[:10]
                and str(doc.get("endDate", ""))[:10] == date_end[:10]
                for doc in same
            )
            if exact:
                already_exact.append(offer)
            else:
                excluded.append({"offer_id": offer, "reason": "same_number_type_or_date_conflict"})
            continue

        payload = merge_wb(card, [desired])
        if payload is None:
            already_exact.append(offer)
            continue
        before[offer] = card
        updates.append({"offer_id": offer, "nmID": card["nmID"], "payload": payload})

    if excluded:
        # Scope exclusions are expected only for mismatching WB TN VED codes.
        unexpected = [x for x in excluded if x["reason"] != "wb_tnved_out_of_scope_or_unconfirmed"]
        if unexpected:
            raise RuntimeError(f"unexpected_wb_prewrite_conflicts:{len(unexpected)}")
    save(BEFORE_PATH, {
        "checked_at": now(), "read_only_snapshot_basis": True,
        "pages": pages, "full_catalog_cards": full_count,
        "target_card_count": sum(map(len, cards_by_offer.values())),
        "cards": {offer: rows[0] for offer, rows in cards_by_offer.items() if len(rows) == 1},
    })
    state = {
        "started_at": now(), "number": NUMBER, "ozon_certificate_id": 5920271,
        "ozon_targets_approved": 929, "wb_target_cards_exact": 929,
        "wb_scope_evidence_basis_counts": dict(evidence),
        "wb_updates_planned": len(updates), "already_exact": len(already_exact),
        "excluded": excluded, "pages_read": pages, "catalog_rows_read": full_count,
        "phase": "preflight_passed_before_first_write", "batches": [],
        "wb_review_left_pending": True, "local_files_deleted": False,
    }
    save(STATE_PATH, state)
    print(json.dumps({k: v for k, v in state.items() if k not in {"excluded", "batches"}},
                     ensure_ascii=False), flush=True)

    batches = [updates[i:i + 100] for i in range(0, len(updates), 100)]
    for index, batch in enumerate(batches, 1):
        payload = [row["payload"] for row in batch]
        payload_bytes = len(json.dumps(payload, ensure_ascii=False,
                                       separators=(",", ":")).encode())
        if payload_bytes > 9_500_000:
            raise RuntimeError(f"wb_batch_payload_too_large:{index}")
        marker = hashlib.sha256(json.dumps(payload, sort_keys=True,
                                            ensure_ascii=False).encode()).hexdigest()
        prepared = {
            "key": f"wb:52132:{marker}", "phase": "prepared", "at": now(),
            "batch": index, "cards": len(batch),
            "offers": [row["offer_id"] for row in batch],
            "request_sha256": marker, "request_bytes": payload_bytes,
        }
        journal(prepared)
        response = client.call("wb", "/content/v2/cards/update", payload, mutation=True)
        if response.get("error") is not False:
            journal({**prepared, "phase": "response_rejected", "response": response,
                     "finished_at": now()})
            state["phase"] = "wb_write_rejected_readback_required"
            state["batches"].append({"batch": index, "cards": len(batch),
                                     "response_error": response.get("error")})
            save(STATE_PATH, state)
            raise RuntimeError(f"wb_batch_rejected:{index}")
        journal({**prepared, "phase": "response", "response": response,
                 "finished_at": now()})
        state["batches"].append({"batch": index, "cards": len(batch),
                                 "response": response})
        state["phase"] = "wb_batch_updates_accepted"
        state["updated_at"] = now()
        save(STATE_PATH, state)
        print(json.dumps({"phase": "wb_batch_accepted", "batch": index,
                          "batch_count": len(batches), "cards": len(batch),
                          "total_accepted": sum(x["cards"] for x in state["batches"]),
                          "response": response}, ensure_ascii=False), flush=True)

    state["phase"] = "all_wb_batches_accepted_readback_pending"
    state["accepted_at"] = now()
    save(STATE_PATH, state)
    print(json.dumps({"phase": state["phase"], "total_accepted": len(updates),
                      "readback_required": True}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
