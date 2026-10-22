"""Execute one reviewed STEKKER Ozon/WB batch once; mutations never auto-retry."""
from __future__ import annotations

import base64
import collections
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

from api_client import BASE, ROOT, Client, digest, now
from group4_ozon import doc_identity

PLAN_PATH = BASE / "stekker_reconciliation_plan.json"
RUN_PATH = BASE / "stekker_reconciliation_execution.json"
MAX_REQUEST_BYTES = 15_000_000
WB_FIELDS = (
    "nmID", "vendorCode", "brand", "title", "gtin", "description",
    "dimensions", "characteristics", "sizes", "kizMarked",
)
WB_DOC_FIELDS = (
    "id", "type", "number", "productNumber", "tradeName", "applicant",
    "startDate", "endDate", "isEndless",
)
DOC_DERIVATIVES = {
    "ЕАЭС N RU Д-CN.PA07.B.01452/23": "stekker_upload_files/01452_23.pdf",
}


def save_run(run: dict) -> None:
    tmp = RUN_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(run, ensure_ascii=False, indent=2))
    tmp.replace(RUN_PATH)


def list_certificates(client: Client) -> list[dict]:
    rows = []
    page = 1
    while True:
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100})["result"]
        rows.extend(result["certificates"])
        if page >= result["page_count"]:
            break
        page += 1
    if len({str(x["certificate_id"]) for x in rows}) != len(rows):
        raise RuntimeError("Duplicate certificate_id in Ozon list")
    return rows


def same_number(a: str, b: str) -> bool:
    return doc_identity(a or "") == doc_identity(b or "")


def iso_date(v: str) -> str:
    return str(v or "")[:10]


def canonical_card(card: dict) -> dict:
    result = json.loads(json.dumps(card))
    result["characteristics"] = sorted(result.get("characteristics") or [], key=lambda x: x.get("id", -1))
    return result


def doc_signature(doc: dict) -> tuple:
    return (int(doc.get("type", 0)), doc_identity(doc.get("number", "")),
            iso_date(doc.get("startDate")), iso_date(doc.get("endDate")),
            bool(doc.get("isEndless", False)))


def doc_plan_signature(doc: dict) -> tuple:
    return (int(doc["wb_type"]), doc_identity(doc["number"]),
            doc["issue_date"], doc["expire_date"], False)


def check_products(client: Client, plan: dict) -> dict[str, dict]:
    offers = sorted(plan["products"])
    rows = client.call("ozon", "/v3/product/info/list", {"offer_id": offers})["items"]
    live = {str(x.get("offer_id")): x for x in rows}
    if len(rows) != len(offers) or set(live) != set(offers):
        raise RuntimeError("Fresh Ozon product read does not equal the reviewed offer set")
    normalized = {}
    for offer, expected in plan["products"].items():
        item = live[offer]
        if (str(item.get("id") or item.get("product_id")) != expected["product_id"] or
                str(item.get("sku")) != expected["sku"] or item.get("is_archived")):
            raise RuntimeError(f"Ozon identity changed or offer archived: {offer}")
        normalized[offer] = {
            "product_id": str(item.get("id") or item.get("product_id")),
            "sku": str(item.get("sku")),
            "name": item.get("name"),
        }
    return normalized


def read_wb_cards(client: Client, plan: dict) -> dict[str, list[dict]]:
    live = {}
    seen_nmid = set()
    for offer in sorted(plan["products"]):
        rows = [x for x in client.wb_cards(offer) if x.get("vendorCode") == offer]
        expected_ids = {str(x["nmID"]) for x in plan["wb_cards"][offer]}
        if {str(x.get("nmID")) for x in rows} != expected_ids:
            raise RuntimeError(f"WB card identity/count changed for {offer}")
        for card in rows:
            nmid = str(card["nmID"])
            if nmid in seen_nmid:
                raise RuntimeError(f"Duplicate WB nmID in target set: {nmid}")
            seen_nmid.add(nmid)
        live[offer] = rows
    return live


