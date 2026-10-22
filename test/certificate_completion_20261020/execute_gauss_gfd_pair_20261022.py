#!/usr/bin/env python3
"""Upload and attach the two complementary Gauss GFD documents to live-safe targets."""
from __future__ import annotations

import base64
import collections
import datetime as dt
import hashlib
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import comparable_card, norm_number, wb_datetime  # noqa: E402
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402

PREFLIGHT = HERE / "gauss_gfd_pair_live_preflight_20261022.json"
STATE_PATH = HERE / "gauss_gfd_pair_execution_20261022.json"
OZON_JOURNAL = HERE / "gauss_gfd_pair_ozon_mutations_20261022.jsonl"
WB_JOURNAL = HERE / "gauss_gfd_pair_wb_mutations_20261022.jsonl"
WB_BEFORE = HERE / "gauss_gfd_pair_wb_before_20261022.json"
WB_READBACK = HERE / "gauss_gfd_pair_wb_readback_20261022.json"
OZON_READBACK = HERE / "gauss_gfd_pair_ozon_readback_20261022.json"
EXPECTED_TNVED = {"9405420012"}
DOCS = [
    {"number": "ЕАЭС RU C-CN.НВ12.В.01250/24", "type_code": "certificate_of_conformity",
     "ozon_type": "CERTIFICATE_OF_CONFORMITY", "wb_type": 1,
     "issue_date": "2024-05-31", "expire_date": "2029-05-30",
     "source": ROOT / "output_to_user/certificates/group_1/documents/gauss/b35f33696bdfdfe23a91781d.pdf",
     "sha256": "1b763da18ff83df1b09596fee3b82d92c0cea2997467c0978355c4e818d1ce90"},
    {"number": "ЕАЭС N RU Д-CN.PA04.В.65150/24", "type_code": "declaration",
     "ozon_type": "DECLARATION", "wb_type": 2,
     "issue_date": "2024-05-31", "expire_date": "2029-05-30",
     "source": ROOT / "output_to_user/certificates/group_1/documents/gauss/84289bfc2e2b173292ad34d9.pdf",
     "sha256": "d8338a77eef5efb26031c200fbe5a4d33cb049522ed811dd77295fc110f17775"},
]


