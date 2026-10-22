#!/usr/bin/env python3
"""Bind only three exact, already WB-valid Feron DLT offers to Ozon record 87126/22."""
from __future__ import annotations
import collections
import hashlib
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

PREFLIGHT = HERE / "feron_87126_missing_ozon_preflight_20261022.json"
STATE = HERE / "feron_87126_missing_ozon_execution_20261022.json"
JOURNAL = HERE / "feron_87126_missing_ozon_journal_20261022.jsonl"
NUMBER = "ЕАЭС N RU Д-CN.РА02.В.87126/22"
CERTIFICATE_ID = 5610114
OFFERS = ["29771-1", "29772-1", "32441-1"]
ALLOWED_TNVED = {"9405190015", "9405190029", "9405190039"}
ISSUE, EXPIRY = "2022-04-05", "2027-04-03"


def save(path: pathlib.Path, data: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def log(row: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()


def values(row: dict, attr_id: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(x.get("value") or "").strip()
            for x in (attrs.get(str(attr_id)) or {}).get("values") or []
            if str(x.get("value") or "").strip()]


def wb_codes(card: dict) -> list[str]:
    out = []
    for item in card.get("characteristics") or []:
        key = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in key and "тнвед" not in key:
            continue
        raw = item.get("value")
        out.extend(str(v or "").split(" - ", 1)[0].strip()
                   for v in (raw if isinstance(raw, list) else [raw]) if v)
    return sorted(set(out))


def main() -> None:
    if STATE.exists() or JOURNAL.exists():
        raise RuntimeError("execution_artifacts_exist_reconcile_before_retry")
    pre = json.loads(PREFLIGHT.read_text())
    if (pre.get("read_only") is not True or pre.get("number") != NUMBER
            or [x.get("offer_id") for x in pre.get("targets", [])] != OFFERS
            or pre.get("all_ozon_bindings_missing") is not True
            or pre.get("all_wb_documents_already_valid") is not True):
        raise RuntimeError("preflight_gate_failed")
    c = Client()

    # Refresh the precise three products and their scope before mutation.
    products = c.call("ozon", "/v3/product/info/list", {"offer_id": OFFERS}).get("items") or []
    attrs = c.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": OFFERS}, "limit": len(OFFERS)
    }).get("result") or []
    if len(products) != len(OFFERS) or len(attrs) != len(OFFERS):
        raise RuntimeError("fresh_ozon_products_incomplete")
    pm = {str(x.get("offer_id") or ""): x for x in products}
    am = {str(x.get("offer_id") or ""): x for x in attrs}
    targets = {str(x["offer_id"]): x for x in pre["targets"]}
    if set(pm) != set(OFFERS) or set(am) != set(OFFERS):
        raise RuntimeError("fresh_ozon_offer_set_changed")
    for offer in OFFERS:
        p, a, t = pm[offer], am[offer], targets[offer]
        brand = values(a, 85)
        tnved = sorted({str(v).split(" - ", 1)[0].strip() for v in values(a, 22232)})
        if (p.get("is_archived") is not False
                or str(p.get("product_id") or p.get("id") or "") != str(t["product_id"])
                or str(p.get("sku") or "") != str(t["sku"])
                or brand != ["Feron"] or t["model"] not in str(p.get("name") or "")
                or not tnved or not set(tnved) <= ALLOWED_TNVED):
            raise RuntimeError("fresh_ozon_identity_or_scope_changed:" + offer)

    records = []
    for page in range(1, 101):
        result = c.call("ozon", "/v1/product/certificate/list", {
            "page": page, "page_size": 100
        }).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("fresh_ozon_certificate_list_incomplete")
        records.extend(batch)
        if page >= int(result.get("page_count") or 0):
            break
    else:
        raise RuntimeError("ozon_certificate_pages_exceeded")
    exact = [x for x in records
             if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(exact) != 1:
        raise RuntimeError("fresh_ozon_exact_record_count_changed")
    cert = exact[0]
    if (str(cert.get("certificate_id")) != str(CERTIFICATE_ID)
            or cert.get("status_code") != "approved"
            or cert.get("type_code") != "declaration"
            or cert.get("accordance_type_code") != "EAEU"
            or str(cert.get("issue_date", ""))[:10] != ISSUE
            or str(cert.get("expire_date", ""))[:10] != EXPIRY):
        raise RuntimeError("fresh_ozon_record_metadata_changed")

    bindings = c.ozon_bindings(CERTIFICATE_ID)
    by_pid = {str(x.get("product_id")): x for x in bindings}
    if len(by_pid) != len(bindings):
        raise RuntimeError("duplicate_live_ozon_bindings")
    missing = []
    for offer in OFFERS:
        t = targets[offer]
        found = by_pid.get(str(t["product_id"]))
        if found:
            if str(found.get("sku")) != str(t["sku"]):
                raise RuntimeError("ozon_binding_identity_conflict:" + offer)
            raise RuntimeError("ozon_target_already_bound_reconcile:" + offer)
        missing.append(t["sku"])
        cards = c.wb_cards(offer)
        if len(cards) != 1:
            raise RuntimeError("fresh_wb_card_count_changed:" + offer)
        card = cards[0]
        docs = ((card.get("documents") or {}).get("items") or [])
        same = [d for d in docs if norm_number(d.get("number")) == norm_number(NUMBER)]
        valid = [d for d in same if int(d.get("type") or 0) == 2
                 and str(d.get("startDate", ""))[:10] == ISSUE
                 and str(d.get("endDate", ""))[:10] == EXPIRY
                 and d.get("verdict", {}).get("verified") is True
                 and d.get("verdict", {}).get("status") == 1
                 and d.get("verdict", {}).get("reason") == "valid"]
        if (str(card.get("nmID")) != t["wb_nmID"] or str(card.get("vendorCode")) != offer
                or str(card.get("brand") or "").strip().casefold() != "feron"
                or t["model"] not in str(card.get("title") or "")
                or wb_codes(card) != t["ozon_tnved"] or len(same) != 1 or len(valid) != 1):
            raise RuntimeError("fresh_wb_valid_document_or_scope_changed:" + offer)

    payload = {"certificate_id": CERTIFICATE_ID, "skus": sorted(missing)}
    payload_raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    entry = {"at_utc": now(), "phase": "prepared", "platform": "ozon",
             "endpoint": "/v1/product/certificate/bind", "offers": OFFERS,
             "skus": sorted(missing), "request_sha256": hashlib.sha256(payload_raw).hexdigest()}
    state = {"started_at_utc": now(), "phase": "preflight_verified",
             "number": NUMBER, "certificate_id": CERTIFICATE_ID,
             "fsa_record_id": pre["fsa_record_id"], "target_offers": OFFERS,
             "target_product_ids": [targets[x]["product_id"] for x in OFFERS],
             "target_skus": sorted(missing), "wb_already_valid_count": 3,
             "wb_write_needed": False, "ozon_bind_sent": False,
             "wb_review_left_to_marketplace": True, "local_source_pdf_deleted": False}
    save(STATE, state)
    log(entry)
    state.update(phase="ozon_binding_in_progress", ozon_bind_sent=True, updated_at_utc=now())
    save(STATE, state)
    response = c.call("ozon", "/v1/product/certificate/bind", payload, mutation=True)
    log({**entry, "phase": "response", "response": response, "finished_at_utc": now()})
    if response.get("result") is not True:
        state.update(phase="ozon_bind_not_accepted", response=response)
        save(STATE, state)
        raise RuntimeError("ozon_bind_not_accepted")

    live = []
    for attempt in range(1, 9):
        rows = c.ozon_bindings(CERTIFICATE_ID)
        by_pid = {str(x.get("product_id")): x for x in rows}
        live = []
        for offer in OFFERS:
            t = targets[offer]
            b = by_pid.get(str(t["product_id"]))
            if not b or str(b.get("sku")) != str(t["sku"]):
                live.append({"offer_id": offer, "product_id": t["product_id"],
                             "sku": t["sku"], "bound": False, "status": None})
            else:
                live.append({"offer_id": offer, "product_id": t["product_id"],
                             "sku": t["sku"], "bound": True,
                             "status": b.get("product_status_code")})
        if all(x["bound"] and x["status"] == "approved" for x in live):
            break
        if attempt < 8:
            time.sleep(5)
    verification = {
        "checked_at_utc": now(), "number": NUMBER,
        "certificate_id": CERTIFICATE_ID, "ozon_record_status": cert.get("status_code"),
        "ozon_targets": live, "exact_bindings_visible": all(x["bound"] for x in live),
        "all_bindings_approved": all(x["bound"] and x["status"] == "approved" for x in live),
        "wb_valid_documents_preexisting": True, "wb_write_needed": False,
        "wb_review_left_to_marketplace": True, "local_source_pdf_deleted": False,
    }
    save(HERE / "feron_87126_missing_ozon_readback_20261022.json", verification)
    state.update(phase="finished_verified_readback" if verification["exact_bindings_visible"] else "binding_readback_incomplete",
                 completed_at_utc=verification["checked_at_utc"], verification=verification)
    save(STATE, state)
    print(json.dumps({"phase": state["phase"], "readback": verification,
                      "state": str(STATE), "wb_write_needed": False,
                      "local_source_pdf_deleted": False}, ensure_ascii=False, indent=2))
    if not verification["exact_bindings_visible"]:
        raise RuntimeError("exact_binding_readback_incomplete; do not repeat mutation")


if __name__ == "__main__":
    main()
