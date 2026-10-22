#!/usr/bin/env python3
"""Bind only fresh, in-scope Jazzway 37909 products on Ozon and missing WB cards."""
from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
sys.path.insert(0, str(HERE))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import comparable_card, copy_documents, norm_number  # noqa: E402
from apply_arlight_52132_wb_20261020 import code_values  # noqa: E402
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402

NUMBER = "ЕАЭС N RU Д-HK.РА08.В.37909/22"
SOURCE = ROOT / "output_to_user/certificates/group_2/JAZZWAY/documents/certificate_c5a7e15132.pdf"
SOURCE_SHA256 = "ac05304912cfc122dfe810a85f16a4f801e680da3b6ccf93bff2707cfa8335ae"
RECORD_ID = 5458891
ISSUE = "2022-11-21"
EXPIRY = "2027-11-20"
ALLOWED = {"8539520001", "8539520002", "8539520003", "8539520009"}
PREFLIGHT = HERE / "jazzway_37909_uncovered_preflight_20261022.json"
STATE = HERE / "jazzway_37909_uncovered_execution_20261022.json"
OZON_JOURNAL = HERE / "jazzway_37909_uncovered_ozon_journal_20261022.jsonl"
WB_JOURNAL = HERE / "jazzway_37909_uncovered_wb_journal_20261022.jsonl"
WB_BEFORE = HERE / "jazzway_37909_uncovered_wb_before_20261022.json"
WB_READBACK = HERE / "jazzway_37909_uncovered_wb_readback_20261022.json"


def save(path: pathlib.Path, value: object) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def journal(path: pathlib.Path, row: dict) -> None:
    with path.open("a") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()


def exact_docs(card: dict) -> list[dict]:
    docs = ((card.get("documents") or {}).get("items") or [])
    return [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)]


def is_exact(doc: dict) -> bool:
    return (str(doc.get("type")) == "2"
            and str(doc.get("startDate", ""))[:10] == ISSUE
            and str(doc.get("endDate", ""))[:10] == EXPIRY)


