#!/usr/bin/env python3
"""Attach Gauss declaration 53277/22 to the exact listed product articles on Ozon/WB."""
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
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
import run_all_found_certificates_20261014 as runner  # noqa: E402
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    copy_documents, doc_key, norm_number, wb_datetime, comparable_card,
)

PREFLIGHT = HERE / "gauss_53277_scope_preflight_20261022.json"
SCOPE_PROOF = HERE / "gauss_53277_scope_proof_20261022.json"
STATE = HERE / "gauss_53277_scope_execution_20261022.json"
BEFORE = HERE / "gauss_53277_scope_wb_before_20261022.json"
READBACK = HERE / "gauss_53277_scope_readback_20261022.json"
JOURNAL = HERE / "gauss_53277_scope_mutation_journal_20261022.jsonl"

DOCS = {
    "declaration": {
        "number": "ЕАЭС N RU Д-CN.PA01.В.53277/22",
        "type_code": "declaration",
        "wb_type": 2,
        "issue_date": "2022-02-01",
        "expire_date": "2027-01-31",
        "file": ROOT / "output_to_user/certificates/group_1/documents/gauss/7a873cb4c9a98e7713618935.pdf",
        "sha256": "3f1197e48a91cae3c774c20547ae4bd2f93bac1ae4443d66d4de14f662990fbf",
        "registry_url": "https://pub.fsa.gov.ru/rds/declaration/view/16650422/common",
    },
}
ALLOWED_TNVED = {"8539519009"}
SCOPE_BY_OFFER: dict[str, dict] = {}


def save(path: pathlib.Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def append_journal(row: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()


def list_certificates(client: Client) -> list[dict]:
    all_rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        rows = result.get("certificates")
        if not isinstance(rows, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        all_rows.extend(rows)
        if page >= int(result.get("page_count") or 0):
            return all_rows
    raise RuntimeError("ozon_certificate_list_page_limit")


def fetch_products(client: Client, targets: list[dict]) -> list[dict]:
    offers = [str(row["offer_id"]) for row in targets]
    products, attrs = [], []
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        products.extend(client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or [])
        attrs.extend(client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)
        }).get("result") or [])
    pmap: dict[str, list[dict]] = collections.defaultdict(list)
    amap: dict[str, list[dict]] = collections.defaultdict(list)
    for row in products:
        pmap[str(row.get("offer_id"))].append(row)
    for row in attrs:
        amap[str(row.get("offer_id"))].append(row)
    fresh = []
    for target in targets:
        offer = str(target["offer_id"])
        if len(pmap[offer]) != 1 or len(amap[offer]) != 1:
            raise RuntimeError("fresh_ozon_product_or_attributes_missing:" + offer)
        p, attr = pmap[offer][0], amap[offer][0]
        if (str(p.get("product_id") or p.get("id")) != str(target["product_id"])
                or str(p.get("sku")) != str(target["sku"])
                or p.get("is_archived") is not False):
            raise RuntimeError("fresh_ozon_product_identity_conflict:" + offer)
        values = {str(item.get("id")): [str(v.get("value") or "").strip()
                   for v in item.get("values") or [] if str(v.get("value") or "").strip()]
                  for item in attr.get("attributes") or []}
        brands = values.get("85", [])
        tnved = sorted({x.split(" - ", 1)[0].strip() for x in values.get("22232", [])})
        scope = SCOPE_BY_OFFER.get(offer)
        if ("gauss" not in str(p.get("name") or "").casefold()
                or (brands and any("gauss" not in x.casefold() for x in brands))):
            raise RuntimeError("fresh_ozon_brand_conflict:" + offer)
        if not scope or scope.get("declared_article_found_in_source") is not True:
            raise RuntimeError("fresh_ozon_model_scope_not_proven:" + offer)
        if not tnved or tnved != sorted(target.get("ozon_tnved") or []):
            raise RuntimeError("fresh_ozon_tnved_missing_or_changed_since_preflight:" + offer)
        fresh.append({"offer_id": offer, "product_id": str(target["product_id"]),
                      "sku": str(target["sku"]), "name": p.get("name"),
                      "brand_values": brands, "tnved": tnved,
                      "declaration_model": scope.get("declaration_model") or scope["article_code"],
                      "tnved_differs_from_declaration": set(tnved) != ALLOWED_TNVED})
    return fresh