def validate_source_files(plan: dict) -> dict[str, dict]:
    derivative_audit = {}
    for spec in plan["documents"]:
        source = Path(spec["absolute_source_file"])
        if not source.is_file() or source.is_symlink() or digest(source) != spec["source_sha256"]:
            raise RuntimeError(f"Original document changed since plan: {source}")
        upload = source
        derivative_rel = DOC_DERIVATIVES.get(spec["number"])
        if derivative_rel:
            upload = BASE / derivative_rel
            if not upload.is_file():
                raise RuntimeError(f"Verified JPEG-to-PDF transport copy missing: {upload}")
            info = subprocess.run(["pdfinfo", str(upload)], capture_output=True, text=True, check=True).stdout
            pages = re.search(r"^Pages:\s+(\d+)", info, re.M)
            size = re.search(r"^Page size:\s+([^\n]+)", info, re.M)
            if not pages or pages.group(1) != "1" or not size or "595" not in size.group(1):
                raise RuntimeError(f"Transport copy is not a single A4 page: {upload}")
            derivative_audit[spec["number"]] = {
                "original_file": str(source), "original_sha256": digest(source),
                "upload_file": str(upload), "upload_sha256": digest(upload),
                "upload_bytes": upload.stat().st_size, "pdfinfo_pages": 1,
                "pdfinfo_page_size": size.group(1).strip(),
                "visual_round_trip_checked": True,
            }
        if upload.stat().st_size * 4 // 3 + 100_000 >= MAX_REQUEST_BYTES:
            raise RuntimeError(f"Ozon create would exceed the verified request limit: {spec['number']}")
    return derivative_audit


def fresh_cert_match(certs: list[dict], spec: dict) -> dict | None:
    found = [x for x in certs if same_number(x.get("certificate_number", ""), spec["number"])]
    if len(found) > 1:
        raise RuntimeError(f"Duplicate live Ozon records for {spec['number']}")
    return found[0] if found else None


def check_existing_record(record: dict, spec: dict, planned: dict) -> None:
    if (str(record.get("certificate_id")) != str((planned.get("ozon_live_record") or {}).get("certificate_id")) or
            record.get("type_code") != spec["type_code"] or
            iso_date(record.get("issue_date")) != spec["issue_date"] or
            iso_date(record.get("expire_date")) != spec["expire_date"] or
            record.get("accordance_type_code") != "EAEU"):
        raise RuntimeError(f"Ozon record changed or metadata conflicts for {spec['number']}")
    if record.get("status_code") != "approved":
        raise RuntimeError(f"Ozon record not approved; do not bind: {spec['number']}")


def bind_and_verify(client: Client, spec: dict, group: dict, products: dict,
                    record: dict, run: dict) -> dict:
    target_pairs = {
        (products[offer]["product_id"], products[offer]["sku"]): offer
        for offer in spec["offers"]
    }
    if len(target_pairs) != len(spec["offers"]):
        raise RuntimeError(f"Duplicate product/SKU pair in {spec['number']}")
    before = client.ozon_bindings(record["certificate_id"])
    current = {(str(x.get("product_id")), str(x.get("sku"))): x for x in before}
    missing = [pair for pair in target_pairs if pair not in current]
    if missing:
        entry = {"platform": "ozon", "number": spec["number"],
                 "certificate_id": record["certificate_id"], "phase": "binding",
                 "target_pairs": len(target_pairs), "missing_pairs_before": len(missing)}
        run["results"].append(entry)
        save_run(run)
        skus = sorted({sku for _, sku in missing})
        if len(skus) != len(missing):
            raise RuntimeError(f"Binding by SKU is ambiguous for {spec['number']}")
        body = client.call("ozon", "/v1/product/certificate/bind",
                           {"certificate_id": int(record["certificate_id"]), "skus": skus},
                           mutation=True)
        entry["response"] = body
        if body.get("result") is not True:
            entry["outcome"] = "bind_incomplete_do_not_retry"
            save_run(run)
            raise RuntimeError(f"Ozon bind response was not true for {spec['number']}")
        save_run(run)

    after = client.ozon_bindings(record["certificate_id"])
    by_pair = {(str(x.get("product_id")), str(x.get("sku"))): x for x in after}
    absent = [target_pairs[p] for p in target_pairs if p not in by_pair]
    if absent:
        raise RuntimeError(f"Ozon readback lacks {len(absent)} pairs for {spec['number']}")
    statuses = collections.Counter(
        str(by_pair[pair].get("product_status_code"))
        for pair in target_pairs
    )
    return {
        "outcome": "bound_and_readback_verified" if missing else "already_bound_and_readback_verified",
        "certificate_id": record["certificate_id"],
        "target_pairs": len(target_pairs),
        "newly_bound_pairs": len(missing),
        "product_status_counts": dict(statuses),
        "exact_pairs": [
            {"offer_id": offer, "product_id": pair[0], "sku": pair[1],
             "product_status_code": by_pair[pair].get("product_status_code")}
            for pair, offer in target_pairs.items()
        ],
    }


