#!/usr/bin/env python3
"""Attach the exact Navigator NLL-G-T8 certificate to current Ozon pack SKUs.

WB cards are read only here: their live TN VED differs from the certificate.
The declaration is excluded because its declared TN VED differs from current
marketplace attributes. No local source file is deleted.
"""
from __future__ import annotations

import base64
import collections
import csv
import hashlib
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number, wb_datetime  # noqa: E402

MANIFEST = ROOT / "output_to_user/certificates/group_2/NAVIGATOR/manifest.csv"
OZON_CATALOG = ROOT / "output_to_user/ozon_catalog/catalog.csv"
CERTIFICATE = {
    "number": "ЕАЭС KG417/042.RU.02.05749",
    "type_code": "certificate_of_conformity",
    "ozon_type": "CERTIFICATE_OF_CONFORMITY",
    "country": "KG",
    "accordance_type": "EAEU",
    "issue_date": "2026-04-16",
    "expire_date": "2031-04-15",
    "tnved": "8539520002",
    "file": ROOT / "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_eac_certificate_95777_a293f686e2e3.pdf",
    "sha256": "a293f686e2e37eecb34f6ef7df4fd7623ca263042273a41c2f4cc394ca442d38",
    "source_url": "https://navigator-light.ru/lamps/led/linejnyie-nll-t8/seriya-lamp-nll-g-t8-rf.html",
}
DECLARATION = {
    "number": "ЕАЭС KZ.7500533.13.12.17315",
    "tnved": "8539512012",
    "file": ROOT / "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_declaration_95777_c12820968226.pdf",
    "sha256": "c12820968226502ddd0ad24b6c7ee1652c72a61aff36e13d79b4c73504bc83ea",
}
WB_DOC = {"type": 1, "number": CERTIFICATE["number"],
          "startDate": "2026-04-16T00:00:00Z", "endDate": "2031-04-15T00:00:00Z",
          "isEndless": False}
TNVE_CODE = CERTIFICATE["tnved"]

PREFLIGHT = HERE / "navigator_95777_preflight_20261024.json"
STATE = HERE / "navigator_95777_execution_20261024.json"
JOURNAL = HERE / "navigator_95777_mutation_journal_20261024.jsonl"
READBACK = HERE / "navigator_95777_readback_20261024.json"


