"""Attach Arlight declaration 79626/26 to exact-scope WB cards; leave review to WB."""
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
import run_all_found_certificates_20261014 as runner  # noqa: E402
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    comparable_card, copy_documents, doc_key, norm_number, wb_datetime,
)

PREFLIGHT = HERE / "arlight_79626_preflight_live_20261021.json"
OZON_STATE = HERE / "arlight_79626_ozon_execution_20261021.json"
STATE = HERE / "arlight_79626_wb_execution_20261021.json"
BEFORE = HERE / "arlight_79626_wb_before_20261021.json"
READBACK = HERE / "arlight_79626_wb_readback_20261021.json"
JOURNAL = HERE / "arlight_79626_wb_mutation_journal_20261021.jsonl"
NUMBER = "ЕАЭС N RU Д-CN.РА03.В.79626/26"
ISSUE = "2026-04-29"
EXPIRY = "2031-04-27"
ALLOWED_TNVED = {"9405420012", "9405420019"}


def save(path: pathlib.Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(path)


def card_tnv(card: dict) -> list[str]:
    out = []
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        vals = raw if isinstance(raw, list) else [raw]
        out.extend(str(v or "").split(" - ", 1)[0].strip() for v in vals if v)
    return sorted(set(out))


def signature(d: dict) -> tuple:
    return (doc_key(d), str(d.get("startDate", ""))[:10],
            str(d.get("endDate", ""))[:10], bool(d.get("isEndless")))


def doc_status(doc: dict) -> str:
    verdict = doc.get("verdict") or {}
    if verdict.get("verified") is True and verdict.get("reason") == "valid":
        return "valid"
    if verdict.get("verified") is True and verdict.get("reason") not in (None, "", "valid"):
        return "rejected_or_invalid"
    return "pending_review_or_verdict_missing"


def main() -> None:
    if any(x.exists() for x in (STATE, BEFORE, READBACK, JOURNAL)):
        raise RuntimeError("wb_execution_artifact_exists_reconcile_before_retry")
    pre = json.loads(PREFLIGHT.read_text())
    ozon = json.loads(OZON_STATE.read_text())
    if (pre.get("eligible_for_partial_upload") is not True
            or ozon.get("phase") != "ozon_verified_complete"
            or ozon.get("verified_target_pairs") != 70
            or ozon.get("certificate_info", {}).get("status_code") != "approved"):
        raise RuntimeError("partial_ozon_verification_or_preflight_incomplete")
    all_targets = {str(x["offer_id"]): x for x in pre["ozon_targets"]}
    wanted_rows = [x for x in pre["wb_targets"] if x.get("safe_for_update") is True]
    wanted = {str(x["offer_id"]): x for x in wanted_rows}
    if len(all_targets) != 70 or len(wanted) != 70:
        raise RuntimeError("unexpected_partial_target_counts")

    client = Client()
    info = client.call("ozon", "/v1/product/certificate/info",
                       {"certificate_number": NUMBER}).get("result") or {}
    if (str(info.get("certificate_id")) != str(ozon.get("certificate_id"))
            or norm_number(info.get("certificate_number")) != norm_number(NUMBER)
            or str(info.get("issue_date", ""))[:10] != ISSUE
            or str(info.get("expire_date", ""))[:10] != EXPIRY
            or info.get("status_code") != "approved"):
        raise RuntimeError("ozon_live_certificate_changed_before_wb_write")
    bindings = client.ozon_bindings(int(ozon["certificate_id"]))
    binding_by_id = {str(x.get("product_id")): x for x in bindings}
    for offer, row in wanted.items():
        target = all_targets[offer]
        b = binding_by_id.get(str(target["product_id"]))
        if (not b or str(b.get("sku")) != str(target["sku"])
                or not target.get("tnved_codes") or not set(target["tnved_codes"]) <= ALLOWED_TNVED):
            raise RuntimeError("ozon_target_binding_or_scope_changed:" + offer)

    before_cards = []
    prepared = []
    target_doc = {"type": 2, "number": NUMBER, "startDate": wb_datetime(ISSUE),
                  "endDate": wb_datetime(EXPIRY), "isEndless": False}
    statuses_before = collections.Counter()
    for offer, expected in sorted(wanted.items()):
        target = all_targets[offer]
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            raise RuntimeError(f"wb_live_card_count_changed:{offer}:{len(cards)}")
        card = cards[0]
        title = str(card.get("title") or "")
        if (str(card.get("vendorCode") or "") != offer
                or str(card.get("nmID") or "") != str(expected.get("nmID") or "")
                or str(card.get("brand") or "").strip().casefold() != "arlight"
                or "прожектор" not in title.casefold()):
            raise RuntimeError("wb_live_identity_or_product_scope_changed:" + offer)
        codes = card_tnv(card)
        if codes and not set(codes) <= ALLOWED_TNVED:
            raise RuntimeError("wb_live_tnved_conflicts_with_fsa:" + offer)
        docs = copy_documents(card)
        same = [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)]
        if same:
            exact = (len(same) == 1 and doc_key(same[0]) == doc_key(target_doc)
                     and str(same[0].get("startDate", ""))[:10] == ISSUE
                     and str(same[0].get("endDate", ""))[:10] == EXPIRY
                     and same[0].get("isEndless") is False)
            if not exact:
                raise RuntimeError("wb_same_number_metadata_conflict:" + offer)
            statuses_before[str(same[0].get("verdict") or "already_exact")] += 1
            continue
        payload = runner.merge_wb(card, [target_doc])
        if payload is None:
            raise RuntimeError("wb_merge_returned_empty_for_missing_document:" + offer)
        before_cards.append(card)
        prepared.append({"offer_id": offer, "nmID": str(card["nmID"]),
                         "before": card, "payload": payload,
                         "prior_doc_signatures": [signature(x) for x in docs],
                         "scope_basis": "exact vendor code and brand plus in-scope Ozon product; WB TNVED blank"
                             if not codes else "exact WB TNVED code"})

    save(BEFORE, {"checked_at": now(), "complete": True, "number": NUMBER,
                  "target_count": len(wanted), "update_count": len(prepared),
                  "already_exact_count": len(wanted) - len(prepared),
                  "cards": before_cards})
    state = {"started_at": now(), "phase": "wb_fresh_snapshot_complete", "number": NUMBER,
             "ozon_certificate_id": ozon["certificate_id"], "ozon_verified_target_pairs": 70,
             "eligible_ozon_targets": 70, "wb_safe_targets": len(wanted),
             "wb_update_count": len(prepared), "wb_no_exact_card_count": pre.get("wb_no_card_count"),
             "review_left_to_wb": True, "local_file_deleted": False,
             "document": target_doc, "writes_sent": 0}
    save(STATE, state)

    if prepared:
        payloads = [x["payload"] for x in prepared]
        marker = hashlib.sha256(json.dumps(payloads, sort_keys=True,
                                           ensure_ascii=False).encode()).hexdigest()
        with JOURNAL.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"phase": "prepared", "at": now(), "cards": len(prepared),
                                     "sha256": marker}, ensure_ascii=False) + "\n")
            stream.flush()
        state.update(phase="wb_update_sent", writes_sent=1, updated_at=now())
        save(STATE, state)
        try:
            response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
        except Exception as exc:
            state.update(phase="wb_update_uncertain", error_type=type(exc).__name__, updated_at=now())
            save(STATE, state)
            raise RuntimeError("wb_update_uncertain_read_live_before_retry") from None
        with JOURNAL.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"phase": "response", "at": now(), "response": response},
                                    ensure_ascii=False) + "\n")
            stream.flush()
        state.update(phase="wb_update_response", wb_response_error=response.get("error"),
                     updated_at=now())
        save(STATE, state)
        if response.get("error") is not False:
            state.update(phase="wb_update_rejected", error_text=str(response.get("errorText") or "")[:500])
            save(STATE, state)
            raise RuntimeError("wb_update_rejected_reconcile_before_retry")

    before_by_offer = {x["offer_id"]: x["before"] for x in prepared}
    prior_by_offer = {x["offer_id"]: x["prior_doc_signatures"] for x in prepared}
    rows = []
    status_counts = collections.Counter()
    failures = []
    for offer, expected in sorted(wanted.items()):
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            failures.append({"offer_id": offer, "problem": "readback_card_count_changed",
                             "card_count": len(cards)})
            continue
        card = cards[0]
        docs = copy_documents(card)
        exact = [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact_meta = [x for x in exact if doc_key(x) == doc_key(target_doc)
                      and str(x.get("startDate", ""))[:10] == ISSUE
                      and str(x.get("endDate", ""))[:10] == EXPIRY
                      and x.get("isEndless") is False]
        preserved = True
        if offer in before_by_offer:
            preserved = comparable_card(card) == comparable_card(before_by_offer[offer])
            after_sigs = [signature(x) for x in docs]
            preserved = preserved and all(sig in after_sigs for sig in prior_by_offer[offer])
        status = doc_status(exact_meta[0]) if len(exact_meta) == 1 else "readback_missing_or_conflicting"
        status_counts[status] += 1
        row = {"offer_id": offer, "nmID": str(card.get("nmID") or ""),
               "exact_document_count": len(exact), "metadata_exact": len(exact_meta) == 1,
               "unrelated_fields_and_prior_documents_preserved": preserved,
               "document_status": status,
               "verdict": exact_meta[0].get("verdict") if len(exact_meta) == 1 else None}
        rows.append(row)
        if not row["metadata_exact"] or not preserved:
            failures.append(row)
    readback = {"checked_at": now(), "complete": len(rows) == len(wanted), "number": NUMBER,
                "target_cards": len(wanted), "updated_cards": len(prepared),
                "verified_target_cards": len(rows) - len(failures),
                "status_counts": dict(status_counts), "failures": failures,
                "cards": rows, "wb_review_left_pending": True}
    save(READBACK, readback)
    if failures or len(rows) != len(wanted):
        state.update(phase="wb_readback_incomplete", failure_count=len(failures), updated_at=now())
        save(STATE, state)
        raise RuntimeError("wb_readback_incomplete")
    state.update(phase="verified_complete", readback_path=str(READBACK),
                 verified_target_cards=len(rows), wb_status_counts=dict(status_counts),
                 wb_review_left_pending=True, local_file_deleted=False, updated_at=now())
    save(STATE, state)
    print(json.dumps({"phase": state["phase"], "updated_cards": len(prepared),
                      "verified_target_cards": len(rows), "status_counts": dict(status_counts),
                      "review_left_to_wb": True, "source_pdf_deleted": False},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