def create_declaration(client: Client, spec: dict, plan_doc: dict,
                       products: dict, run: dict, derivative: dict) -> dict:
    if fresh_cert_match(list_certificates(client), spec):
        raise RuntimeError(f"Declaration appeared after preflight; reconcile instead of create: {spec['number']}")
    upload = Path(derivative["upload_file"])
    if digest(upload) != derivative["upload_sha256"]:
        raise RuntimeError("PDF transport copy changed immediately before upload")
    import datetime
    end = datetime.date.fromisoformat(spec["expire_date"])
    skus = sorted({products[x]["sku"] for x in spec["offers"]})
    if len(skus) != len(spec["offers"]):
        raise RuntimeError("Duplicate SKU in new declaration group")
    params = {
        "name": "Декларация о соответствии № " + spec["number"],
        "certificate_type": "DECLARATION",
        "certificate_country": "RU",
        "accordance_type": "EAEU",
        "number": spec["number"],
        "issue_date": spec["issue_date"] + "T00:00:00Z",
        "expired_date": {"date": {"day": end.day, "month": end.month, "year": end.year}},
        "skus": skus,
        "product_type": "UNKNOWN",
        "files": [{
            "file_content": base64.b64encode(upload.read_bytes()).decode("ascii"),
            "name": upload.name,
        }],
    }
    payload = {"params": params}
    body_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(body_bytes) >= MAX_REQUEST_BYTES:
        raise RuntimeError("Ozon create JSON exceeds the observed 15 MB request limit")
    entry = {
        "platform": "ozon", "number": spec["number"], "phase": "creating",
        "request_bytes": len(body_bytes), "request_sha256": __import__("hashlib").sha256(body_bytes).hexdigest(),
        "original_sha256": spec["source_sha256"], "upload_sha256": derivative["upload_sha256"],
        "target_skus": skus,
    }
    run["results"].append(entry)
    save_run(run)
    try:
        body = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
    except Exception as exc:
        entry.update({"outcome": "uncertain_create_do_not_retry", "error_type": type(exc).__name__})
        save_run(run)
        raise
    entry["response"] = body
    if (body.get("status") != "COMPLETED" or not body.get("certificate_id") or
            any(x.get("state") == "INVALID" for x in body.get("params", []))):
        entry["outcome"] = "create_incomplete_do_not_retry"
        save_run(run)
        raise RuntimeError(f"Ozon create incomplete for {spec['number']}; reconcile live state")
    entry["certificate_id"] = body["certificate_id"]
    save_run(run)

    record = fresh_cert_match(list_certificates(client), spec)
    if not record:
        entry["outcome"] = "create_response_missing_from_live_list_do_not_retry"
        save_run(run)
        raise RuntimeError(f"Created declaration absent from Ozon live list: {spec['number']}")
    if (str(record.get("certificate_id")) != str(body["certificate_id"]) or
            record.get("type_code") != "declaration" or
            iso_date(record.get("issue_date")) != spec["issue_date"] or
            iso_date(record.get("expire_date")) != spec["expire_date"] or
            record.get("accordance_type_code") != "EAEU"):
        entry["outcome"] = "create_metadata_conflict_do_not_retry"
        entry["live_record"] = record
        save_run(run)
        raise RuntimeError(f"Created declaration metadata differs from scan: {spec['number']}")

    bindings = client.ozon_bindings(record["certificate_id"])
    by_pair = {(str(x.get("product_id")), str(x.get("sku"))): x for x in bindings}
    expected = {
        (products[offer]["product_id"], products[offer]["sku"]): offer
        for offer in spec["offers"]
    }
    absent = [expected[p] for p in expected if p not in by_pair]
    if absent:
        entry["outcome"] = "create_binding_readback_incomplete"
        save_run(run)
        raise RuntimeError(f"Created declaration missing exact Ozon pairs: {absent}")
    status_counts = collections.Counter(str(by_pair[p].get("product_status_code")) for p in expected)
    entry.update({
        "outcome": "created_and_exact_pairs_readback_verified",
        "live_status": record.get("status_code"),
        "target_pairs": len(expected),
        "product_status_counts": dict(status_counts),
        "exact_pairs": [
            {"offer_id": offer, "product_id": pair[0], "sku": pair[1],
             "product_status_code": by_pair[pair].get("product_status_code")}
            for pair, offer in expected.items()
        ],
    })
    save_run(run)
    return {"certificate": record, "bindings": entry}