def certificate_record(client: Client) -> dict:
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        rows = result.get("certificates")
        if not isinstance(rows, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        matches = [x for x in rows if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
        if matches:
            if len(matches) != 1 or str(matches[0].get("certificate_id")) != str(RECORD_ID):
                raise RuntimeError("ozon_record_identity_ambiguous")
            return matches[0]
        if not rows or page >= int(result.get("page_count") or 0):
            break
    raise RuntimeError("ozon_record_not_found")


def main() -> None:
    for path in (STATE, OZON_JOURNAL, WB_JOURNAL, WB_BEFORE, WB_READBACK):
        if path.exists():
            raise RuntimeError("execution_artifact_exists_reconcile_before_retry:" + path.name)
    pre = json.loads(PREFLIGHT.read_text())
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("source_file_hash_mismatch")
    if (pre.get("read_only") is not True or pre.get("number") != NUMBER
            or pre.get("ozon_safe_targets") != 109 or pre.get("wb_safe_targets") != 106
            or pre.get("ozon_record_current_approved") is not True):
        raise RuntimeError("preflight_identity_or_counts_changed")
    ozon_targets = {x["offer_id"]: x for x in pre["ozon_targets"] if x.get("safe_for_new_bind") is True}
    wb_targets = {x["offer_id"]: x for x in pre["wb_targets"] if x.get("safe_for_update") is True}
    if len(ozon_targets) != 109 or len(wb_targets) != 106:
        raise RuntimeError("preflight_target_sets_not_unique")

    client = Client()
    record = certificate_record(client)
    if (record.get("status_code") != "approved"
            or str(record.get("issue_date") or "")[:10] != ISSUE
            or str(record.get("expire_date") or "")[:10] != EXPIRY):
        raise RuntimeError("ozon_record_no_longer_current_and_approved")
    bindings_before = client.ozon_bindings(RECORD_ID)
    bind_by_product = {str(x.get("product_id")): x for x in bindings_before}
    bind_by_sku = {str(x.get("sku")): x for x in bindings_before}

    # Fresh Ozon product/attribute check immediately before binding.
    fresh_products, fresh_attrs = {}, {}
    ozon_offers = sorted(ozon_targets)
    for start in range(0, len(ozon_offers), 100):
        batch = ozon_offers[start:start + 100]
        ps = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items")
        attrs = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)}).get("result")
        if not isinstance(ps, list) or not isinstance(attrs, list):
            raise RuntimeError("fresh_ozon_data_incomplete")
        for x in ps: fresh_products[str(x.get("offer_id") or "")] = x
        for x in attrs: fresh_attrs[str(x.get("offer_id") or "")] = x
    if set(fresh_products) != set(ozon_offers) or set(fresh_attrs) != set(ozon_offers):
        raise RuntimeError("fresh_ozon_offer_set_changed")

    fresh_bind_skus = []
    for offer, expected in sorted(ozon_targets.items()):
        p, a = fresh_products[offer], fresh_attrs[offer]
        pid = str(p.get("product_id") or p.get("id") or "")
        sku = str(p.get("sku") or "")
        brand = [str(x.get("value") or "").strip() for x in
                 ({str(y.get("id")): y for y in a.get("attributes") or []}.get("85") or {}).get("values") or []
                 if str(x.get("value") or "").strip()]
        tnvs = sorted({str(x.get("value") or "").split(" - ", 1)[0].strip() for x in
                 ({str(y.get("id")): y for y in a.get("attributes") or []}.get("22232") or {}).get("values") or []
                 if str(x.get("value") or "").strip()})
        if (p.get("is_archived") is not False or brand != ["Jazzway"]
                or len(tnvs) != 1 or tnvs[0] not in ALLOWED
                or pid != expected["product_id"] or sku != expected["sku"]):
            raise RuntimeError("fresh_ozon_identity_or_scope_changed:" + offer)
        prior = bind_by_product.get(pid) or bind_by_sku.get(sku)
        if prior:
            raise RuntimeError("fresh_ozon_binding_now_exists_reconcile:" + offer + ":" + str(prior.get("product_status_code")))
        fresh_bind_skus.append(sku)
    if len(fresh_bind_skus) != 109 or len(set(fresh_bind_skus)) != 109:
        raise RuntimeError("fresh_ozon_bind_sku_set_invalid")

    state = {
        "started_at_utc": now(), "number": NUMBER, "certificate_id": RECORD_ID,
        "source_sha256": SOURCE_SHA256, "ozon_record_status": record.get("status_code"),
        "ozon_bind_targets": 109, "ozon_bindings_before": len(bindings_before),
        "ozon_mutation_attempted": False, "ozon_bindings_after": None,
        "wb_target_cards": 106, "wb_mutation_attempted": False,
        "wb_readback": None, "wb_review_left_pending": True,
        "local_source_deleted": False, "phase": "fresh_preflight_passed",
    }
    save(STATE, state)

    bind_payload = {"certificate_id": RECORD_ID, "skus": fresh_bind_skus}
    marker = hashlib.sha256(json.dumps(bind_payload, sort_keys=True).encode()).hexdigest()
    journal(OZON_JOURNAL, {"key": "ozon:37909:bind:" + marker, "phase": "prepared",
        "at": now(), "request_sha256": marker, "certificate_id": RECORD_ID,
        "skus": fresh_bind_skus, "sku_count": len(fresh_bind_skus)})
    state["ozon_mutation_attempted"] = True
    state["phase"] = "ozon_bind_outcome_pending"
    save(STATE, state)
    response = client.call("ozon", "/v1/product/certificate/bind", bind_payload, mutation=True)
    journal(OZON_JOURNAL, {"key": "ozon:37909:bind:" + marker, "phase": "response",
        "at": now(), "response": response})
    state["ozon_bind_response"] = response
    if response.get("result") is not True:
        state["phase"] = "ozon_bind_rejected_reconcile_required"
        save(STATE, state)
        raise RuntimeError("ozon_bind_rejected_reconcile_before_any_retry")

    bindings_after = client.ozon_bindings(RECORD_ID)
    after_by_product = {str(x.get("product_id")): x for x in bindings_after}
    ozon_target_rows = []
    for offer, target in sorted(ozon_targets.items()):
        row = after_by_product.get(target["product_id"])
        exact_identity = bool(row and str(row.get("sku")) == target["sku"])
        ozon_target_rows.append({"offer_id": offer, "product_id": target["product_id"],
            "sku": target["sku"], "binding_visible": bool(row),
            "binding_identity_exact": exact_identity,
            "product_status_code": (row or {}).get("product_status_code")})
    ozon_status_counts = collections.Counter(str(x.get("product_status_code") or "missing") for x in ozon_target_rows)
    if any(not x["binding_visible"] or not x["binding_identity_exact"] for x in ozon_target_rows):
        state["phase"] = "ozon_bind_readback_incomplete"
        state["ozon_bindings_after"] = len(bindings_after)
        state["ozon_target_binding_status_counts"] = dict(ozon_status_counts)
        state["ozon_missing_or_identity_conflict"] = [x for x in ozon_target_rows if not x["binding_visible"] or not x["binding_identity_exact"]]
        save(STATE, state)
        raise RuntimeError("ozon_binding_readback_incomplete_stop_before_wb")
    state["ozon_bindings_after"] = len(bindings_after)
    state["ozon_target_binding_status_counts"] = dict(ozon_status_counts)
    state["ozon_targets_visible"] = len(ozon_target_rows)
    state["phase"] = "ozon_bindings_visible_wb_preflight_next"
    save(STATE, state)
    print(json.dumps({"phase": state["phase"], "ozon_targets_visible": len(ozon_target_rows),
        "ozon_target_binding_status_counts": dict(ozon_status_counts),
        "ozon_bindings_total": len(bindings_after)}, ensure_ascii=False), flush=True)

    # Targeted fresh WB validation and metadata update; the user asked to keep WB in review.
    desired = {"type": 2, "number": NUMBER, "startDate": f"{ISSUE}T00:00:00Z",
        "endDate": f"{EXPIRY}T00:00:00Z", "isEndless": False}
    updates, before, wb_exclusions, wb_already = [], {}, [], []
    wb_offers = sorted(wb_targets)
    for index, offer in enumerate(wb_offers, 1):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            wb_exclusions.append({"offer_id": offer, "reason": "fresh_wb_card_missing_or_duplicate"})
            continue
        card, expected = cards[0], wb_targets[offer]
        tnvs = sorted(set(code_values(card)))
        if (str(card.get("nmID") or "") != str(expected.get("nmID") or "")
                or str(card.get("brand") or "").strip().casefold() not in {"jazzway", "jazz way"}
                or len(tnvs) != 1 or tnvs[0] not in ALLOWED):
            wb_exclusions.append({"offer_id": offer, "reason": "fresh_wb_identity_or_scope_changed", "tnved": tnvs})
            continue
        same = exact_docs(card)
        if same:
            if len(same) == 1 and is_exact(same[0]):
                wb_already.append(offer)
            else:
                wb_exclusions.append({"offer_id": offer, "reason": "same_number_metadata_conflict"})
            continue
        payload = merge_wb(card, [desired])
        if payload is None:
            wb_already.append(offer)
            continue
        updates.append({"offer_id": offer, "nmID": str(card.get("nmID")), "payload": payload})
        before[offer] = card
        if index % 25 == 0:
            print(json.dumps({"phase": "fresh_wb_preflight", "checked": index,
                "targets": len(wb_offers), "updates": len(updates)}, ensure_ascii=False), flush=True)
    if wb_exclusions:
        state["phase"] = "wb_fresh_preflight_conflicts_stop"
        state["wb_preflight_exclusions"] = wb_exclusions
        save(STATE, state)
        raise RuntimeError("wb_fresh_preflight_conflict_reconcile_before_write")
    if len(updates) + len(wb_already) != 106 or len(updates) != 106 - len(wb_already):
        state["phase"] = "wb_fresh_preflight_count_changed"
        save(STATE, state)
        raise RuntimeError("wb_update_count_changed")
    save(WB_BEFORE, {"checked_at_utc": now(), "read_only": True, "cards": before,
                     "already_exact_offers": wb_already})
    payload = [x["payload"] for x in updates]
    size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
    if size > 9_500_000:
        raise RuntimeError("wb_payload_too_large")
    wb_marker = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    journal(WB_JOURNAL, {"key": "wb:37909:" + wb_marker, "phase": "prepared", "at": now(),
        "request_sha256": wb_marker, "request_bytes": size, "cards": len(updates),
        "offers": [x["offer_id"] for x in updates]})
    state["wb_mutation_attempted"] = bool(updates)
    state["phase"] = "wb_update_outcome_pending"
    state["wb_updates_planned"] = len(updates)
    save(STATE, state)
    wb_response = client.call("wb", "/content/v2/cards/update", payload, mutation=True)
    journal(WB_JOURNAL, {"key": "wb:37909:" + wb_marker, "phase": "response", "at": now(), "response": wb_response})
    if wb_response.get("error") is not False:
        state["phase"] = "wb_update_rejected_reconcile_required"
        state["wb_response"] = wb_response
        save(STATE, state)
        raise RuntimeError("wb_update_rejected_reconcile_before_retry")

    # Per-offer live readback avoids catalog cursor movement after card updates.
    readback_rows = []
    for index, offer in enumerate(sorted(wb_targets), 1):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            readback_rows.append({"offer_id": offer, "status": "missing_or_duplicate", "card_count": len(cards)})
            continue
        card = cards[0]
        docs = exact_docs(card)
        exact = len(docs) == 1 and is_exact(docs[0])
        unchanged = offer not in before or comparable_card(before[offer]) == comparable_card(card)
        if offer in wb_already:
            unchanged = True
        readback_rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
            "status": "verified_exact" if exact and unchanged else "readback_mismatch",
            "exact_metadata": exact, "non_document_fields_unchanged": unchanged,
            "verdict": docs[0].get("verdict") if docs else None, "documents": docs})
        if index % 25 == 0:
            print(json.dumps({"phase": "wb_targeted_readback", "queried": index,
                "targets": len(wb_targets), "verified": sum(x["status"] == "verified_exact" for x in readback_rows)}, ensure_ascii=False), flush=True)
    wb_status_counts = collections.Counter(x["status"] for x in readback_rows)
    verdict_counts = collections.Counter()
    for row in readback_rows:
        if row["status"] != "verified_exact": continue
        verdict = row.get("verdict")
        if isinstance(verdict, dict):
            verdict_counts[str(verdict.get("reason") or verdict.get("status") or "unknown")] += 1
        else:
            verdict_counts[str(verdict or "not_returned")] += 1
    wb_readback = {"checked_at_utc": now(), "read_only": True, "number": NUMBER,
        "target_cards": len(wb_targets), "exact_document_metadata_cards": sum(x["status"] == "verified_exact" for x in readback_rows),
        "status_counts": dict(wb_status_counts), "verdict_counts": dict(verdict_counts),
        "wb_review_left_pending": True, "local_source_deleted": False, "results": readback_rows}
    save(WB_READBACK, wb_readback)
    state["wb_response"] = wb_response
    state["wb_readback"] = {k: wb_readback[k] for k in ("target_cards", "exact_document_metadata_cards", "status_counts", "verdict_counts", "wb_review_left_pending")}
    state["phase"] = "complete_verified" if wb_readback["exact_document_metadata_cards"] == len(wb_targets) and wb_status_counts.get("verified_exact") == len(wb_targets) else "wb_readback_incomplete"
    state["finished_at_utc"] = now()
    save(STATE, state)
    print(json.dumps({"phase": state["phase"], "ozon_targets_visible": len(ozon_target_rows),
        "ozon_target_binding_status_counts": dict(ozon_status_counts), "wb_readback": state["wb_readback"],
        "local_source_deleted": False}, ensure_ascii=False), flush=True)
    if state["phase"] != "complete_verified":
        raise RuntimeError("jazzway_wb_readback_incomplete")


if __name__ == "__main__":
    main()
