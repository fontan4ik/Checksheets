"""Fresh read-only verification for the STEKKER Ozon binds and WB card update."""
from __future__ import annotations

import collections
import json
from datetime import datetime
from pathlib import Path

from api_client import BASE, Client, now
from execute_stekker_reconciliation import (
    canonical_card, compare_unrelated_fields, doc_signature, iso_date, same_number,
)
from group4_ozon import doc_identity

PLAN_PATH = BASE / "stekker_reconciliation_plan.json"
RUN_PATH = BASE / "stekker_reconciliation_execution.json"
OUT = BASE / "stekker_reconciliation_verification.json"


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
        raise RuntimeError("Duplicate certificate IDs in fresh Ozon list")
    return rows


def all_wb_error_batches(client: Client) -> list[dict]:
    result, cursor = [], {"limit": 100}
    for _ in range(100):
        body = client.call("wb", "/content/v2/cards/error/list",
                           {"cursor": cursor, "order": {"ascending": True}})
        if body.get("error"):
            raise RuntimeError("WB error-list returned an API error")
        data = body.get("data") or {}
        result.extend(data.get("items") or [])
        c = data.get("cursor") or {}
        if c.get("next") is not True:
            return result
        if not c.get("updatedAt") or not c.get("batchUUID"):
            raise RuntimeError("WB error-list cursor incomplete")
        cursor = {"limit": 100, "updatedAt": c["updatedAt"], "batchUUID": c["batchUUID"]}
    raise RuntimeError("WB error-list pagination exceeded 100 pages")


def wb_update_started_at() -> str:
    log = BASE / "api_calls.jsonl"
    run = json.loads(RUN_PATH.read_text())
    events = []
    for line in log.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (event.get("platform") == "wb" and
                event.get("path") == "/content/v2/cards/update" and
                event.get("mutation") is True and
                str(event.get("started_at") or "") >= run["started_at"] and
                event.get("phase") in {"prepared", "response"}):
            events.append(event)
    if not events:
        raise RuntimeError("WB update event is not present in the API journal")
    return min(x["started_at"] for x in events)


