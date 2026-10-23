#!/usr/bin/env python3
"""Upload/bind Faza 037 declaration to exact in-scope Ozon and WB offers."""
from __future__ import annotations

import base64
import collections
import csv
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import norm_number, wb_datetime
from run_all_found_certificates_20261014 import merge_wb

PREFLIGHT = HERE / "faza_12063_crossplatform_preflight_v2_20261023.json"
STATE = HERE / "faza_12063_execution_20261023.json"
JOURNAL = HERE / "faza_12063_mutation_journal_20261023.jsonl"
WB_BEFORE = HERE / "faza_12063_wb_before_20261023.json"
READBACK = HERE / "faza_12063_crossplatform_readback_20261023.json"
NUMBER = "ЕАЭС N RU Д-HK.РА02.В.12063/23"
ISSUE, EXPIRY = "2023-03-01", "2028-02-29"
SOURCE = "output_to_user/certificates/additional_search/brand_research/faza/followup_2026_10_02_suppliers/docs/037_battery_12063_23_manufacturer.pdf"
SOURCE_SHA = "2d8f4e6125dc8a1a4fc96787d5c4a9fc3842c5b13b41ca780543415d0259fc5e"
WB_ALLOWED_BRANDS = {"jazzway", "faza", "фаза", "фаzа"}


