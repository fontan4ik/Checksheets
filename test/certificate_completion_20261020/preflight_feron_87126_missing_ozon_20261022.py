#!/usr/bin/env python3
"""Fresh, read-only gate for three already WB-valid Feron DLT offers."""
from __future__ import annotations
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА02.В.87126/22"
CERTIFICATE_ID = 5610114
FSA_RECORD_ID = 16650422
OFFERS = ["29771-1", "29772-1", "32441-1"]
ALLOWED_TNVED = {"9405190015", "9405190029", "9405190039"}
ISSUE, EXPIRY = "2022-04-05", "2027-04-03"
OUT = HERE / "feron_87126_missing_ozon_preflight_20261022.json"


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
    if OUT.exists():
        raise RuntimeError("preflight_exists_review_before_retry")
    c = Client()
    ps = c.call("ozon", "/v3/product/info/list", {"offer_id": OFFERS}).get("items") or []
    ats = c.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": OFFERS}, "limit": len(OFFERS)
    }).get("result") or []
    if len(ps) != len(OFFERS) or len(ats) != len(OFFERS):
        raise RuntimeError("ozon_target_snapshot_incomplete")
    pm = {str(x.get("offer_id") or ""): x for x in ps}
    am = {str(x.get("offer_id") or ""): x for x in ats}
    if set(pm) != set(OFFERS) or set(am) != set(OFFERS):
        raise RuntimeError("ozon_offer_identity_set_changed")

    records = []
    for page in range(1, 101):
        result = c.call("ozon", "/v1/product/certificate/list", {
            "page": page, "page_size": 100
        }).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        records.extend(batch)
        if page >= int(result.get("page_count") or 0):
            break
    else:
        raise RuntimeError("ozon_certificate_pages_exceeded")
    exact = [x for x in records
             if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(exact) != 1:
        raise RuntimeError("ozon_exact_record_count:" + str(len(exact)))
    cert = exact[0]
    if (str(cert.get("certificate_id")) != str(CERTIFICATE_ID)
            or cert.get("type_code") != "declaration"
            or cert.get("accordance_type_code") != "EAEU"
            or cert.get("status_code") != "approved"
            or str(cert.get("issue_date", ""))[:10] != ISSUE
            or str(cert.get("expire_date", ""))[:10] != EXPIRY):
        raise RuntimeError("ozon_current_record_status_or_metadata_changed")
    bindings = c.ozon_bindings(CERTIFICATE_ID)
    by_pid = {str(x.get("product_id")): x for x in bindings}

    targets = []
    for offer in OFFERS:
        p, a = pm[offer], am[offer]
        pid, sku = str(p.get("product_id") or p.get("id") or ""), str(p.get("sku") or "")
        brands = values(a, 85)
        names = str(p.get("name") or "")
        tnv = sorted({str(v).split(" - ", 1)[0].strip() for v in values(a, 22232)})
        model = next((m for m in ("DLT201", "DLT202", "DLT203") if m in names), None)
        if (p.get("is_archived") is not False or brands != ["Feron"]
                or model is None or not tnv or not set(tnv) <= ALLOWED_TNVED or not pid or not sku):
            raise RuntimeError("ozon_product_brand_model_or_tnved_out_of_scope:" + offer)
        prior = by_pid.get(pid)
        if prior:
            if str(prior.get("sku")) != sku:
                raise RuntimeError("ozon_existing_binding_identity_conflict:" + offer)
            raise RuntimeError("ozon_target_binding_already_present_reconcile:" + offer)
        cards = c.wb_cards(offer)
        if len(cards) != 1:
            raise RuntimeError("wb_exact_card_count:" + offer + ":" + str(len(cards)))
        card = cards[0]
        same = [d for d in (((card.get("documents") or {}).get("items")) or [])
                if norm_number(d.get("number")) == norm_number(NUMBER)]
        valid = [d for d in same if int(d.get("type") or 0) == 2
                 and str(d.get("startDate", ""))[:10] == ISSUE
                 and str(d.get("endDate", ""))[:10] == EXPIRY
                 and d.get("verdict", {}).get("verified") is True
                 and d.get("verdict", {}).get("status") == 1
                 and d.get("verdict", {}).get("reason") == "valid"]
        if (str(card.get("vendorCode") or "") != offer
                or str(card.get("brand") or "").strip().casefold() != "feron"
                or model not in str(card.get("title") or "")
                or wb_codes(card) != tnv or len(same) != 1 or len(valid) != 1):
            raise RuntimeError("wb_identity_scope_or_valid_doc_check_failed:" + offer)
        targets.append({"offer_id": offer, "product_id": pid, "sku": sku,
                        "product_name": names, "model": model, "brand": brands,
                        "ozon_tnved": tnv, "wb_nmID": str(card.get("nmID")),
                        "wb_title": card.get("title"), "wb_tnved": wb_codes(card),
                        "wb_existing_valid_document": valid[0],
                        "wb_card": card})

    out = {
        "checked_at_utc": now(), "read_only": True,
        "number": cert.get("certificate_number"), "ozon_certificate": {
            k: cert.get(k) for k in ("certificate_id", "certificate_number", "type_code",
                "accordance_type_code", "status_code", "issue_date", "expire_date", "products_count")},
        "fsa_record_id": FSA_RECORD_ID,
        "fsa_record_url": f"https://pub.fsa.gov.ru/rds/declaration/view/{FSA_RECORD_ID}/common",
        "fsa_status_last_checked_utc": "2026-10-12T06:49:40.537270+00:00",
        "source_scope": "Feron embedded luminaires series CD, GS-M, DL, DLT; EAEU TN VED 9405190015/0029/0039; TR EAEU 037/2016. FSA end date 2027-04-03; signed scan differs by one day, so use the existing approved marketplace/FSA record dates.",
        "targets": targets, "all_ozon_bindings_missing": True,
        "all_wb_documents_already_valid": True, "wb_write_needed": False,
        "local_source_pdf_deleted": False,
    }
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(OUT)
    print(json.dumps({"checked_at_utc": out["checked_at_utc"], "number": out["number"],
        "ozon_certificate": out["ozon_certificate"],
        "targets": [{k: t[k] for k in ("offer_id", "product_id", "sku", "model", "ozon_tnved", "wb_nmID")} for t in targets],
        "all_wb_documents_already_valid": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
