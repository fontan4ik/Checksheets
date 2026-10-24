#!/usr/bin/env python3
"""Upload and attach verified Navigator driver declaration and certificate.

The script rechecks live identities and scope immediately before writing,
journals each mutation, never retries uncertain writes, reads results back,
leaves WB review to the marketplace, and retains all local source PDFs.
"""
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
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
import run_all_found_certificates_20261014 as runner  # noqa: E402
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    copy_documents, doc_key, norm_number, wb_datetime, comparable_card,
)

PREFLIGHT = HERE / "navigator_81746_31480_live_preflight_20261024.json"
STATE = HERE / "navigator_81746_31480_execution_20261024.json"
BEFORE = HERE / "navigator_81746_31480_wb_before_20261024.json"
READBACK = HERE / "navigator_81746_31480_readback_20261024.json"
JOURNAL = HERE / "navigator_81746_31480_mutation_journal_20261024.jsonl"
ALLOWED_TNVED = {"8504409100"}

DOCS = {
    "declaration": {
        "number": "ЕАЭС N RU Д-CN.РА08.В.81746/23",
        "type_code": "declaration", "wb_type": 2,
        "issue_date": "2023-10-20", "expire_date": "2028-10-17",
        "file": ROOT / "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_declaration_71463_a9376c13312a.pdf",
        "sha256": "a9376c13312a5a94adc153bd08a2daad43870649ddbecfeb00fd36ea8230d750",
        "registry_url": "https://pub.fsa.gov.ru/rds/declaration/view/18254666/common",
    },
    "certificate": {
        "number": "ЕАЭС RU С-CN.АЯ46.В.31480/23",
        "type_code": "certificate_of_conformity", "wb_type": 1,
        "issue_date": "2023-10-12", "expire_date": "2028-10-11",
        "file": ROOT / "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_eac_certificate_71463_334715b90037.pdf",
        "sha256": "334715b900377fa233651bc452b1c0ba737cbb4fa05387192f004edd845241c6",
        "registry_url": "https://pub.fsa.gov.ru/rss/certificate/view/3328338/baseInfo",
    },
}