def wb_doc_payloads(plan: dict, wb_live: dict[str, list[dict]]) -> tuple[list[dict], list[dict]]:
    desired_by_offer = collections.defaultdict(list)
    for spec in plan["documents"]:
        for offer in spec["offers"]:
            desired_by_offer[offer].append(spec)
    payloads, expected_rows = [], []
    for offer, cards in wb_live.items():
        for card in cards:
            docs = card.get("documents") or {}
            if docs.get("excludeDocuments") is not False:
                raise RuntimeError(f"WB does not currently include documents on {offer}")
            old_items = docs.get("items") or []
            items = [{k: d[k] for k in WB_DOC_FIELDS if k in d} for d in old_items]
            additions = []
            for spec in desired_by_offer[offer]:
                signature = doc_plan_signature(spec)
                matches = [d for d in items if doc_signature(d)[:2] == signature[:2]]
                if matches:
                    if any(doc_signature(d) != signature for d in matches):
                        raise RuntimeError(f"Conflicting existing WB document metadata on {offer}: {spec['number']}")
                    continue
                new_doc = {
                    "type": spec["wb_type"], "number": spec["number"],
                    "startDate": spec["issue_date"] + "T00:00:00Z",
                    "endDate": spec["expire_date"] + "T00:00:00Z",
                    "isEndless": False,
                }
                items.append(new_doc)
                additions.append(new_doc)
            payload = {k: card[k] for k in WB_FIELDS if k in card}
            payload["documents"] = {"items": items, "excludeDocuments": False}
            if additions:
                payloads.append(payload)
            expected_rows.append({
                "offer_id": offer, "nmID": card["nmID"],
                "documents_expected": [
                    {"type": x["wb_type"], "number": x["number"],
                     "issue_date": x["issue_date"], "expire_date": x["expire_date"]}
                    for x in desired_by_offer[offer]
                ],
                "documents_newly_added": len(additions),
            })
    return payloads, expected_rows


def compare_unrelated_fields(before: dict, after: dict) -> bool:
    for field in ("nmID", "vendorCode", "brand", "title", "gtin", "description",
                  "dimensions", "sizes", "kizMarked"):
        if before.get(field) != after.get(field):
            return False
    before_chars = sorted((x.get("id"), json.dumps(x.get("value"), ensure_ascii=False, sort_keys=True))
                          for x in before.get("characteristics") or []
                          if int(x.get("id", -1)) not in {15001135, 15001136, 15001137, 15001138})
    after_chars = sorted((x.get("id"), json.dumps(x.get("value"), ensure_ascii=False, sort_keys=True))
                         for x in after.get("characteristics") or []
                         if int(x.get("id", -1)) not in {15001135, 15001136, 15001137, 15001138})
    return before_chars == after_chars