def ensure_ozon_record(client: Client, doc: dict, seed_sku: str) -> tuple[dict | None, dict]:
    """Create once if absent, then reconcile with live list; never retry a write."""
    before = [x for x in list_certificates(client)
              if norm_number(x.get("certificate_number")) == norm_number(doc["number"])]
    if len(before) > 1:
        raise RuntimeError("ozon_duplicate_document_records:" + doc["number"])
    if before:
        record = before[0]
        if (record.get("type_code") != doc["type_code"]
                or str(record.get("issue_date", ""))[:10] != doc["issue_date"]
                or str(record.get("expire_date", ""))[:10] != doc["expire_date"]):
            raise RuntimeError("ozon_existing_document_metadata_conflict:" + doc["number"])
        return record, {"created": False, "already_present": True}

    # Avoid locale-dependent date serialization; expiry is encoded as day/month/year.
    y, m, d = map(int, doc["expire_date"].split("-"))
    source = doc["file"]
    params = {
        "name": "Документ " + doc["number"],
        "certificate_type": doc["type_code"].upper(),
        "certificate_country": "RU",
        "accordance_type": "EAEU",
        "number": doc["number"],
        "issue_date": wb_datetime(doc["issue_date"]),
        "expired_date": {"date": {"day": d, "month": m, "year": y}},
        "skus": [str(seed_sku)],
        "product_type": "UNKNOWN",
        "link_to_registry": doc["registry_url"],
        "files": [{"file_content": base64.b64encode(source.read_bytes()).decode("ascii"),
                   "name": source.name}],
    }
    encoded = json.dumps({"params": params}, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) >= 15_000_000:
        raise RuntimeError("ozon_create_request_too_large")
    entry = {"at": now(), "platform": "ozon", "endpoint": "/v2/product/certificate/create",
             "document_number": doc["number"], "phase": "prepared",
             "payload_sha256": hashlib.sha256(encoded).hexdigest(), "payload_bytes": len(encoded),
             "seed_sku": str(seed_sku)}
    append_journal(entry)
    save(STATE, {"updated_at_utc": now(), "phase": "ozon_create_started",
                 "documents": STATE_DATA["documents"], "local_source_files_deleted": False})
    response = None
    err = None
    try:
        response = client.call("ozon", "/v2/product/certificate/create", {"params": params}, mutation=True)
    except Exception as exc:
        err = type(exc).__name__
    entry.update({"at": now(), "phase": "response" if response is not None else "uncertain",
                  "response": response, "error_type": err})
    append_journal(entry)

    found = []
    for attempt in range(6):
        found = [x for x in list_certificates(client)
                 if norm_number(x.get("certificate_number")) == norm_number(doc["number"])]
        if found:
            break
        if attempt < 5:
            time.sleep(2)
    if len(found) != 1:
        return None, {"created": response is not None and bool(response.get("certificate_id")),
                      "outcome": "uncertain_no_record_visible_no_retry", "error_type": err,
                      "create_response": response}
    record = found[0]
    if (record.get("type_code") != doc["type_code"]
            or str(record.get("issue_date", ""))[:10] != doc["issue_date"]
            or str(record.get("expire_date", ""))[:10] != doc["expire_date"]):
        raise RuntimeError("ozon_created_record_metadata_conflict:" + doc["number"])
    states = [x.get("state") for x in (response or {}).get("params", []) if isinstance(x, dict)]
    if response is not None and (response.get("status") != "COMPLETED" or not states or set(states) != {"VALID"}):
        return record, {"created": True, "outcome": "record_visible_but_create_response_not_fully_validated",
                        "create_response": response}
    return record, {"created": True, "outcome": "record_visible", "create_response": response}


