#!/usr/bin/env python3
"""Attach only live, FSA-scope Stekker 01452/23 products on Ozon and WB.

Uses the current approved Ozon record, skips Ozon TNVED mismatches, and
preserves every pre-existing WB card field and document. Writes are journaled;
uncertain mutations are reconciled by readback and never automatically resent.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    copy_documents, doc_key, norm_number, comparable_card,
)
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402

PREFLIGHT = HERE / "stekker_01452_refresh_preflight_20261024.json"
OUT = HERE / "stekker_01452_scoped_execution_20261024.json"
JOURNAL = HERE / "stekker_01452_scoped_journal_20261024.jsonl"
RECORD_ID = "5606380"
DOC_NUMBER = "ЕАЭС N RU Д-CN.РА07.В.01452/23"
ISSUE = "2023-08-31"
EXPIRE = "2028-08-30"
WB_DOC = {
    "type": 2,
    "number": DOC_NUMBER,
    "startDate": ISSUE + "T00:00:00Z",
    "endDate": EXPIRE + "T00:00:00Z",
    "isEndless": False,
}
FAMILY = re.compile(r"\b(?:HM|PRF|STD)[A-Z0-9-]*", re.IGNORECASE)


def atomic(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def log(event: str, **fields) -> None:
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": now(), "event": event, **fields}, ensure_ascii=False) + "\n")


def has_scope_model(title: str) -> bool:
    return bool(FAMILY.search(str(title or "")))


def tnved_from_wb(card: dict) -> set[str]:
    found = set()
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" in name or "тнвед" in name:
            vals = item.get("value")
            vals = vals if isinstance(vals, list) else [vals]
            found.update(str(x).split(" - ", 1)[0].strip() for x in vals if str(x or "").strip())
    return found


def ozon_attr_values(row: dict) -> dict[str, list[str]]:
    return {
        str(x.get("id")): [str(v.get("value") or "").strip()
                           for v in (x.get("values") or [])
                           if str(v.get("value") or "").strip()]
        for x in row.get("attributes") or []
    }


def fetch_readback(client: Client, offers: list[str]) -> dict[str, dict]:
    rows = {}
    for offer in offers:
        found = client.wb_cards(offer)
        if len(found) != 1:
            continue
        rows[offer] = found[0]
    return rows


def verify_wb(before: dict[str, dict], after: dict[str, dict], offers: list[str]) -> dict:
    per_offer = {}
    for offer in offers:
        b, a = before.get(offer), after.get(offer)
        target_docs = []
        if a:
            target_docs = [x for x in (a.get("documents") or {}).get("items") or []
                           if doc_key(x) == doc_key(WB_DOC)
                           and str(x.get("startDate", ""))[:10] == ISSUE
                           and str(x.get("endDate", ""))[:10] == EXPIRE
                           and x.get("isEndless") is False]
        bdocs = {doc_key(x): x for x in copy_documents(b or {})}
        adocs = {doc_key(x): x for x in copy_documents(a or {})}
        old_preserved = all(
            key in adocs
            and str(adocs[key].get("startDate", ""))[:10] == str(old.get("startDate", ""))[:10]
            and str(adocs[key].get("endDate", ""))[:10] == str(old.get("endDate", ""))[:10]
            and adocs[key].get("isEndless") == old.get("isEndless")
            for key, old in bdocs.items()
        )
        docs = (a or {}).get("documents", {}).get("items") or []
        verdicts = [x.get("verdict") for x in docs if doc_key(x) == doc_key(WB_DOC)]
        per_offer[offer] = {
            "nmID": str((a or b or {}).get("nmID") or ""),
            "document_visible": len(target_docs) == 1,
            "new_document_count": len(target_docs),
            "preexisting_documents_preserved": old_preserved,
            "unrelated_card_fields_preserved": bool(a and b and comparable_card(a) == comparable_card(b)),
            "verdicts": verdicts,
            "document_items_before": len(bdocs),
            "document_items_after": len(adocs),
        }
    return {
        "cards_checked": len(per_offer),
        "all_target_cards_read": len(per_offer) == len(offers),
        "all_documents_visible": len(per_offer) == len(offers) and all(x["document_visible"] for x in per_offer.values()),
        "all_old_documents_preserved": len(per_offer) == len(offers) and all(x["preexisting_documents_preserved"] for x in per_offer.values()),
        "all_unrelated_fields_preserved": len(per_offer) == len(offers) and all(x["unrelated_card_fields_preserved"] for x in per_offer.values()),
        "wb_review_pending_or_returned": sum(
            1 for x in per_offer.values() for v in x["verdicts"]
            if not (isinstance(v, dict) and v.get("verified") is True
                    and v.get("status") == 1 and v.get("reason") == "valid")
        ),
        "per_offer": per_offer,
    }


def main() -> None:
    if OUT.exists() or JOURNAL.exists():
        raise RuntimeError("execution_artifacts_exist_inspect_before_any_write")
    pre = json.loads(PREFLIGHT.read_text())
    checked = dt.datetime.fromisoformat(pre["checked_at_utc"])
    if (dt.datetime.now(dt.timezone.utc) - checked).total_seconds() > 7200:
        raise RuntimeError("preflight_older_than_two_hours")
    if not pre.get("read_only") or pre.get("summary", {}).get("writes_performed") is not False:
        raise RuntimeError("preflight_not_read_only")

    # FSA 18056436 explicitly lists series HM, PRF, STD; the related protocol
    # is 2023-08-30. Do not infer applicability for other Stekker lines.
    ozon_by_offer = {x["offer_id"]: x for x in pre["ozon_targets"]}
    ozon_candidates = [x for x in pre["ozon_targets"] if x.get("eligible") and has_scope_model(x.get("name"))]
    # WB titles often omit the model. The exact vendorCode/offer_id mapping is
    # independently matched in both live catalogs, so use the Ozon product name
    # for model-family scope and WB's own live fields for WB identity/brand/TNVED.
    wb_candidates = [x for x in pre["wb_targets"] if x.get("eligible")
                     and x.get("offer_id") in ozon_by_offer
                     and ozon_by_offer[x["offer_id"]].get("identity_exact")
                     and has_scope_model(ozon_by_offer[x["offer_id"]].get("name"))]
    ozon_conflicts_in_scope = [x for x in pre["ozon_conflicts"]
                               if has_scope_model(next((p.get("name") for p in pre["ozon_targets"]
                                                       if p.get("offer_id") == x.get("offer_id")), ""))]
    excluded_scope = [x for x in pre["ozon_targets"] if not has_scope_model(x.get("name"))]
    if (len(ozon_candidates), len(wb_candidates), len(ozon_conflicts_in_scope), len(excluded_scope)) != (47, 51, 4, 5):
        raise RuntimeError("unexpected_scoped_target_counts_refusing_write")

    client = Client()
    # Reconfirm exact Ozon record metadata and current target identities immediately before mutation.
    certs = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_record_list_incomplete")
        certs.extend(batch)
        if page >= int(result.get("page_count") or 0):
            break
    same_number = [c for c in certs if norm_number(c.get("certificate_number")) == norm_number(DOC_NUMBER)]
    if len(same_number) != 1:
        raise RuntimeError("ozon_exact_record_missing_or_duplicated")
    record = same_number[0]
    if (str(record.get("certificate_id")) != RECORD_ID
            or record.get("type_code") != "declaration"
            or record.get("status_code") != "approved"
            or str(record.get("issue_date", ""))[:10] != ISSUE
            or str(record.get("expire_date", ""))[:10] != EXPIRE):
        raise RuntimeError("ozon_exact_record_metadata_or_status_changed")
    offer_ids = [x["offer_id"] for x in ozon_candidates]
    expected_by_offer = {x["offer_id"]: {"product_id": str(x["product_id"]), "sku": str(x["sku"])}
                         for x in ozon_candidates}
    if len(set(offer_ids)) != len(offer_ids) or len({v["sku"] for v in expected_by_offer.values()}) != len(offer_ids):
        raise RuntimeError("duplicate_ozon_offer_or_sku")
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": offer_ids}).get("items") or []
    attrs = client.call("ozon", "/v4/product/info/attributes",
                        {"filter": {"offer_id": offer_ids}, "limit": len(offer_ids)}).get("result") or []
    pmap = collections.defaultdict(list)
    amap = collections.defaultdict(list)
    for p in products:
        pmap[str(p.get("offer_id"))].append(p)
    for a in attrs:
        amap[str(a.get("offer_id"))].append(a)
    for offer, expected in expected_by_offer.items():
        if len(pmap[offer]) != 1 or len(amap[offer]) != 1:
            raise RuntimeError("ozon_target_not_unique:" + offer)
        product, values = pmap[offer][0], ozon_attr_values(amap[offer][0])
        current_id = str(product.get("product_id") or product.get("id") or "")
        current_sku = str(product.get("sku") or "")
        brand = values.get("85", [])
        codes = {x.split(" - ", 1)[0].strip() for x in values.get("22232", [])}
        if (current_id != expected["product_id"] or current_sku != expected["sku"]
                or product.get("is_archived") is not False
                or not brand or any(x.casefold() != "stekker" for x in brand)
                or codes != {"8544429009"}
                or not has_scope_model(product.get("name"))):
            raise RuntimeError("ozon_target_live_scope_or_identity_changed:" + offer)

    prior_bindings = client.ozon_bindings(int(RECORD_ID))
    prior_by_sku = {}
    for row in prior_bindings:
        sku = str(row.get("sku") or "")
        if not sku or sku in prior_by_sku:
            raise RuntimeError("ozon_existing_binding_missing_or_duplicate_sku")
        prior_by_sku[sku] = row
    if any(x.get("product_status_code") != "approved" for x in prior_bindings):
        raise RuntimeError("ozon_preexisting_bindings_not_approved")
    if set(prior_by_sku) & {x["sku"] for x in expected_by_offer.values()}:
        raise RuntimeError("unexpected_target_overlap_with_existing_ozon_bindings")
    if len(prior_bindings) != 10:
        raise RuntimeError("ozon_prior_binding_count_changed")

    # Refresh each target WB card and recheck identity, code, and FSA model scope.
    wb_offers = [x["offer_id"] for x in wb_candidates]
    pre_wb = {x["offer_id"]: x["card"] for x in pre["wb_targets"] if x["offer_id"] in set(wb_offers)}
    wb_before = {}
    for offer in wb_offers:
        found = client.wb_cards(offer)
        if len(found) != 1:
            raise RuntimeError("wb_target_card_not_unique:" + offer)
        card = found[0]
        source = next(x for x in wb_candidates if x["offer_id"] == offer)
        if (str(card.get("nmID")) != str(source["nmID"])
                or card.get("vendorCode") != offer
                or str(card.get("brand") or "").strip().casefold() != "stekker"
                or tnved_from_wb(card) != {"8544429009"}
                or not ozon_by_offer[offer].get("identity_exact")
                or not has_scope_model(ozon_by_offer[offer].get("name"))):
            raise RuntimeError("wb_target_live_scope_or_identity_changed:" + offer)
        if comparable_card(card) != comparable_card(pre_wb[offer]):
            raise RuntimeError("wb_non_document_fields_changed_since_preflight:" + offer)
        wb_before[offer] = card

    desired = []
    for row in wb_candidates:
        merged = merge_wb(wb_before[row["offer_id"]], [WB_DOC])
        if merged is None:
            raise RuntimeError("wb_document_already_present_after_preflight:" + row["offer_id"])
        desired.append({"offer_id": row["offer_id"], "nmID": str(row["nmID"]),
                        "before": wb_before[row["offer_id"]], "payload": merged})
    payload = [x["payload"] for x in desired]
    request_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
    if request_bytes > 9_000_000:
        raise RuntimeError("wb_update_batch_exceeds_safe_payload_limit")

    state = {
        "started_at_utc": now(), "state": "prepared",
        "fsa_evidence": {
            "record_id": "18056436", "number": DOC_NUMBER,
            "status": "Действует", "valid_from": ISSUE, "valid_to": EXPIRE,
            "tnved": "8544429009", "explicit_series": ["HM", "PRF", "STD"],
            "sample_protocol_date": "2023-08-30",
            "sample_date_limitation": "FSA states declaration applies to products manufactured from sample date; marketplace batch dates are unavailable.",
            "registry_url": "https://pub.fsa.gov.ru/rds/declaration/view/18056436/product",
        },
        "ozon": {"certificate_id": RECORD_ID, "record_status": "approved",
                 "target_count": len(offer_ids), "target_offers": offer_ids,
                 "bindings_before": len(prior_bindings), "existing_status_counts": dict(collections.Counter(
                     str(x.get("product_status_code") or "unknown") for x in prior_bindings)),
                 "mutation": "not_started", "bindings_after": None},
        "wb": {"target_count": len(wb_offers), "target_offers": wb_offers,
               "expected_new_document_edges": len(wb_offers), "request_bytes": request_bytes,
               "mutation": "not_started", "readback": None},
        "scope_exclusions": {
            "out_of_scope_series_or_model_count": len(excluded_scope),
            "out_of_scope_series_or_model_offers": [x["offer_id"] for x in excluded_scope],
            "ozon_tnved_conflicts_in_scope_count": len(ozon_conflicts_in_scope),
            "ozon_tnved_conflicts_in_scope_offers": [x["offer_id"] for x in ozon_conflicts_in_scope],
            "four_tnved_conflict_products_are_in_scope_for_wb_if_wb_code_matches": True,
        },
        "local_files_deleted": False,
    }
    atomic(OUT, state)

    missing_skus = sorted(x["sku"] for x in expected_by_offer.values())
    log("ozon_bind_prepared", certificate_id=RECORD_ID, target_count=len(missing_skus),
        request_sha256=__import__("hashlib").sha256(json.dumps(
            {"certificate_id": int(RECORD_ID), "skus": missing_skus},
            ensure_ascii=False, separators=(",", ":")).encode()).hexdigest())
    state["state"] = "ozon_binding_submitted"
    state["ozon"]["mutation"] = "prepared"
    atomic(OUT, state)
    try:
        response = client.call("ozon", "/v1/product/certificate/bind",
                               {"certificate_id": int(RECORD_ID), "skus": missing_skus}, mutation=True)
        state["ozon"]["mutation"] = "accepted" if response.get("result") is True else "response_not_true"
        state["ozon"]["mutation_response"] = response
        log("ozon_bind_response", response=response)
    except Exception as exc:
        state["ozon"]["mutation"] = "uncertain_reconcile_without_retry"
        state["ozon"]["mutation_error"] = type(exc).__name__
        log("ozon_bind_uncertain", error=type(exc).__name__)
    atomic(OUT, state)

    expected_skus = set(prior_by_sku) | {x["sku"] for x in expected_by_offer.values()}
    ozon_after = []
    for attempt in range(7):
        ozon_after = client.ozon_bindings(int(RECORD_ID))
        after_by_sku = {str(x.get("sku") or ""): x for x in ozon_after}
        if len(after_by_sku) == len(ozon_after) and set(after_by_sku) == expected_skus:
            break
        if attempt < 6:
            time.sleep(8)
    after_by_sku = {str(x.get("sku") or ""): x for x in ozon_after}
    ozon_good = (len(after_by_sku) == len(ozon_after)
                 and set(after_by_sku) == expected_skus
                 and all(str(after_by_sku[x["sku"]].get("product_id") or "") == x["product_id"]
                         for x in expected_by_offer.values()))
    state["ozon"]["bindings_after"] = {
        "count": len(ozon_after),
        "status_counts": dict(collections.Counter(str(x.get("product_status_code") or "unknown")
                                                    for x in ozon_after)),
        "expected_count": len(expected_skus),
        "all_expected_skus_present": set(after_by_sku) == expected_skus,
        "new_target_skus_with_matching_product_ids": sum(
            1 for x in expected_by_offer.values()
            if x["sku"] in after_by_sku
            and str(after_by_sku[x["sku"]].get("product_id") or "") == x["product_id"]),
    }
    if not ozon_good:
        state["state"] = "ozon_reconcile_incomplete_wb_not_submitted"
        state["finished_at_utc"] = now()
        atomic(OUT, state)
        raise RuntimeError("Ozon bindings are not fully visible; WB write intentionally not submitted")
    state["ozon"]["readback_verified"] = True
    state["state"] = "ozon_verified_wb_submitting"
    atomic(OUT, state)

    log("wb_update_prepared", cards=len(payload), request_bytes=request_bytes)
    state["wb"]["mutation"] = "prepared"
    atomic(OUT, state)
    try:
        response = client.call("wb", "/content/v2/cards/update", payload, mutation=True)
        state["wb"]["mutation"] = "accepted" if response.get("error") is False else "response_not_accepted"
        state["wb"]["mutation_response"] = response
        log("wb_update_response", response=response, cards=len(payload))
    except Exception as exc:
        state["wb"]["mutation"] = "uncertain_reconcile_without_retry"
        state["wb"]["mutation_error"] = type(exc).__name__
        log("wb_update_uncertain", error=type(exc).__name__)
    atomic(OUT, state)

    after = fetch_readback(client, wb_offers)
    report = verify_wb(wb_before, after, wb_offers)
    # WB may expose accepted metadata after an eventual-consistency delay. Re-read
    # only missing cards; a successful/uncertain update is never blindly resent.
    for attempt in range(5):
        if report["all_documents_visible"] and report["all_old_documents_preserved"] and report["all_unrelated_fields_preserved"]:
            break
        time.sleep(20)
        missing = [offer for offer in wb_offers
                   if not report["per_offer"].get(offer, {}).get("document_visible")
                   or not report["per_offer"].get(offer, {}).get("preexisting_documents_preserved")
                   or not report["per_offer"].get(offer, {}).get("unrelated_card_fields_preserved")]
        latest = fetch_readback(client, missing)
        after.update(latest)
        report = verify_wb(wb_before, after, wb_offers)

    state["wb"]["readback"] = report
    state["wb"]["visible_edges"] = sum(x["document_visible"] for x in report["per_offer"].values())
    state["wb"]["all_old_documents_preserved"] = report["all_old_documents_preserved"]
    state["wb"]["all_unrelated_fields_preserved"] = report["all_unrelated_fields_preserved"]
    state["wb"]["review_pending_or_returned_count"] = report["wb_review_pending_or_returned"]
    state["state"] = ("both_platform_links_readback_verified" if ozon_good
                       and report["all_documents_visible"] and report["all_old_documents_preserved"]
                       and report["all_unrelated_fields_preserved"] else "readback_incomplete_no_resend")
    state["finished_at_utc"] = now()
    atomic(OUT, state)
    log("finished", state=state["state"], ozon_target_count=len(offer_ids), wb_edges=state["wb"]["visible_edges"])
    print(json.dumps({
        "state": state["state"],
        "ozon_targets": len(offer_ids), "ozon_target_skus_visible": state["ozon"]["bindings_after"]["new_target_skus_with_matching_product_ids"],
        "ozon_status_counts": state["ozon"]["bindings_after"]["status_counts"],
        "wb_targets": len(wb_offers), "wb_edges_visible": state["wb"]["visible_edges"],
        "wb_review_pending_or_returned": state["wb"]["review_pending_or_returned_count"],
        "wb_old_docs_preserved": report["all_old_documents_preserved"],
        "wb_unrelated_fields_preserved": report["all_unrelated_fields_preserved"],
        "out_of_scope_skipped": len(excluded_scope),
        "ozon_tnved_conflicts_skipped": len(ozon_conflicts_in_scope),
        "local_files_deleted": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
