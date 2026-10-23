#!/usr/bin/env python3
"""Add active Arlight declaration 33344/26 to exact-scope WB cards only.

The script makes one non-retriable WB batch after fresh per-offer card reads,
then performs fresh per-card readback. It never deletes local source files.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
import pathlib
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API_DIR = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API_DIR))

import run_all_found_certificates_20261014 as runner  # noqa: E402
from api_client import Client, digest, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    comparable_card,
    copy_documents,
    doc_key,
    norm_number,
    wb_datetime,
)

NUMBER = "ЕАЭС N RU Д-CN.РА03.В.33344/26"
ISSUE_DATE = "2026-04-13"
EXPIRY_DATE = "2031-04-09"
ALLOWED_TNVED = {"8537109800"}
DECLARED_SHA256 = "284dffc5179434fb9cffd9df16417de57b05e11013edb3055bdfddb9ec86b06e"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/arlight/DCE8C157436F3C4E9898E20868978ACD.pdf"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
STATE = HERE / "arlight_33344_wb_execution_20261023.json"
BEFORE = HERE / "arlight_33344_wb_before_20261023.json"
READBACK = HERE / "arlight_33344_wb_readback_20261023.json"
JOURNAL = HERE / "arlight_33344_wb_mutation_journal_20261023.jsonl"

FSA_EVIDENCE = {
    "registry_url": "https://pub.fsa.gov.ru/rds/declaration/view/21321061/common",
    "record_id": "21321061",
    "checked_at_utc": "2026-10-23T07:20:00Z",
    "status": "Действует",
    "number": NUMBER,
    "issue_date": ISSUE_DATE,
    "expiry_date": EXPIRY_DATE,
    "applicant": "ООО ТРАНЗИСТОР.РУ",
    "manufacturer": "Heilongjiang Arlight Trade Company Limited",
    "product_scope": (
        "Диммеры, микродиммеры, выпускаемые под товарным знаком Arlight, "
        "INTELLIGENT ARLIGHT, серий SMART, SR, LN, TY, TUYA, MATTER, ZB, "
        "DALI, KNX, ARL, VT, WF, TRIAC, SENS"
    ),
    "tnved": "8537109800",
    "evidence_source": "ФГИС Росаккредитации: карточка common и вкладка product",
}


def atomic_json(path: pathlib.Path, value: object) -> None:
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def card_tnved(card: dict) -> set[str]:
    result: set[str] = set()
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        values = raw if isinstance(raw, list) else [raw]
        result.update(str(value or "").split(" - ", 1)[0].strip() for value in values if value)
    return result


def prior_signature(doc: dict) -> tuple:
    return (
        doc_key(doc),
        str(doc.get("startDate") or "")[:10],
        str(doc.get("endDate") or "")[:10],
        bool(doc.get("isEndless")),
    )


def exact_doc(doc: dict, wanted: dict) -> bool:
    return (
        doc_key(doc) == doc_key(wanted)
        and str(doc.get("startDate") or "")[:10] == ISSUE_DATE
        and str(doc.get("endDate") or "")[:10] == EXPIRY_DATE
        and doc.get("isEndless") is False
    )


def load_source_targets() -> list[dict]:
    if digest(SOURCE) != DECLARED_SHA256:
        raise RuntimeError("source_sha256_mismatch")
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        rows = [row for row in csv.DictReader(stream)
                if "33344/26" in row.get("Номер/название документа", "")]
    by_offer: dict[str, dict] = {}
    for row in rows:
        offer = str(row.get("Артикул продавца") or "").strip()
        source_path = str(row.get("Локальный файл") or "")
        if not offer or source_path != "output_to_user/certificates/group_1/documents/arlight/DCE8C157436F3C4E9898E20868978ACD.pdf":
            raise RuntimeError("unexpected_source_assignment")
        if row.get("SHA256 фактический") != DECLARED_SHA256 or row.get("Аудит файла") != "SHA-256 совпадает":
            raise RuntimeError("assignment_hash_evidence_mismatch:" + offer)
        basis = str(row.get("Основание сопоставления") or "")
        if "Точный артикул" not in basis and "официальной карточке артикула" not in basis:
            raise RuntimeError("non_exact_source_assignment:" + offer)
        if str(row.get("Тип документа") or "").casefold() != "декларация соответствия":
            raise RuntimeError("source_document_type_conflict:" + offer)
        if str(row.get("Бренд подтвержденный") or "").strip().casefold() != "arlight":
            raise RuntimeError("source_brand_conflict:" + offer)
        prior = by_offer.get(offer)
        if prior and prior != row:
            raise RuntimeError("duplicate_conflicting_source_assignment:" + offer)
        by_offer[offer] = row
    if len(by_offer) != 90:
        raise RuntimeError(f"unexpected_exact_target_count:{len(by_offer)}")
    return [{"offer_id": offer, **row} for offer, row in sorted(by_offer.items())]


def append_journal(event: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def main() -> None:
    if any(path.exists() for path in (STATE, BEFORE, READBACK, JOURNAL)):
        raise RuntimeError("execution_artifact_exists_reconcile_before_retry")
    if not (ISSUE_DATE <= dt.datetime.now(dt.timezone.utc).date().isoformat() <= EXPIRY_DATE):
        raise RuntimeError("declaration_not_current_today")

    targets = load_source_targets()
    client = Client()
    desired = {
        "type": 2,
        "number": NUMBER,
        "startDate": wb_datetime(ISSUE_DATE),
        "endDate": wb_datetime(EXPIRY_DATE),
        "isEndless": False,
    }
    prepared: list[dict] = []
    already_present: list[dict] = []
    skipped: list[dict] = []
    before_cards: list[dict] = []

    for index, target in enumerate(targets, 1):
        offer = target["offer_id"]
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            skipped.append({"offer_id": offer, "reason": "no_unique_exact_card", "card_count": len(cards)})
            continue
        card = cards[0]
        nm_id = str(card.get("nmID") or "")
        if str(card.get("vendorCode") or "") != offer or not nm_id:
            skipped.append({"offer_id": offer, "reason": "live_card_identity_mismatch"})
            continue
        brand = str(card.get("brand") or "").strip().casefold()
        if brand != "arlight":
            skipped.append({"offer_id": offer, "reason": "live_brand_not_in_scope", "brand": card.get("brand")})
            continue
        codes = card_tnved(card)
        if not codes or not codes <= ALLOWED_TNVED:
            skipped.append({"offer_id": offer, "reason": "live_tnved_not_in_scope", "tnved": sorted(codes)})
            continue
        title = str(card.get("title") or "").casefold()
        assigned_title = str(target.get("Название товара Ozon") or "").casefold()
        if "диммер" not in title and "микродиммер" not in title and "диммер" not in assigned_title and "микродиммер" not in assigned_title:
            skipped.append({"offer_id": offer, "reason": "product_name_not_dimmer", "title": card.get("title")})
            continue

        existing = copy_documents(card)
        same_number = [doc for doc in existing if norm_number(doc.get("number")) == norm_number(NUMBER)]
        if same_number:
            if len(same_number) == 1 and exact_doc(same_number[0], desired):
                verdict = same_number[0].get("verdict") or {}
                already_present.append({"offer_id": offer, "nmID": nm_id,
                                        "verdict": verdict, "status": "already_present"})
            else:
                skipped.append({"offer_id": offer, "reason": "existing_document_metadata_conflict"})
            continue
        try:
            payload = runner.merge_wb(card, [desired])
        except ValueError as exc:
            skipped.append({"offer_id": offer, "reason": str(exc)})
            continue
        if payload is None:
            skipped.append({"offer_id": offer, "reason": "no_missing_document_to_add"})
            continue
        row = {
            "offer_id": offer,
            "nmID": nm_id,
            "brand": card.get("brand"),
            "tnved": sorted(codes),
            "before": card,
            "payload": payload,
            "prior_document_signatures": [prior_signature(doc) for doc in existing],
        }
        prepared.append(row)
        before_cards.append(card)
        if index % 20 == 0:
            print(json.dumps({"phase": "live_wb_preflight", "checked": index,
                              "of": len(targets), "safe_updates": len(prepared),
                              "already_present": len(already_present), "skipped": len(skipped)}), flush=True)

    state = {
        "started_at": now(),
        "phase": "live_preflight_complete",
        "number": NUMBER,
        "fsa_evidence": FSA_EVIDENCE,
        "source_file": str(SOURCE),
        "source_sha256": digest(SOURCE),
        "source_targets": len(targets),
        "safe_update_count": len(prepared),
        "already_present_count": len(already_present),
        "skipped_count": len(skipped),
        "skipped": skipped,
        "wb_review_left_to_wb": True,
        "local_file_deleted": False,
        "writes_sent": 0,
    }
    atomic_json(BEFORE, {
        "checked_at": now(), "complete": True, "source_targets": len(targets),
        "update_count": len(prepared), "already_present": already_present,
        "skipped": skipped, "cards": before_cards,
    })
    atomic_json(STATE, state)

    if not prepared:
        state.update(phase="no_safe_updates", finished_at=now())
        atomic_json(STATE, state)
        print(json.dumps({"phase": state["phase"], "updated": 0,
                          "already_present": len(already_present), "skipped": len(skipped)}), flush=True)
        return

    payloads = [row["payload"] for row in prepared]
    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > 9_000_000 or len(payloads) > 1000:
        raise RuntimeError("wb_payload_limit_exceeded")
    marker = hashlib.sha256(encoded).hexdigest()
    state.update(phase="wb_update_prepared", payload_sha256=marker,
                 payload_bytes=len(encoded), writes_sent=1)
    atomic_json(STATE, state)
    append_journal({"phase": "prepared", "at": now(), "platform": "wb",
                    "endpoint": "/content/v2/cards/update", "cards": len(payloads),
                    "payload_bytes": len(encoded), "sha256": marker,
                    "nmIDs": [row["nmID"] for row in prepared]})

    response = None
    mutation_error = None
    try:
        response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
        append_journal({"phase": "response", "at": now(), "response": response,
                        "payload_sha256": marker})
        if response.get("error") is not False:
            mutation_error = "wb_response_reported_error"
    except Exception as exc:  # uncertain mutations are reconciled below, never retried
        mutation_error = type(exc).__name__
        append_journal({"phase": "uncertain", "at": now(), "error_type": mutation_error,
                        "payload_sha256": marker})
    state.update(phase="wb_update_response_received" if response is not None else "wb_update_uncertain",
                 mutation_error=mutation_error, response=response, updated_at=now())
    atomic_json(STATE, state)

    readbacks = []
    for index, row in enumerate(prepared, 1):
        offer = row["offer_id"]
        try:
            cards = client.wb_cards(offer)
            if len(cards) != 1 or str(cards[0].get("nmID") or "") != row["nmID"]:
                readbacks.append({"offer_id": offer, "nmID": row["nmID"],
                                  "readback_ok": False, "reason": "identity_changed_or_card_missing"})
                continue
            fresh = cards[0]
            docs = copy_documents(fresh)
            matching = [doc for doc in docs if norm_number(doc.get("number")) == norm_number(NUMBER)]
            correct = len(matching) == 1 and exact_doc(matching[0], desired)
            old_docs_preserved = set(row["prior_document_signatures"]) <= {prior_signature(doc) for doc in docs}
            unrelated_fields_preserved = comparable_card(fresh) == comparable_card(row["before"])
            verdict = (matching[0].get("verdict") or {}) if matching else {}
            readbacks.append({
                "offer_id": offer,
                "nmID": row["nmID"],
                "readback_ok": bool(correct and old_docs_preserved and unrelated_fields_preserved),
                "expected_document_visible": correct,
                "prior_documents_preserved": old_docs_preserved,
                "unrelated_fields_preserved": unrelated_fields_preserved,
                "wb_verdict": verdict,
                "left_pending": not bool(verdict.get("verified") is True and verdict.get("reason") == "valid"),
                "card": fresh,
            })
        except Exception as exc:
            readbacks.append({"offer_id": offer, "nmID": row["nmID"],
                              "readback_ok": False, "error_type": type(exc).__name__})
        if index % 20 == 0:
            print(json.dumps({"phase": "wb_targeted_readback", "checked": index,
                              "of": len(prepared), "confirmed": sum(x.get("readback_ok") is True for x in readbacks)}), flush=True)

    atomic_json(READBACK, {
        "checked_at": now(), "number": NUMBER, "payload_sha256": marker,
        "mutation_response_received": response is not None,
        "mutation_error": mutation_error,
        "results": readbacks,
        "confirmed_count": sum(x.get("readback_ok") is True for x in readbacks),
        "wb_review_left_to_wb": True,
    })
    state.update(
        phase="wb_readback_complete",
        finished_at=now(),
        confirmed_count=sum(x.get("readback_ok") is True for x in readbacks),
        readback_failure_count=sum(x.get("readback_ok") is not True for x in readbacks),
        response_received=response is not None,
    )
    atomic_json(STATE, state)
    print(json.dumps({
        "phase": state["phase"], "targets": len(targets), "updated": len(prepared),
        "already_present": len(already_present), "skipped": len(skipped),
        "confirmed": state["confirmed_count"], "readback_failures": state["readback_failure_count"],
        "wb_review_left_to_wb": True, "local_file_deleted": False,
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