def bind_ozon_document(client: Client, doc: dict, record: dict, targets: list[dict]) -> dict:
    cid = int(record["certificate_id"])
    existing = client.ozon_bindings(cid)
    expected = {(str(x["product_id"]), str(x["sku"])) for x in targets}
    by_product = {}
    for row in existing:
        pid = str(row.get("product_id") or "")
        if not pid or pid in by_product:
            raise RuntimeError("ozon_binding_duplicate_or_missing_product_id:" + doc["number"])
        by_product[pid] = row
    outside = [x for x in existing if (str(x.get("product_id")), str(x.get("sku"))) not in expected]
    if outside:
        raise RuntimeError("ozon_record_has_outside_bindings:" + doc["number"])
    missing = []
    for target in targets:
        prior = by_product.get(str(target["product_id"]))
        if prior and str(prior.get("sku")) != str(target["sku"]):
            raise RuntimeError("ozon_existing_binding_identity_conflict:" + target["offer_id"])
        if prior and prior.get("product_status_code") == "declined":
            raise RuntimeError("ozon_existing_binding_declined:" + target["offer_id"])
        if not prior:
            missing.append(target)
    if missing:
        skus = [str(x["sku"]) for x in missing]
        request = {"certificate_id": cid, "skus": skus}
        append_journal({"at": now(), "platform": "ozon", "endpoint": "/v1/product/certificate/bind",
                        "document_number": doc["number"], "certificate_id": cid,
                        "phase": "prepared", "skus": skus,
                        "payload_sha256": hashlib.sha256(json.dumps(request, separators=(",", ":")).encode()).hexdigest()})
        try:
            response = client.call("ozon", "/v1/product/certificate/bind", request, mutation=True)
            err = None
        except Exception as exc:
            response, err = None, type(exc).__name__
        append_journal({"at": now(), "platform": "ozon", "endpoint": "/v1/product/certificate/bind",
                        "document_number": doc["number"], "certificate_id": cid,
                        "phase": "response" if response is not None else "uncertain",
                        "response": response, "error_type": err, "sku_count": len(skus)})
    live = client.ozon_bindings(cid)
    live_by_pair = {(str(x.get("product_id")), str(x.get("sku"))): x for x in live}
    visible = [live_by_pair.get(pair) for pair in sorted(expected)]
    missing_pairs = [pair for pair, row in zip(sorted(expected), visible) if row is None]
    statuses = collections.Counter(str(row.get("product_status_code") or "unknown")
                                   for row in visible if row is not None)
    record_info = client.call("ozon", "/v1/product/certificate/info",
                              {"certificate_number": doc["number"]}).get("result") or {}
    return {"certificate_id": cid, "record_status": record_info.get("status_code"),
            "record_visible": True, "expected_bindings": len(expected),
            "visible_bindings": len(visible) - len(missing_pairs), "missing_pairs": missing_pairs,
            "outside_binding_count": len([x for x in live if (str(x.get("product_id")), str(x.get("sku"))) not in expected]),
            "binding_status_counts": dict(statuses), "all_expected_pairs_visible": not missing_pairs,
            "local_source_file_deleted": False}


def card_tnved(card: dict) -> list[str]:
    values = []
    for item in card.get("characteristics") or []:
        label = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in label and "тнвед" not in label:
            continue
        raw = item.get("value")
        values.extend(raw if isinstance(raw, list) else [raw])
    return sorted({str(x).split(" - ", 1)[0].strip() for x in values if str(x).strip()})


def doc_signature(item: dict) -> tuple:
    return (doc_key(item), str(item.get("startDate", ""))[:10],
            str(item.get("endDate", ""))[:10], bool(item.get("isEndless")))


