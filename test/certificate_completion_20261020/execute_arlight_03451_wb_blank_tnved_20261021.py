"""Attach Arlight 03451/22 to exactly revalidated WB cards with blank TN VED."""
from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import re
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

PREFLIGHT = HERE / "arlight_03451_wb_blank_tnved_preflight_20261021.json"
INITIAL = HERE / "arlight_03451_preflight_live_20261021.json"
OZON_STATE = HERE / "arlight_03451_ozon_execution_20261021.json"
STATE = HERE / "arlight_03451_wb_blank_tnved_execution_20261021.json"
BEFORE = HERE / "arlight_03451_wb_blank_tnved_before_20261021.json"
READBACK = HERE / "arlight_03451_wb_blank_tnved_readback_20261021.json"
JOURNAL = HERE / "arlight_03451_wb_blank_tnved_mutation_journal_20261021.jsonl"
NUMBER = "ЕАЭС RU С-HK.НА46.В.03451/22"
ISSUE = "2022-04-16"
EXPIRY = "2027-04-15"
TNVED = "8504408300"
CERT_ID = "5925989"
EXPECTED = 248
MODEL_RE = re.compile(r"\bAR(?:PJ|PV|J|V)-[A-Z0-9]+(?:-[A-Z0-9]+)*\b", re.I)


