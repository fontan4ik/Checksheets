#!/usr/bin/env python3
"""Resume WB metadata attachment for verified Arlight 13936/25 after Ozon is approved."""
from __future__ import annotations
import collections, datetime, hashlib, json, pathlib, sys, time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PILOT = ROOT / "test/certificate_api_pilot_20261012"
PREFLIGHT = HERE / "arlight_13936_crossplatform_preflight_v2_20261022.json"
STATE = HERE / "arlight_13936_execution_20261022.json"
WB_BEFORE = HERE / "arlight_13936_wb_resume_before_20261022.json"
WB_STATE = HERE / "arlight_13936_wb_resume_execution_20261022.json"
WB_JOURNAL = HERE / "arlight_13936_wb_resume_journal_20261022.jsonl"
READBACK = HERE / "arlight_13936_final_crossplatform_readback_20261022.json"
ADDENDUM = HERE / "postwrite_coverage_addendum_20261022.json"
NUMBER = "ЕАЭС N RU Д-HK.РА02.В.13936/25"
ISSUE, EXPIRE, REGISTRY_ID = "2025-02-20", "2030-02-19", "19916418"
TNVED = {"8539519009"}
sys.path.insert(0, str(PILOT))
import run_all_found_certificates_20261014 as runner
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import copy_documents, doc_key, norm_number, wb_datetime, comparable_card