def verify_wb_readback(client: Client, plan: dict, before: dict[str, list[dict]],
                       expected_rows: list[dict]) -> dict:
    after = read_wb_cards(client, plan)
    checked, verdicts = [], collections.Counter()
    for offer, cards in after.items():
        prior_by_nmid = {str(x["nmID"]): x for x in before[offer]}
        for card in cards:
            prior = prior_by_nmid[str(card["nmID"])]
            if not compare_unrelated_fields(prior, card):
                raise RuntimeError(f"Unrelated WB card fields changed: {offer}")
            actual = (card.get("documents") or {}).get("items") or []
            expected_docs = next(x for x in expected_rows
                                 if x["offer_id"] == offer and str(x["nmID"]) == str(card["nmID"]))["documents_expected"]
            for expected in expected_docs:
                sig = (expected["type"], doc_identity(expected["number"]),
                       expected["issue_date"], expected["expire_date"], False)
                if not any(doc_signature(d) == sig for d in actual):
                    raise RuntimeError(f"WB readback missing exact document on {offer}: {expected['number']}")
            if (card.get("documents") or {}).get("excludeDocuments") is not False:
                raise RuntimeError(f"WB excludes documents after update on {offer}")
            for doc in actual:
                verdict = doc.get("verdict") or {}
                if verdict:
                    verdicts[f"{verdict.get('status')}:{verdict.get('reason')}"] += 1
            checked.append({"offer_id": offer, "nmID": card["nmID"],
                            "documents_visible": True, "excludeDocuments": False,
                            "unrelated_fields_preserved": True,
                            "overallVerdict": (card.get("documents") or {}).get("overallVerdict"),
                            "document_verdicts": [
                                {"number": d.get("number"), "verdict": d.get("verdict")}
                                for d in actual if any(same_number(d.get("number", ""), x["number"])
                                    for x in expected_docs)
                            ]})
    return {"cards_checked": len(checked), "all_documents_visible": True,
            "all_unrelated_fields_preserved": True,
            "all_exclude_documents_false": True,
            "verdict_counts": dict(verdicts), "cards": checked}


