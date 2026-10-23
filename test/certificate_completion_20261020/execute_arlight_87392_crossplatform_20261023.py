#!/usr/bin/env python3
"""Bind the verified Arlight declaration 87392/22 to exact, in-scope marketplace items."""
from __future__ import annotations

import base64
import collections
import hashlib
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import copy_documents, comparable_card, norm_number, wb_datetime  # noqa: E402
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.PA08.B.87392/22"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/arlight/E8503D1F8C103B41B49B024538942102.pdf"
SOURCE_SHA256 = "cb52ca8a72f07018e22ecf6861cfcf48aad25963c11ab6937efb97a921d99267"
ISSUE = "2022-12-07"
EXPIRY = "2027-12-06"
ALLOWED_TNVED = {"8539519009"}
PREFLIGHT = HERE / "arlight_87392_crossplatform_preflight_20261023.json"
STATE = HERE / "arlight_87392_crossplatform_execution_20261023.json"
JOURNAL = HERE / "arlight_87392_mutation_journal_20261023.jsonl"
BEFORE = HERE / "arlight_87392_wb_before_20261023.json"
READBACK = HERE / "arlight_87392_final_crossplatform_readback_20261023.json"


def save(path: pathlib.Path, value: object) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def journal(value: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")
        stream.flush()


def attr_values(row: dict, ident: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(v.get("value") or "").strip()
            for v in (attrs.get(str(ident)) or {}).get("values") or []
            if str(v.get("value") or "").strip()]


def codes(values: list[str]) -> set[str]:
    return {str(v).split(" - ", 1)[0].strip() for v in values if str(v).strip()}


def live_records(client: Client) -> list[dict]:
    rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_page_incomplete")
        rows.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("ozon_certificate_page_limit")


def fresh_ozon_targets(client: Client, expected: dict[str, dict]) -> dict[str, dict]:
    offers = sorted(expected)
    products, attributes = {}, {}
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        p_rows = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items")
        a_rows = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)}).get("result")
        if not isinstance(p_rows, list) or not isinstance(a_rows, list):
            raise RuntimeError("ozon_product_or_attribute_response_incomplete")
        for row in p_rows:
            offer = str(row.get("offer_id") or "")
            if offer in products:
                raise RuntimeError("duplicate_live_ozon_product:" + offer)
            products[offer] = row
        for row in a_rows:
            offer = str(row.get("offer_id") or "")
            if offer in attributes:
                raise RuntimeError("duplicate_live_ozon_attributes:" + offer)
            attributes[offer] = row
    if set(products) != set(offers) or set(attributes) != set(offers):
        raise RuntimeError("fresh_ozon_offer_set_changed")
    result = {}
    for offer, old in expected.items():
        p, a = products[offer], attributes[offer]
        pid, sku = str(p.get("product_id") or p.get("id") or ""), str(p.get("sku") or "")
        if (p.get("is_archived") is not False or pid != str(old.get("product_id") or "")
                or sku != str(old.get("sku") or "")
                or attr_values(a, 85) != ["Arlight"]
                or codes(attr_values(a, 22232)) != ALLOWED_TNVED):
            raise RuntimeError("fresh_ozon_identity_or_scope_changed:" + offer)
        result[offer] = {"offer_id": offer, "product_id": pid, "sku": sku}
    return result