def save(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def journal(value):
    with WB_JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")
        stream.flush()


def codes(card):
    out = []
    for item in card.get("characteristics") or []:
        label = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" in label or "тнвед" in label:
            raw = item.get("value")
            out.extend(raw if isinstance(raw, list) else [raw])
    return sorted({str(x).split(" - ", 1)[0].strip() for x in out if str(x).strip()})


def get_unique_card(client, offer, attempts=3):
    observations = []
    for attempt in range(attempts):
        cards = client.wb_cards(offer)
        observations.append(len(cards))
        if len(cards) == 1:
            return cards[0], observations
        if attempt + 1 < attempts:
            time.sleep(2)
    return None, observations


def has_valid_doc(card):
    for doc in (card.get("documents") or {}).get("items") or []:
        verdict = doc.get("verdict")
        if isinstance(verdict, dict) and verdict.get("verified") is True and verdict.get("status") == 1 and verdict.get("reason") == "valid":
            return True
    return False


def list_certificates(client):
    rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        rows.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("ozon_certificate_page_limit")


def verify_ozon(client, pre):
    records = [x for x in list_certificates(client)
               if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(records) != 1:
        raise RuntimeError("ozon_record_missing_or_duplicate_during_wb_resume")
    record = records[0]
    if (record.get("type_code") != "declaration" or record.get("status_code") != "approved"
            or str(record.get("issue_date") or "")[:10] != ISSUE
            or str(record.get("expire_date") or "")[:10] != EXPIRE):
        raise RuntimeError("ozon_record_not_current_approved_exact")
    bindings = client.ozon_bindings(int(record["certificate_id"]))
    by_pair = collections.defaultdict(list)
    for b in bindings:
        by_pair[(str(b.get("product_id") or ""), str(b.get("sku") or ""))].append(b)
    rows = []
    targets = [x for x in pre["ozon_targets"] if x.get("eligible") and not x.get("already_exact")]
    for target in targets:
        matches = by_pair.get((str(target["product_id"]), str(target["sku"])), [])
        rows.append({"offer_id": target["offer_id"], "exact": len(matches) == 1,
                     "status": matches[0].get("product_status_code") if len(matches) == 1 else None})
    if len(rows) != 72 or any(x["exact"] is not True or x["status"] != "approved" for x in rows):
        raise RuntimeError("ozon_72_approved_bindings_not_confirmed")
    return record, rows


def main():
    for p in (WB_BEFORE, WB_STATE, WB_JOURNAL, READBACK):
        if p.exists():
            raise RuntimeError("resume_artifact_exists_inspect_before_retry:" + p.name)
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    state = json.loads(STATE.read_text(encoding="utf-8"))
    if (pre.get("read_only") is not True or pre.get("number") != NUMBER
            or state.get("phase") != "ozon_bound_wb_pending"):
        raise RuntimeError("preflight_or_ozon_execution_state_mismatch")
    source = ROOT / pre["source_file"]
    if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != pre["source_sha256"]:
        raise RuntimeError("source_hash_mismatch")
    wb_targets = [x for x in pre["wb_targets"] if x.get("eligible") and not x.get("already_exact")]
    if len(wb_targets) != 71:
        raise RuntimeError("safe_wb_target_count_changed:" + str(len(wb_targets)))

    client = Client()
    record, ozon_before = verify_ozon(client, pre)
    wb_state = {"started_at_utc": now(), "phase": "fresh_wb_readback", "ozon_record_id": str(record["certificate_id"]),
                "ozon_approved_bindings": len(ozon_before), "wb_candidate_cards": len(wb_targets),
                "local_source_file_deleted": False, "review_state_changed_by_agent": False}
    save(WB_STATE, wb_state)

    before_rows, updates, skipped = [], [], []
    for index, target in enumerate(wb_targets, 1):
        offer = target["offer_id"]
        card, observed_counts = get_unique_card(client, offer)
        if card is None:
            skipped.append({"offer_id": offer, "reason": "fresh_wb_card_not_unique",
                            "observed_card_counts": observed_counts})
            continue
        card_codes = codes(card)
        if (str(card.get("vendorCode") or "") != offer
                or str(card.get("brand") or "").casefold() != "arlight"
                or str(card.get("nmID") or "") != str(target.get("nmID") or "")
                or not card_codes or not set(card_codes).issubset(TNVED)):
            skipped.append({"offer_id": offer, "reason": "fresh_wb_identity_or_scope_changed",
                            "nmID": str(card.get("nmID") or ""), "brand": card.get("brand"),
                            "tnved_codes": card_codes})
            continue
        docs = copy_documents(card)
        same = [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in same if int(x.get("type") or 0) == 2
                 and str(x.get("startDate") or "")[:10] == ISSUE
                 and str(x.get("endDate") or "")[:10] == EXPIRE
                 and x.get("isEndless") is False]
        if same and len(exact) != 1:
            skipped.append({"offer_id": offer, "reason": "same_number_metadata_conflict"})
            continue
        already = len(exact) == 1
        before_rows.append({"offer_id": offer, "nmID": str(card["nmID"]), "card": card,
                            "prior_documents": docs, "already_exact": already,
                            "already_had_valid_document": has_valid_doc(card),
                            "observed_card_counts": observed_counts})
        if already:
            continue
        wanted = {"type": 2, "number": NUMBER, "startDate": wb_datetime(ISSUE),
                  "endDate": wb_datetime(EXPIRE), "isEndless": False}
        payload = runner.merge_wb(card, [wanted])
        if payload is not None:
            updates.append({"offer_id": offer, "nmID": str(card["nmID"]), "payload": payload})
        if index % 15 == 0 or index == len(wb_targets):
            print(json.dumps({"wb_fresh_cards_checked": index, "total": len(wb_targets),
                              "safe": len(before_rows), "skipped": len(skipped)}, ensure_ascii=False), flush=True)

    save(WB_BEFORE, {"checked_at_utc": now(), "complete": True,
                     "requested_cards": len(wb_targets), "fresh_exact_cards": len(before_rows),
                     "updates": len(updates), "already_exact": sum(x["already_exact"] for x in before_rows),
                     "skipped": skipped, "cards": before_rows})
    wb_state.update({"phase": "wb_preflight_complete", "fresh_exact_cards": len(before_rows),
                     "updates": len(updates), "skipped": skipped})
    save(WB_STATE, wb_state)

    response, error_type = None, None
    if updates:
        payloads = [x["payload"] for x in updates]
        marker = hashlib.sha256(json.dumps(payloads, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        journal({"at": now(), "platform": "wb", "endpoint": "/content/v2/cards/update",
                 "phase": "prepared", "document_number": NUMBER, "cards": len(updates),
                 "offers": [x["offer_id"] for x in updates], "request_sha256": marker})
        try:
            response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
        except Exception as exc:
            error_type = type(exc).__name__
        journal({"at": now(), "platform": "wb", "endpoint": "/content/v2/cards/update",
                 "phase": "response" if response is not None else "uncertain", "response": response,
                 "error_type": error_type, "document_number": NUMBER})
    wb_state.update({"phase": "wb_write_sent", "updates_sent": len(updates),
                     "response": response, "error_type": error_type})
    save(WB_STATE, wb_state)

    time.sleep(60)
    before_map = {x["offer_id"]: x for x in before_rows}
    readbacks, failures = [], []
    for index, target in enumerate(wb_targets, 1):
        offer = target["offer_id"]
        prior = before_map.get(offer)
        if not prior:
            readbacks.append({"offer_id": offer, "exact_metadata": False,
                              "verdict": None, "skipped": True})
            continue
        card, observed_counts = get_unique_card(client, offer)
        if card is None:
            failures.append({"offer_id": offer, "reason": "readback_card_not_unique",
                             "observed_card_counts": observed_counts})
            readbacks.append({"offer_id": offer, "exact_metadata": False, "verdict": None})
            continue
        docs = (card.get("documents") or {}).get("items") or []
        matches = [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)
                   and int(x.get("type") or 0) == 2
                   and str(x.get("startDate") or "")[:10] == ISSUE
                   and str(x.get("endDate") or "")[:10] == EXPIRE
                   and x.get("isEndless") is False]
        old_signatures = [(doc_key(x), str(x.get("startDate") or "")[:10],
                           str(x.get("endDate") or "")[:10], x.get("isEndless"))
                          for x in prior["prior_documents"]]
        new_signatures = [(doc_key(x), str(x.get("startDate") or "")[:10],
                           str(x.get("endDate") or "")[:10], x.get("isEndless")) for x in docs]
        old_preserved = all(x in new_signatures for x in old_signatures)
        fields_preserved = comparable_card(card) == comparable_card(prior["card"])
        verdict = matches[0].get("verdict") if len(matches) == 1 else None
        valid = (isinstance(verdict, dict) and verdict.get("verified") is True
                 and verdict.get("status") == 1 and verdict.get("reason") == "valid")
        row = {"offer_id": offer, "nmID": str(card.get("nmID") or ""),
               "exact_metadata": len(matches) == 1, "prior_documents_preserved": old_preserved,
               "unrelated_card_fields_preserved": fields_preserved,
               "had_valid_document_before": prior["already_had_valid_document"],
               "verdict": verdict, "marketplace_valid": valid}
        readbacks.append(row)
        if len(matches) != 1 or not old_preserved or not fields_preserved:
            failures.append({"offer_id": offer, "reason": "document_or_preservation_readback_failed",
                             "exact_metadata_count": len(matches), "prior_documents_preserved": old_preserved,
                             "unrelated_card_fields_preserved": fields_preserved})
        if index % 15 == 0 or index == len(wb_targets):
            print(json.dumps({"wb_readbacks": index, "total": len(wb_targets)}, ensure_ascii=False), flush=True)

    record_after, ozon_after = verify_ozon(client, pre)
    exact = sum(x.get("exact_metadata") is True for x in readbacks)
    valid = sum(x.get("marketplace_valid") is True for x in readbacks)
    fresh_unique = sum(x.get("marketplace_valid") is True and not x.get("had_valid_document_before", False)
                       for x in readbacks)
    readback = {"checked_at_utc": now(), "read_only_delayed_reconciliation": True,
                "brand": "Arlight", "document_number": NUMBER, "type": "declaration",
                "fsa_registry_id": REGISTRY_ID, "fsa_status": "active",
                "issue_date": ISSUE, "expire_date": EXPIRE, "source_sha256": pre["source_sha256"],
                "ozon_certificate_id": str(record_after["certificate_id"]),
                "ozon_record_status": record_after.get("status_code"),
                "ozon_expected_bindings": 72, "ozon_exact_bindings": len(ozon_after),
                "ozon_binding_status_counts": dict(collections.Counter(x.get("status") for x in ozon_after)),
                "wb_expected_cards": len(wb_targets), "wb_exact_cards": exact,
                "wb_valid_cards": valid, "wb_pending_or_unverified_cards": exact - valid,
                "wb_skipped": skipped, "wb_newly_valid_unique_cards": fresh_unique,
                "wb_review_state_changed_by_agent": False, "wb_left_for_marketplace_review": True,
                "local_source_file_deleted": False, "failures": failures,
                "verification_artifacts": [PREFLIGHT.name, STATE.name, WB_BEFORE.name, WB_STATE.name],
                "ozon_bindings": {"expected": 72, "exact_visible": len(ozon_after),
                                  "status_counts": dict(collections.Counter(x.get("status") for x in ozon_after)),
                                  "bindings": ozon_after},
                "wb_cards": readbacks}
    save(READBACK, readback)

    state.update({"phase": "delayed_readback_complete", "finished_at_utc": now(),
                  "wb_resume": {"expected_cards": len(wb_targets), "updates_sent": len(updates),
                                "exact_metadata_cards": exact, "valid_cards": valid,
                                "pending_or_unverified_cards": exact-valid, "skipped": skipped,
                                "failures": failures},
                  "ozon_final_record_status": record_after.get("status_code"),
                  "ozon_final_binding_status_counts": dict(collections.Counter(x.get("status") for x in ozon_after)),
                  "local_source_file_deleted": False})
    save(STATE, state)
    wb_state.update({"phase": "delayed_readback_complete", "finished_at_utc": now(),
                     "exact_metadata_cards": exact, "valid_cards": valid,
                     "pending_or_unverified_cards": exact-valid, "fresh_unique_valid_cards": fresh_unique,
                     "failures": failures})
    save(WB_STATE, wb_state)

    add = json.loads(ADDENDUM.read_text(encoding="utf-8"))
    if any(x.get("document_number") == NUMBER for x in add.get("post_snapshot_writes", [])):
        raise RuntimeError("addendum_already_contains_document")
    entry = {"brand": "Arlight", "document_number": NUMBER, "type": "declaration",
             "fsa_record_id": REGISTRY_ID, "fsa_status": "active", "source_sha256": pre["source_sha256"],
             "ozon_certificate_id": str(record_after["certificate_id"]),
             "ozon_record_status": record_after.get("status_code"),
             "ozon_exact_bindings": len(ozon_after), "ozon_binding_status_counts": dict(collections.Counter(x.get("status") for x in ozon_after)),
             "wb_exact_cards": exact, "wb_valid_cards": valid, "wb_pending_or_unverified_cards": exact-valid,
             "wb_skipped_cards": len(skipped), "wb_review_state_changed_by_agent": False,
             "wb_left_for_marketplace_review": True, "local_source_pdf_deleted": False,
             "limitation": "72 Ozon target offers now have approved exact bindings; 71 exact WB cards were processed. One WB offer (039608-1) had no unique exact card and was skipped. Source PDF retained.",
             "verification_artifacts": [PREFLIGHT.name, STATE.name, WB_BEFORE.name, WB_STATE.name, READBACK.name]}
    add.setdefault("post_snapshot_writes", []).append(entry)
    refs = add.setdefault("verification_artifacts", {})
    if isinstance(refs, dict):
        refs["arlight_13936_readback"] = str(READBACK)
    elif isinstance(refs, list):
        refs.append(str(READBACK))
    totals = add.get("post_snapshot_totals") or {}
    if totals:
        totals["ozon_certificate_records"] = int(totals.get("ozon_certificate_records", 0)) + 1
        statuses = totals.setdefault("ozon_certificate_statuses", {})
        statuses["approved"] = int(statuses.get("approved", 0)) + 1
        totals["ozon_live_bindings"] = int(totals.get("ozon_live_bindings", 0)) + 72
        totals["ozon_products_with_at_least_one_current_approved_document"] = int(totals.get("ozon_products_with_at_least_one_current_approved_document", 0)) + 72
        totals["ozon_products_without_any_current_approved_document"] = max(0, int(totals.get("ozon_products_without_any_current_approved_document", 0)) - 72)
        totals["wb_cards_with_at_least_one_valid_document"] = int(totals.get("wb_cards_with_at_least_one_valid_document", 0)) + fresh_unique
        totals["newly_verified_wb_cards"] = int(totals.get("newly_verified_wb_cards", 0)) + valid
        add["post_snapshot_totals"] = totals
    reconciliations = add.setdefault("current_live_reconciliations", {})
    reconciliations["arlight_13936_20261022"] = {
        "ozon_exact_bindings": len(ozon_after), "ozon_status_counts": dict(collections.Counter(x.get("status") for x in ozon_after)),
        "wb_exact_cards": exact, "wb_valid_cards": valid, "wb_pending_or_unverified_cards": exact-valid,
        "wb_skipped_cards": skipped, "failures": failures, "local_source_file_deleted": False,
        "verification_artifact": str(READBACK)}
    add["checked_at_utc"] = now()
    add["complete"] = False
    add["local_source_pdfs_deleted"] = False
    save(ADDENDUM, add)
    print(json.dumps({"readback": str(READBACK), "ozon": {"record_status": record_after.get("status_code"),
                      "exact_approved_bindings": len(ozon_after)},
                      "wb": {"target_cards": len(wb_targets), "exact_metadata": exact,
                             "valid": valid, "pending_or_unverified": exact-valid,
                             "skipped": skipped, "failures": failures},
                      "local_source_file_deleted": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