def save(path: Path, obj: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def log(obj: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at_utc": now(), **obj}, ensure_ascii=False) + "\n")
        stream.flush()


def values(attrs, ident):
    mapping = {str(x.get("id")): x for x in attrs or []}
    return [str(v.get("value") or "").strip() for v in (mapping.get(str(ident)) or {}).get("values") or []
            if str(v.get("value") or "").strip()]


def codes(raw):
    if not isinstance(raw, list): raw = [raw]
    return sorted({str(x).split(" - ", 1)[0].strip() for x in raw if str(x).strip()})


def wb_codes(card):
    out = []
    for c in card.get("characteristics") or []:
        label = "".join(str(c.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" in label or "тнвед" in label:
            raw = c.get("value")
            out.extend(raw if isinstance(raw, list) else [raw])
    return codes(out)


def all_ozon_records(client):
    out = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list): raise RuntimeError("ozon_certificate_list_invalid")
        out.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0): return out
    raise RuntimeError("ozon_certificate_page_limit")


def matching_record(client):
    return [r for r in all_ozon_records(client)
            if norm_number(r.get("certificate_number")) == norm_number(NUMBER)]


def verified_targets(client, preflight):
    rows = preflight["targets"]
    offers = [x["offer_id"] for x in rows]
    fresh_products = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items") or []
    fresh_attrs = client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": offers}, "limit": len(offers)}).get("result") or []
    pm, am = {str(x.get("offer_id")): x for x in fresh_products}, {str(x.get("offer_id")): x for x in fresh_attrs}
    ozon_eligible, wb_cards, ozon_all = [], {}, {}
    for item in rows:
        offer = item["offer_id"]
        p, a = pm.get(offer) or {}, am.get(offer) or {}
        pid = str(p.get("product_id") or p.get("id") or "")
        sku = str(p.get("sku") or "")
        brand = values(a.get("attributes"), 85)
        tnved = codes(values(a.get("attributes"), 22232))
        if (pid != str(item["ozon"]["product_id"]) or sku != str(item["ozon"]["sku"])
                or p.get("is_archived") is not False or [x.casefold() for x in brand] != ["фазa"]
                or p.get("name") != item["ozon"]["title"]):
            # Ozon's brand value uses a Latin "z" in the account catalog.
            if not (pid == str(item["ozon"]["product_id"]) and sku == str(item["ozon"]["sku"])
                    and p.get("is_archived") is False and brand == ["Фаzа"]
                    and p.get("name") == item["ozon"]["title"]):
                raise RuntimeError("ozon_target_identity_changed:" + offer)
        current = {**item["ozon"], "product_id": pid, "sku": sku, "brand": brand, "tnved": tnved}
        ozon_all[offer] = current
        if tnved and set(tnved).issubset({"8513100000"}):
            if item["conflicts"]:
                raise RuntimeError("eligible_ozon_target_has_preflight_conflict:" + offer)
            ozon_eligible.append(offer)
        elif "ozon_tnved_out_of_scope" not in item["conflicts"]:
            raise RuntimeError("unexpected_ozon_tnved_or_conflict:" + offer)

        cards = [c for c in client.wb_cards(offer) if str(c.get("vendorCode") or "") == offer]
        if len(cards) != 1: raise RuntimeError("wb_card_missing_or_ambiguous:" + offer)
        card = cards[0]
        if (str(card.get("nmID") or "") != str(item["wb"]["nmID"])
                or str(card.get("brand") or "").casefold() not in WB_ALLOWED_BRANDS
                or str(card.get("title") or "") != str(item["wb"]["title"])
                or not set(wb_codes(card)).issubset({"8513100000"})):
            raise RuntimeError("wb_target_identity_or_scope_changed:" + offer)
        wb_cards[offer] = card
    if len(ozon_eligible) != 7 or len(wb_cards) != 11:
        raise RuntimeError("fresh_eligible_target_count_changed")
    return ozon_all, ozon_eligible, wb_cards


def ozon_upload_bind(client, state, targets):
    matches = matching_record(client)
    if len(matches) > 1: raise RuntimeError("duplicate_ozon_document_records")
    create_response = None
    record = matches[0] if matches else None
    if record and (record.get("type_code") != "declaration"
            or str(record.get("issue_date") or "")[:10] != ISSUE
            or str(record.get("expire_date") or "")[:10] != EXPIRY):
        raise RuntimeError("existing_ozon_record_metadata_conflict")
    if record is None:
        expiry = dt.date.fromisoformat(EXPIRY)
        source_path = ROOT / SOURCE
        payload = {"params": {
            "name": "Декларация о соответствии № " + NUMBER,
            "certificate_type": "DECLARATION",
            "certificate_country": "RU",
            "accordance_type": "EAEU",
            "number": NUMBER,
            "issue_date": ISSUE + "T00:00:00Z",
            "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
            "skus": [targets[o]["sku"] for o in targets],
            "product_type": "UNKNOWN",
            "files": [{"file_content": base64.b64encode(source_path.read_bytes()).decode("ascii"),
                       "name": source_path.name}],
        }}
        if len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()) > 9_500_000:
            return {"outcome": "skipped_payload_too_large", "number": NUMBER}
        req_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        log({"phase": "ozon_create_prepared", "request_sha256": req_hash, "target_count": len(targets)})
        state["ozon_create_phase"] = "prepared_no_retry_after_uncertain"
        save(STATE, state)
        try:
            create_response = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
            log({"phase": "ozon_create_response", "status": create_response.get("status"),
                 "params": create_response.get("params")})
        except Exception as exc:
            log({"phase": "ozon_create_uncertain", "error_type": type(exc).__name__})
        matches = matching_record(client)
        if len(matches) != 1:
            return {"outcome": "create_not_visible_no_retry", "record_count": len(matches), "create_response": create_response}
        record = matches[0]
        if (record.get("type_code") != "declaration"
                or str(record.get("issue_date") or "")[:10] != ISSUE
                or str(record.get("expire_date") or "")[:10] != EXPIRY):
            raise RuntimeError("created_ozon_record_metadata_conflict")

    if record.get("status_code") in {"declined", "rejected", "invalid", "cancelled"}:
        return {"outcome": "record_declined_no_bind", "record": record}
    cid = int(record["certificate_id"])
    bindings = client.ozon_bindings(cid)
    by_product = collections.defaultdict(list)
    for b in bindings: by_product[str(b.get("product_id") or "")].append(b)
    need_bind = []
    for offer, target in targets.items():
        prior = by_product.get(target["product_id"], [])
        if prior and (len(prior) != 1 or str(prior[0].get("sku") or "") != target["sku"]):
            raise RuntimeError("ozon_existing_binding_conflict:" + offer)
        if not prior: need_bind.append(target["sku"])
    bind_response = None
    if need_bind:
        body = {"certificate_id": cid, "skus": need_bind}
        req_hash = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        log({"phase": "ozon_bind_prepared", "certificate_id": cid, "request_sha256": req_hash,
             "sku_count": len(need_bind)})
        state["ozon_bind_phase"] = "prepared_no_retry_after_uncertain"
        save(STATE, state)
        try:
            bind_response = client.call("ozon", "/v1/product/certificate/bind", body, mutation=True)
            log({"phase": "ozon_bind_response", "response": bind_response})
        except Exception as exc:
            log({"phase": "ozon_bind_uncertain", "error_type": type(exc).__name__})
    after = client.ozon_bindings(cid)
    rows = []
    for offer, target in targets.items():
        exact = [b for b in after if str(b.get("product_id") or "") == target["product_id"]
                 and str(b.get("sku") or "") == target["sku"]]
        rows.append({"offer_id": offer, "product_id": target["product_id"], "sku": target["sku"],
                     "exact_binding_count": len(exact),
                     "binding_status": exact[0].get("product_status_code") if len(exact) == 1 else None})
    return {"outcome": "record_visible_readback_complete", "record": record,
            "create_response": create_response, "bind_response": bind_response, "bindings": rows,
            "all_exact_bindings_present": all(x["exact_binding_count"] == 1 for x in rows)}


def main():
    if any(p.exists() for p in (STATE, JOURNAL, WB_BEFORE, READBACK)):
        raise RuntimeError("execution_artifact_exists_reconcile_before_retry")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if pre.get("read_only") is not True or pre.get("document", {}).get("fsa_registry_id") != "17493213":
        raise RuntimeError("preflight_wrong_document_or_not_read_only")
    if pre.get("document", {}).get("fsa_status_from_live_ui") != "Действует":
        raise RuntimeError("fsa_document_not_currently_active")
    source_path = ROOT / SOURCE
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != SOURCE_SHA:
        raise RuntimeError("source_hash_changed")
    if pre.get("summary", {}).get("eligible_both_platforms") != 7:
        raise RuntimeError("expected_preflight_eligibility_changed")
    client = Client()
    ozon_all, ozon_offers, wb_cards = verified_targets(client, pre)
    eligible_targets = {o: ozon_all[o] for o in ozon_offers}
    matches = matching_record(client)
    if len(matches) > 1: raise RuntimeError("duplicate_ozon_document_records_before_mutation")

    wb_desired = {o: {"type": 2, "number": NUMBER, "startDate": wb_datetime(ISSUE),
                      "endDate": wb_datetime(EXPIRY), "isEndless": False} for o in wb_cards}
    wb_updates = []
    wb_before_rows = []
    for offer, card in wb_cards.items():
        existing = ((card.get("documents") or {}).get("items") or [])
        same = [x for x in existing if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in same if str(x.get("type")) == "2"
                 and str(x.get("startDate") or "")[:10] == ISSUE
                 and str(x.get("endDate") or "")[:10] == EXPIRY and x.get("isEndless") is False]
        if same and len(exact) != 1: raise RuntimeError("wb_number_metadata_conflict:" + offer)
        update = merge_wb(card, [wb_desired[offer]])
        if update: wb_updates.append(update)
        wb_before_rows.append({"offer_id": offer, "nmID": str(card.get("nmID")),
                               "brand": card.get("brand"), "same_number": len(same), "exact": len(exact),
                               "documents_preserved": len(existing)})
    save(WB_BEFORE, {"checked_at_utc": now(), "read_only": True, "cards": wb_before_rows,
                     "full_cards": list(wb_cards.values())})
    state = {"started_at_utc": now(), "phase": "fresh_prewrite_verified", "document_number": NUMBER,
             "fsa_registry_id": "17493213", "fsa_status": "Действует", "source_sha256": SOURCE_SHA,
             "ozon_target_offers": ozon_offers, "ozon_skipped_tnved_offers": sorted(set(ozon_all) - set(ozon_offers)),
             "wb_target_offers": sorted(wb_cards), "wb_review_left_to_marketplace": True,
             "local_file_deleted": False, "mutations": []}
    save(STATE, state)

    ozon_result = ozon_upload_bind(client, state, eligible_targets)
    state["ozon_result"] = ozon_result
    state["mutations"].append({"platform": "Ozon", "outcome": ozon_result.get("outcome"),
                               "exact_bindings_present": ozon_result.get("all_exact_bindings_present")})
    save(STATE, state)

    wb_result = {"attempted": False, "request_count": len(wb_updates), "rows": []}
    if wb_updates:
        marker = hashlib.sha256(json.dumps(wb_updates, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        log({"phase": "wb_update_prepared", "request_sha256": marker, "card_count": len(wb_updates)})
        state["wb_update_phase"] = "prepared_no_retry_after_uncertain"
        state["wb_update_request_sha256"] = marker
        save(STATE, state)
        try:
            response = client.call("wb", "/content/v2/cards/update", wb_updates, mutation=True)
            wb_result.update({"attempted": True, "response": response})
            log({"phase": "wb_update_response", "response": response})
        except Exception as exc:
            wb_result.update({"attempted": True, "error_type": type(exc).__name__})
            log({"phase": "wb_update_uncertain", "error_type": type(exc).__name__})
    else:
        wb_result["already_exact_count"] = len(wb_cards)
    state["wb_result"] = wb_result
    state["mutations"].append({"platform": "WB", "attempted": wb_result["attempted"],
                               "requested_cards": len(wb_updates)})
    save(STATE, state)

    ozon_records_now = matching_record(client)
    if len(ozon_records_now) == 1:
        cid = int(ozon_records_now[0]["certificate_id"])
        all_bindings = client.ozon_bindings(cid)
        ozon_rows = []
        for offer in sorted(eligible_targets):
            t = eligible_targets[offer]
            exact = [b for b in all_bindings if str(b.get("product_id") or "") == t["product_id"]
                     and str(b.get("sku") or "") == t["sku"]]
            ozon_rows.append({"offer_id": offer, "product_id": t["product_id"], "sku": t["sku"],
                              "exact_binding_count": len(exact),
                              "binding_status": exact[0].get("product_status_code") if len(exact) == 1 else None})
        record_summary = {k: ozon_records_now[0].get(k) for k in
                          ["certificate_id", "certificate_number", "type_code", "status_code", "issue_date", "expire_date"]}
    else:
        ozon_rows, record_summary = [], None
    wb_rows = []
    for offer in sorted(wb_cards):
        fresh = [c for c in client.wb_cards(offer) if str(c.get("vendorCode") or "") == offer]
        if len(fresh) != 1:
            wb_rows.append({"offer_id": offer, "nmID": None, "exact_metadata_count": 0, "verdicts": [], "readback_error": "card_not_unique"})
            continue
        card = fresh[0]
        docs = ((card.get("documents") or {}).get("items") or [])
        exact = [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)
                 and str(x.get("type")) == "2" and str(x.get("startDate") or "")[:10] == ISSUE
                 and str(x.get("endDate") or "")[:10] == EXPIRY and x.get("isEndless") is False]
        wb_rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                        "exact_metadata_count": len(exact),
                        "verdicts": [x.get("verdict") for x in exact],
                        "prior_documents_preserved": len(docs) >= len(((wb_cards[offer].get("documents") or {}).get("items") or []))})
    readback = {"checked_at_utc": now(), "read_only": True, "document_number": NUMBER,
                "ozon_record": record_summary, "ozon_bindings": ozon_rows,
                "wb_cards": wb_rows, "wb_review_left_to_marketplace": True,
                "local_file_deleted": False}
    save(READBACK, readback)
    state["readback_file"] = READBACK.name
    state["phase"] = "readback_complete"
    state["local_file_deleted"] = False
    save(STATE, state)
    print(json.dumps({"ozon_record_status": (record_summary or {}).get("status_code"),
                      "ozon_exact_bindings": sum(x["exact_binding_count"] == 1 for x in ozon_rows),
                      "ozon_bindings_total": len(ozon_rows),
                      "wb_exact_metadata": sum(x["exact_metadata_count"] == 1 for x in wb_rows),
                      "wb_cards_total": len(wb_rows),
                      "wb_verdicts": dict(collections.Counter(v.get("reason", "unknown") for x in wb_rows for v in x.get("verdicts", []) if isinstance(v, dict))),
                      "local_file_deleted": False,
                      "ozon_skipped_out_of_scope": state["ozon_skipped_tnved_offers"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
