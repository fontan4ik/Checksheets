#!/usr/bin/env python3
"""Read-only audit of every live Ozon binding and matching WB card for IEK docs."""
from __future__ import annotations

import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
sys.path.insert(0, str(ROOT))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

DETAIL = HERE / "iek_66629_71483_live_link_audit_20261023.json"
OUTPUT = HERE / "iek_66629_71483_all_live_record_bindings_20261023.json"


def values(row: dict, ident: str) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(x.get("value") or "").strip()
            for x in (attrs.get(ident) or {}).get("values") or []]


def codes(raw: list[str]) -> set[str]:
    return {str(x).split(" - ", 1)[0].strip() for x in raw if str(x).strip()}


def main() -> None:
    detail = json.loads(DETAIL.read_text(encoding="utf-8"))
    client = Client()
    results = []
    for audit in detail["results"]:
        cid = int(audit["record_id"])
        bindings = client.ozon_bindings(cid)
        pids = sorted({str(x.get("product_id") or "") for x in bindings})
        if not pids or "" in pids:
            raise RuntimeError("binding_product_ids_missing")
        products = {}
        for start in range(0, len(pids), 100):
            batch = pids[start:start + 100]
            rows = client.call("ozon", "/v3/product/info/list",
                               {"product_id": [int(x) for x in batch]}).get("items")
            if not isinstance(rows, list):
                raise RuntimeError("ozon_product_info_incomplete")
            for row in rows:
                products[str(row.get("product_id") or row.get("id") or "")] = row
        by_offer = {str(x.get("offer_id") or ""): x for x in products.values()}
        offer_ids = sorted(by_offer)
        attributes = {}
        for start in range(0, len(offer_ids), 100):
            batch = offer_ids[start:start + 100]
            rows = client.call("ozon", "/v4/product/info/attributes",
                               {"filter": {"offer_id": batch}, "limit": len(batch)}).get("result")
            if not isinstance(rows, list):
                raise RuntimeError("ozon_product_attributes_incomplete")
            attributes.update({str(x.get("offer_id") or ""): x for x in rows})
        bindings_by_pid = {str(x.get("product_id") or ""): x for x in bindings}
        targets = []
        for pid, p in products.items():
            offer = str(p.get("offer_id") or "")
            attr = attributes.get(offer) or {}
            binding = bindings_by_pid.get(pid) or {}
            brand = values(attr, "85")
            tnv = codes(values(attr, "22232"))
            cards = [c for c in client.wb_cards(offer)
                     if str(c.get("vendorCode") or "") == offer]
            card_result = {"count": len(cards), "exact_document": False, "verdict": "missing_or_duplicate_card"}
            if len(cards) == 1:
                card = cards[0]
                matching = [d for d in ((card.get("documents") or {}).get("items") or [])
                            if norm_number(d.get("number")) == norm_number(audit["number"])
                            and str(d.get("type")) == "2"
                            and str(d.get("startDate") or "")[:10] == audit["issue_date"]
                            and str(d.get("endDate") or "")[:10] == audit["expire_date"]
                            and d.get("isEndless") is False]
                card_result = {"count": 1, "nmID": str(card.get("nmID") or ""),
                               "exact_document": len(matching) == 1,
                               "verdict": ((matching[0].get("verdict") or {}).get("reason")
                                           or "pending_or_missing") if len(matching) == 1 else "missing_or_conflicting"}
            targets.append({"offer_id": offer, "product_id": pid, "sku": str(p.get("sku") or ""),
                            "active": p.get("is_archived") is False,
                            "brand_values": brand, "tnved_codes": sorted(tnv),
                            "binding_status": binding.get("product_status_code"),
                            "wb": card_result})
        results.append({
            "number": audit["number"], "record_id": cid, "record_status": audit["record_status"],
            "binding_count": len(bindings),
            "binding_status_counts": dict(collections.Counter(str(x.get("product_status_code") or "unknown") for x in bindings)),
            "active_bindings": sum(x["active"] for x in targets),
            "brand_iek_count": sum(x["brand_values"] == ["IEK"] for x in targets),
            "scope_tnved_count": sum(x["tnved_codes"] == ["8536201007"] for x in targets),
            "wb_exact_count": sum(x["wb"]["exact_document"] for x in targets),
            "wb_verdict_counts": dict(collections.Counter(str(x["wb"]["verdict"]) for x in targets)),
            "bindings": targets,
        })
    out = {"checked_at_utc": now(), "read_only": True, "results": results}
    OUTPUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"checked_at_utc": out["checked_at_utc"], "read_only": True,
                      "results": [{k: v for k, v in x.items() if k != "bindings"} for x in results]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