def fresh_wb_updates(client: Client, expected: dict[str, dict]) -> tuple[list[dict], dict[str, dict]]:
    updates, before = [], {}
    wanted = {"type": 2, "number": NUMBER, "startDate": wb_datetime(ISSUE),
              "endDate": wb_datetime(EXPIRY), "isEndless": False}
    for index, (offer, old) in enumerate(sorted(expected.items()), 1):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            raise RuntimeError("fresh_wb_card_missing_or_duplicate:" + offer)
        card = cards[0]
        tnv = set()
        for item in card.get("characteristics") or []:
            label = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
            if "тнвэд" in label or "тнвед" in label:
                raw = item.get("value")
                vals = raw if isinstance(raw, list) else [raw]
                tnv.update(str(v).split(" - ", 1)[0].strip() for v in vals if v)
        if (str(card.get("nmID") or "") != str(old.get("nmID") or "")
                or str(card.get("brand") or "").strip().casefold() != "arlight"
                or tnv != ALLOWED_TNVED):
            raise RuntimeError("fresh_wb_identity_or_scope_changed:" + offer)
        docs = copy_documents(card)
        same = [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in same if str(x.get("type")) == "2"
                 and str(x.get("startDate") or "")[:10] == ISSUE
                 and str(x.get("endDate") or "")[:10] == EXPIRY
                 and x.get("isEndless") is False]
        if same and not (len(same) == len(exact) == 1):
            raise RuntimeError("fresh_wb_same_number_conflict:" + offer)
        if exact:
            continue
        payload = merge_wb(card, [wanted])
        if payload is None:
            raise RuntimeError("wb_merge_unexpected_noop:" + offer)
        updates.append(payload)
        before[offer] = card
        if index % 25 == 0:
            print(json.dumps({"phase": "wb_prewrite_recheck", "checked": index,
                              "updates": len(updates)}, ensure_ascii=False), flush=True)
    return updates, before