def save(path: pathlib.Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def journal(row: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()


def scoped_offers() -> list[dict]:
    rows = [r for r in csv.DictReader(MANIFEST.open(encoding="utf-8-sig"))
            if norm_number(r.get("document_number")) == norm_number(CERTIFICATE["number"])]
    by_offer = {}
    for row in rows:
        offer = str(row.get("ozon_article") or "")
        if offer in by_offer and by_offer[offer] != row:
            raise RuntimeError("duplicate_manifest_offer_conflict:" + offer)
        by_offer[offer] = row
    if len(by_offer) != 14:
        raise RuntimeError("unexpected_manifest_target_count:" + str(len(by_offer)))
    catalog = {}
    for row in csv.DictReader(OZON_CATALOG.open(encoding="utf-8-sig")):
        offer = str(row.get("Артикул продавца") or "")
        if offer in by_offer:
            if offer in catalog:
                raise RuntimeError("duplicate_current_catalog_offer:" + offer)
            catalog[offer] = row
    if set(catalog) != set(by_offer):
        raise RuntimeError("manifest_targets_missing_from_current_catalog")
    result = []
    for offer in sorted(by_offer):
        row = catalog[offer]
        if row.get("Бренд") != "Navigator" or "NLL-G-T8" not in str(row.get("Название товара")):
            raise RuntimeError("catalog_brand_or_model_mismatch:" + offer)
        result.append({"offer_id": offer, "catalog_product_id": str(row.get("Ozon Product ID")),
                       "catalog_sku": str(row.get("Ozon SKU")),
                       "catalog_name": row.get("Название товара"),
                       "manufacturer_exact_model": by_offer[offer].get("provider_exact_product_heading")})
    return result


def read_ozon_targets(client: Client, targets: list[dict]) -> list[dict]:
    offers = [x["offer_id"] for x in targets]
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items") or []
    attrs = client.call("ozon", "/v4/product/info/attributes",
                        {"filter": {"offer_id": offers}, "limit": len(offers)}).get("result") or []
    pmap, amap = collections.defaultdict(list), collections.defaultdict(list)
    for x in products:
        pmap[str(x.get("offer_id"))].append(x)
    for x in attrs:
        amap[str(x.get("offer_id"))].append(x)
    result = []
    for target in targets:
        offer = target["offer_id"]
        if len(pmap[offer]) != 1 or len(amap[offer]) != 1:
            raise RuntimeError("live_ozon_product_or_attributes_not_unique:" + offer)
        p, a = pmap[offer][0], amap[offer][0]
        product_id = str(p.get("product_id") or p.get("id") or "")
        sku = str(p.get("sku") or "")
        if (product_id != target["catalog_product_id"] or sku != target["catalog_sku"]
                or p.get("is_archived") is not False):
            raise RuntimeError("live_ozon_identity_conflict:" + offer)
        values = {str(i.get("id")): [str(v.get("value") or "").strip()
                   for v in i.get("values") or [] if str(v.get("value") or "").strip()]
                  for i in a.get("attributes") or []}
        brands = values.get("85", [])
        tnved = sorted({v.split(" - ", 1)[0].strip() for v in values.get("22232", [])})
        if (not brands or any(x.casefold() != "navigator" for x in brands)
                or tnved != [TNVE_CODE]):
            raise RuntimeError("live_ozon_brand_or_tnved_conflict:" + offer)
        result.append({"offer_id": offer, "product_id": product_id, "sku": sku,
                       "name": p.get("name"), "brands": brands, "tnved": tnved,
                       "manufacturer_exact_model": target["manufacturer_exact_model"]})
    return result


def card_tnved(card: dict) -> list[str]:
    out = []
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" in name or "тнвед" in name:
            raw = item.get("value")
            out.extend(raw if isinstance(raw, list) else [raw])
    return sorted({str(x).split(" - ", 1)[0].strip() for x in out if str(x).strip()})


def read_wb_scope(client: Client, targets: list[dict]) -> list[dict]:
    out = []
    for target in targets:
        cards = client.wb_cards(target["offer_id"])
        if len(cards) > 1:
            raise RuntimeError("wb_exact_card_not_unique:" + target["offer_id"])
        if not cards:
            out.append({"offer_id": target["offer_id"], "card_found": False,
                        "action": "skip_exact_wb_card_not_found"})
            continue
        card = cards[0]
        codes = card_tnved(card)
        if (str(card.get("vendorCode")) != target["offer_id"]
                or str(card.get("brand") or "").strip().casefold() != "navigator"):
            raise RuntimeError("wb_exact_card_identity_conflict:" + target["offer_id"])
        exact_scope = codes == [TNVE_CODE]
        out.append({"offer_id": target["offer_id"], "nmID": str(card.get("nmID")),
                    "title": card.get("title"), "brand": card.get("brand"), "tnved": codes,
                    "card_found": True,
                    "existing_document_numbers": [x.get("number") for x in
                        ((card.get("documents") or {}).get("items") or [])],
                    "action": "eligible_for_wb_update" if exact_scope else "skip_wb_tnved_conflict"})
    return out


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


def ozon_record_and_bindings(client: Client, targets: list[dict]) -> tuple[dict | None, list[dict]]:
    matches = [x for x in list_certificates(client)
               if norm_number(x.get("certificate_number")) == norm_number(CERTIFICATE["number"])]
    if len(matches) > 1:
        raise RuntimeError("ozon_duplicate_document_records")
    if not matches:
        return None, []
    record = matches[0]
    if (record.get("type_code") != CERTIFICATE["type_code"]
            or str(record.get("issue_date", ""))[:10] != CERTIFICATE["issue_date"]
            or str(record.get("expire_date", ""))[:10] != CERTIFICATE["expire_date"]
            or record.get("accordance_type_code") != "EAEU"):
        raise RuntimeError("ozon_existing_record_metadata_conflict")
    bindings = client.ozon_bindings(int(record["certificate_id"]))
    expected = {(x["product_id"], x["sku"]) for x in targets}
    observed = [(str(x.get("product_id") or ""), str(x.get("sku") or "")) for x in bindings]
    if any(not x[0] or not x[1] for x in observed) or len(observed) != len(set(observed)):
        raise RuntimeError("ozon_existing_bindings_duplicate_or_missing_identity")
    if any(x not in expected for x in observed):
        raise RuntimeError("ozon_record_has_bindings_outside_exact_current_targets")
    if any(str(x.get("product_status_code") or "").casefold() in
           {"declined", "rejected", "cancelled", "invalid"} for x in bindings):
        raise RuntimeError("ozon_existing_target_binding_declined")
    return record, bindings


def create_record(client: Client, seed_sku: str) -> tuple[dict | None, dict]:
    year, month, day = map(int, CERTIFICATE["expire_date"].split("-"))
    payload = {"params": {
        "name": "Сертификат соответствия " + CERTIFICATE["number"],
        "certificate_type": CERTIFICATE["ozon_type"],
        "certificate_country": CERTIFICATE["country"],
        "accordance_type": CERTIFICATE["accordance_type"],
        "number": CERTIFICATE["number"],
        "issue_date": wb_datetime(CERTIFICATE["issue_date"]),
        "expired_date": {"date": {"day": day, "month": month, "year": year}},
        "skus": [str(seed_sku)],
        "product_type": "UNKNOWN",
        "link_to_registry": CERTIFICATE["source_url"],
        "files": [{"file_content": base64.b64encode(CERTIFICATE["file"].read_bytes()).decode("ascii"),
                   "name": CERTIFICATE["file"].name}],
    }}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) >= 15_000_000:
        raise RuntimeError("ozon_create_request_too_large")
    marker = {"at": now(), "platform": "ozon", "endpoint": "/v2/product/certificate/create",
              "document_number": CERTIFICATE["number"], "phase": "prepared",
              "payload_sha256": hashlib.sha256(encoded).hexdigest(), "payload_bytes": len(encoded),
              "seed_sku": str(seed_sku)}
    journal(marker)
    state = json.loads(STATE.read_text())
    state["phase"] = "ozon_create_started"
    save(STATE, state)
    response, err = None, None
    try:
        response = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
    except Exception as exc:
        err = type(exc).__name__
    journal({**marker, "at": now(), "phase": "response" if response is not None else "uncertain",
             "response": response, "error_type": err})
    for attempt in range(6):
        matches = [x for x in list_certificates(client)
                   if norm_number(x.get("certificate_number")) == norm_number(CERTIFICATE["number"])]
        if matches or attempt == 5:
            break
        time.sleep(2)
    if len(matches) != 1:
        return None, {"created": bool((response or {}).get("certificate_id")),
                      "outcome": "no_unique_record_visible_no_retry", "error_type": err,
                      "create_response": response}
    record = matches[0]
    if (record.get("type_code") != CERTIFICATE["type_code"]
            or str(record.get("issue_date", ""))[:10] != CERTIFICATE["issue_date"]
            or str(record.get("expire_date", ""))[:10] != CERTIFICATE["expire_date"]
            or record.get("accordance_type_code") != "EAEU"):
        raise RuntimeError("ozon_created_record_metadata_conflict")
    states = [x.get("state") for x in (response or {}).get("params", []) if isinstance(x, dict)]
    if response is None or response.get("status") != "COMPLETED" or not states or set(states) != {"VALID"}:
        return record, {"created": True, "outcome": "visible_create_response_not_fully_validated",
                        "error_type": err, "create_response": response}
    return record, {"created": True, "outcome": "visible_and_create_response_validated",
                    "create_response": response}


def bind_missing(client: Client, record: dict, targets: list[dict]) -> dict:
    cid = int(record["certificate_id"])
    current = client.ozon_bindings(cid)
    expected = {(x["product_id"], x["sku"]) for x in targets}
    by_pair = {(str(x.get("product_id")), str(x.get("sku"))): x for x in current}
    if any(pair not in expected for pair in by_pair):
        raise RuntimeError("ozon_binding_readback_has_unexpected_pair")
    if len(by_pair) != len(current):
        raise RuntimeError("ozon_binding_readback_duplicate_pair")
    missing = sorted(expected - set(by_pair))
    if missing:
        skus = [sku for _, sku in missing]
        request = {"certificate_id": cid, "skus": skus}
        marker = {"at": now(), "platform": "ozon", "endpoint": "/v1/product/certificate/bind",
                  "document_number": CERTIFICATE["number"], "certificate_id": cid,
                  "phase": "prepared", "skus": skus,
                  "payload_sha256": hashlib.sha256(json.dumps(request, separators=(",", ":")).encode()).hexdigest()}
        journal(marker)
        state = json.loads(STATE.read_text())
        state["phase"] = "ozon_bind_started"
        save(STATE, state)
        response, err = None, None
        try:
            response = client.call("ozon", "/v1/product/certificate/bind", request, mutation=True)
        except Exception as exc:
            err = type(exc).__name__
        journal({**marker, "at": now(), "phase": "response" if response is not None else "uncertain",
                 "response": response, "error_type": err})
    live = client.ozon_bindings(cid)
    pairs = [(str(x.get("product_id")), str(x.get("sku"))) for x in live]
    if len(pairs) != len(set(pairs)):
        raise RuntimeError("ozon_binding_readback_duplicate")
    statuses = collections.Counter(str(x.get("product_status_code") or "unknown") for x in live)
    info = client.call("ozon", "/v1/product/certificate/info",
                       {"certificate_number": CERTIFICATE["number"]}).get("result") or {}
    return {"certificate_id": cid, "record_status": info.get("status_code"),
            "expected_exact_bindings": len(expected),
            "visible_exact_bindings": sum(pair in expected for pair in pairs),
            "unexpected_binding_count": sum(pair not in expected for pair in pairs),
            "binding_status_counts": dict(statuses),
            "all_expected_pairs_visible": expected <= set(pairs)}


def main() -> None:
    for path in (PREFLIGHT, STATE, JOURNAL, READBACK):
        if path.exists():
            raise RuntimeError("execution_artifact_exists_reconcile_first:" + path.name)
    for info in (CERTIFICATE, DECLARATION):
        if not info["file"].is_file() or hashlib.sha256(info["file"].read_bytes()).hexdigest() != info["sha256"]:
            raise RuntimeError("source_pdf_missing_or_hash_mismatch:" + info["number"])
    targets = scoped_offers()
    client = Client()
    live = read_ozon_targets(client, targets)
    wb = read_wb_scope(client, targets)
    record, prior_bindings = ozon_record_and_bindings(client, live)
    preflight = {"checked_at_utc": now(), "read_only": True,
                 "source_pdf_sha256": CERTIFICATE["sha256"], "declaration_pdf_sha256": DECLARATION["sha256"],
                 "certificate_scope_tnved": TNVE_CODE, "declaration_scope_tnved": DECLARATION["tnved"],
                 "ozon_target_count": len(live), "ozon_targets": live,
                 "ozon_existing_record": record,
                 "ozon_existing_exact_binding_count": len(prior_bindings),
                 "wb_exact_cards": wb,
                 "wb_update_count": sum(x.get("action") == "eligible_for_wb_update" for x in wb),
                 "wb_skipped_tnved_mismatch_count": sum(x.get("action") == "skip_wb_tnved_conflict" for x in wb),
                 "wb_skipped_missing_card_count": sum(not x.get("card_found") for x in wb),
                 "declaration_excluded_reason": "document TN VED 8539512012 differs from current Ozon/WB TN VED",
                 "sample_date_condition": "certificate sample dated 2026-03; actual stock lots not independently dated",
                 "no_marketplace_writes_sent": True, "no_local_files_deleted": True}
    save(PREFLIGHT, preflight)
    state = {"started_at_utc": now(), "phase": "fresh_preflight_complete",
             "document_number": CERTIFICATE["number"], "source_sha256": CERTIFICATE["sha256"],
             "ozon_target_count": len(live), "ozon_targets": live,
             "wb_preflight": wb, "declaration_excluded_reason": preflight["declaration_excluded_reason"],
             "sample_date_condition": preflight["sample_date_condition"],
             "local_source_files_deleted": False}
    save(STATE, state)

    ozon_result = {"phase": "not_processed"}
    try:
        if record is None:
            record, create = create_record(client, live[0]["sku"])
        else:
            create = {"created": False, "already_present": True}
        if record is None:
            ozon_result = {"phase": "no_unique_record_visible_no_binding", "create": create}
        elif create.get("outcome") == "visible_create_response_not_fully_validated":
            ozon_result = {"phase": "visible_but_create_unvalidated_no_binding", "create": create}
        elif str(record.get("status_code") or "").casefold() in {"declined", "rejected", "cancelled", "invalid"}:
            ozon_result = {"phase": "record_declined_no_binding", "record_status": record.get("status_code"),
                           "create": create}
        else:
            binding = bind_missing(client, record, live)
            ozon_result = {"phase": "binding_readback_complete", "create": create, "binding": binding}
    except Exception as exc:
        ozon_result = {"phase": "processing_error", "error_type": type(exc).__name__, "detail": str(exc)[:400]}
    state = json.loads(STATE.read_text())
    state["ozon"] = ozon_result
    state["phase"] = "ozon_reconciled"
    save(STATE, state)

    report = {"checked_at_utc": now(), "preflight": preflight, "ozon": ozon_result,
              "wb_writes_sent": 0, "wb_reason": "All exact current WB cards have TN VED 8539520009, while certificate scope states 8539520002; seven other offers have no exact WB card.",
              "local_source_files_deleted": False}
    save(READBACK, report)
    state = json.loads(STATE.read_text())
    state["phase"] = "ozon_readback_complete_wb_scope_conflict" if (
        ozon_result.get("binding", {}).get("all_expected_pairs_visible") is True
        and ozon_result.get("binding", {}).get("unexpected_binding_count") == 0
    ) else "finished_with_readback_problems"
    state["finished_at_utc"] = now()
    state["wb_review_pending_or_skipped"] = True
    state["local_source_files_deleted"] = False
    save(STATE, state)
    print(json.dumps({"state": str(STATE), "preflight": str(PREFLIGHT), "readback": str(READBACK),
                      "phase": state["phase"], "ozon": ozon_result,
                      "ozon_target_count": len(live), "wb_target_counts": {
                          "exact_cards": sum(x.get("card_found") for x in wb),
                          "tnved_conflicts": preflight["wb_skipped_tnved_mismatch_count"],
                          "missing_cards": preflight["wb_skipped_missing_card_count"]},
                      "local_source_files_deleted": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
