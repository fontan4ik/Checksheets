from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import pathlib
import sys
import time
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261014"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402

NUMBER = "ЕАЭС N RU Д-HK.РА03.В.65365/24"
TYPE = "declaration"
ISSUE = "2024-04-16"
EXPIRY = "2029-04-15"
ALLOWED_TNVED = {"9405110033"}
FSA_ID = "18827994"
SOURCE = ROOT / "output_to_user/certificates/group_2/JAZZWAY/documents/svetilniki-ppl-psp-pled-vstraivaemye-ds-tr-ts-037-15.04.2029_6a2674d63d15.pdf"
SOURCE_SHA256 = "6a2674d63d159f0d6230f48ff468f84cd2dcce4dc8cd028e4436f8e05fba6597"
PREFLIGHT = HERE / "jazzway_65365_crossplatform_preflight_20261024.json"
STATE = HERE / "jazzway_65365_execution_20261024.json"
JOURNAL = HERE / "jazzway_65365_mutation_journal_20261024.jsonl"
WB_BEFORE = HERE / "jazzway_65365_wb_before_20261024.json"
READBACK = HERE / "jazzway_65365_final_crossplatform_readback_20261024.json"


def save(path: pathlib.Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def log(entry: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at_utc": now(), **entry}, ensure_ascii=False) + "\n")
        f.flush()


def attr_values(row: dict, attr_id: str) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    vals = (attrs.get(attr_id) or {}).get("values") or []
    return [str(x.get("value") or "").strip() for x in vals if str(x.get("value") or "").strip()]


def tnved_values(values: list[str]) -> list[str]:
    return sorted({str(x).split(" - ", 1)[0].strip() for x in values if str(x).strip()})


def wb_tnved(card: dict) -> list[str]:
    vals = []
    for row in card.get("characteristics") or []:
        name = "".join(str(row.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        value = row.get("value")
        vals.extend(value if isinstance(value, list) else [value])
    return tnved_values([str(x) for x in vals if x])


def list_certificates(client: Client) -> list[dict]:
    out = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        rows = result.get("certificates")
        if not isinstance(rows, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        out.extend(rows)
        if not rows or page >= int(result.get("page_count") or 0):
            return out
    raise RuntimeError("ozon_certificate_list_page_limit")


def exact_records(client: Client) -> list[dict]:
    key = norm_number(NUMBER)
    return [x for x in list_certificates(client) if norm_number(x.get("certificate_number")) == key]


def fresh_ozon(client: Client, offers: list[str]) -> tuple[dict[str, dict], dict[str, dict]]:
    products, attrs = {}, {}
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        p = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items")
        a = client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": batch}, "limit": len(batch)}).get("result")
        if not isinstance(p, list) or not isinstance(a, list):
            raise RuntimeError("fresh_ozon_read_incomplete")
        products.update({str(x.get("offer_id") or ""): x for x in p})
        attrs.update({str(x.get("offer_id") or ""): x for x in a})
    if set(products) != set(offers) or set(attrs) != set(offers):
        raise RuntimeError("fresh_ozon_offer_set_changed")
    return products, attrs


def prepare_targets(client: Client, pre: dict) -> tuple[list[dict], list[dict]]:
    offers = sorted(x["offer_id"] for x in pre["ozon_targets"])
    products, attrs = fresh_ozon(client, offers)
    expected = {x["offer_id"]: x for x in pre["ozon_targets"]}
    ozon_targets = []
    wb_updates = []
    wb_before = []
    for offer in offers:
        p, a = products[offer], attrs[offer]
        identity = {"offer_id": offer,
                    "product_id": str(p.get("product_id") or p.get("id") or ""),
                    "sku": str(p.get("sku") or ""), "brand": attr_values(a, "85"),
                    "tnved": tnved_values(attr_values(a, "22232")),
                    "is_archived": p.get("is_archived"), "name": p.get("name")}
        prior = expected[offer]
        if (identity["product_id"] != prior["product_id"] or identity["sku"] != prior["sku"]
                or identity["is_archived"] is not False or identity["brand"] != ["Jazzway"]
                or identity["tnved"] != ["9405110033"]):
            raise RuntimeError("fresh_ozon_identity_or_scope_changed:" + offer)
        ozon_targets.append(identity)

        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            raise RuntimeError(f"fresh_wb_card_count_changed:{offer}:{len(cards)}")
        card = cards[0]
        expected_wb = next((x for x in pre["wb_targets"] if x["offer_id"] == offer), None)
        if (not expected_wb or str(card.get("nmID") or "") != str(expected_wb.get("nmID") or "")
                or str(card.get("brand") or "").casefold() not in {"jazzway", "jazz way"}
                or wb_tnved(card) != ["9405110033"]):
            raise RuntimeError("fresh_wb_identity_or_scope_changed:" + offer)
        existing = [x for x in ((card.get("documents") or {}).get("items") or [])
                    if norm_number(x.get("number")) == norm_number(NUMBER)]
        if existing:
            raise RuntimeError("wb_same_number_appeared_after_preflight_reconcile:" + offer)
        wb_before.append({"offer_id": offer, "nmID": str(card.get("nmID")), "card": card})
        desired = {"type": 2, "number": NUMBER, "startDate": ISSUE + "T00:00:00Z",
                   "endDate": EXPIRY + "T00:00:00Z", "isEndless": False}
        payload = merge_wb(card, [desired])
        if payload is None:
            raise RuntimeError("wb_payload_unexpected_noop:" + offer)
        wb_updates.append({"offer_id": offer, "nmID": str(card.get("nmID")),
                           "before": card, "payload": payload})
    if len(ozon_targets) != 50 or len(wb_updates) != 50:
        raise RuntimeError("fresh_targets_not_complete")
    return ozon_targets, wb_updates


def main() -> None:
    if any(p.exists() for p in (STATE, JOURNAL, WB_BEFORE, READBACK)):
        raise RuntimeError("execution_artifact_exists_reconcile_before_retry")
    if not SOURCE.is_file() or hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("source_pdf_missing_or_hash_mismatch")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if (pre.get("read_only") is not True or pre.get("document", {}).get("number") != NUMBER
            or pre.get("document", {}).get("fsa_record_id") != FSA_ID
            or pre.get("document", {}).get("fsa_status") != "Действует"
            or pre.get("document", {}).get("issue_date") != ISSUE
            or pre.get("document", {}).get("expire_date") != EXPIRY
            or pre.get("document", {}).get("source_sha256") != SOURCE_SHA256
            or pre.get("assignment_count") != 50 or pre.get("ozon_safe_count") != 50
            or pre.get("wb_safe_count") != 50 or pre.get("ozon_already_bound_count") != 0
            or pre.get("wb_already_exact_count") != 0 or pre.get("ozon_exact_records") != []):
        raise RuntimeError("preflight_not_clean_50_exact_target_batch")
    if dt.date.today() > dt.date.fromisoformat(EXPIRY):
        raise RuntimeError("source_document_expired")
    client = Client()
    if exact_records(client):
        raise RuntimeError("exact_ozon_record_appeared_after_preflight_reconcile")
    ozon_targets, wb_updates = prepare_targets(client, pre)
    save(WB_BEFORE, {"checked_at_utc": now(), "read_only": True,
                     "cards": [{"offer_id": x["offer_id"], "nmID": x["nmID"], "card": x["before"]}
                               for x in wb_updates]})
    skus = sorted({x["sku"] for x in ozon_targets})
    payload = {"params": {"name": "Декларация о соответствии № " + NUMBER,
                "certificate_type": "DECLARATION", "certificate_country": "RU",
                "accordance_type": "EAEU", "number": NUMBER,
                "issue_date": ISSUE + "T00:00:00Z",
                "expired_date": {"date": {"day": 15, "month": 4, "year": 2029}},
                "skus": skus, "product_type": "UNKNOWN",
                "files": [{"file_content": base64.b64encode(SOURCE.read_bytes()).decode("ascii"),
                           "name": SOURCE.name}],
                "link_to_registry": f"https://pub.fsa.gov.ru/rds/declaration/view/{FSA_ID}/common"}}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > 15_000_000:
        raise RuntimeError("ozon_create_payload_too_large")
    wb_payloads = [x["payload"] for x in wb_updates]
    wb_encoded = json.dumps(wb_payloads, ensure_ascii=False, separators=(",", ":")).encode()
    if len(wb_encoded) > 9_500_000:
        raise RuntimeError("wb_update_payload_too_large")

    state = {"started_at_utc": now(), "number": NUMBER, "type": TYPE,
             "fsa_record_id": FSA_ID, "fsa_url": f"https://pub.fsa.gov.ru/rds/declaration/view/{FSA_ID}/common",
             "issue_date": ISSUE, "expire_date": EXPIRY,
             "sample_date_condition": pre["document"]["sample_date_condition"],
             "source_file": str(SOURCE.relative_to(ROOT)), "source_sha256": SOURCE_SHA256,
             "target_count": 50, "ozon_target_count": len(ozon_targets), "wb_target_count": len(wb_updates),
             "ozon": {"state": "create_pending", "request_sha256": hashlib.sha256(encoded).hexdigest(),
                      "request_bytes": len(encoded), "expected_pairs": ozon_targets},
             "wb": {"state": "update_pending", "request_sha256": hashlib.sha256(wb_encoded).hexdigest(),
                    "request_bytes": len(wb_encoded), "expected_cards": [
                        {"offer_id": x["offer_id"], "nmID": x["nmID"]} for x in wb_updates]},
             "wb_review_left_pending": True, "local_file_deleted": False}
    save(STATE, state)

    log({"phase": "ozon_create_prepared", "request_sha256": state["ozon"]["request_sha256"],
         "request_bytes": len(encoded), "target_count": 50})
    try:
        ozon_response = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
    except Exception as exc:
        state["ozon"].update({"state": "create_outcome_uncertain_reconcile_before_retry",
                              "error_type": type(exc).__name__})
        save(STATE, state)
        log({"phase": "ozon_create_uncertain", "error_type": type(exc).__name__})
        raise
    state["ozon"].update({"state": "create_response_received", "response": ozon_response,
                          "certificate_id": str(ozon_response.get("certificate_id") or ""),
                          "create_status": ozon_response.get("status")})
    save(STATE, state)
    log({"phase": "ozon_create_response", "response": ozon_response})

    # WB card updates are independent of Ozon moderation; every card remains in WB review.
    log({"phase": "wb_update_prepared", "request_sha256": state["wb"]["request_sha256"],
         "request_bytes": len(wb_encoded), "target_count": 50})
    try:
        wb_response = client.call("wb", "/content/v2/cards/update", wb_payloads, mutation=True)
    except Exception as exc:
        state["wb"].update({"state": "update_outcome_uncertain_reconcile_before_retry",
                            "error_type": type(exc).__name__})
        save(STATE, state)
        log({"phase": "wb_update_uncertain", "error_type": type(exc).__name__})
        raise
    state["wb"].update({"state": "update_response_received", "response": wb_response,
                        "accepted": wb_response.get("error") is False})
    save(STATE, state)
    log({"phase": "wb_update_response", "response": wb_response})
    if wb_response.get("error") is not False:
        raise RuntimeError("wb_update_not_accepted_reconcile_before_retry")

    # Read the exact Ozon record and all expected target pairs back after propagation.
    records = []
    for attempt in range(6):
        records = exact_records(client)
        if records:
            break
        if attempt < 5:
            time.sleep(3)
    if len(records) != 1:
        state["ozon"].update({"state": "postwrite_exact_record_missing_or_duplicate",
                              "postwrite_record_count": len(records)})
        save(STATE, state)
        raise RuntimeError("ozon_postwrite_record_missing_or_duplicate")
    record = records[0]
    cid = int(record["certificate_id"])
    bindings = client.ozon_bindings(cid)
    expected_pairs = {(x["product_id"], x["sku"]): x["offer_id"] for x in ozon_targets}
    actual_pairs = {(str(x.get("product_id") or ""), str(x.get("sku") or "")): x for x in bindings}
    missing_pairs = [v for k, v in expected_pairs.items() if k not in actual_pairs]
    if record.get("status_code") == "approved" and missing_pairs:
        # The record creation request already included every target SKU. Bind only after approval,
        # and only after a complete live identity readback.
        bind_skus = sorted({next(x["sku"] for x in ozon_targets if x["offer_id"] == offer) for offer in missing_pairs})
        bind_payload = {"certificate_id": cid, "skus": bind_skus}
        log({"phase": "ozon_bind_prepared", "certificate_id": cid, "skus": bind_skus})
        try:
            response = client.call("ozon", "/v1/product/certificate/bind", bind_payload, mutation=True)
        except Exception as exc:
            state["ozon"].update({"state": "bind_outcome_uncertain_reconcile_before_retry",
                                  "bind_error_type": type(exc).__name__})
            save(STATE, state)
            raise
        state["ozon"]["bind_response"] = response
        bindings = client.ozon_bindings(cid)
        actual_pairs = {(str(x.get("product_id") or ""), str(x.get("sku") or "")): x for x in bindings}
    ozon_readback = [{"offer_id": x["offer_id"], "product_id": x["product_id"], "sku": x["sku"],
                      "visible": (x["product_id"], x["sku"]) in actual_pairs,
                      "binding_status": actual_pairs.get((x["product_id"], x["sku"]), {}).get("product_status_code")}
                     for x in ozon_targets]
    state["ozon"].update({"certificate_id": str(cid), "record_status": record.get("status_code"),
                          "readback_count": sum(x["visible"] for x in ozon_readback),
                          "binding_status_counts": dict(Counter(x["binding_status"] or "missing" for x in ozon_readback)),
                          "readback": ozon_readback})
    state["ozon"]["state"] = "all_50_pairs_visible" if all(x["visible"] for x in ozon_readback) else "readback_incomplete"
    save(STATE, state)

    # WB exact cards: read back the exact document metadata and current verdict per target.
    wb_readback = []
    for index, expected in enumerate(wb_updates, 1):
        cards = [x for x in client.wb_cards(expected["offer_id"])
                 if str(x.get("vendorCode") or "") == expected["offer_id"]]
        if len(cards) != 1 or str(cards[0].get("nmID") or "") != expected["nmID"]:
            wb_readback.append({"offer_id": expected["offer_id"], "nmID": expected["nmID"],
                                "exact_card": False, "state": "card_missing_or_changed"})
            continue
        docs = [x for x in ((cards[0].get("documents") or {}).get("items") or [])
                if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in docs if str(x.get("type")) == "2"
                 and str(x.get("startDate") or "")[:10] == ISSUE
                 and str(x.get("endDate") or "")[:10] == EXPIRY
                 and x.get("isEndless") is False]
        verdicts = [x.get("verdict") or {} for x in exact]
        valid = any(v.get("verified") is True and v.get("status") == 1 and v.get("reason") == "valid" for v in verdicts)
        pending = bool(exact) and not valid and all(v.get("status") in (None, 1) and v.get("reason") in (None, "", "valid") for v in verdicts)
        wb_readback.append({"offer_id": expected["offer_id"], "nmID": expected["nmID"],
                            "exact_card": True, "exact_document_count": len(exact),
                            "valid": valid, "pending": pending,
                            "verdicts": verdicts})
        if index % 20 == 0:
            print(f"read_wb_back={index}/{len(wb_updates)}", flush=True)
    wb_valid = sum(x.get("valid") is True for x in wb_readback)
    wb_pending = sum(x.get("pending") is True for x in wb_readback)
    wb_metadata_exact = sum(x.get("exact_document_count") == 1 for x in wb_readback)
    state["wb"].update({"readback_count": len(wb_readback), "exact_metadata_count": wb_metadata_exact,
                        "valid_count": wb_valid, "pending_count": wb_pending,
                        "readback": wb_readback,
                        "state": "all_metadata_visible_pending_review" if wb_metadata_exact == 50 else "readback_incomplete"})
    state["finished_at_utc"] = now()
    state["wb_review_left_pending"] = True
    state["local_file_deleted"] = False
    save(STATE, state)
    save(READBACK, {"checked_at_utc": now(), "read_only": True, "number": NUMBER,
                    "ozon_record": {k: record.get(k) for k in ("certificate_id", "certificate_number", "type_code", "status_code", "issue_date", "expire_date")},
                    "ozon_pairs": ozon_readback, "wb_cards": wb_readback,
                    "ozon_visible_pairs": sum(x["visible"] for x in ozon_readback),
                    "wb_exact_metadata_cards": wb_metadata_exact,
                    "wb_valid": wb_valid, "wb_pending": wb_pending,
                    "local_file_deleted": False})
    print(json.dumps({"state_file": str(STATE), "readback_file": str(READBACK),
                      "ozon": {"certificate_id": str(cid), "record_status": record.get("status_code"),
                               "visible_pairs": sum(x["visible"] for x in ozon_readback), "targets": 50,
                               "binding_status_counts": dict(Counter(x["binding_status"] or "missing" for x in ozon_readback))},
                      "wb": {"exact_metadata": wb_metadata_exact, "valid": wb_valid, "pending": wb_pending,
                             "targets": 50}, "local_file_deleted": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
