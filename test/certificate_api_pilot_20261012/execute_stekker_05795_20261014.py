"""Upload Stekker certificate 05795/22 to Ozon and attach it to exact WB cards.

The marketplace client's logged call wrapper is intentionally bypassed so no
full card contents or authenticated headers are written to api_calls.jsonl.
Writes are single-shot; after uncertain outcomes the script reads live state
and never blindly retries a mutation.
"""
from __future__ import annotations

import base64
import collections
import datetime as dt
import hashlib
import json
import re
import sys
import time
from pathlib import Path

from api_client import BASE, ROOT, Client, digest
from preflight_stekker_05795_20261014 import (
    DOC_NUMBER, SOURCE_REL, read_offers, read_ozon_attributes,
    read_ozon_certificates, read_ozon_products, read_wb_cards,
)

NUMBER = "ЕАЭС RU С-CN.АБ53.В.05795/22"
FSA_ID = 3150023
FSA_URL = "https://pub.fsa.gov.ru/rss/certificate/view/3150023/product"
ISSUE = "2022-10-05"
EXPIRY = "2027-10-04"
TARGET_TNVED = "8536901000"
PDF = BASE / "stekker_05795_upload_files/05795_22.pdf"
PREFLIGHT = BASE / "stekker_05795_execution_preflight_20261014.json"
RUN = BASE / "stekker_05795_execution_20261014.json"
VERIFY = BASE / "stekker_05795_verification_20261014.json"
WB_CARD_FIELDS = ("nmID", "vendorCode", "brand", "title", "gtin", "description",
                  "dimensions", "characteristics", "sizes", "kizMarked")
WB_DOC_FIELDS = ("id", "type", "number", "productNumber", "tradeName", "applicant",
                 "startDate", "endDate", "isEndless")
WB_DOC_CHAR_IDS = {15001135, 15001136, 15001137, 15001138}