def main() -> None:
    if any(p.exists() for p in (STATE, JOURNAL, BEFORE, READBACK)):
        raise RuntimeError("execution_artifact_exists_inspect_before_retry")
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("source_pdf_hash_changed")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if (pre.get("read_only") is not True or pre.get("number") != NUMBER
            or pre.get("source_sha256") != SOURCE_SHA256
            or pre.get("issue_date") != ISSUE or pre.get("expire_date") != EXPIRY
            or pre.get("assignment_target_count") != 153
            or pre.get("ozon_safe_count") != 153 or pre.get("wb_safe_count") != 153
            or pre.get("wb_already_exact_count") != 0
            or pre.get("ozon_unresolved_outside_bindings")):
        raise RuntimeError("preflight_identity_or_counts_changed")
    ozon_expected = {x["offer_id"]: x for x in pre["ozon_targets"] if x.get("ozon_safe") is True}
    wb_expected = {x["offer_id"]: x for x in pre["wb_targets"] if x.get("safe_for_wb") is True}
    if (len(ozon_expected) != 153 or len(wb_expected) != 153
            or set(ozon_expected) != set(wb_expected)
            or len({x["sku"] for x in ozon_expected.values()}) != 153
            or len({x["nmID"] for x in wb_expected.values()}) != 153):
        raise RuntimeError("preflight_target_identity_not_unique")

    client = Client()
    state = {"started_at_utc": now(), "number": NUMBER, "source_sha256": SOURCE_SHA256,
        "issue_date": ISSUE, "expire_date": EXPIRY, "ozon_record_id": 5944403,
        "preflight_targets": {"ozon": 153, "wb": 153},
        "ozon_bind_attempted": False, "wb_update_attempted": False,
        "wb_review_left_pending": True, "local_source_deleted": False,
        "phase": "fresh_prewrite_check"}
    save(STATE, state)

    ozon_targets = fresh_ozon_targets(client, ozon_expected)
    records = [x for x in live_records(client)
               if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(records) != 1:
        raise RuntimeError("ozon_record_identity_changed")
    record = records[0]
    if (int(record.get("certificate_id") or 0) != 5944403
            or record.get("type_code") != "declaration"
            or record.get("accordance_type_code") != "EAEU"
            or record.get("status_code") != "approved"
            or str(record.get("issue_date") or "")[:10] != ISSUE
            or str(record.get("expire_date") or "")[:10] != EXPIRY):
        raise RuntimeError("ozon_record_not_current_approved_exact")
    bindings = client.ozon_bindings(5944403)
    by_pid = {str(x.get("product_id") or ""): x for x in bindings}
    if len(by_pid) != len(bindings):
        raise RuntimeError("duplicate_ozon_binding_product_id")
    conflicts = [b for b in bindings if str(b.get("product_id") or "") in
                 {x["product_id"] for x in ozon_targets.values()}
                 and str(b.get("sku") or "") != ozon_targets[next(
                     offer for offer, t in ozon_targets.items()
                     if t["product_id"] == str(b.get("product_id") or ""))]["sku"]]
    if conflicts:
        raise RuntimeError("ozon_binding_identity_conflict")
    missing = [x for x in ozon_targets.values() if x["product_id"] not in by_pid]
    state.update({"phase": "ozon_prewrite_verified", "ozon_existing_bindings": len(bindings),
                  "ozon_missing_targets": len(missing)})
    save(STATE, state)
    for offset in range(0, len(missing), 100):
        batch = missing[offset:offset + 100]
        payload = {"certificate_id": 5944403, "skus": sorted(x["sku"] for x in batch)}
        marker = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        journal({"at": now(), "platform": "ozon", "phase": "bind_prepared",
                 "request_sha256": marker, "offers": sorted(x["offer_id"] for x in batch),
                 "sku_count": len(batch)})
        state.update({"phase": "ozon_bind_outcome_pending", "ozon_bind_attempted": True,
                      "ozon_bind_payload_sha256": marker,
                      "ozon_bind_batch": offset // 100 + 1})
        save(STATE, state)
        try:
            response = client.call("ozon", "/v1/product/certificate/bind", payload, mutation=True)
            journal({"at": now(), "platform": "ozon", "phase": "bind_response", "response": response})
        except Exception as exc:
            journal({"at": now(), "platform": "ozon", "phase": "bind_outcome_uncertain",
                     "error_type": type(exc).__name__})
            state["ozon_bind_error_type"] = type(exc).__name__
        save(STATE, state)
        time.sleep(1)

    visible_bindings = client.ozon_bindings(5944403)
    visible_by_pid = {str(x.get("product_id") or ""): x for x in visible_bindings}
    ozon_rows = []
    for offer, target in sorted(ozon_targets.items()):
        binding = visible_by_pid.get(target["product_id"])
        ozon_rows.append({"offer_id": offer, "product_id": target["product_id"], "sku": target["sku"],
            "exact_visible": bool(binding and str(binding.get("sku") or "") == target["sku"]),
            "status": (binding or {}).get("product_status_code")})
    ozon_counts = collections.Counter(str(x["status"] or "unknown")
                                      for x in ozon_rows if x["exact_visible"])
    state.update({"phase": "ozon_readback_complete", "ozon_exact_visible": sum(x["exact_visible"] for x in ozon_rows),
                  "ozon_binding_status_counts": dict(ozon_counts)})
    save(STATE, state)

    # Only add declaration metadata to exact current WB cards; preserve all other card fields.
    wb_updates, wb_before = fresh_wb_updates(client, wb_expected)
    save(BEFORE, {"checked_at_utc": now(), "read_only": True, "cards": wb_before,
        "update_count": len(wb_updates), "already_exact_count": 153 - len(wb_updates)})
    for offset in range(0, len(wb_updates), 100):
        batch = wb_updates[offset:offset + 100]
        request_bytes = len(json.dumps(batch, ensure_ascii=False, separators=(",", ":")).encode())
        if request_bytes > 9_500_000:
            raise RuntimeError("wb_update_payload_exceeds_safe_limit")
        marker = hashlib.sha256(json.dumps(batch, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        offers_in_batch = [str((x.get("cards") or [x])[0].get("vendorCode") or "")
                           for x in batch]
        journal({"at": now(), "platform": "wb", "phase": "update_prepared",
                 "request_sha256": marker, "request_bytes": request_bytes,
                 "card_count": len(batch), "offers": offers_in_batch})
        state.update({"phase": "wb_update_outcome_pending", "wb_update_attempted": True,
                      "wb_update_payload_sha256": marker, "wb_update_batch": offset // 100 + 1,
                      "wb_update_cards": len(batch)})
        save(STATE, state)
        try:
            response = client.call("wb", "/content/v2/cards/update", batch, mutation=True)
            state.setdefault("wb_update_responses", []).append(response)
            journal({"at": now(), "platform": "wb", "phase": "update_response",
                     "response": response})
        except Exception as exc:
            state.setdefault("wb_update_error_types", []).append(type(exc).__name__)
            journal({"at": now(), "platform": "wb", "phase": "update_outcome_uncertain",
                     "error_type": type(exc).__name__})
        save(STATE, state)
        time.sleep(1)

    wb_rows = []
    for index, (offer, old) in enumerate(sorted(wb_expected.items()), 1):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            wb_rows.append({"offer_id": offer, "nmID": old["nmID"], "status": "missing_or_duplicate"})
            continue
        card = cards[0]
        same = [x for x in copy_documents(card)
                if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in same if str(x.get("type")) == "2"
                 and str(x.get("startDate") or "")[:10] == ISSUE
                 and str(x.get("endDate") or "")[:10] == EXPIRY
                 and x.get("isEndless") is False]
        unchanged = (offer not in wb_before or comparable_card(wb_before[offer]) == comparable_card(card))
        wb_rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
            "exact_metadata": len(same) == len(exact) == 1,
            "non_document_fields_unchanged": unchanged,
            "verdict": exact[0].get("verdict") if exact else None,
            "status": "verified_exact" if len(same) == len(exact) == 1 and unchanged
                     else "readback_mismatch"})
        if index % 25 == 0:
            print(json.dumps({"phase": "wb_readback", "checked": index,
                              "targets": len(wb_expected)}, ensure_ascii=False), flush=True)

    wb_status = collections.Counter(x["status"] for x in wb_rows)
    wb_verdicts = collections.Counter()
    for row in wb_rows:
        if row.get("status") != "verified_exact":
            continue
        v = row.get("verdict") or {}
        wb_verdicts["valid" if v.get("verified") is True and v.get("status") == 1
                    and v.get("reason") == "valid"
                    else "invalid" if v.get("verified") is True and v.get("status") == 2
                    else "pending_or_missing"] += 1

    readback = {"checked_at_utc": now(), "read_only": True, "number": NUMBER,
        "source_sha256": SOURCE_SHA256,
        "ozon_record": {k: record.get(k) for k in ("certificate_id", "certificate_number",
            "type_code", "status_code", "issue_date", "expire_date")},
        "ozon_targets": len(ozon_targets), "ozon_exact_visible": sum(x["exact_visible"] for x in ozon_rows),
        "ozon_binding_status_counts": dict(ozon_counts), "ozon_bindings": ozon_rows,
        "wb_targets": len(wb_expected), "wb_update_cards": len(wb_updates),
        "wb_exact_cards": wb_status.get("verified_exact", 0), "wb_card_status_counts": dict(wb_status),
        "wb_verdict_counts": dict(wb_verdicts), "wb_review_left_pending": True,
        "wb_cards": wb_rows, "local_source_deleted": False}
    save(READBACK, readback)
    state.update({"phase": "crossplatform_readback_complete", "finished_at_utc": now(),
        "ozon_exact_visible": readback["ozon_exact_visible"],
        "ozon_binding_status_counts": dict(ozon_counts), "wb_exact_cards": readback["wb_exact_cards"],
        "wb_card_status_counts": dict(wb_status), "wb_verdict_counts": dict(wb_verdicts),
        "wb_review_left_pending": True, "local_source_deleted": False})
    save(STATE, state)
    print(json.dumps({k: v for k, v in state.items()
                      if k not in ("wb_update_responses",)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
