"""Fresh read-only verification of Arlight 46747/26 across Ozon and WB."""
from __future__ import annotations

import collections
import csv
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import copy_documents, doc_key, norm_number  # noqa: E402

SHA = "2fc3790ce4644d8e1c4150df3d1efdb2a06361442dc916e9c288c48fa7363d5c"
NUMBER = "ЕАЭС RU С-CN.АЯ46.В.46747/26"
ISSUE = "2026-03-23"
EXPIRY = "2031-03-22"
TNVED = "8504408300"
CERTIFICATE_ID = 5445163
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
OZON_SNAPSHOT = HERE / "all_found_ozon_products_snapshot_20261014.json"
OUT = HERE / "arlight_46747_crossplatform_live_recheck_20261021.json"


def wb_tnved(card: dict) -> list[str]:
    out = []
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        out.extend(str(v or "").split(" - ", 1)[0].strip()
                   for v in (raw if isinstance(raw, list) else [raw]) if v)
    return sorted(set(out))


def main() -> None:
    if OUT.exists():
        raise RuntimeError("recheck_output_exists")
    assignments = []
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if str(row.get("SHA256 фактический") or "").lower() == SHA:
                assignments.append(row)
    confirmed = [r for r in assignments if r.get("Применимость") == "Подтверждено статусом покрытия"]
    candidates = [r for r in assignments if r.get("Применимость") != "Подтверждено статусом покрытия"]
    offers = sorted({str(r.get("Артикул продавца") or "") for r in confirmed})
    if len(confirmed) != 114 or len(offers) != 114 or len(candidates) != 1:
        raise RuntimeError("source_assignment_counts_changed")
    snap = json.loads(OZON_SNAPSHOT.read_text(encoding="utf-8"))
    snap_products = {str(p.get("offer_id") or ""): p for p in snap.get("products") or []}
    if any(o not in snap_products for o in offers):
        raise RuntimeError("source_offer_missing_from_current_snapshot")
    ids = {str(snap_products[o].get("product_id") or snap_products[o].get("id") or "") for o in offers}
    if "" in ids or len(ids) != 114:
        raise RuntimeError("snapshot_product_identity_not_unique")

    client = Client()
    records = []
    page = 1
    pages = 1
    seen = set()
    while page <= pages:
        body = client.call("ozon", "/v1/product/certificate/list", {
            "page": page, "page_size": 100
        }).get("result") or {}
        batch = body.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        for row in batch:
            cid = int(row.get("certificate_id") or 0)
            if not cid or cid in seen:
                raise RuntimeError("ozon_certificate_id_missing_or_duplicate")
            seen.add(cid)
        records.extend(batch)
        pages = int(body.get("page_count") or page)
        page += 1
    record = next((r for r in records if int(r.get("certificate_id") or 0) == CERTIFICATE_ID), None)
    if not record or norm_number(record.get("certificate_number")) != norm_number(NUMBER):
        raise RuntimeError("ozon_certificate_record_missing_or_changed")
    if record.get("status_code") != "approved":
        raise RuntimeError("ozon_certificate_record_not_approved")
    bindings = client.ozon_bindings(CERTIFICATE_ID)
    if len(bindings) != int(record.get("products_count") or 0):
        raise RuntimeError("ozon_binding_count_mismatch")
    bind_by_id = {}
    for item in bindings:
        pid = str(item.get("product_id") or "")
        if not pid or pid in bind_by_id:
            raise RuntimeError("ozon_binding_product_id_missing_or_duplicate")
        bind_by_id[pid] = item

    detail_by_id = {}
    id_list = sorted(ids)
    for offset in range(0, len(id_list), 500):
        batch_ids = id_list[offset:offset + 500]
        rows = client.call("ozon", "/v3/product/info/list", {
            "product_id": [int(x) for x in batch_ids]
        }).get("items")
        if not isinstance(rows, list):
            raise RuntimeError("ozon_product_details_missing")
        for row in rows:
            pid = str(row.get("product_id") or row.get("id") or "")
            if pid not in batch_ids or pid in detail_by_id:
                raise RuntimeError("ozon_detail_identity_mismatch")
            detail_by_id[pid] = row
    if set(detail_by_id) != ids:
        raise RuntimeError("ozon_product_details_incomplete")

    ozon_rows = []
    for offer in offers:
        old = snap_products[offer]
        pid = str(old.get("product_id") or old.get("id") or "")
        detail = detail_by_id[pid]
        link = bind_by_id.get(pid)
        okay = (str(detail.get("offer_id") or "") == offer
                and str(detail.get("product_id") or detail.get("id") or "") == pid
                and str(detail.get("sku") or "") == str(old.get("sku") or "")
                and link is not None and str(link.get("sku") or "") == str(detail.get("sku") or ""))
        ozon_rows.append({"offer_id": offer, "product_id": pid, "sku": str(detail.get("sku") or ""),
                          "binding_status": link.get("product_status_code") if link else None,
                          "identity_matches": okay, "product_name": detail.get("name") or detail.get("name_ru")})
    if not all(r["identity_matches"] for r in ozon_rows):
        raise RuntimeError("ozon_live_target_binding_identity_incomplete")

    wb_rows = []
    for idx, offer in enumerate(offers, 1):
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            wb_rows.append({"offer_id": offer, "card_count": len(cards), "exact_document": False,
                            "reason": "missing_or_ambiguous_card"})
            continue
        card = cards[0]
        docs = copy_documents(card)
        same = [d for d in docs if norm_number(d.get("number")) == norm_number(NUMBER)]
        exact = [d for d in same if doc_key(d) == (1, norm_number(NUMBER))
                 and str(d.get("startDate", ""))[:10] == ISSUE
                 and str(d.get("endDate", ""))[:10] == EXPIRY
                 and d.get("isEndless") is False]
        wb_rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                        "brand": card.get("brand"), "tnved_codes": wb_tnved(card),
                        "exact_document_count": len(exact), "same_number_count": len(same),
                        "exact_document": len(exact) == 1,
                        "verdict": exact[0].get("verdict") if len(exact) == 1 else None})
        if idx % 50 == 0:
            print(json.dumps({"phase": "fresh_wb_recheck", "checked": idx,
                              "target_cards": len(offers)}, ensure_ascii=False), flush=True)

    doc_stats = collections.Counter("exact" if x.get("exact_document") else x.get("reason", "missing")
                                    for x in wb_rows)
    verdicts = collections.Counter((x.get("verdict") or {}).get("reason") or "no_verdict"
                                   for x in wb_rows if x.get("exact_document"))
    result = {"checked_at": now(), "read_only": True, "number": NUMBER,
              "certificate_id": CERTIFICATE_ID, "ozon_document_status": record.get("status_code"),
              "ozon_record_products_count": record.get("products_count"),
              "ozon_binding_count": len(bindings),
              "ozon_binding_status_counts": dict(collections.Counter(x.get("product_status_code") for x in bindings)),
              "source_assignment_count": len(assignments), "confirmed_source_offers": len(offers),
              "source_candidate_offers": [r.get("Артикул продавца") for r in candidates],
              "sample_date_cutoff_from_original_pdf": "2026-01",
              "wb_target_cards_checked": len(wb_rows), "wb_document_counts": dict(doc_stats),
              "wb_verdict_counts": dict(verdicts), "ozon_targets": ozon_rows,
              "wb_targets": wb_rows, "local_file_deleted": False,
              "manual_wb_review_action_taken": False}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("checked_at", "ozon_document_status",
                  "ozon_record_products_count", "ozon_binding_status_counts",
                  "confirmed_source_offers", "source_candidate_offers", "wb_target_cards_checked",
                  "wb_document_counts", "wb_verdict_counts", "local_file_deleted")},
                  ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
