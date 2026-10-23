#!/usr/bin/env python3
"""Read-only exact scope/link audit for two already-approved IEK EAEU declarations."""
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

MANIFEST = HERE / "expanded_found_certificates_manifest_20261020.json"
OUTPUT = HERE / "iek_66629_71483_live_link_audit_20261023.json"


def attr_values(row: dict, attr_id: str) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(x.get("value") or "").strip()
            for x in (attrs.get(attr_id) or {}).get("values") or []]


def tnved(values: list[str]) -> set[str]:
    return {str(v).split(" - ", 1)[0].strip() for v in values if str(v).strip()}


def list_certificates(client: Client) -> list[dict]:
    rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_page_incomplete")
        rows.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("ozon_certificate_page_limit")


def wb_doc_status(card: dict, group: dict) -> tuple[dict | None, str]:
    wanted_key = norm_number(group["number"])
    rows = [x for x in ((card.get("documents") or {}).get("items") or [])
            if norm_number(x.get("number")) == wanted_key]
    exact = [x for x in rows if str(x.get("type")) == "2"
             and str(x.get("startDate") or "")[:10] == group["issue_date"]
             and str(x.get("endDate") or "")[:10] == group["expire_date"]
             and x.get("isEndless") is False]
    if len(rows) > 1 or (rows and len(exact) != 1):
        return None, "same_number_conflict"
    if not exact:
        return None, "missing"
    doc = exact[0]
    verdict = doc.get("verdict") or {}
    reason = str(verdict.get("reason") or verdict.get("status") or "pending_or_missing")
    if verdict.get("verified") is True or reason.casefold() == "valid":
        reason = "valid"
    return doc, reason


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    wanted_numbers = {"66629/26", "71483/26"}
    groups = [g for g in manifest.get("groups", [])
              if any(s in str(g.get("number")) for s in wanted_numbers)]
    if len(groups) != 2:
        raise RuntimeError("expected_two_manifest_groups")
    client = Client()
    certs = list_certificates(client)
    results = []
    for group in groups:
        number_key = norm_number(group["number"])
        records = [c for c in certs
                   if norm_number(c.get("certificate_number")) == number_key]
        target_rows = group.get("targets") or []
        expected = {str(t["offer_id"]): t for t in target_rows}
        if len(expected) != len(target_rows):
            raise RuntimeError("duplicate_manifest_offers:" + group["number"])
        matched = [c for c in records if c.get("type_code") == group["type_code"]
                   and c.get("accordance_type_code") == "EAEU"
                   and str(c.get("issue_date") or "")[:10] == group["issue_date"]
                   and str(c.get("expire_date") or "")[:10] == group["expire_date"]]
        cert = matched[0] if len(matched) == 1 else None
        ozon = []
        if cert:
            bindings = client.ozon_bindings(cert["certificate_id"])
            by_pid = {str(x.get("product_id") or ""): x for x in bindings}
            if len(by_pid) != len(bindings):
                raise RuntimeError("duplicate_ozon_binding_product_id")
            offers = sorted(expected)
            products, attributes = {}, {}
            for start in range(0, len(offers), 100):
                batch = offers[start:start + 100]
                ps = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items")
                ats = client.call("ozon", "/v4/product/info/attributes",
                                  {"filter": {"offer_id": batch}, "limit": len(batch)}).get("result")
                if not isinstance(ps, list) or not isinstance(ats, list):
                    raise RuntimeError("ozon_target_info_incomplete")
                products.update({str(x.get("offer_id")): x for x in ps})
                attributes.update({str(x.get("offer_id")): x for x in ats})
            for offer, target in expected.items():
                p = products.get(offer) or {}
                a = attributes.get(offer) or {}
                pid = str(p.get("product_id") or p.get("id") or "")
                sku = str(p.get("sku") or "")
                brand = attr_values(a, "85")
                codes = tnved(attr_values(a, "22232"))
                binding = by_pid.get(pid)
                ozon.append({"offer_id": offer, "product_id": pid, "sku": sku,
                             "identity_matches": p.get("is_archived") is False
                             and pid == str(target["product_id"]) and sku == str(target["sku"]),
                             "brand_values": brand, "brand_matches": brand == [target.get("brand", "IEK")],
                             "tnved_codes": sorted(codes),
                             "tnved_in_scope": codes == set(map(str, group.get("allowed_tnved") or [])),
                             "binding_exact": bool(binding and sku == str(target["sku"])),
                             "binding_status": (binding or {}).get("product_status_code")})
        wb = []
        for offer, target in expected.items():
            cards = [x for x in client.wb_cards(offer)
                     if str(x.get("vendorCode") or "") == offer]
            if len(cards) != 1:
                wb.append({"offer_id": offer, "card_count": len(cards), "exact_metadata": False,
                           "verdict": "missing_or_duplicate_card"})
                continue
            card = cards[0]
            doc, verdict = wb_doc_status(card, group)
            values = tnved([str(value) for ch in card.get("characteristics") or []
                            if "тнвэд" in "".join(str(ch.get("name") or "").casefold().split()).replace("ё", "е")
                            or "тнвед" in "".join(str(ch.get("name") or "").casefold().split()).replace("ё", "е")
                            for value in (ch.get("value") if isinstance(ch.get("value"), list)
                                          else [ch.get("value")])])
            wb.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                       "brand": card.get("brand"), "brand_matches": card.get("brand") == target.get("brand", "IEK"),
                       "tnved_codes": sorted(values),
                       "tnved_in_scope": not values or values == set(map(str, group.get("allowed_tnved") or [])),
                       "exact_metadata": doc is not None, "verdict": verdict})
        results.append({
            "number": group["number"], "type_code": group["type_code"],
            "issue_date": group["issue_date"], "expire_date": group["expire_date"],
            "target_count": len(expected), "record_matches": len(matched),
            "record_id": (cert or {}).get("certificate_id"),
            "record_status": (cert or {}).get("status_code"),
            "all_record_numbers_found": len(records),
            "ozon_target_identity_exact": sum(x["identity_matches"] for x in ozon),
            "ozon_scope_exact": sum(x["brand_matches"] and x["tnved_in_scope"] for x in ozon),
            "ozon_binding_exact": sum(x["binding_exact"] for x in ozon),
            "ozon_binding_status_counts": dict(collections.Counter(
                str(x.get("binding_status") or "missing") for x in ozon)),
            "wb_exact_metadata": sum(x["exact_metadata"] for x in wb),
            "wb_verdict_counts": dict(collections.Counter(x["verdict"] for x in wb)),
            "ozon_targets": ozon, "wb_targets": wb,
        })
    result = {"checked_at_utc": now(), "read_only": True, "results": results}
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"checked_at_utc": result["checked_at_utc"], "read_only": True,
                      "results": [{k: v for k, v in x.items()
                                   if k not in ("ozon_targets", "wb_targets")}
                                  for x in results]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