def main() -> None:
    plan = json.loads(PLAN_PATH.read_text())
    if not plan.get("complete") or plan.get("target_offer_count") != 17:
        raise RuntimeError("Reviewed read-only STEKKER preflight is incomplete")
    derivatives = validate_source_files(plan)
    client = Client()
    products = check_products(client, plan)
    wb_before = read_wb_cards(client, plan)

    if RUN_PATH.exists():
        run = json.loads(RUN_PATH.read_text())
        if run.get("complete") or run.get("results") or run.get("mutation_started"):
            raise RuntimeError(f"Execution journal contains work; reconcile live state before another write: {RUN_PATH}")
        start = str(run.get("started_at") or "")
        api_log = BASE / "api_calls.jsonl"
        mutations = []
        if api_log.is_file():
            for line in api_log.read_text().splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (event.get("mutation") is True and str(event.get("started_at") or "") >= start):
                    mutations.append(event)
        if mutations:
            raise RuntimeError(f"Mutation events exist after the previous start; reconcile first: {RUN_PATH}")
        run["recovered_after_prewrite_validation_error_at"] = now()
    else:
        run = None

    # Reconcile the read-only plan with live Ozon records before the first mutation.
    certs = list_certificates(client)
    for spec in plan["documents"]:
        planned = spec
        if planned["ozon_action"] == "create":
            if fresh_cert_match(certs, spec):
                raise RuntimeError(f"Ozon now has the create target; reconcile instead: {spec['number']}")
        else:
            record = fresh_cert_match(certs, spec)
            if not record:
                raise RuntimeError(f"Approved Ozon certificate vanished: {spec['number']}")
            check_existing_record(record, spec, planned)

    # Confirm cards have not changed since the plan; use canonical char ordering only.
    for offer, rows in wb_before.items():
        expected_by_nmid = {str(x["nmID"]): x for x in plan["wb_cards"][offer]}
        for card in rows:
            if canonical_card(card) != canonical_card(expected_by_nmid[str(card["nmID"])]):
                raise RuntimeError(f"WB card changed since read-only preflight: {offer}")

    if run is None:
        run = {
            "started_at": now(), "plan_file": str(PLAN_PATH),
            "source_sha256s_verified": {x["number"]: x["source_sha256"] for x in plan["documents"]},
            "pdf_derivative_audit": derivatives, "results": [], "complete": False,
        }
    else:
        run["pdf_derivative_audit"] = derivatives
    save_run(run)

    # Bind exact SKU/product pairs to existing approved Ozon records.
    for spec in plan["documents"]:
        planned = spec
        if planned["ozon_action"] == "create":
            continue
        cert = fresh_cert_match(list_certificates(client), spec)
        if not cert:
            raise RuntimeError(f"Ozon record disappeared before bind: {spec['number']}")
        check_existing_record(cert, spec, planned)
        result = bind_and_verify(client, spec, planned, products, cert, run)
        result.update({"platform": "ozon", "number": spec["number"]})
        run["results"].append(result)
        save_run(run)

    # Create only the one declaration absent from Ozon. Existing records are reused above.
    for spec in plan["documents"]:
        planned = spec
        if planned["ozon_action"] != "create":
            continue
        derivative = derivatives.get(spec["number"])
        if not derivative:
            raise RuntimeError(f"No inspected PDF transport derivative for {spec['number']}")
        create_declaration(client, spec, planned, products, run, derivative)

    # Copy complete live WB cards and documents; one batch receives the 34 metadata rows.
    wb_fresh = read_wb_cards(client, plan)
    for offer, rows in wb_fresh.items():
        expected_by_nmid = {str(x["nmID"]): x for x in wb_before[offer]}
        for card in rows:
            if canonical_card(card) != canonical_card(expected_by_nmid[str(card["nmID"])]):
                raise RuntimeError(f"WB card changed immediately before write: {offer}")
    payloads, expected_rows = wb_doc_payloads(plan, wb_fresh)
    expected_count = sum(len(x["offers"]) for x in plan["documents"])
    if len(payloads) != 17 or sum(x["documents_newly_added"] for x in expected_rows) != expected_count:
        raise RuntimeError("WB payload does not contain all 17 cards and 34 exact additions")
    (BASE / "stekker_wb_update_payload.json").write_text(json.dumps(payloads, ensure_ascii=False, indent=2))
    entry = {"platform": "wb", "phase": "updating_complete_cards",
             "cards": len(payloads), "documents": expected_count}
    run["results"].append(entry)
    save_run(run)
    try:
        body = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
    except Exception as exc:
        entry.update({"outcome": "uncertain_update_do_not_retry", "error_type": type(exc).__name__})
        save_run(run)
        raise
    entry["response"] = body
    if body.get("error") is not False:
        entry["outcome"] = "update_not_accepted_do_not_retry"
        save_run(run)
        raise RuntimeError("WB update response was not error=false")
    save_run(run)

    readback = verify_wb_readback(client, plan, wb_fresh, expected_rows)
    entry.update({"outcome": "accepted_and_readback_verified", "readback": readback})
    run["finished_at"] = now()
    run["complete"] = True
    run["wb_documents_left_for_moderation"] = True
    run["wb_exact_documents_added"] = expected_count
    run["wb_cards_updated"] = len(payloads)
    save_run(run)
    print(json.dumps({
        "complete": run["complete"],
        "ozon_results": [
            {"number": x.get("number"), "outcome": x.get("outcome"),
             "new_pairs": x.get("newly_bound_pairs"), "status_counts": x.get("product_status_counts")}
            for x in run["results"] if x.get("platform") == "ozon"
        ],
        "wb_cards": readback["cards_checked"],
        "wb_document_rows": expected_count,
        "wb_verdict_counts": readback["verdict_counts"],
        "wb_review_pending": True,
        "journal": str(RUN_PATH),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
