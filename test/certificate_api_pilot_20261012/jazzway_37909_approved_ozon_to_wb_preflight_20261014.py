"""Freshly verify only Jazzway bindings approved by Ozon before WB writes."""
from __future__ import annotations

import collections
import datetime as dt
import json
from pathlib import Path

from api_client import Client, now

BASE_DIR = Path(__file__).resolve().parent
SOURCE = BASE_DIR / "jazzway_37909_in_scope_ozon_mutation_preflight_20261014.json"
OUT = BASE_DIR / "jazzway_37909_approved_ozon_to_wb_preflight_20261014.json"
CERTIFICATE_ID = 5458891
CERTIFICATE_NUMBER = "ЕАЭС N RU Д-HK.РА08.В.37909/22"
TNVED_CODE = "8539520009"


def attr_values(item: dict, attribute_id: str) -> list[str]:
    for attr in item.get("attributes") or []:
        if str(attr.get("id")) == attribute_id:
            return [str(v.get("value")) for v in attr.get("values") or []
                    if v.get("value") not in (None, "")]
    return []


def read_record(client: Client) -> dict:
    found = []
    page = 1
    while True:
        result = client.call("ozon", "/v1/product/certificate/list", {
            "page": page, "page_size": 100})["result"]
        found.extend(c for c in result.get("certificates") or []
                     if str(c.get("certificate_id")) == str(CERTIFICATE_ID))
        if page >= int(result.get("page_count") or 0):
            break
        page += 1
    if len(found) != 1:
        raise RuntimeError("Current Ozon record is absent or ambiguous")
    c = found[0]
    if (c.get("certificate_number") != CERTIFICATE_NUMBER or c.get("type_code") != "declaration"
            or c.get("accordance_type_code") != "EAEU" or c.get("status_code") != "approved"
            or str(c.get("expire_date") or "")[:10] < dt.datetime.now(dt.timezone.utc).date().isoformat()):
        raise RuntimeError("Current Ozon declaration is no longer approved/current or exact")
    return c


def main() -> None:
    source = json.loads(SOURCE.read_text())
    targets = source["targets"]
    if len(targets) != 158:
        raise RuntimeError("Expected the previously verified 158 in-scope targets")
    client = Client()
    record = read_record(client)
    bindings = client.ozon_bindings(CERTIFICATE_ID)
    binding_by_id = {str(b.get("product_id")): b for b in bindings}
    if len(binding_by_id) != len(bindings):
        raise RuntimeError("Duplicate current Ozon binding Product IDs")
    statuses = collections.Counter((binding_by_id.get(str(t["product_id"])) or {}).get("product_status_code", "missing")
                                   for t in targets)
    approved = []
    declined = []
    blocked = []
    for t in targets:
        b = binding_by_id.get(str(t["product_id"]))
        status = (b or {}).get("product_status_code")
        if not b or str(b.get("sku") or "") != str(t["sku"]):
            blocked.append({**t, "reason": "live_binding_missing_or_sku_mismatch", "status": status})
        elif status == "approved":
            approved.append(t)
        elif status == "declined":
            declined.append({**t, "reason": "ozon_binding_declined"})
        else:
            blocked.append({**t, "reason": "ozon_binding_not_final", "status": status})

    if blocked:
        raise RuntimeError(f"{len(blocked)} targets have missing/ambiguous or non-final status; investigate before WB")
    product_ids = [int(x["product_id"]) for x in approved]
    details = client.call("ozon", "/v3/product/info/list", {"product_id": product_ids}).get("items")
    if not isinstance(details, list) or len(details) != len(approved):
        raise RuntimeError("Fresh product info read for approved targets is incomplete")
    details_by_id = {str(p.get("product_id") or p.get("id") or ""): p for p in details}
    if len(details_by_id) != len(details):
        raise RuntimeError("Fresh product info read has duplicate/missing IDs")
    offers = [x["offer_id"] for x in approved]
    attr_result = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": offers}, "limit": len(offers)}).get("result")
    if not isinstance(attr_result, list) or len(attr_result) != len(approved):
        raise RuntimeError("Fresh attribute read for approved targets is incomplete")
    attrs_by_offer = {str(a.get("offer_id") or ""): a for a in attr_result}
    if set(attrs_by_offer) != set(offers):
        raise RuntimeError("Fresh attribute read has missing/extra offers")
    verified = []
    for target in approved:
        detail = details_by_id.get(str(target["product_id"]))
        attr = attrs_by_offer[target["offer_id"]]
        if (not detail or str(detail.get("offer_id") or "") != target["offer_id"]
                or str(detail.get("sku") or "") != str(target["sku"])
                or detail.get("is_archived") is not False
                or str(attr.get("id") or attr.get("product_id") or "") != str(target["product_id"])):
            raise RuntimeError(f"Fresh exact product identity/status mismatch for {target['offer_id']}")
        brands = attr_values(attr, "85")
        tnv = attr_values(attr, "22232")
        codes = sorted({v.split(" - ", 1)[0].strip() for v in tnv})
        if brands != ["Jazzway"] or codes != [TNVED_CODE]:
            raise RuntimeError(f"Fresh brand/TNVED scope mismatch for {target['offer_id']}")
        verified.append({**target, "live_brand": brands[0], "live_tnved": codes[0],
                         "ozon_binding_status": "approved", "live_archived": False})

    out = {
        "checked_at": now(), "certificate": record, "certificate_id": CERTIFICATE_ID,
        "certificate_number": CERTIFICATE_NUMBER, "status_counts_all_in_scope_targets": dict(statuses),
        "approved_targets": len(verified), "declined_targets": len(declined),
        "blocked_targets": len(blocked), "wb_candidates": verified,
        "ozon_declined_skipped": declined,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({"checked_at": out["checked_at"], "status_counts": dict(statuses),
                      "wb_candidates": len(verified), "declined_skipped": len(declined),
                      "output": OUT.name}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
