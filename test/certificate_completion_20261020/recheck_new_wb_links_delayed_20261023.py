#!/usr/bin/env python3
"""Read-only delayed readback for marketplace certificate writes from 2026-10-23."""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client  # noqa: E402
from run_all_found_certificates_20261014 import (  # noqa: E402
    OZON_TO_WB_TYPE, comparable_card, copy_documents, doc_key, merge_wb,
    valid_dates, wb_datetime,
)

IMMEDIATE = HERE / "all_found_wb_readback_7e2263c3d25893a4.json"
PRODUCTS = HERE / "all_found_ozon_products_snapshot_20261014.json"
CERTS = HERE / "all_found_ozon_certificates_snapshot_20261014.json"
OUT = HERE / "all_found_wb_delayed_readback_20261023.json"


def main() -> None:
    immediate = json.loads(IMMEDIATE.read_text(encoding="utf-8"))
    products_doc = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    certs_doc = json.loads(CERTS.read_text(encoding="utf-8"))
    if products_doc.get("complete") is not True or certs_doc.get("complete") is not True:
        raise RuntimeError("complete_current_ozon_snapshots_required")

    products_by_sku = {str(p["sku"]): p for p in products_doc["products"] if p.get("sku")}
    desired: dict[str, list[dict]] = {}
    for cert in certs_doc["certificates"]:
        typ = OZON_TO_WB_TYPE.get(cert.get("type_code"))
        if (not typ or cert.get("accordance_type_code") != "EAEU" or
                cert.get("status_code") != "approved" or
                not valid_dates(cert.get("issue_date"), cert.get("expire_date"))):
            continue
        wanted = {
            "type": typ,
            "number": cert.get("certificate_number"),
            "startDate": wb_datetime(cert["issue_date"]),
            "endDate": wb_datetime(cert["expire_date"]),
            "isEndless": False,
        }
        for binding in cert.get("live_bindings") or []:
            product = products_by_sku.get(str(binding.get("sku") or ""))
            if (binding.get("product_status_code") != "approved" or not product or
                    str(product.get("product_id")) != str(binding.get("product_id")) or
                    not product.get("offer_id")):
                continue
            desired.setdefault(str(product["offer_id"]), []).append(wanted)

    targets = [x for x in immediate["results"] if not x.get("expected_docs_visible")]
    client = Client()
    rows = []
    for previous in targets:
        offer = str(previous["offer_id"])
        docs = desired.get(offer, [])
        fresh = client.wb_cards(offer)
        exact = len(fresh) == 1
        visible = exact and bool(docs) and merge_wb(fresh[0], docs) is None
        old_cards = previous.get("cards") or []
        preserved = exact and len(old_cards) == 1 and comparable_card(fresh[0]) == comparable_card(old_cards[0])
        prior_docs = {(doc_key(d), str(d.get("startDate", ""))[:10], str(d.get("endDate", ""))[:10])
                      for d in copy_documents(old_cards[0])} if len(old_cards) == 1 else set()
        fresh_docs = {(doc_key(d), str(d.get("startDate", ""))[:10], str(d.get("endDate", ""))[:10])
                      for d in copy_documents(fresh[0])} if exact else set()
        prior_preserved = prior_docs <= fresh_docs
        rows.append({
            "offer_id": offer,
            "submitted_in_prior_batch": previous.get("submitted") is True,
            "expected_documents": docs,
            "card_count": len(fresh),
            "expected_documents_visible": visible,
            "unrelated_fields_preserved_since_immediate_readback": preserved,
            "prior_documents_preserved": prior_preserved,
            "fresh_cards": fresh,
        })
    result = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "source_batch_checked_at": immediate.get("checked_at"),
        "target_count": len(targets),
        "visible_exact_document_count": sum(x["expected_documents_visible"] for x in rows),
        "preserved_card_count": sum(x["unrelated_fields_preserved_since_immediate_readback"] for x in rows),
        "prior_documents_preserved_count": sum(x["prior_documents_preserved"] for x in rows),
        "rows": rows,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