def save(path: pathlib.Path, value: object) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def append(event: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        stream.flush()


def tnved(card: dict) -> list[str]:
    values = []
    for char in card.get("characteristics") or []:
        name = "".join(str(char.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = char.get("value")
        values.extend(str(v or "").split(" - ", 1)[0].strip()
                      for v in (raw if isinstance(raw, list) else [raw]) if v)
    return sorted(set(values))


def model_match(card: dict, product: dict) -> bool:
    ozon_models = sorted(set(x.upper() for x in MODEL_RE.findall(product.get("product_name") or "")))
    wb_models = sorted(set(x.upper() for x in MODEL_RE.findall(str(card.get("title") or ""))))
    return len(ozon_models) == 1 and ozon_models == wb_models


def signature(doc: dict) -> tuple:
    return (doc_key(doc), str(doc.get("startDate", ""))[:10],
            str(doc.get("endDate", ""))[:10], bool(doc.get("isEndless")))


def main() -> None:
    prior_attempt = None
    if STATE.exists():
        prior_attempt = json.loads(STATE.read_text(encoding="utf-8"))
    safe_prewrite_retry = (prior_attempt is not None
                           and prior_attempt.get("phase") == "wb_prewrite_verified"
                           and prior_attempt.get("writes_sent") == 0
                           and BEFORE.exists() and not READBACK.exists() and not JOURNAL.exists())
    if ((STATE.exists() or BEFORE.exists() or READBACK.exists() or JOURNAL.exists())
            and not safe_prewrite_retry):
        raise RuntimeError("wb_mutation_artifact_exists_reconcile_before_retry")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    initial = json.loads(INITIAL.read_text(encoding="utf-8"))
    ozon_state = json.loads(OZON_STATE.read_text(encoding="utf-8"))
    planned = {r["offer_id"]: r for r in pre.get("cards") or []
               if r.get("reason") == "eligible_by_exact_offer_brand_model_and_ozon_scope"}
    if (pre.get("read_only") is not True or pre.get("eligible_for_add") != EXPECTED
            or len(planned) != EXPECTED
            or not pre.get("source_pdf_sha256")
            or pre.get("source_pdf_sha256") != initial.get("source_pdf_sha256")
            or ozon_state.get("phase") != "ozon_verified_complete"
            or str(ozon_state.get("certificate_id")) != CERT_ID
            or ozon_state.get("verified_target_pairs") != 462):
        raise RuntimeError("fresh_preflight_source_or_ozon_evidence_incomplete")

    state = ({**prior_attempt, "phase": "fresh_prewrite_recheck",
              "reconciled_prior_attempt": {"phase": prior_attempt.get("phase"),
                                            "writes_sent": prior_attempt.get("writes_sent"),
                                            "mutation_sent": False},
              "revalidation_started_at": now()} if safe_prewrite_retry else
             {"started_at": now(), "phase": "fresh_prewrite_recheck", "number": NUMBER,
              "certificate_id": CERT_ID, "target_cards": EXPECTED, "writes_sent": 0,
              "wb_review_left_pending": True, "local_file_deleted": False,
              "scope_basis": pre.get("scope_basis")})
    save(STATE, state)
    client = Client()
    info = client.call("ozon", "/v1/product/certificate/info", {
        "certificate_number": NUMBER
    }).get("result") or {}
    if (str(info.get("certificate_id")) != CERT_ID
            or norm_number(info.get("certificate_number")) != norm_number(NUMBER)
            or info.get("type_code") != "certificate_of_conformity"
            or str(info.get("issue_date", ""))[:10] != ISSUE
            or str(info.get("expire_date", ""))[:10] != EXPIRY
            or str(info.get("accordance_type_code", "")).upper() != "EAEU"
            or info.get("status_code") in {"declined", "rejected", "invalid", "cancelled"}):
        state.update(phase="aborted_ozon_metadata_changed", certificate_info=info, updated_at=now())
        save(STATE, state)
        raise RuntimeError("ozon_document_metadata_changed_before_wb_write")
    bindings = client.ozon_bindings(int(CERT_ID))
    binding_by_id = {str(x.get("product_id")): x for x in bindings}
    if len(bindings) != 462 or len(binding_by_id) != 462:
        state.update(phase="aborted_ozon_binding_count_changed", binding_count=len(bindings), updated_at=now())
        save(STATE, state)
        raise RuntimeError("ozon_live_binding_count_changed_before_wb_write")
    ozon_by_offer = {x["offer_id"]: x for x in initial.get("ozon_targets") or []}

    prepared, failures = [], []
    target_doc = {"type": 1, "number": NUMBER, "startDate": wb_datetime(ISSUE),
                  "endDate": wb_datetime(EXPIRY), "isEndless": False}
    for index, (offer, first_check) in enumerate(sorted(planned.items()), 1):
        product = ozon_by_offer.get(offer)
        binding = binding_by_id.get(str(product.get("product_id") if product else ""))
        if (not product or not product.get("identity_matches") or not product.get("in_scope")
                or product.get("brand_values") != ["Arlight"] or product.get("tnved_codes") != [TNVED]
                or not binding or str(binding.get("sku")) != str(product.get("sku"))):
            failures.append({"offer_id": offer, "reason": "ozon_scope_or_binding_changed"})
            continue
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            failures.append({"offer_id": offer, "reason": "live_card_missing_or_ambiguous"})
            continue
        card = cards[0]
        identity = (str(card.get("vendorCode") or "") == offer
                    and str(card.get("nmID") or "") == str(first_check.get("nmID") or ""))
        brand = str(card.get("brand") or "").strip().casefold() == "arlight"
        docs = copy_documents(card)
        same = [d for d in docs if norm_number(d.get("number")) == norm_number(NUMBER)]
        if (not identity or not brand or tnved(card) != [] or not model_match(card, product)
                or same):
            failures.append({"offer_id": offer, "reason": "live_card_or_document_changed",
                             "identity_matches": identity, "brand_matches": brand,
                             "tnved_codes": tnved(card), "model_match": model_match(card, product),
                             "matching_number_docs": len(same)})
            continue
        payload = runner.merge_wb(card, [target_doc])
        if payload is None or str(payload.get("nmID")) != str(card.get("nmID")):
            failures.append({"offer_id": offer, "reason": "merge_refused_or_identity_mismatch"})
            continue
        prepared.append({"offer_id": offer, "nmID": str(card["nmID"]), "before": card,
                         "payload": payload,
                         "prior_document_signatures": [signature(d) for d in docs]})
        if index % 50 == 0:
            print(json.dumps({"phase": "fresh_prewrite_recheck", "checked": index,
                              "prepared": len(prepared), "failures": len(failures)},
                             ensure_ascii=False), flush=True)
    if len(prepared) != EXPECTED or failures:
        state.update(phase="aborted_prewrite_recheck_changed", prepared_cards=len(prepared),
                     failures=failures, mutation_sent=False, updated_at=now())
        save(STATE, state)
        raise RuntimeError("live_prewrite_recheck_incomplete_no_mutation")

    save(BEFORE, {"checked_at": now(), "complete": True, "target_count": len(prepared),
                  "scope": pre.get("scope_basis"), "cards": [x["before"] for x in prepared]})
    payloads = [x["payload"] for x in prepared]
    batches = [payloads[i:i + 100] for i in range(0, len(payloads), 100)]
    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > 9_000_000:
        raise RuntimeError("wb_payload_exceeds_safe_batch_size")
    state.update(phase="wb_prewrite_verified", prepared_cards=len(prepared),
                 payload_bytes=len(encoded), batch_count=len(batches), document=target_doc,
                 certificate_info=info, ozon_live_binding_count=len(bindings), updated_at=now())
    save(STATE, state)

    previous_send = None
    for batch_no, batch in enumerate(batches, 1):
        if previous_send is not None:
            delay = 7.0 - (time.monotonic() - previous_send)
            if delay > 0:
                time.sleep(delay)
        marker = hashlib.sha256(json.dumps(batch, ensure_ascii=False,
                                           sort_keys=True).encode()).hexdigest()
        append({"phase": "prepared", "at": now(), "batch": batch_no,
                "cards": len(batch), "sha256": marker})
        state.update(phase="wb_update_sent", current_batch=batch_no,
                     writes_sent=state["writes_sent"] + 1, updated_at=now())
        save(STATE, state)
        previous_send = time.monotonic()
        try:
            response = client.call("wb", "/content/v2/cards/update", batch, mutation=True)
        except Exception as exc:
            state.update(phase="wb_update_uncertain", error_type=type(exc).__name__, updated_at=now())
            save(STATE, state)
            raise RuntimeError("wb_write_outcome_uncertain_reconcile_live_before_retry") from None
        append({"phase": "response", "at": now(), "batch": batch_no,
                "response": response, "sha256": marker})
        if response.get("error") is not False or response.get("additionalErrors"):
            state.update(phase="wb_update_rejected", response=response, updated_at=now())
            save(STATE, state)
            raise RuntimeError("wb_update_rejected_stop_and_reconcile")
        state.update(phase="wb_batches_progress", completed_batches=batch_no, updated_at=now())
        save(STATE, state)
        print(json.dumps({"phase": "wb_batch_complete", "batch": batch_no,
                          "batches": len(batches), "cards": len(batch)}, ensure_ascii=False), flush=True)

    old_by_offer = {x["offer_id"]: x["before"] for x in prepared}
    old_doc_sigs = {x["offer_id"]: collections.Counter(x["prior_document_signatures"])
                    for x in prepared}
    rows = []
    for index, entry in enumerate(prepared, 1):
        offer = entry["offer_id"]
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            rows.append({"offer_id": offer, "nmID": entry["nmID"], "verified": False,
                         "reason": "live_card_missing_or_ambiguous"})
            continue
        card = cards[0]
        docs = copy_documents(card)
        same = [d for d in docs if norm_number(d.get("number")) == norm_number(NUMBER)]
        exact = [d for d in same if doc_key(d) == doc_key(target_doc)
                 and str(d.get("startDate", ""))[:10] == ISSUE
                 and str(d.get("endDate", ""))[:10] == EXPIRY
                 and d.get("isEndless") is False]
        actual = collections.Counter(signature(d) for d in docs)
        preserved = all(actual[key] >= count for key, count in old_doc_sigs[offer].items())
        fields = comparable_card(card) == comparable_card(old_by_offer[offer])
        identity = (str(card.get("vendorCode") or "") == offer
                    and str(card.get("nmID") or "") == entry["nmID"])
        brand = str(card.get("brand") or "").strip().casefold() == "arlight"
        okay = (len(same) == 1 and len(exact) == 1 and preserved and fields and identity
                and brand and tnved(card) == [])
        rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                     "verified": okay, "exact_document_count": len(exact),
                     "metadata_exact": len(exact) == 1,
                     "document_status": "pending_review_or_verdict_missing" if len(exact) == 1 else "missing_or_conflicting",
                     "prior_documents_preserved": preserved, "unrelated_fields_preserved": fields,
                     "identity_preserved": identity, "brand_preserved": brand,
                     "tnved_still_blank": tnved(card) == []})
        if index % 50 == 0:
            print(json.dumps({"phase": "wb_targeted_readback", "checked": index,
                              "target_cards": len(prepared)}, ensure_ascii=False), flush=True)
    failed_readback = [r for r in rows if not r.get("verified")]
    status_counts = collections.Counter(r["document_status"] for r in rows if r.get("verified"))
    readback = {"checked_at": now(), "complete": not failed_readback and len(rows) == len(prepared),
                "number": NUMBER, "target_cards": len(rows),
                "verified_target_cards": len(rows) - len(failed_readback),
                "status_counts": dict(status_counts), "failures": failed_readback, "cards": rows,
                "wb_review_left_pending": True, "manual_wb_review_action_taken": False,
                "local_file_deleted": False}
    save(READBACK, readback)
    state.update(phase="verified_complete" if not failed_readback else "readback_incomplete",
                 readback_path=str(READBACK), verified_target_cards=len(rows) - len(failed_readback),
                 status_counts=dict(status_counts), failures=failed_readback,
                 wb_review_left_pending=True, updated_at=now(), local_file_deleted=False)
    save(STATE, state)
    print(json.dumps({"phase": state["phase"], "verified_target_cards": len(rows) - len(failed_readback),
                      "status_counts": dict(status_counts), "failures": failed_readback,
                      "wb_review_left_pending": True, "local_file_deleted": False},
                     ensure_ascii=False, indent=2))
    if failed_readback:
        raise RuntimeError("wb_readback_incomplete")


if __name__ == "__main__":
    main()