def save(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def number_key(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def number_digits(value: object) -> str:
    return re.sub(r"[^0-9]", "", str(value or ""))


def direct_post(client: Client, platform: str, path: str, payload: dict,
                *, mutation: bool = False) -> tuple[int, dict]:
    host, headers = (("https://api-seller.ozon.ru", client.ozon_headers)
                     if platform == "ozon" else
                     ("https://content-api.wildberries.ru", client.wb_headers))
    response = client.http.post(host + path, json=payload, headers=headers, timeout=(15, 120))
    try:
        body = response.json()
    except ValueError:
        body = {"non_json_response": True}
    if not mutation and response.status_code in (429, 500, 502, 503, 504):
        raise RuntimeError(f"Read response requires a bounded retry: {platform} {path} HTTP {response.status_code}")
    time.sleep(0.25 if platform == "ozon" else 0.45)
    return response.status_code, body


def live_number_lookup(client: Client, number: str) -> tuple[int, dict]:
    return direct_post(client, "ozon", "/v1/product/certificate/info",
                       {"certificate_number": number})


def live_ozon_bindings(client: Client, cert_id: int) -> list[dict]:
    rows = []
    expected_count = None
    last_id = 0
    seen = set()
    while True:
        status, body = direct_post(client, "ozon", "/v1/product/certificate/products/list",
                                   {"certificate_id": cert_id, "limit": 500, "last_id": last_id})
        if status != 200:
            raise RuntimeError(f"Ozon binding read failed with HTTP {status}")
        result = body.get("result") or {}
        batch, count = result.get("items"), result.get("count")
        if not isinstance(batch, list) or not isinstance(count, int):
            raise RuntimeError("Ozon binding page omitted items/count")
        if expected_count is None:
            expected_count = count
        elif count != expected_count:
            raise RuntimeError("Ozon binding count changed during pagination")
        rows.extend(batch)
        if len(rows) == expected_count:
            keys = [(str(x.get("product_id")), str(x.get("sku"))) for x in rows]
            if len(keys) != len(set(keys)):
                raise RuntimeError("Duplicate Ozon product/SKU bindings")
            return rows
        if len(rows) > expected_count or not batch:
            raise RuntimeError("Ozon binding pagination is incomplete")
        next_id = max(int(x.get("product_id") or 0) for x in batch)
        if next_id <= last_id or next_id in seen:
            raise RuntimeError("Ozon binding cursor repeated")
        seen.add(next_id)
        last_id = next_id


def live_record(client: Client, number: str, attempts: int = 1) -> dict | None:
    for attempt in range(attempts):
        status, body = live_number_lookup(client, number)
        if status == 200:
            result = body.get("result")
            if isinstance(result, dict):
                return result
            raise RuntimeError("Ozon certificate info returned no result object")
        if status == 404 and body.get("code") == 5:
            if attempt + 1 < attempts:
                time.sleep(2)
                continue
            return None
        raise RuntimeError(f"Ozon certificate lookup inconclusive (HTTP {status})")
    return None


def clean_wb_doc(item: dict) -> dict:
    return {key: item[key] for key in WB_DOC_FIELDS if key in item}


def doc_sig(item: dict) -> tuple:
    return (int(item.get("type") or 0), number_key(item.get("number")),
            str(item.get("startDate") or "")[:10],
            str(item.get("endDate") or "")[:10], bool(item.get("isEndless", False)))


def target_doc_sig() -> tuple:
    return (1, number_key(NUMBER), ISSUE, EXPIRY, False)


def canonical_unrelated(card: dict) -> dict:
    result = {key: card.get(key) for key in WB_CARD_FIELDS if key in card}
    result["characteristics"] = sorted(
        [row for row in card.get("characteristics") or []
         if int(row.get("id", -1)) not in WB_DOC_CHAR_IDS],
        key=lambda row: int(row.get("id", -1)))
    return result


def wb_snapshot(client: Client, offers: list[str]) -> dict[str, dict]:
    cards = {}
    seen_nmids = set()
    for offer in offers:
        rows = [x for x in read_wb_cards(client, offer) if x.get("vendorCode") == offer]
        if len(rows) != 1:
            raise RuntimeError(f"WB offer {offer} has {len(rows)} exact cards; expected one")
        card = rows[0]
        nmid = str(card.get("nmID") or "")
        if not nmid or nmid in seen_nmids or str(card.get("brand") or "").casefold() != "stekker":
            raise RuntimeError(f"WB card identity/brand conflict for {offer}")
        seen_nmids.add(nmid)
        docs = card.get("documents") or {}
        if docs.get("excludeDocuments") is not False:
            raise RuntimeError(f"WB documents are excluded on {offer}")
        for existing in docs.get("items") or []:
            if number_digits(existing.get("number")).endswith("0579522"):
                if doc_sig(existing) != target_doc_sig():
                    raise RuntimeError(f"Conflicting existing 05795/22 metadata on {offer}")
        cards[offer] = card
    return cards


def make_wb_payloads(cards: dict[str, dict]) -> tuple[list[dict], dict[str, dict]]:
    payloads, expected = [], {}
    desired = {"type": 1, "number": NUMBER, "startDate": ISSUE + "T00:00:00Z",
               "endDate": EXPIRY + "T00:00:00Z", "isEndless": False}
    for offer, card in cards.items():
        docs = card.get("documents") or {}
        old_items = docs.get("items") or []
        existing = [item for item in old_items if number_digits(item.get("number")).endswith("0579522")]
        if existing:
            if len(existing) != 1 or doc_sig(existing[0]) != target_doc_sig():
                raise RuntimeError(f"WB document duplicate/conflict on {offer}")
            items = [clean_wb_doc(item) for item in old_items]
            added = False
        else:
            items = [clean_wb_doc(item) for item in old_items] + [desired]
            added = True
        payload = {key: card[key] for key in WB_CARD_FIELDS if key in card}
        payload["documents"] = {"items": items, "excludeDocuments": False}
        payloads.append(payload)
        expected[offer] = {"nmID": str(card["nmID"]), "documents_before": old_items,
                           "added": added, "new_document_signature": target_doc_sig()}
    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payloads) > 100 or len(encoded) > 10_000_000:
        raise RuntimeError(f"WB payload exceeds checked limits: {len(payloads)} cards / {len(encoded)} bytes")
    return payloads, {"rows": expected, "body_bytes": len(encoded),
                      "body_sha256": hashlib.sha256(encoded).hexdigest()}


def create_and_bind_ozon(client: Client, offers: list[str], products: list[dict],
                         run: dict, source_path: Path, source_row: dict) -> dict:
    product_by_offer = {x["offer_id"]: x for x in products}
    if len(products) != len(offers) or set(product_by_offer) != set(offers):
        raise RuntimeError("Fresh Ozon product set differs from target offers")
    if any(x["archived"] is not False or not x["sku"] or x["sku"] == "0"
           or not re.search(r"\bLD\d*", x["name"], re.I) for x in products):
        raise RuntimeError("An Ozon target is archived, lacks SKU, or lacks LD series in its current title")
    if len({x["product_id"] for x in products}) != len(products) or len({x["sku"] for x in products}) != len(products):
        raise RuntimeError("Ozon product/SKU identity is not one-to-one")
    if not source_path.is_file() or digest(source_path) != source_row["SHA256"]:
        raise RuntimeError("The unchanged official source scan no longer matches the master hash")
    if not PDF.is_file():
        raise RuntimeError("The verified PDF transport copy is missing")
    pdf_sha = digest(PDF)
    audit_path = PDF.with_name("05795_22_pdf_audit.json")
    pdf_audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if pdf_audit.get("output_sha256") != pdf_sha or pdf_audit.get("page_count") != 1:
        raise RuntimeError("PDF transport copy changed after visual validation")
    records = read_ozon_certificates(client)
    matches = [x for x in records if number_digits(x.get("certificate_number")).endswith("0579522")]
    status, lookup_body = live_number_lookup(client, NUMBER)
    if matches or status != 404 or lookup_body.get("code") != 5:
        raise RuntimeError("Ozon already resolves 05795/22 or exact-number absence is inconclusive")

    seed = product_by_offer[offers[0]]
    expiry = dt.date.fromisoformat(EXPIRY)
    params = {
        "name": "Сертификат соответствия № " + NUMBER,
        "certificate_type": "CERTIFICATE_OF_CONFORMITY",
        "certificate_country": "RU", "accordance_type": "EAEU",
        "number": NUMBER, "issue_date": ISSUE + "T00:00:00Z",
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [seed["sku"]], "product_type": "UNKNOWN", "link_to_registry": FSA_URL,
        "files": [{"file_content": base64.b64encode(PDF.read_bytes()).decode("ascii"),
                   "name": PDF.name}],
    }
    request = json.dumps({"params": params}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(request) >= 15_000_000:
        raise RuntimeError("Ozon create request exceeds the verified 15 MB limit")
    entry = {"platform": "ozon", "phase": "create_prepared", "number": NUMBER,
             "fsa_record_id": FSA_ID, "fsa_registry_url": FSA_URL,
             "target_offers": len(offers), "target_skus": len(products),
             "seed_offer_id": offers[0], "seed_product_id": seed["product_id"],
             "seed_sku": seed["sku"], "source_sha256": source_row["SHA256"],
             "pdf_sha256": pdf_sha, "request_bytes": len(request),
             "request_sha256": hashlib.sha256(request).hexdigest(),
             "precreate_exact_lookup": {"http_status": status, "code": lookup_body.get("code")}}
    run["ozon"] = entry
    save(RUN, run)
    try:
        http_status, created = direct_post(client, "ozon", "/v2/product/certificate/create",
                                           {"params": params}, mutation=True)
    except Exception as exc:
        entry.update({"phase": "create_uncertain", "error_type": type(exc).__name__})
        save(RUN, run)
        created = None
        http_status = 0
    if created is not None:
        entry["create_response"] = created
        entry["create_http_status"] = http_status
        save(RUN, run)
        created_states = [x.get("state") for x in created.get("params", []) if isinstance(x, dict)]
        create_valid = (http_status == 200 and created.get("status") == "COMPLETED"
                        and bool(created_states) and set(created_states) == {"VALID"})
    else:
        create_valid = True  # outcome is reconciled by the live exact-number lookup below
    if created is None or http_status != 200 or not created.get("certificate_id"):
        entry["phase"] = "create_uncertain_reconciling"
        save(RUN, run)
        record = live_record(client, NUMBER, attempts=5)
        if not record:
            entry["phase"] = "create_not_visible_no_retry"
            save(RUN, run)
            return {"created": False, "record": None, "bindings": [], "target_map": product_by_offer}
        cert_id = int(record["certificate_id"])
    else:
        states = [x.get("state") for x in created.get("params", []) if isinstance(x, dict)]
        if created.get("status") != "COMPLETED" or not states or set(states) != {"VALID"}:
            entry["phase"] = "create_response_incomplete_reconciling"
            save(RUN, run)
        cert_id = int(created["certificate_id"])
        record = None

    for attempt in range(5):
        record = live_record(client, NUMBER, attempts=1)
        if record:
            break
        if attempt < 4:
            time.sleep(2)
    if not record:
        entry["phase"] = "created_but_not_visible_no_retry"
        save(RUN, run)
        return {"created": True, "record": None, "bindings": [], "target_map": product_by_offer}
    if str(record.get("certificate_id")) != str(cert_id):
        raise RuntimeError("Ozon certificate ID differs between create and exact-number readback")
    if (record.get("type_code") != "certificate_of_conformity"
            or str(record.get("issue_date", ""))[:10] != ISSUE
            or str(record.get("expire_date", ""))[:10] != EXPIRY):
        raise RuntimeError("Ozon certificate type or dates differ from the official record")
    if record.get("status_code") in {"declined", "rejected", "cancelled", "invalid"}:
        raise RuntimeError("Ozon rejected the certificate; no bindings sent")

    if not create_valid:
        current = live_ozon_bindings(client, cert_id)
        entry.update({"phase": "created_response_incomplete_no_bind_retry",
                      "certificate_id": cert_id, "record_status_after_create": record.get("status_code"),
                      "bindings_visible_after_create": len(current)})
        save(RUN, run)
        target_pairs = {(p["product_id"], p["sku"]) for p in products}
        return {"created": True, "record": record, "bindings": current,
                "target_map": product_by_offer, "target_pairs": target_pairs}

    before = live_ozon_bindings(client, cert_id)
    by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for item in before:
        by_sku[str(item.get("sku") or "")].append(item)
    target_by_sku = {product["sku"]: product["product_id"] for product in products}
    if len(target_by_sku) != len(products):
        raise RuntimeError("Ozon target SKU map is ambiguous")
    outside = sorted(set(by_sku) - set(target_by_sku))
    duplicates = sorted(sku for sku, values in by_sku.items() if len(values) != 1)
    identity_mismatches = [sku for sku, values in by_sku.items() if sku in target_by_sku
                           and {str(x.get("product_id")) for x in values} != {target_by_sku[sku]}]
    if outside or duplicates or identity_mismatches:
        raise RuntimeError("Ozon initial bindings contain outside SKU, duplicate, or product mismatch")
    missing = sorted(set(target_by_sku) - set(by_sku))
    entry.update({"phase": "binding_missing_skus", "certificate_id": cert_id,
                  "record_status_before_bind": record.get("status_code"),
                  "initial_binding_count": len(before), "missing_skus_before_bind": len(missing)})
    save(RUN, run)
    if missing:
        try:
            status, response = direct_post(client, "ozon", "/v1/product/certificate/bind",
                                           {"certificate_id": cert_id, "skus": missing}, mutation=True)
        except Exception as exc:
            entry.update({"phase": "bind_uncertain_reconciling", "bind_error_type": type(exc).__name__})
            save(RUN, run)
            status, response = 0, {}
        entry["bind_http_status"] = status
        entry["bind_response"] = response
        save(RUN, run)
        if status != 200 or response.get("result") is not True:
            entry["phase"] = "bind_response_inconclusive_reconcile_only"
            save(RUN, run)
    after = live_ozon_bindings(client, cert_id)
    final_record = live_record(client, NUMBER, attempts=3) or record
    by_pair = {(str(x.get("product_id")), str(x.get("sku"))): x for x in after}
    target_pairs = {(p["product_id"], p["sku"]) for p in products}
    exact = {pair: by_pair[pair] for pair in target_pairs if pair in by_pair}
    extra = [x for x in after if (str(x.get("product_id")), str(x.get("sku"))) not in target_pairs]
    if len(after) != len(by_pair):
        raise RuntimeError("Ozon returned duplicate product/SKU pairs after binding")
    entry.update({"phase": "bound_readback_complete", "record_status_after_bind": final_record.get("status_code"),
                  "all_target_pairs_visible": len(exact) == len(target_pairs),
                  "target_pairs_visible": len(exact), "target_pairs_expected": len(target_pairs),
                  "outside_bindings": len(extra),
                  "product_status_counts": dict(collections.Counter(
                      str(x.get("product_status_code") or "") for x in exact.values()))})
    save(RUN, run)
    return {"created": True, "record": final_record, "bindings": after,
            "target_map": product_by_offer, "target_pairs": target_pairs}


def main() -> None:
    if RUN.exists() or VERIFY.exists():
        raise RuntimeError("Execution evidence already exists; reconcile current Ozon/WB state before any retry")
    offers, source = read_offers()
    if len(offers) != 55:
        raise RuntimeError("Expected exact 55-offer certificate scope")
    source_path = ROOT / SOURCE_REL
    client = Client()
    checked_at = dt.datetime.now(dt.timezone.utc).isoformat()
    products = read_ozon_products(client, offers)
    read_ozon_attributes(client, offers, products)
    for item in products:
        if (item["brand_values"] != ["Stekker"] or len(item["tnved_values"]) != 1
                or item["tnved_values"][0].split(" - ", 1)[0].strip() != TARGET_TNVED):
            raise RuntimeError(f"Live Ozon brand/TN VED is outside verified scope: {item['offer_id']}")
    preflight = {
        "checked_at_utc": checked_at, "fsa_record_id": FSA_ID, "fsa_registry_url": FSA_URL,
        "source": {"path": str(source_path), "sha256": digest(source_path),
                   "bytes": source_path.stat().st_size},
        "document_number": NUMBER, "issue_date": ISSUE, "expire_date": EXPIRY,
        "type": "certificate_of_conformity", "tnved": TARGET_TNVED,
        "offers": offers, "ozon_products": products,
    }
    run = {"started_at_utc": checked_at, "preflight": preflight,
           "local_cleanup_allowed": False, "complete": False}
    save(PREFLIGHT, preflight)
    save(RUN, run)

    ozon_result = create_and_bind_ozon(client, offers, products, run, source_path, source["row"])
    if not run.get("ozon"):
        raise RuntimeError("Ozon phase did not write its execution journal")

    wb_before = wb_snapshot(client, offers)
    wb_payloads, wb_plan = make_wb_payloads(wb_before)
    if len(wb_payloads) != 55:
        raise RuntimeError("WB payload does not contain all 55 exact cards")
    wb_entry = {"phase": "prepared", "cards": len(wb_payloads),
                "document_rows_to_add": sum(1 for x in wb_plan["rows"].values() if x["added"]),
                "nmids": {offer: value["nmID"] for offer, value in wb_plan["rows"].items()},
                "payload_body_bytes": wb_plan["body_bytes"], "payload_sha256": wb_plan["body_sha256"],
                "preserved_existing_document_rows": True, "excludeDocuments_false": True}
    run["wb"] = wb_entry
    save(RUN, run)
    time.sleep(5.4)
    try:
        status, wb_response = direct_post(client, "wb", "/content/v2/cards/update", wb_payloads, mutation=True)
    except Exception as exc:
        wb_entry.update({"phase": "update_uncertain_readback_required", "error_type": type(exc).__name__})
        save(RUN, run)
        status, wb_response = 0, {}
    wb_entry["http_status"] = status
    wb_entry["response"] = wb_response
    wb_entry["phase"] = "accepted_waiting_for_readback" if status == 200 and wb_response.get("error") is False else "response_inconclusive_readback_required"
    save(RUN, run)

    wb_after = wb_snapshot(client, offers)
    wb_statuses = collections.Counter()
    wb_verified = []
    wb_missing = []
    wb_conflicts = []
    for offer in offers:
        before, after = wb_before[offer], wb_after[offer]
        if (str(before["nmID"]) != str(after["nmID"])
                or canonical_unrelated(before) != canonical_unrelated(after)):
            wb_conflicts.append({"offer_id": offer, "reason": "identity_or_unrelated_fields_changed"})
        docs = (after.get("documents") or {}).get("items") or []
        matching = [x for x in docs if number_digits(x.get("number")).endswith("0579522")]
        if len(matching) != 1 or doc_sig(matching[0]) != target_doc_sig():
            wb_missing.append(offer)
            continue
        before_sigs = collections.Counter(doc_sig(x) for x in ((before.get("documents") or {}).get("items") or []))
        after_sigs = collections.Counter(doc_sig(x) for x in docs)
        if any(after_sigs[sig] < count for sig, count in before_sigs.items()):
            wb_conflicts.append({"offer_id": offer, "reason": "existing_document_row_lost"})
        verdict = matching[0].get("verdict") or {}
        wb_statuses[str(verdict.get("status") or verdict.get("reason") or "pending")] += 1
        wb_verified.append({"offer_id": offer, "nmID": str(after["nmID"]),
                            "document": clean_wb_doc(matching[0]), "verdict": verdict,
                            "overall_verdict": (after.get("documents") or {}).get("overallVerdict")})
    ozon_exact_count = sum(
        (str(item.get("product_id")), str(item.get("sku"))) in ozon_result.get("target_pairs", set())
        for item in ozon_result.get("bindings", []))
    verification = {
        "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "number": NUMBER, "type": "certificate_of_conformity", "fsa_record_id": FSA_ID,
        "ozon_certificate_id": (ozon_result.get("record") or {}).get("certificate_id"),
        "ozon_certificate_status": (ozon_result.get("record") or {}).get("status_code"),
        "ozon_exact_pairs": ozon_exact_count,
        "ozon_expected_pairs": len(offers),
        "ozon_binding_status_counts": dict(collections.Counter(
            str(x.get("product_status_code") or "") for x in ozon_result.get("bindings", [])
            if (str(x.get("product_id")), str(x.get("sku"))) in ozon_result.get("target_pairs", set()))),
        "wb_target_cards": len(offers), "wb_exact_rows_verified": len(wb_verified),
        "wb_missing_or_conflicting_rows": wb_missing,
        "wb_unrelated_field_or_prior_doc_conflicts": wb_conflicts,
        "wb_document_verdict_counts": dict(wb_statuses),
        "wb_review_statuses": [x["overall_verdict"] for x in wb_verified],
        "wb_readback_verified": len(wb_verified) == len(offers) and not wb_missing and not wb_conflicts,
        "local_source_retained": source_path.is_file() and digest(source_path) == source["row"]["SHA256"],
        "local_pdf_retained": PDF.is_file() and digest(PDF) == json.loads(PDF.with_name("05795_22_pdf_audit.json").read_text()) ["output_sha256"],
        "local_cleanup_allowed": False,
    }
    save(VERIFY, verification)
    run["verification_path"] = str(VERIFY)
    run["complete"] = verification["wb_readback_verified"]
    run["finished_at_utc"] = verification["checked_at_utc"]
    save(RUN, run)
    print(json.dumps({
        "document": NUMBER, "ozon_certificate_id": verification["ozon_certificate_id"],
        "ozon_exact_pairs": f"{ozon_exact_count}/{len(offers)}",
        "ozon_certificate_status": verification["ozon_certificate_status"],
        "ozon_binding_status_counts": verification["ozon_binding_status_counts"],
        "wb_exact_rows": f"{verification['wb_exact_rows_verified']}/{verification['wb_target_cards']}",
        "wb_verdicts": verification["wb_document_verdict_counts"],
        "wb_readback_verified": verification["wb_readback_verified"],
        "local_files_retained": verification["local_source_retained"] and verification["local_pdf_retained"],
        "verification": str(VERIFY),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