def main() -> None:
    plan, run = json.loads(PLAN_PATH.read_text()), json.loads(RUN_PATH.read_text())
    if run.get("complete") or not any(
        x.get("platform") == "wb" and x.get("response", {}).get("error") is False
        for x in run.get("results", [])
    ):
        raise RuntimeError("No accepted STEKKER WB update to verify")
    client = Client()
    fresh_info = client.call("ozon", "/v3/product/info/list",
                             {"offer_id": sorted(plan["products"])})["items"]
    live_products = {str(x.get("offer_id")): x for x in fresh_info}
    product_identity_ok = len(live_products) == len(plan["products"])
    for offer, expected in plan["products"].items():
        live = live_products.get(offer) or {}
        product_identity_ok &= (
            str(live.get("id") or live.get("product_id")) == expected["product_id"] and
            str(live.get("sku")) == expected["sku"] and not live.get("is_archived")
        )

    certs = list_certificates(client)
    ozon_docs = []
    ozon_exact_pairs = 0
    ozon_missing_pairs = []
    ozon_pair_status_counts = collections.Counter()
    for spec in plan["documents"]:
        matches = [x for x in certs if same_number(
            x.get("certificate_number", ""), spec["number"])]
        unique = len(matches) == 1
        record = matches[0] if unique else (matches[0] if matches else {})
        metadata_ok = bool(unique and
            record.get("type_code") == spec["type_code"] and
            iso_date(record.get("issue_date")) == spec["issue_date"] and
            iso_date(record.get("expire_date")) == spec["expire_date"] and
            record.get("accordance_type_code") == "EAEU")
        bindings = client.ozon_bindings(record["certificate_id"]) if unique else []
        by_pair = {(str(x.get("product_id")), str(x.get("sku"))): x for x in bindings}
        exact = []
        for offer in spec["offers"]:
            expected = plan["products"][offer]
            pair = (expected["product_id"], expected["sku"])
            item = by_pair.get(pair)
            if item:
                ozon_exact_pairs += 1
                status = str(item.get("product_status_code"))
                ozon_pair_status_counts[status] += 1
                exact.append({"offer_id": offer, "product_id": pair[0], "sku": pair[1],
                              "product_status_code": item.get("product_status_code")})
            else:
                ozon_missing_pairs.append({"number": spec["number"], "offer_id": offer,
                                           "product_id": pair[0], "sku": pair[1]})
        ozon_docs.append({
            "number": spec["number"], "type_code": spec["type_code"],
            "certificate_id": record.get("certificate_id"),
            "status_code": record.get("status_code"),
            "issue_date": iso_date(record.get("issue_date")),
            "expire_date": iso_date(record.get("expire_date")),
            "unique_live_record": unique, "metadata_matches_source": metadata_ok,
            "expected_pairs": len(spec["offers"]), "exact_live_pairs": len(exact),
            "binding_status_counts": dict(collections.Counter(
                str(x.get("product_status_code")) for x in exact)),
        })

    wb_before = plan["wb_cards"]
    wb_after, wb_card_results = {}, []
    item_verdicts, overall_verdicts = collections.Counter(), collections.Counter()
    target_vendor_codes = set(plan["products"])
    for offer in sorted(target_vendor_codes):
        cards = [x for x in client.wb_cards(offer) if x.get("vendorCode") == offer]
        wb_after[offer] = cards
        expected_nmids = {str(x["nmID"]) for x in wb_before[offer]}
        identity_ok = {str(x.get("nmID")) for x in cards} == expected_nmids
        for card in cards:
            before = next((x for x in wb_before[offer]
                           if str(x.get("nmID")) == str(card.get("nmID"))), {})
            docs = card.get("documents") or {}
            actual = docs.get("items") or []
            expected_docs = [spec for spec in plan["documents"] if offer in spec["offers"]]
            exact_visible, required_items = [], []
            for spec in expected_docs:
                signature = (spec["wb_type"], doc_identity(spec["number"]),
                             spec["issue_date"], spec["expire_date"], False)
                match = next((d for d in actual if doc_signature(d) == signature), None)
                if match:
                    exact_visible.append(spec["number"])
                    verdict = match.get("verdict") or {}
                    state = f"{verdict.get('status', 'missing')}:{verdict.get('reason', '')}"
                    item_verdicts[state] += 1
                    required_items.append({"number": spec["number"], "id": match.get("id"),
                                           "type": match.get("type"), "verdict": verdict})
                else:
                    required_items.append({"number": spec["number"], "missing": True})
            overall = docs.get("overallVerdict") or {}
            ov_state = f"{overall.get('status', 'missing')}:{overall.get('isFullyChecked', False)}"
            overall_verdicts[ov_state] += 1
            fields_ok = compare_unrelated_fields(before, card)
            # These fields are not part of the payload but should remain unchanged.
            fields_ok &= all(before.get(k) == card.get(k) for k in ("photos", "video", "tags"))
            wb_card_results.append({
                "offer_id": offer, "nmID": card.get("nmID"),
                "identity_matches": identity_ok,
                "documents_exclude": docs.get("excludeDocuments"),
                "expected_documents": len(expected_docs),
                "visible_documents": len(exact_visible),
                "all_documents_visible": len(exact_visible) == len(expected_docs),
                "document_items": required_items,
                "unrelated_fields_preserved": fields_ok,
                "overallVerdict": overall,
            })

    update_started = wb_update_started_at()
    all_errors = all_wb_error_batches(client)
    from datetime import timezone
    try:
        update_dt = datetime.fromisoformat(update_started.replace("Z", "+00:00"))
    except ValueError:
        update_dt = datetime.fromisoformat(update_started).replace(tzinfo=timezone.utc)
    relevant_errors = []
    for batch in all_errors:
        try:
            updated = datetime.fromisoformat(str(batch.get("updatedAt", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        codes = set(batch.get("vendorCodes") or []) | set(batch.get("errors") or {})
        intersect = target_vendor_codes & codes
        if updated >= update_dt and intersect:
            relevant_errors.append({"batchUUID": batch.get("batchUUID"),
                                    "updatedAt": batch.get("updatedAt"),
                                    "vendor_codes": sorted(intersect)})

    wb_complete = bool(wb_card_results) and all(
        x["identity_matches"] and x["all_documents_visible"] and
        x["documents_exclude"] is False and x["unrelated_fields_preserved"]
        for x in wb_card_results
    )
    report = {
        "checked_at": now(), "plan_checked_at": plan.get("checked_at"),
        "ozon_products_checked_at": now(), "wb_update_started_at": update_started,
        "ozon_target_offers": len(plan["products"]), "ozon_product_identity_ok": bool(product_identity_ok),
        "ozon_documents": ozon_docs, "ozon_expected_pairs": sum(len(x["offers"]) for x in plan["documents"]),
        "ozon_exact_live_pairs": ozon_exact_pairs, "ozon_missing_pairs": ozon_missing_pairs,
        "ozon_certificate_status_counts": dict(collections.Counter(
            str(x.get("status_code")) for x in ozon_docs)),
        "ozon_product_binding_status_counts": dict(ozon_pair_status_counts),
        "wb_cards_checked": len(wb_card_results),
        "wb_document_rows_expected": sum(len(x["offers"]) for x in plan["documents"]),
        "wb_document_items_verdict_counts": dict(item_verdicts),
        "wb_overall_verdict_counts": dict(overall_verdicts),
        "wb_target_errors_after_update": relevant_errors,
        "wb_error_batches_checked": len(all_errors),
        "wb_all_expected_documents_visible": wb_complete,
        "wb_cards": wb_card_results,
    }
    report["complete"] = bool(
        product_identity_ok and ozon_exact_pairs == report["ozon_expected_pairs"] and
        not ozon_missing_pairs and all(x["unique_live_record"] and x["metadata_matches_source"]
                                      for x in ozon_docs) and wb_complete and not relevant_errors
    )
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    tmp.replace(OUT)
    print(json.dumps({
        "complete": report["complete"], "ozon_offers": report["ozon_target_offers"],
        "ozon_exact_pairs": report["ozon_exact_live_pairs"],
        "ozon_binding_statuses": report["ozon_product_binding_status_counts"],
        "wb_cards": report["wb_cards_checked"],
        "wb_documents_expected": report["wb_document_rows_expected"],
        "wb_item_verdicts": report["wb_document_items_verdict_counts"],
        "wb_overall_verdicts": report["wb_overall_verdict_counts"],
        "wb_target_errors": len(relevant_errors), "report": str(OUT),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