def save(path: pathlib.Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def journal(row: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as out:
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
        out.flush()


def list_certificates(client: Client) -> list[dict]:
    rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        rows.extend(batch)
        if page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("ozon_certificate_list_page_limit")


def card_tnved(card: dict) -> list[str]:
    values = []
    for item in card.get("characteristics") or []:
        label = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" in label or "тнвед" in label:
            raw = item.get("value")
            values.extend(raw if isinstance(raw, list) else [raw])
    return sorted({str(v).split(" - ", 1)[0].strip() for v in values if str(v).strip()})


def fresh_ozon_targets(client: Client, targets: list[dict]) -> list[dict]:
    offers = [str(x["offer_id"]) for x in targets]
    products, attrs = [], []
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        products.extend(client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or [])
        attrs.extend(client.call("ozon", "/v4/product/info/attributes",
                                {"filter": {"offer_id": batch}, "limit": len(batch)}).get("result") or [])
    pmap, amap = collections.defaultdict(list), collections.defaultdict(list)
    for row in products:
        pmap[str(row.get("offer_id"))].append(row)
    for row in attrs:
        amap[str(row.get("offer_id"))].append(row)
    output = []
    for target in targets:
        offer = str(target["offer_id"])
        if len(pmap[offer]) != 1 or len(amap[offer]) != 1:
            raise RuntimeError("fresh_ozon_product_or_attributes_not_unique:" + offer)
        product, attr = pmap[offer][0], amap[offer][0]
        product_id, sku = str(product.get("product_id") or product.get("id") or ""), str(product.get("sku") or "")
        values = {str(a.get("id")): [str(v.get("value") or "").strip()
                  for v in a.get("values") or [] if str(v.get("value") or "").strip()]
                  for a in attr.get("attributes") or []}
        brands = values.get("85", [])
        codes = sorted({v.split(" - ", 1)[0].strip() for v in values.get("22232", [])})
        if (product_id != str(target["product_id"]) or sku != str(target["sku"])
                or product.get("is_archived") is not False
                or not brands or any(x.casefold() != "navigator" for x in brands)
                or not codes or not set(codes) <= ALLOWED_TNVED):
            raise RuntimeError("fresh_ozon_identity_brand_or_tnved_conflict:" + offer)
        output.append({**target, "name": product.get("name"), "brand_values": brands, "tnved_codes": codes})
    return output


def fresh_wb_cards(client: Client, targets: list[dict]) -> list[dict]:
    output = []
    for target in targets:
        offer = str(target["offer_id"])
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            raise RuntimeError("fresh_wb_card_count_conflict:" + offer)
        card = cards[0]
        codes = card_tnved(card)
        if (str(card.get("vendorCode")) != offer or str(card.get("nmID")) != str(target["wb_nmID"])
                or str(card.get("brand") or "").strip().casefold() != "navigator"
                or not codes or not set(codes) <= ALLOWED_TNVED):
            raise RuntimeError("fresh_wb_identity_brand_or_tnved_conflict:" + offer)
        output.append({"offer_id": offer, "nmID": str(card["nmID"]), "card": card,
                       "tnved_codes": codes})
    return output


def exact_record(client: Client, doc: dict) -> tuple[dict | None, list[dict]]:
    matches = [x for x in list_certificates(client)
               if norm_number(x.get("certificate_number")) == norm_number(doc["number"])]
    if len(matches) > 1:
        raise RuntimeError("ozon_duplicate_exact_document_records:" + doc["number"])
    if not matches:
        return None, []
    record = matches[0]
    if (record.get("type_code") != doc["type_code"]
            or str(record.get("issue_date", ""))[:10] != doc["issue_date"]
            or str(record.get("expire_date", ""))[:10] != doc["expire_date"]
            or record.get("accordance_type_code") not in (None, "EAEU")):
        raise RuntimeError("ozon_existing_document_metadata_conflict:" + doc["number"])
    return record, client.ozon_bindings(int(record["certificate_id"]))


def create_record(client: Client, doc: dict, seed_sku: str) -> tuple[dict | None, dict]:
    record, _ = exact_record(client, doc)
    if record:
        return record, {"created": False, "already_present": True}
    expiry = dt.date.fromisoformat(doc["expire_date"])
    payload = {"params": {
        "name": "Документ " + doc["number"],
        "certificate_type": doc["type_code"].upper(),
        "certificate_country": "RU", "accordance_type": "EAEU",
        "number": doc["number"], "issue_date": wb_datetime(doc["issue_date"]),
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [str(seed_sku)], "product_type": "UNKNOWN",
        "link_to_registry": doc["registry_url"],
        "files": [{"file_content": base64.b64encode(doc["file"].read_bytes()).decode("ascii"),
                   "name": doc["file"].name}],
    }}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) >= 15_000_000:
        raise RuntimeError("ozon_create_request_too_large")
    marker = {"at": now(), "platform": "ozon", "endpoint": "/v2/product/certificate/create",
              "document_number": doc["number"], "phase": "prepared",
              "payload_sha256": hashlib.sha256(encoded).hexdigest(),
              "payload_bytes": len(encoded), "seed_sku": str(seed_sku)}
    journal(marker)
    state = json.loads(STATE.read_text())
    state["phase"] = "ozon_create_started"
    state["current_document"] = doc["number"]
    save(STATE, state)
    response, error = None, None
    try:
        response = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
    except Exception as exc:
        error = type(exc).__name__
    journal({**marker, "at": now(), "phase": "response" if response is not None else "uncertain",
             "response": response, "error_type": error})
    found = []
    for attempt in range(6):
        found = [x for x in list_certificates(client)
                 if norm_number(x.get("certificate_number")) == norm_number(doc["number"])]
        if found or attempt == 5:
            break
        time.sleep(2)
    if len(found) != 1:
        return None, {"created": bool((response or {}).get("certificate_id")),
                      "outcome": "uncertain_no_unique_record_visible_no_retry", "error_type": error,
                      "create_response": response}
    record = found[0]
    if (record.get("type_code") != doc["type_code"]
            or str(record.get("issue_date", ""))[:10] != doc["issue_date"]
            or str(record.get("expire_date", ""))[:10] != doc["expire_date"]
            or record.get("accordance_type_code") not in (None, "EAEU")):
        raise RuntimeError("ozon_created_document_metadata_conflict:" + doc["number"])
    params = [x for x in (response or {}).get("params", []) if isinstance(x, dict)]
    validated = response is not None and response.get("status") == "COMPLETED" and params and all(x.get("state") == "VALID" for x in params)
    if not validated:
        return record, {"created": True, "outcome": "visible_create_response_not_fully_validated",
                        "create_response": response, "error_type": error}
    return record, {"created": True, "outcome": "visible_and_create_response_validated",
                    "create_response": response}


def bind_document(client: Client, doc: dict, record: dict, targets: list[dict]) -> dict:
    cid = int(record["certificate_id"])
    expected = {(str(x["product_id"]), str(x["sku"])) for x in targets}
    current = client.ozon_bindings(cid)
    pairs = [(str(x.get("product_id") or ""), str(x.get("sku") or "")) for x in current]
    if any(not p or not s for p, s in pairs) or len(pairs) != len(set(pairs)):
        raise RuntimeError("ozon_binding_identity_missing_or_duplicate:" + doc["number"])
    if any(p not in {x[0] for x in expected} for p, _ in pairs):
        raise RuntimeError("ozon_record_has_binding_outside_target_products:" + doc["number"])
    by_product = {str(x.get("product_id")): x for x in current}
    for product_id, sku in expected:
        old = by_product.get(product_id)
        if old and str(old.get("sku")) != sku:
            raise RuntimeError("ozon_binding_sku_conflict:" + product_id)
        if old and str(old.get("product_status_code") or "").casefold() in {"declined", "rejected", "cancelled", "invalid"}:
            raise RuntimeError("ozon_target_binding_declined:" + product_id)
    missing = sorted(expected - set(pairs))
    if missing:
        request = {"certificate_id": cid, "skus": [sku for _, sku in missing]}
        entry = {"at": now(), "platform": "ozon", "endpoint": "/v1/product/certificate/bind",
                 "document_number": doc["number"], "certificate_id": cid, "phase": "prepared",
                 "skus": request["skus"], "payload_sha256": hashlib.sha256(
                     json.dumps(request, separators=(",", ":")).encode()).hexdigest()}
        journal(entry)
        state = json.loads(STATE.read_text())
        state["phase"] = "ozon_bind_started"
        save(STATE, state)
        response, error = None, None
        try:
            response = client.call("ozon", "/v1/product/certificate/bind", request, mutation=True)
        except Exception as exc:
            error = type(exc).__name__
        journal({**entry, "at": now(), "phase": "response" if response is not None else "uncertain",
                 "response": response, "error_type": error})
    live = client.ozon_bindings(cid)
    live_pairs = [(str(x.get("product_id") or ""), str(x.get("sku") or "")) for x in live]
    statuses = collections.Counter(str(x.get("product_status_code") or "unknown") for x in live)
    info = client.call("ozon", "/v1/product/certificate/info",
                       {"certificate_number": doc["number"]}).get("result") or {}
    exact_count = sum(pair in expected for pair in live_pairs)
    outside = sum(pair not in expected for pair in live_pairs)
    return {"certificate_id": cid, "record_status": info.get("status_code"),
            "expected_exact_bindings": len(expected), "visible_exact_bindings": exact_count,
            "unexpected_binding_count": outside, "binding_status_counts": dict(statuses),
            "all_expected_pairs_visible": expected <= set(live_pairs),
            "local_source_file_deleted": False}


def apply_wb(client: Client, wb_rows: list[dict]) -> dict:
    wanted = [{"type": doc["wb_type"], "number": doc["number"],
               "startDate": wb_datetime(doc["issue_date"]), "endDate": wb_datetime(doc["expire_date"]),
               "isEndless": False} for doc in DOCS.values()]
    prepared, before_rows = [], []
    for row in wb_rows:
        card = row["card"]
        items = copy_documents(card)
        for wish in wanted:
            same = [x for x in items if norm_number(x.get("number")) == norm_number(wish["number"])]
            exact = [x for x in same if doc_key(x) == doc_key(wish)
                     and str(x.get("startDate", ""))[:10] == wish["startDate"][:10]
                     and str(x.get("endDate", ""))[:10] == wish["endDate"][:10]
                     and x.get("isEndless") is False]
            if same and (len(same) != 1 or len(exact) != 1):
                raise RuntimeError("wb_same_number_metadata_conflict:" + row["offer_id"] + ":" + wish["number"])
        payload = runner.merge_wb(card, wanted)
        before_rows.append({"offer_id": row["offer_id"], "nmID": row["nmID"], "card": card,
                            "prior_document_count": len(items), "already_exact": payload is None})
        if payload is not None:
            prepared.append({"offer_id": row["offer_id"], "nmID": row["nmID"], "payload": payload,
                             "before": card, "prior_documents": items})
    save(BEFORE, {"checked_at_utc": now(), "target_count": len(wb_rows),
                  "update_count": len(prepared), "cards": before_rows})
    state = json.loads(STATE.read_text())
    state.update({"phase": "wb_fresh_cards_verified", "wb_update_count": len(prepared),
                  "wb_already_exact_count": len(wb_rows) - len(prepared)})
    save(STATE, state)
    if prepared:
        payloads = [x["payload"] for x in prepared]
        marker = hashlib.sha256(json.dumps(payloads, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        journal({"at": now(), "platform": "wb", "endpoint": "/content/v2/cards/update",
                 "phase": "prepared", "offers": [x["offer_id"] for x in prepared],
                 "document_numbers": [x["number"] for x in DOCS.values()], "payload_sha256": marker})
        state = json.loads(STATE.read_text())
        state["phase"] = "wb_update_started"
        save(STATE, state)
        response, error = None, None
        try:
            response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
        except Exception as exc:
            error = type(exc).__name__
        journal({"at": now(), "platform": "wb", "endpoint": "/content/v2/cards/update",
                 "phase": "response" if response is not None else "uncertain",
                 "payload_sha256": marker, "response": response, "error_type": error})
    else:
        response, error = None, None

    before_by_offer = {x["offer_id"]: x for x in prepared}
    results, failures, verdict_counts = [], [], collections.Counter()
    for wb_row in wb_rows:
        offer = wb_row["offer_id"]
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            failures.append({"offer_id": offer, "problem": "readback_card_count", "count": len(cards)})
            continue
        card = cards[0]
        items = copy_documents(card)
        exact_docs = []
        for wish in wanted:
            found = [x for x in items if norm_number(x.get("number")) == norm_number(wish["number"])
                     and doc_key(x) == doc_key(wish)
                     and str(x.get("startDate", ""))[:10] == wish["startDate"][:10]
                     and str(x.get("endDate", ""))[:10] == wish["endDate"][:10]
                     and x.get("isEndless") is False]
            if len(found) != 1:
                failures.append({"offer_id": offer, "problem": "exact_document_missing_or_duplicate",
                                 "number": wish["number"], "count": len(found)})
            else:
                exact_docs.extend(found)
                verdict = found[0].get("verdict")
                status = "valid" if isinstance(verdict, dict) and verdict.get("verified") is True and verdict.get("reason") == "valid" else "pending_review_or_unverified"
                verdict_counts[status] += 1
        before = before_by_offer.get(offer)
        if before:
            previous = before["prior_documents"]
            old_sigs = {(doc_key(x), str(x.get("number")), str(x.get("startDate", ""))[:10],
                         str(x.get("endDate", ""))[:10], bool(x.get("isEndless"))) for x in previous}
            new_sigs = {(doc_key(x), str(x.get("number")), str(x.get("startDate", ""))[:10],
                         str(x.get("endDate", ""))[:10], bool(x.get("isEndless"))) for x in items}
            old_preserved = old_sigs <= new_sigs
            fields_preserved = comparable_card(card) == comparable_card(before["before"])
            if not old_preserved or not fields_preserved:
                failures.append({"offer_id": offer, "problem": "prior_data_or_card_fields_changed"})
        else:
            old_preserved, fields_preserved = True, True
        results.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                        "exact_document_count": len(exact_docs), "expected_documents": 2,
                        "prior_documents_preserved": old_preserved,
                        "unrelated_card_fields_preserved": fields_preserved,
                        "document_verdicts": [x.get("verdict") for x in exact_docs]})
    return {"checked_at_utc": now(), "complete": len(results) == len(wb_rows),
            "target_cards": len(wb_rows), "updated_cards": len(prepared),
            "cards_with_both_exact_documents": sum(x["exact_document_count"] == 2 for x in results),
            "document_verdict_counts": dict(verdict_counts), "failures": failures,
            "response": response, "error_type": error, "cards": results,
            "wb_left_for_marketplace_review": True}


def main() -> None:
    for path in (STATE, BEFORE, READBACK, JOURNAL):
        if path.exists():
            raise RuntimeError("execution_artifact_exists_reconcile_first:" + path.name)
    if not PREFLIGHT.is_file():
        raise RuntimeError("fresh_preflight_missing")
    pre = json.loads(PREFLIGHT.read_text())
    checked = dt.datetime.fromisoformat(pre["checked_at_utc"].replace("Z", "+00:00"))
    if (pre.get("read_only") is not True or pre.get("target_count") != 8
            or pre.get("summary", {}).get("ozon_identity_brand_tnved_exact") != 8
            or pre.get("summary", {}).get("wb_unique_identity_brand_tnved_exact") != 8
            or (dt.datetime.now(dt.timezone.utc) - checked).total_seconds() > 3600):
        raise RuntimeError("fresh_preflight_incomplete_or_stale")
    for doc in DOCS.values():
        if not doc["file"].is_file() or hashlib.sha256(doc["file"].read_bytes()).hexdigest() != doc["sha256"]:
            raise RuntimeError("source_pdf_missing_or_hash_mismatch:" + doc["number"])
        if not (dt.date.fromisoformat(doc["issue_date"]) <= dt.datetime.now(dt.timezone.utc).date()
                <= dt.date.fromisoformat(doc["expire_date"])):
            raise RuntimeError("document_outside_validity_dates:" + doc["number"])
    targets = pre["targets"]
    if len(targets) != 8 or len({x["offer_id"] for x in targets}) != 8:
        raise RuntimeError("unexpected_fresh_target_set")

    client = Client()
    ozon_targets = fresh_ozon_targets(client, targets)
    wb_rows = fresh_wb_cards(client, targets)
    state = {"started_at_utc": now(), "phase": "fresh_identities_verified",
             "preflight_checked_at_utc": pre["checked_at_utc"], "target_count": 8,
             "ozon_target_count": len(ozon_targets), "wb_target_count": len(wb_rows),
             "documents": {}, "wb_left_for_marketplace_review": True,
             "local_source_files_deleted": False}
    save(STATE, state)

    for key, doc in DOCS.items():
        result = {"phase": "not_processed"}
        try:
            record, create = create_record(client, doc, ozon_targets[0]["sku"])
            if record is None:
                result = {"phase": "no_unique_record_visible_no_binding", "create": create}
            elif create.get("outcome") == "visible_create_response_not_fully_validated":
                result = {"phase": "visible_create_response_unvalidated_no_binding",
                          "record_id": record.get("certificate_id"), "create": create}
            elif str(record.get("status_code") or "").casefold() in {"declined", "rejected", "cancelled", "invalid"}:
                result = {"phase": "record_declined_no_binding", "record_status": record.get("status_code"),
                          "create": create}
            else:
                binding = bind_document(client, doc, record, ozon_targets)
                result = {"phase": "binding_readback_complete", "create": create, "binding": binding,
                          "source_sha256": doc["sha256"]}
        except Exception as exc:
            result = {"phase": "processing_error", "error_type": type(exc).__name__, "detail": str(exc)[:500]}
        state = json.loads(STATE.read_text())
        state["documents"][key] = result
        state["phase"] = "ozon_document_processed"
        save(STATE, state)
        print(json.dumps({"ozon_document": doc["number"], "result": result}, ensure_ascii=False), flush=True)

    state = json.loads(STATE.read_text())
    state["phase"] = "ozon_reconciled_starting_wb"
    save(STATE, state)
    try:
        wb_result = apply_wb(client, wb_rows)
    except Exception as exc:
        wb_result = {"phase": "processing_error", "error_type": type(exc).__name__, "detail": str(exc)[:500],
                     "wb_left_for_marketplace_review": True}
    save(READBACK, wb_result)
    state = json.loads(STATE.read_text())
    state["wb"] = {k: v for k, v in wb_result.items() if k != "cards"}
    ozon_ok = all(x.get("binding", {}).get("all_expected_pairs_visible") is True
                  and x.get("binding", {}).get("unexpected_binding_count") == 0
                  for x in state["documents"].values()) and len(state["documents"]) == len(DOCS)
    wb_ok = wb_result.get("complete") is True and wb_result.get("cards_with_both_exact_documents") == 8 and not wb_result.get("failures")
    state["phase"] = "finished_readback_complete_wb_review_pending" if ozon_ok and wb_ok else "finished_with_readback_problems"
    state["finished_at_utc"] = now()
    state["all_ozon_exact_bindings_visible"] = ozon_ok
    state["all_wb_exact_document_metadata_visible"] = wb_ok
    state["local_source_files_deleted"] = False
    save(STATE, state)
    print(json.dumps({"state": str(STATE), "readback": str(READBACK), "phase": state["phase"],
                      "documents": state["documents"], "wb": state["wb"],
                      "local_source_files_deleted": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