def save(path: pathlib.Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def journal(path: pathlib.Path, row: dict) -> None:
    with path.open("a") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()


def attr_values(row: dict, ident: str) -> set[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return {str(v.get("value") or "").strip()
            for v in (attrs.get(ident) or {}).get("values") or []
            if str(v.get("value") or "").strip()}


def wb_tnved(card: dict) -> set[str]:
    found: set[str] = set()
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        batch = raw if isinstance(raw, list) else [raw]
        found.update(str(x).split(" - ", 1)[0].strip() for x in batch if str(x or "").strip())
    return found


def all_records(client: Client) -> list[dict]:
    rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("invalid Ozon certificate list")
        rows.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("Ozon certificate page limit")


def find_record(client: Client, number: str, records: list[dict] | None = None) -> list[dict]:
    records = records if records is not None else all_records(client)
    return [x for x in records if norm_number(x.get("certificate_number")) == norm_number(number)]


def exact_wb_docs(card: dict, number: str) -> list[dict]:
    return [d for d in ((card.get("documents") or {}).get("items") or [])
            if norm_number(d.get("number")) == norm_number(number)]


def main() -> None:
    artifacts = (STATE_PATH, OZON_JOURNAL, WB_JOURNAL, WB_BEFORE, WB_READBACK, OZON_READBACK)
    if any(p.exists() for p in artifacts):
        raise RuntimeError("execution artifacts exist; reconcile before any retry")
    pre = json.loads(PREFLIGHT.read_text())
    if pre.get("read_only") is not True or pre.get("targets_expected") != 96 \
            or pre.get("ozon_safe_targets") != 93 or pre.get("wb_safe_targets") != 96:
        raise RuntimeError("live preflight scope or counts changed")
    for d in DOCS:
        if not d["source"].is_file() or hashlib.sha256(d["source"].read_bytes()).hexdigest() != d["sha256"]:
            raise RuntimeError("document source hash changed:" + d["number"])
    ozon_targets = {x["offer_id"]: x for x in pre["ozon_targets"] if x.get("safe_for_ozon") is True}
    wb_targets = {x["offer_id"]: x for x in pre["wb_targets"] if x.get("safe_for_wb") is True}
    exclusions = [{"platform": "Ozon", "offer_id": x["offer_id"], "problems": x["problems"]}
                  for x in pre["ozon_targets"] if not x.get("safe_for_ozon")]
    if len(ozon_targets) != 93 or len(wb_targets) != 96:
        raise RuntimeError("target sets are not unique or complete")
    if len({x["sku"] for x in ozon_targets.values()}) != 93:
        raise RuntimeError("Ozon target SKUs are not unique")

    client = Client()
    state = {"started_at_utc": now(), "documents": [{k: d[k] for k in ("number", "type_code", "issue_date", "expire_date", "sha256")} for d in DOCS],
        "ozon_preflight_targets_per_document": 93, "wb_preflight_cards": 96,
        "ozon_exclusions": exclusions, "ozon_mutation_attempted": False,
        "wb_mutation_attempted": False, "local_source_files_deleted": False,
        "wb_review_metadata_manually_changed": False, "phase": "fresh_prewrite_check"}
    save(STATE_PATH, state)

    # Recheck current Ozon identities before any record creation or binding.
    offers = sorted(ozon_targets)
    products, attrs = {}, {}
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        p_rows = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items")
        a_rows = client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": batch}, "limit": len(batch)}).get("result")
        if not isinstance(p_rows, list) or not isinstance(a_rows, list):
            raise RuntimeError("fresh Ozon product page invalid")
        for row in p_rows: products.setdefault(str(row.get("offer_id") or ""), []).append(row)
        for row in a_rows: attrs.setdefault(str(row.get("offer_id") or ""), []).append(row)
    if set(products) != set(offers) or set(attrs) != set(offers):
        raise RuntimeError("fresh Ozon target set changed")
    for offer, expected in ozon_targets.items():
        p_rows, a_rows = products[offer], attrs[offer]
        if len(p_rows) != 1 or len(a_rows) != 1:
            raise RuntimeError("Ozon product identity ambiguous:" + offer)
        p, a = p_rows[0], a_rows[0]
        brand = {x.casefold() for x in attr_values(a, "85")}
        tnved = {x.split(" - ", 1)[0].strip() for x in attr_values(a, "22232")}
        if (p.get("is_archived") is not False
                or str(p.get("product_id") or p.get("id") or "") != expected["product_id"]
                or str(p.get("sku") or "") != expected["sku"]
                or brand != {"gauss"} or not tnved or not tnved <= EXPECTED_TNVED):
            raise RuntimeError("fresh Ozon identity/scope changed:" + offer)

    # Recheck each Ozon number; reuse only an exact record without outside product bindings.
    all_rows = all_records(client)
    expected_pairs = {(x["product_id"], x["sku"]) for x in ozon_targets.values()}
    for d in DOCS:
        matches = find_record(client, d["number"], all_rows)
        if len(matches) > 1:
            raise RuntimeError("duplicate Ozon records:" + d["number"])
        record = matches[0] if matches else None
        if record and (record.get("type_code") != d["type_code"]
                       or str(record.get("issue_date") or "")[:10] != d["issue_date"]
                       or str(record.get("expire_date") or "")[:10] != d["expire_date"]):
            raise RuntimeError("Ozon record metadata conflict:" + d["number"])
        if record:
            existing = client.ozon_bindings(record["certificate_id"])
            outside = [b for b in existing if (str(b.get("product_id") or ""), str(b.get("sku") or "")) not in expected_pairs]
            if outside:
                raise RuntimeError("existing Ozon record has bindings outside this exact target set:" + d["number"])

    state["phase"] = "fresh_prewrite_checked"
    save(STATE_PATH, state)

    ozon_doc_results = []
    for d in DOCS:
        matches = find_record(client, d["number"])
        record = matches[0] if matches else None
        if record is None:
            expiry = dt.date.fromisoformat(d["expire_date"])
            first = next(iter(ozon_targets.values()))
            payload = {"params": {"name": ("Сертификат соответствия № " if d["type_code"] == "certificate_of_conformity" else "Декларация о соответствии № ") + d["number"],
                "certificate_type": d["ozon_type"], "certificate_country": "RU", "accordance_type": "EAEU",
                "number": d["number"], "issue_date": wb_datetime(d["issue_date"]),
                "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
                "skus": [first["sku"]], "product_type": "UNKNOWN",
                "files": [{"file_content": base64.b64encode(d["source"].read_bytes()).decode("ascii"), "name": d["source"].name}]}}
            marker = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            journal(OZON_JOURNAL, {"phase": "create_prepared", "at": now(), "number": d["number"],
                "request_sha256": marker, "source_sha256": d["sha256"], "initial_sku": first["sku"]})
            state.update({"phase": "ozon_create_outcome_pending", "ozon_mutation_attempted": True,
                          "creating_number": d["number"], "last_ozon_create_payload_sha256": marker})
            save(STATE_PATH, state)
            try:
                response = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
                journal(OZON_JOURNAL, {"phase": "create_response", "at": now(), "number": d["number"], "response": response})
            except Exception as exc:
                state.update({"phase": "ozon_create_outcome_uncertain", "uncertain_number": d["number"], "error_type": type(exc).__name__})
                journal(OZON_JOURNAL, {"phase": "create_outcome_uncertain", "at": now(), "number": d["number"], "error_type": type(exc).__name__})
                save(STATE_PATH, state)
                raise
            record = None
            for attempt in range(6):
                visible = find_record(client, d["number"])
                if len(visible) > 1: raise RuntimeError("duplicate Ozon records after create:" + d["number"])
                if visible: record = visible[0]; break
                if attempt < 5: time.sleep(2)
            if not record:
                state.update({"phase": "ozon_record_not_visible_no_retry", "uncertain_number": d["number"]}); save(STATE_PATH, state)
                raise RuntimeError("created Ozon record not visible; do not retry")
        if (record.get("type_code") != d["type_code"]
                or str(record.get("issue_date") or "")[:10] != d["issue_date"]
                or str(record.get("expire_date") or "")[:10] != d["expire_date"]):
            state.update({"phase": "ozon_created_record_metadata_conflict", "conflict_number": d["number"], "record": record}); save(STATE_PATH, state)
            raise RuntimeError("created record metadata mismatch")
        status = str(record.get("status_code") or "").casefold()
        result = {"number": d["number"], "certificate_id": int(record["certificate_id"]),
                  "record_status": status, "type_code": record.get("type_code"),
                  "issue_date": str(record.get("issue_date") or "")[:10], "expire_date": str(record.get("expire_date") or "")[:10]}
        if status in {"declined", "rejected", "invalid", "cancelled"}:
            result.update({"bindings_expected": 93, "bindings_visible_exact": 0, "binding_status_counts": {}, "problem": "record_declined_no_binding"})
            ozon_doc_results.append(result)
            state["ozon_documents"] = ozon_doc_results; state.update({"phase": "ozon_record_declined_skip_document", "declined_number": d["number"]}); save(STATE_PATH, state)
            continue

        cid = result["certificate_id"]
        bindings_before = client.ozon_bindings(cid)
        before_pairs = {(str(b.get("product_id") or ""), str(b.get("sku") or "")) for b in bindings_before}
        outside = [b for b in bindings_before if (str(b.get("product_id") or ""), str(b.get("sku") or "")) not in expected_pairs]
        if outside: raise RuntimeError("new/reused Ozon record has outside bindings:" + d["number"])
        missing = [x for x in ozon_targets.values() if (x["product_id"], x["sku"]) not in before_pairs]
        if missing:
            bind_payload = {"certificate_id": cid, "skus": sorted(x["sku"] for x in missing)}
            marker = hashlib.sha256(json.dumps(bind_payload, sort_keys=True).encode()).hexdigest()
            journal(OZON_JOURNAL, {"phase": "bind_prepared", "at": now(), "number": d["number"], "certificate_id": cid,
                "request_sha256": marker, "sku_count": len(missing), "skus": bind_payload["skus"]})
            state.update({"phase": "ozon_bind_outcome_pending", "ozon_mutation_attempted": True,
                          "binding_number": d["number"], "binding_skus": len(missing)})
            save(STATE_PATH, state)
            response = client.call("ozon", "/v1/product/certificate/bind", bind_payload, mutation=True)
            journal(OZON_JOURNAL, {"phase": "bind_response", "at": now(), "number": d["number"], "response": response})
        rows = []
        after = []
        for attempt in range(5):
            after = client.ozon_bindings(cid)
            by_product = {str(b.get("product_id") or ""): b for b in after}
            rows = []
            for x in ozon_targets.values():
                b = by_product.get(x["product_id"])
                rows.append({"offer_id": x["offer_id"], "product_id": x["product_id"], "sku": x["sku"],
                    "visible": bool(b), "identity_exact": bool(b and str(b.get("sku") or "") == x["sku"]),
                    "product_status_code": (b or {}).get("product_status_code")})
            if all(x["visible"] and x["identity_exact"] for x in rows): break
            if attempt < 4: time.sleep(2)
        result.update({"bindings_expected": 93,
            "bindings_visible_exact": sum(x["visible"] and x["identity_exact"] for x in rows),
            "binding_status_counts": dict(collections.Counter(str(x.get("product_status_code") or "unknown") for x in rows if x["visible"] and x["identity_exact"])),
            "missing_or_conflicting": [x for x in rows if not x["visible"] or not x["identity_exact"]],
            "rows": rows, "binding_total": len(after)})
        ozon_doc_results.append(result)
        state.update({"ozon_documents": ozon_doc_results, "phase": "ozon_bindings_read_back"})
        save(STATE_PATH, state)

    save(OZON_READBACK, {"checked_at_utc": now(), "read_only": True, "targets": 93, "documents": ozon_doc_results,
        "excluded_ozon_offers": exclusions, "local_source_files_deleted": False})

    # Add each non-declined document to WB, with a live identity/scope check immediately before update.
    accepted_docs = []
    declined = {x["number"] for x in ozon_doc_results if x.get("problem") == "record_declined_no_binding"}
    for d, result in zip(DOCS, ozon_doc_results):
        if d["number"] not in declined:
            accepted_docs.append(d)
    if not accepted_docs:
        state.update({"phase": "no_ozon_document_accepted_skip_wb", "wb_updates_planned": 0}); save(STATE_PATH, state)
        raise RuntimeError("both Ozon document records declined; skipped WB writes")

    updates, already, wb_exclusions, before = [], [], [], {}
    desired_by_number = {norm_number(d["number"]): {"type": d["wb_type"], "number": d["number"],
        "startDate": wb_datetime(d["issue_date"]), "endDate": wb_datetime(d["expire_date"]), "isEndless": False}
        for d in accepted_docs}
    for i, (offer, expected) in enumerate(sorted(wb_targets.items()), 1):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            wb_exclusions.append({"offer_id": offer, "reason": "fresh_wb_card_missing_or_duplicate", "count": len(cards)}); continue
        card = cards[0]; codes = wb_tnved(card)
        if (str(card.get("nmID") or "") != expected["nmID"]
                or str(card.get("brand") or "").strip().casefold() != "gauss"
                or not codes or not codes <= EXPECTED_TNVED):
            wb_exclusions.append({"offer_id": offer, "reason": "fresh_wb_identity_or_scope_changed",
                "nmID": str(card.get("nmID") or ""), "brand": card.get("brand"), "tnved": sorted(codes)}); continue
        missing_desired = []
        for d in accepted_docs:
            same = exact_wb_docs(card, d["number"])
            exact = [x for x in same if str(x.get("type")) == str(d["wb_type"])
                     and str(x.get("startDate") or "")[:10] == d["issue_date"]
                     and str(x.get("endDate") or "")[:10] == d["expire_date"]
                     and x.get("isEndless") is False]
            if len(exact) == 1 and len(same) == 1:
                already.append({"offer_id": offer, "number": d["number"], "document": exact[0]})
            elif same:
                wb_exclusions.append({"offer_id": offer, "reason": "existing_document_metadata_conflict", "number": d["number"], "documents": same})
            else:
                missing_desired.append(desired_by_number[norm_number(d["number"])])
        if missing_desired:
            payload = merge_wb(card, missing_desired)
            if payload is not None:
                updates.append({"offer_id": offer, "nmID": expected["nmID"], "payload": payload})
                before[offer] = card
        if i % 20 == 0: print(json.dumps({"phase": "fresh_wb_prewrite", "checked": i, "targets": len(wb_targets), "cards_to_update": len(updates), "exclusions": len(wb_exclusions)}, ensure_ascii=False), flush=True)

    save(WB_BEFORE, {"checked_at_utc": now(), "read_only": True, "cards": before,
        "already_exact": already, "exclusions": wb_exclusions})
    state.update({"wb_fresh_targets": len(wb_targets), "wb_updates_planned": len(updates),
        "wb_already_exact_documents": len(already), "wb_prewrite_exclusions": wb_exclusions,
        "phase": "wb_fresh_prewrite_checked"})
    save(STATE_PATH, state)
    if updates:
        for batch_index, start in enumerate(range(0, len(updates), 24), 1):
            batch = updates[start:start + 24]
            payload = [x["payload"] for x in batch]
            nbytes = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
            if nbytes > 9_500_000: raise RuntimeError("WB chunk exceeds safe request size")
            marker = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            journal(WB_JOURNAL, {"phase": "update_prepared", "at": now(), "batch_index": batch_index,
                "request_sha256": marker, "request_bytes": nbytes, "card_count": len(batch), "offers": [x["offer_id"] for x in batch]})
            state.update({"phase": "wb_update_outcome_pending", "wb_mutation_attempted": True,
                "wb_batch_index": batch_index, "wb_batch_count": (len(updates) + 23) // 24, "wb_request_sha256": marker})
            save(STATE_PATH, state)
            try:
                response = client.call("wb", "/content/v2/cards/update", payload, mutation=True)
                journal(WB_JOURNAL, {"phase": "update_response", "at": now(), "batch_index": batch_index, "response": response})
            except Exception as exc:
                state.update({"phase": "wb_update_outcome_uncertain", "error_type": type(exc).__name__, "uncertain_batch": batch_index})
                save(STATE_PATH, state); raise
            if response.get("error") is not False:
                state.update({"phase": "wb_update_rejected_reconcile", "wb_update_response": response, "rejected_batch": batch_index}); save(STATE_PATH, state)
                raise RuntimeError("WB update rejected; reconcile before retry")

    readback_rows = []
    for i, (offer, expected) in enumerate(sorted(wb_targets.items()), 1):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            readback_rows.append({"offer_id": offer, "status": "missing_or_duplicate", "card_count": len(cards)}); continue
        card = cards[0]; checks = []
        for d in accepted_docs:
            docs_now = exact_wb_docs(card, d["number"])
            exact = [x for x in docs_now if str(x.get("type")) == str(d["wb_type"])
                     and str(x.get("startDate") or "")[:10] == d["issue_date"]
                     and str(x.get("endDate") or "")[:10] == d["expire_date"]
                     and x.get("isEndless") is False]
            checks.append({"number": d["number"], "exact_metadata": len(exact) == 1 and len(docs_now) == 1,
                           "verdict": (exact[0].get("verdict") if exact else None), "documents": docs_now})
        unchanged = offer not in before or comparable_card(before[offer]) == comparable_card(card)
        exact_all = all(x["exact_metadata"] for x in checks)
        readback_rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
            "status": "verified_exact" if exact_all and unchanged else "readback_mismatch",
            "all_exact_metadata": exact_all, "non_document_fields_unchanged": unchanged,
            "documents": checks})
        if i % 20 == 0: print(json.dumps({"phase": "wb_targeted_readback", "queried": i, "targets": len(wb_targets),
            "verified_exact": sum(x["status"] == "verified_exact" for x in readback_rows)}, ensure_ascii=False), flush=True)
    statuses = collections.Counter(x["status"] for x in readback_rows)
    verdicts = collections.Counter()
    for row in readback_rows:
        if row["status"] != "verified_exact": continue
        for doc in row["documents"]:
            verdict = doc.get("verdict") or {}
            key = "valid" if verdict.get("verified") is True and verdict.get("status") == 1 and verdict.get("reason") == "valid" else (
                "invalid" if verdict.get("verified") is True and verdict.get("status") == 2 else "no_verdict_yet")
            verdicts[key] += 1
    wb_result = {"checked_at_utc": now(), "read_only": True, "documents": [d["number"] for d in accepted_docs],
        "target_cards": len(wb_targets), "updated_cards": len(updates), "preexisting_exact_document_edges": len(already),
        "prewrite_exclusions": wb_exclusions, "status_counts": dict(statuses), "verdict_counts": dict(verdicts),
        "review_metadata_manually_changed": False, "local_source_files_deleted": False, "results": readback_rows}
    save(WB_READBACK, wb_result)
    state.update({"wb_readback_status_counts": dict(statuses), "wb_verdict_counts": dict(verdicts),
        "wb_exact_metadata_cards": statuses.get("verified_exact", 0), "wb_review_metadata_manually_changed": False,
        "wb_documents_attached": [d["number"] for d in accepted_docs], "local_source_files_deleted": False,
        "phase": "cross_marketplace_readback_incomplete", "finished_at_utc": now()})
    save(STATE_PATH, state)
    print(json.dumps({"phase": state["phase"], "documents": ozon_doc_results,
        "ozon_excluded": len(exclusions), "wb_updates": len(updates), "wb_status_counts": dict(statuses),
        "wb_verdict_counts": dict(verdicts), "wb_review_metadata_manually_changed": False}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