def apply_wb(client: Client, targets: list[dict]) -> dict:
    wanted_docs = [{"type": row["wb_type"], "number": row["number"],
                    "startDate": wb_datetime(row["issue_date"]),
                    "endDate": wb_datetime(row["expire_date"]), "isEndless": False}
                   for row in DOCS.values()]
    prepared = []
    before_rows = []
    for i, target in enumerate(targets, start=1):
        offer = str(target["offer_id"])
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            raise RuntimeError("wb_fresh_card_count_conflict:" + offer + ":" + str(len(cards)))
        card = cards[0]
        if (str(card.get("vendorCode")) != offer
                or str(card.get("nmID")) != str(target["wb_nmID"])
                or str(card.get("brand") or "").strip().casefold() != "gauss"):
            raise RuntimeError("wb_fresh_identity_conflict:" + offer)
        tnved = card_tnved(card)
        scope = SCOPE_BY_OFFER.get(offer)
        if not scope or scope.get("declared_article_found_in_source") is not True:
            raise RuntimeError("wb_model_scope_not_proven:" + offer)
        if not tnved or tnved != sorted(target.get("wb_tnved") or []):
            raise RuntimeError("wb_fresh_tnved_missing_or_changed_since_preflight:" + offer)
        docs = copy_documents(card)
        for wanted in wanted_docs:
            same = [x for x in docs if norm_number(x.get("number")) == norm_number(wanted["number"])]
            exact = [x for x in same if doc_key(x) == doc_key(wanted)
                     and str(x.get("startDate", ""))[:10] == wanted["startDate"][:10]
                     and str(x.get("endDate", ""))[:10] == wanted["endDate"][:10]
                     and x.get("isEndless") is False]
            if same and (len(same) != 1 or len(exact) != 1):
                raise RuntimeError("wb_same_number_metadata_conflict:" + offer + ":" + wanted["number"])
        payload = runner.merge_wb(card, wanted_docs)
        before_rows.append({"offer_id": offer, "nmID": str(card["nmID"]),
                            "card": card, "prior_doc_signatures": [doc_signature(x) for x in docs],
                            "already_exact": payload is None})
        if payload is not None:
            prepared.append({"offer_id": offer, "nmID": str(card["nmID"]),
                             "payload": payload, "before": card,
                             "prior_doc_signatures": [doc_signature(x) for x in docs]})
        if i % 20 == 0 or i == len(targets):
            print(json.dumps({"live_wb_cards_prepared": i, "total": len(targets)}, ensure_ascii=False), flush=True)

    save(BEFORE, {"checked_at_utc": now(), "complete": True, "target_count": len(targets),
                  "update_count": len(prepared), "already_exact_count": len(targets) - len(prepared),
                  "cards": before_rows})
    STATE_DATA["phase"] = "wb_fresh_prewrite_complete"
    STATE_DATA["wb_update_count"] = len(prepared)
    STATE_DATA["wb_already_exact_count"] = len(targets) - len(prepared)
    save(STATE, STATE_DATA)

    for start in range(0, len(prepared), 100):
        batch = prepared[start:start + 100]
        payloads = [x["payload"] for x in batch]
        marker = hashlib.sha256(json.dumps(payloads, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        append_journal({"at": now(), "platform": "wb", "endpoint": "/content/v2/cards/update",
                        "phase": "prepared", "batch": start // 100 + 1,
                        "offers": [x["offer_id"] for x in batch], "payload_sha256": marker})
        STATE_DATA.update({"phase": "wb_update_started", "wb_batches_sent": start // 100 + 1,
                           "wb_last_batch_offers": [x["offer_id"] for x in batch]})
        save(STATE, STATE_DATA)
        try:
            response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
            err = None
        except Exception as exc:
            response, err = None, type(exc).__name__
        append_journal({"at": now(), "platform": "wb", "endpoint": "/content/v2/cards/update",
                        "phase": "response" if response is not None else "uncertain",
                        "batch": start // 100 + 1, "response": response, "error_type": err})
        STATE_DATA.setdefault("wb_batch_results", []).append({"batch": start // 100 + 1,
            "count": len(batch), "response": response, "error_type": err})
        save(STATE, STATE_DATA)

    before_by_offer = {x["offer_id"]: x for x in before_rows}
    readback_rows = []
    status_counts = collections.Counter()
    failures = []
    for i, target in enumerate(targets, start=1):
        offer = str(target["offer_id"])
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            failures.append({"offer_id": offer, "problem": "readback_card_count", "count": len(cards)})
            continue
        card = cards[0]
        docs = ((card.get("documents") or {}).get("items") or [])
        exact_docs = []
        for wanted in wanted_docs:
            found = [x for x in docs if norm_number(x.get("number")) == norm_number(wanted["number"])
                     and doc_key(x) == doc_key(wanted)
                     and str(x.get("startDate", ""))[:10] == wanted["startDate"][:10]
                     and str(x.get("endDate", ""))[:10] == wanted["endDate"][:10]
                     and x.get("isEndless") is False]
            if len(found) != 1:
                failures.append({"offer_id": offer, "problem": "readback_document_missing_or_duplicate",
                                 "number": wanted["number"], "exact_count": len(found)})
            else:
                exact_docs.extend(found)
                verdict = found[0].get("verdict")
                status = "valid" if isinstance(verdict, dict) and verdict.get("verified") is True and verdict.get("status") == 1 and verdict.get("reason") == "valid" else "pending_review_or_unverified"
                status_counts[status] += 1
        prior_sigs = before_by_offer[offer]["prior_doc_signatures"]
        after_sigs = [doc_signature(x) for x in docs]
        prior_preserved = all(sig in after_sigs for sig in prior_sigs)
        other_preserved = comparable_card(card) == comparable_card(before_by_offer[offer]["card"])
        row = {"offer_id": offer, "nmID": str(card.get("nmID") or ""),
               "exact_metadata_count": len(exact_docs), "target_documents_expected": len(wanted_docs),
               "prior_documents_preserved": prior_preserved,
               "unrelated_card_fields_preserved": other_preserved,
               "document_verdicts": [x.get("verdict") for x in exact_docs]}
        readback_rows.append(row)
        if not prior_preserved or not other_preserved:
            failures.append({"offer_id": offer, "problem": "preservation_check_failed"})
        if i % 20 == 0 or i == len(targets):
            print(json.dumps({"live_wb_card_readbacks": i, "total": len(targets)}, ensure_ascii=False), flush=True)

    result = {"checked_at_utc": now(), "complete": len(readback_rows) == len(targets),
              "target_cards": len(targets), "updated_cards": len(prepared),
              "cards_with_all_exact_documents": sum(x["exact_metadata_count"] == len(wanted_docs) for x in readback_rows),
              "document_verdict_counts": dict(status_counts), "failures": failures,
              "cards": readback_rows, "wb_left_for_marketplace_review": True}
    save(READBACK, result)
    return result


def main() -> None:
    for path in (STATE, BEFORE, READBACK, JOURNAL):
        if path.exists():
            raise RuntimeError("execution_artifact_exists_reconcile_first:" + path.name)
    pre = json.loads(PREFLIGHT.read_text())
    scope_proof = json.loads(SCOPE_PROOF.read_text())
    if (pre.get("read_only") is not True or pre.get("target_count") != 90
            or pre.get("declaration_pdf_sha256") != DOCS["declaration"]["sha256"]
            or scope_proof.get("read_only") is not True
            or scope_proof.get("all_90_article_codes_present_in_declaration") is not True
            or scope_proof.get("declaration_pdf_sha256") != DOCS["declaration"]["sha256"]
            or scope_proof.get("declaration_tnved") != "8539519009"
            or pre.get("wb_eligible_targets") != 90
            or pre.get("wb_declaration_valid") != 0 or pre.get("wb_certificate_valid", 0) != 0
            or pre.get("declaration_only_source_offers") or pre.get("certificate_only_source_offers")):
        raise RuntimeError("fresh_preflight_incomplete_or_conflicting")
    for info in DOCS.values():
        if (not info["file"].is_file()
                or hashlib.sha256(info["file"].read_bytes()).hexdigest() != info["sha256"]):
            raise RuntimeError("source_pdf_missing_or_hash_mismatch:" + info["number"])
    ozon_targets = [x for x in pre["targets"] if x.get("ozon_eligible") is True]
    wb_targets = [x for x in pre["targets"] if x.get("wb_eligible") is True]
    if len(ozon_targets) != int(pre.get("ozon_eligible_targets") or 0) or len(wb_targets) != 90:
        raise RuntimeError("unexpected_target_counts")

    global STATE_DATA, SCOPE_BY_OFFER
    SCOPE_BY_OFFER = {str(x["offer_id"]): x for x in scope_proof["targets"]}
    if set(SCOPE_BY_OFFER) != {str(x["offer_id"]) for x in pre["targets"]}:
        raise RuntimeError("scope_proof_offer_set_differs_from_live_preflight")
    STATE_DATA = {"started_at_utc": now(), "phase": "initializing",
                  "target_count": len(pre["targets"]), "ozon_eligible_count": len(ozon_targets),
                  "wb_eligible_count": len(wb_targets), "documents": {},
                  "wb_left_for_marketplace_review": True, "local_source_files_deleted": False,
                  "scope_proof": str(SCOPE_PROOF),
                  "scope_proof_sha256": hashlib.sha256(SCOPE_PROOF.read_bytes()).hexdigest(),
                  "marketplace_tnved_discrepancy_preserved": False}
    save(STATE, STATE_DATA)
    client = Client()

    fresh = fetch_products(client, ozon_targets)
    if len(fresh) != len(ozon_targets):
        raise RuntimeError("fresh_ozon_target_count_mismatch")
    STATE_DATA["phase"] = "ozon_fresh_targets_verified"
    save(STATE, STATE_DATA)

    for key, doc in DOCS.items():
        if not fresh:
            STATE_DATA["documents"][key] = {"phase": "no_ozon_targets_in_fresh_preflight_no_upload"}
            save(STATE, STATE_DATA)
            continue
        try:
            cert_matches = [x for x in list_certificates(client)
                            if norm_number(x.get("certificate_number")) == norm_number(doc["number"])]
            if len(cert_matches) > 1:
                STATE_DATA["documents"][key] = {"phase": "duplicate_records_found_no_write", "matches": cert_matches}
                save(STATE, STATE_DATA)
                continue
            record, create_result = ensure_ozon_record(client, doc, fresh[0]["sku"])
            if record is None:
                STATE_DATA["documents"][key] = {"phase": "create_uncertain_no_record_visible_no_retry", **create_result}
                save(STATE, STATE_DATA)
                continue
            status = str(record.get("status_code") or "")
            if status in {"declined", "rejected", "cancelled", "invalid"}:
                STATE_DATA["documents"][key] = {"phase": "ozon_record_declined_no_binding", "record": record, **create_result}
                save(STATE, STATE_DATA)
                continue
            if create_result.get("outcome") == "record_visible_but_create_response_not_fully_validated":
                STATE_DATA["documents"][key] = {"phase": "create_visible_but_unvalidated_no_binding", "record": record, **create_result}
                save(STATE, STATE_DATA)
                continue
            binding = bind_ozon_document(client, doc, record, fresh)
            STATE_DATA["documents"][key] = {"phase": "ozon_bindings_read_back", "record": record,
                                            "create": create_result, "binding": binding,
                                            "source_pdf_sha256": doc["sha256"]}
            save(STATE, STATE_DATA)
            print(json.dumps({"ozon_document": doc["number"], **binding}, ensure_ascii=False), flush=True)
        except Exception as exc:
            STATE_DATA["documents"][key] = {"phase": "document_processing_error",
                                            "error_type": type(exc).__name__, "detail": str(exc)[:500]}
            save(STATE, STATE_DATA)

    STATE_DATA["phase"] = "ozon_documents_processed_starting_wb"
    save(STATE, STATE_DATA)
    wb_result = apply_wb(client, wb_targets)
    STATE_DATA["wb_readback"] = {k: v for k, v in wb_result.items() if k != "cards"}
    STATE_DATA["phase"] = "finished_readback_complete" if wb_result.get("complete") and not wb_result.get("failures") else "finished_with_readback_problems"
    STATE_DATA["finished_at_utc"] = now()
    save(STATE, STATE_DATA)
    print(json.dumps({"execution": str(STATE), "readback": str(READBACK),
                      "phase": STATE_DATA["phase"], "ozon_documents": STATE_DATA["documents"],
                      "wb": STATE_DATA["wb_readback"], "local_source_files_deleted": False},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
