#!/usr/bin/env python3
"""Attach Gauss declaration 48971/24 to exact in-scope Ozon and WB offers."""
from __future__ import annotations

import base64
import collections
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import norm_number, wb_datetime
from run_all_found_certificates_20261014 import merge_wb

PREFLIGHT = HERE / "gauss_48971_crossplatform_preflight_20261023.json"
STATE = HERE / "gauss_48971_execution_20261023.json"
JOURNAL = HERE / "gauss_48971_mutation_journal_20261023.jsonl"
WB_BEFORE = HERE / "gauss_48971_wb_before_20261023.json"
READBACK = HERE / "gauss_48971_crossplatform_readback_20261023.json"
NUMBER = "ЕАЭС N RU Д-CN.РА08.В.48971/24"
ISSUE, EXPIRY = "2024-09-18", "2029-09-17"
FSA_ID = "19381489"
SOURCE = "output_to_user/certificates/group_1/documents/gauss/22073e3d9c4580581bbf9d92.pdf"
SOURCE_SHA = "81173faa80fa3b88c9ddf83ccc980fbb2448bce7e370df17424991f19e3ab9d7"
TNVED = {"8539519009"}


def save(path: Path, obj: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def log(obj: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at_utc": now(), **obj}, ensure_ascii=False) + "\n")
        stream.flush()


def values(attrs, ident):
    by_id = {str(x.get("id")): x for x in attrs or []}
    return [str(v.get("value") or "").strip()
            for v in (by_id.get(str(ident)) or {}).get("values") or []
            if str(v.get("value") or "").strip()]


def codes(raw):
    if not isinstance(raw, list):
        raw = [raw]
    return sorted({str(x).split(" - ", 1)[0].strip() for x in raw if str(x).strip()})


def wb_codes(card):
    out = []
    for ch in card.get("characteristics") or []:
        label = "".join(str(ch.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" in label or "тнвед" in label:
            val = ch.get("value")
            out.extend(val if isinstance(val, list) else [val])
    return codes(out)


def all_ozon_records(client):
    out = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_invalid")
        out.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return out
    raise RuntimeError("ozon_certificate_page_limit")


def matching_records(client):
    return [r for r in all_ozon_records(client)
            if norm_number(r.get("certificate_number")) == norm_number(NUMBER)]


def fresh_targets(client, preflight):
    rows = preflight["targets"]
    offers = [x["offer_id"] for x in rows]
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items") or []
    attrs = client.call("ozon", "/v4/product/info/attributes",
                        {"filter": {"offer_id": offers}, "limit": len(offers)}).get("result") or []
    pm = collections.defaultdict(list)
    am = collections.defaultdict(list)
    for x in products:
        pm[str(x.get("offer_id") or "")].append(x)
    for x in attrs:
        am[str(x.get("offer_id") or "")].append(x)
    ozon, wb = {}, {}
    for row in rows:
        offer = row["offer_id"]
        if len(pm[offer]) != 1 or len(am[offer]) != 1:
            raise RuntimeError("ozon_identity_missing_or_ambiguous:" + offer)
        p, a = pm[offer][0], am[offer][0]
        pid, sku = str(p.get("product_id") or p.get("id") or ""), str(p.get("sku") or "")
        brand = values(a.get("attributes"), 85)
        tnved = codes(values(a.get("attributes"), 22232))
        if (pid != str(row["ozon"]["product_id"]) or sku != str(row["ozon"]["sku"])
                or p.get("is_archived") is not False or [x.casefold() for x in brand] != ["gauss"]
                or not tnved or not set(tnved).issubset(TNVED)
                or p.get("name") != row["ozon"]["title"]):
            raise RuntimeError("ozon_identity_brand_or_scope_changed:" + offer)
        ozon[offer] = {"product_id": pid, "sku": sku, "brand": brand, "tnved": tnved,
                       "title": p.get("name")}

        cards = [c for c in client.wb_cards(offer) if str(c.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            raise RuntimeError("wb_card_missing_or_ambiguous:" + offer)
        card = cards[0]
        if (str(card.get("nmID") or "") != str(row["wb"]["nmID"])
                or str(card.get("brand") or "").casefold() != "gauss"
                or str(card.get("title") or "") != str(row["wb"]["title"])
                or not wb_codes(card) or not set(wb_codes(card)).issubset(TNVED)):
            raise RuntimeError("wb_identity_brand_or_scope_changed:" + offer)
        wb[offer] = card
    if len(ozon) != 26 or len(wb) != 26:
        raise RuntimeError("fresh_target_count_changed")
    return ozon, wb


def ozon_upload_and_bind(client, state, targets):
    matches = matching_records(client)
    if len(matches) > 1:
        raise RuntimeError("duplicate_ozon_document_records")
    record = matches[0] if matches else None
    create_response = None
    if record and (record.get("type_code") != "declaration"
                   or str(record.get("issue_date") or "")[:10] != ISSUE
                   or str(record.get("expire_date") or "")[:10] != EXPIRY):
        raise RuntimeError("existing_ozon_record_metadata_conflict")
    if record is None:
        source = ROOT / SOURCE
        expiry = dt.date.fromisoformat(EXPIRY)
        payload = {"params": {
            "name": "Декларация о соответствии № " + NUMBER,
            "certificate_type": "DECLARATION",
            "certificate_country": "RU",
            "accordance_type": "EAEU",
            "number": NUMBER,
            "issue_date": ISSUE + "T00:00:00Z",
            "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
            "skus": [targets[o]["sku"] for o in sorted(targets)],
            "product_type": "UNKNOWN",
            "files": [{"file_content": base64.b64encode(source.read_bytes()).decode("ascii"),
                       "name": source.name}],
            "link_to_registry": "https://pub.fsa.gov.ru/rds/declaration/view/" + FSA_ID,
        }}
        request_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
        if request_bytes > 15_000_000:
            raise RuntimeError("ozon_create_payload_exceeds_safe_limit")
        state["ozon_create_phase"] = "prepared_no_retry_after_uncertain"
        state["ozon_create_request_bytes"] = request_bytes
        save(STATE, state)
        log({"phase": "ozon_create_prepared", "request_bytes": request_bytes,
             "target_count": len(targets),
             "request_sha256": hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()})
        try:
            create_response = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
            log({"phase": "ozon_create_response", "status": create_response.get("status"),
                 "certificate_id": create_response.get("certificate_id"),
                 "params": create_response.get("params")})
        except Exception as exc:
            log({"phase": "ozon_create_uncertain", "error_type": type(exc).__name__})
        matches = matching_records(client)
        if len(matches) != 1:
            return {"outcome": "create_not_visible_no_retry", "record_count": len(matches),
                    "create_response": create_response}
        record = matches[0]
        if (record.get("type_code") != "declaration"
                or str(record.get("issue_date") or "")[:10] != ISSUE
                or str(record.get("expire_date") or "")[:10] != EXPIRY):
            raise RuntimeError("created_ozon_record_metadata_conflict")

    if record.get("status_code") in {"declined", "rejected", "invalid", "cancelled"}:
        return {"outcome": "record_declined_no_bind", "record": record}
    cid = int(record["certificate_id"])
    bindings = client.ozon_bindings(cid)
    by_pid = collections.defaultdict(list)
    for b in bindings:
        by_pid[str(b.get("product_id") or "")].append(b)
    missing_skus = []
    for offer, target in targets.items():
        prior = by_pid.get(target["product_id"], [])
        if prior and (len(prior) != 1 or str(prior[0].get("sku") or "") != target["sku"]):
            raise RuntimeError("ozon_existing_binding_conflict:" + offer)
        if not prior:
            missing_skus.append(target["sku"])
    bind_response = None
    if missing_skus:
        body = {"certificate_id": cid, "skus": missing_skus}
        state["ozon_bind_phase"] = "prepared_no_retry_after_uncertain"
        save(STATE, state)
        log({"phase": "ozon_bind_prepared", "certificate_id": cid,
             "request_sha256": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
             "sku_count": len(missing_skus)})
        try:
            bind_response = client.call("ozon", "/v1/product/certificate/bind", body, mutation=True)
            log({"phase": "ozon_bind_response", "response": bind_response})
        except Exception as exc:
            log({"phase": "ozon_bind_uncertain", "error_type": type(exc).__name__})
    after = client.ozon_bindings(cid)
    rows = []
    for offer, target in sorted(targets.items()):
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
    doc = pre.get("document") or {}
    if (pre.get("read_only") is not True or doc.get("fsa_registry_id") != FSA_ID
            or doc.get("type_code") != "declaration" or doc.get("number") != NUMBER
            or doc.get("fsa_status_from_live_ui") != "Действует"
            or pre.get("summary", {}).get("eligible_both_platforms") != 26):
        raise RuntimeError("preflight_wrong_document_status_or_scope")
    source = ROOT / SOURCE
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA:
        raise RuntimeError("source_hash_changed")
    client = Client()
    ozon_targets, wb_cards = fresh_targets(client, pre)
    matches = matching_records(client)
    if len(matches) > 1:
        raise RuntimeError("duplicate_ozon_records_before_mutation")

    wb_updates, wb_before_rows = [], []
    wb_desired = {o: {"type": 2, "number": NUMBER, "startDate": wb_datetime(ISSUE),
                      "endDate": wb_datetime(EXPIRY), "isEndless": False} for o in wb_cards}
    for offer, card in wb_cards.items():
        existing = ((card.get("documents") or {}).get("items") or [])
        same = [x for x in existing if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in same if str(x.get("type")) == "2"
                 and str(x.get("startDate") or "")[:10] == ISSUE
                 and str(x.get("endDate") or "")[:10] == EXPIRY
                 and x.get("isEndless") is False]
        if same and len(exact) != 1:
            raise RuntimeError("wb_document_metadata_conflict:" + offer)
        update = merge_wb(card, [wb_desired[offer]])
        if update:
            wb_updates.append(update)
        wb_before_rows.append({"offer_id": offer, "nmID": str(card.get("nmID")),
                               "same_number_count": len(same), "exact_count": len(exact),
                               "prior_document_count": len(existing)})

    save(WB_BEFORE, {"checked_at_utc": now(), "read_only": True,
                     "cards": wb_before_rows, "full_cards": list(wb_cards.values())})
    state = {"started_at_utc": now(), "phase": "fresh_prewrite_verified", "document_number": NUMBER,
             "document_type": "declaration", "fsa_registry_id": FSA_ID, "fsa_status": "Действует",
             "issue_date": ISSUE, "expiry_date": EXPIRY, "source_sha256": SOURCE_SHA,
             "ozon_target_offers": sorted(ozon_targets), "wb_target_offers": sorted(wb_cards),
             "wb_review_left_to_marketplace": True, "local_file_deleted": False, "mutations": []}
    save(STATE, state)

    ozon_result = ozon_upload_and_bind(client, state, ozon_targets)
    state["ozon_result"] = ozon_result
    state["mutations"].append({"platform": "Ozon", "outcome": ozon_result.get("outcome"),
                               "exact_bindings_present": ozon_result.get("all_exact_bindings_present")})
    save(STATE, state)

    wb_result = {"attempted": False, "requested_cards": len(wb_updates)}
    if wb_updates:
        marker = hashlib.sha256(json.dumps(wb_updates, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        state["wb_update_phase"] = "prepared_no_retry_after_uncertain"
        state["wb_update_request_sha256"] = marker
        save(STATE, state)
        log({"phase": "wb_update_prepared", "request_sha256": marker, "card_count": len(wb_updates)})
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

    current_records = matching_records(client)
    ozon_rows, record_summary = [], None
    if len(current_records) == 1:
        record = current_records[0]
        record_summary = {k: record.get(k) for k in
                          ["certificate_id", "certificate_number", "type_code", "status_code", "issue_date", "expire_date"]}
        all_bindings = client.ozon_bindings(int(record["certificate_id"]))
        for offer, target in sorted(ozon_targets.items()):
            exact = [b for b in all_bindings if str(b.get("product_id") or "") == target["product_id"]
                     and str(b.get("sku") or "") == target["sku"]]
            ozon_rows.append({"offer_id": offer, "product_id": target["product_id"], "sku": target["sku"],
                              "exact_binding_count": len(exact),
                              "binding_status": exact[0].get("product_status_code") if len(exact) == 1 else None})
    wb_rows = []
    for offer in sorted(wb_cards):
        fresh = [c for c in client.wb_cards(offer) if str(c.get("vendorCode") or "") == offer]
        if len(fresh) != 1:
            wb_rows.append({"offer_id": offer, "exact_metadata_count": 0, "verdicts": [],
                            "readback_error": "card_not_unique"})
            continue
        card = fresh[0]
        docs = ((card.get("documents") or {}).get("items") or [])
        exact = [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)
                 and str(x.get("type")) == "2" and str(x.get("startDate") or "")[:10] == ISSUE
                 and str(x.get("endDate") or "")[:10] == EXPIRY and x.get("isEndless") is False]
        prior_count = len(((wb_cards[offer].get("documents") or {}).get("items") or []))
        wb_rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                        "exact_metadata_count": len(exact),
                        "verdicts": [x.get("verdict") for x in exact],
                        "prior_documents_preserved": len(docs) >= prior_count})
    readback = {"checked_at_utc": now(), "read_only": True, "document_number": NUMBER,
                "ozon_record": record_summary, "ozon_bindings": ozon_rows, "wb_cards": wb_rows,
                "wb_review_left_to_marketplace": True, "local_file_deleted": False,
                "sample_date_limitation": "Declaration applies to serial products manufactured from samples dated 2024-05-15; marketplace data does not expose individual lot manufacture dates."}
    save(READBACK, readback)
    state["readback_file"] = READBACK.name
    state["phase"] = "readback_complete"
    save(STATE, state)
    print(json.dumps({"ozon_record_status": (record_summary or {}).get("status_code"),
                      "ozon_exact_bindings": sum(x["exact_binding_count"] == 1 for x in ozon_rows),
                      "ozon_binding_rows": len(ozon_rows),
                      "ozon_binding_statuses": dict(collections.Counter(str(x.get("binding_status")) for x in ozon_rows)),
                      "wb_exact_metadata": sum(x["exact_metadata_count"] == 1 for x in wb_rows),
                      "wb_cards": len(wb_rows),
                      "wb_verdicts": dict(collections.Counter(str(v.get("reason", "unknown"))
                          for x in wb_rows for v in x.get("verdicts", []) if isinstance(v, dict))),
                      "local_file_deleted": False, "sample_date_limitation": readback["sample_date_limitation"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
