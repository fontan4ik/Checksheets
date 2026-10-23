#!/usr/bin/env python3
"""Read-only live preflight for four newly uncovered Jazzway 06273/22 links."""
from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
from execute_navigator_nll_08110_06643_20261022 import list_certificates  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

OUT = HERE / "jazzway_06273_additional_four_preflight_20261023.json"
ASSIGNMENTS = HERE / "all_confirmed_source_assignments_live_resume_20261023.csv"
SOURCE = ROOT / "output_to_user/certificates/group_2/JAZZWAY/documents/certificate_3ffcd63e2e.pdf"
SOURCE_SHA256 = "9007863e6987077a3770cdbf657813b39b0b6bb65d051bf8201a87c7aa6002ec"
NUMBER = "ЕАЭС RU С-HK.АБ53.В.06273/22"
CERTIFICATE_ID = 5949024
ISSUE = "2022-11-29"
EXPIRY = "2027-11-28"
ALLOWED_TNVED = {"8539520001", "8539520002", "8539520003", "8539520009"}
TARGETS = {
    "2859259-3": {"product_id": "538672925", "sku": "1020800523", "nmID": "489285350"},
    "2859259-5": {"product_id": "538672965", "sku": "1020800512", "nmID": "489285351"},
    "2859280-3": {"product_id": "538672988", "sku": "1020800357", "nmID": "489285352"},
    "2859280-5": {"product_id": "538673046", "sku": "1020800171", "nmID": "489285353"},
}


def digest(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_ozon(client: Client, offers: list[str]) -> dict[str, dict]:
    products, attributes = [], []
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        products.extend(client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or [])
        attributes.extend(client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)}).get("result") or [])
    pmap: dict[str, list[dict]] = collections.defaultdict(list)
    amap: dict[str, list[dict]] = collections.defaultdict(list)
    for row in products:
        pmap[str(row.get("offer_id"))].append(row)
    for row in attributes:
        amap[str(row.get("offer_id"))].append(row)
    out = {}
    for offer in offers:
        if len(pmap[offer]) != 1 or len(amap[offer]) != 1:
            raise RuntimeError("ozon_product_or_attribute_row_count_conflict:" + offer)
        p, a = pmap[offer][0], amap[offer][0]
        attrs = {str(x.get("id")): x for x in a.get("attributes") or []}
        def vals(aid: str) -> list[str]:
            return [str(v.get("value") or "").strip() for v in (attrs.get(aid) or {}).get("values") or []
                    if str(v.get("value") or "").strip()]
        tnved = sorted({x.split(" - ", 1)[0].strip() for x in vals("22232")})
        brands = vals("85")
        out[offer] = {"product_id": str(p.get("product_id") or p.get("id") or ""),
                      "sku": str(p.get("sku") or ""), "name": p.get("name"),
                      "is_archived": p.get("is_archived"), "brands": brands, "tnved": tnved,
                      "identity_matches_assignment": str(p.get("product_id") or p.get("id") or "") == TARGETS[offer]["product_id"]
                        and str(p.get("sku") or "") == TARGETS[offer]["sku"],
                      "brand_match": "jazzway" in str(p.get("name") or "").casefold()
                        and (not brands or all("jazzway" in b.casefold() for b in brands)),
                      "scope_match": bool(tnved) and set(tnved) <= ALLOWED_TNVED
                        and "pled" in str(p.get("name") or "").casefold()}
    return out


def main() -> None:
    source_hash = digest(SOURCE) if SOURCE.is_file() else None
    if source_hash != SOURCE_SHA256:
        raise RuntimeError("original_pdf_missing_or_hash_mismatch")
    client = Client()
    offers = list(TARGETS)
    ozon_products = fetch_ozon(client, offers)
    records = [x for x in list_certificates(client)
               if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(records) != 1:
        raise RuntimeError("ozon_certificate_record_count_conflict:" + str(len(records)))
    record = records[0]
    if (int(record.get("certificate_id") or 0) != CERTIFICATE_ID
            or record.get("type_code") != "certificate_of_conformity"
            or record.get("status_code") != "approved"
            or str(record.get("issue_date") or "")[:10] != ISSUE
            or str(record.get("expire_date") or "")[:10] != EXPIRY):
        raise RuntimeError("ozon_certificate_record_metadata_conflict")
    bindings = client.ozon_bindings(CERTIFICATE_ID)
    by_pid: dict[str, list[dict]] = collections.defaultdict(list)
    for row in bindings:
        by_pid[str(row.get("product_id") or "")].append(row)
    ozon_rows = []
    for offer in offers:
        product = ozon_products[offer]
        found = by_pid.get(TARGETS[offer]["product_id"], [])
        exact = [x for x in found if str(x.get("sku") or "") == TARGETS[offer]["sku"]]
        if len(exact) > 1 or (found and not exact):
            raise RuntimeError("ozon_binding_identity_conflict:" + offer)
        ozon_rows.append({"offer_id": offer, **product, "existing_exact_binding_count": len(exact),
                          "existing_statuses": [str(x.get("product_status_code") or "") for x in exact]})
    wb_rows = []
    wanted_number = norm_number(NUMBER)
    for offer in offers:
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            raise RuntimeError("wb_card_count_conflict:" + offer + ":" + str(len(cards)))
        card = cards[0]
        if (str(card.get("vendorCode")) != offer or str(card.get("nmID")) != TARGETS[offer]["nmID"]
                or str(card.get("brand") or "").strip().casefold() != "jazzway"):
            raise RuntimeError("wb_card_identity_conflict:" + offer)
        tnv = sorted({str(v).split(" - ", 1)[0].strip()
                      for x in card.get("characteristics") or []
                      if "тнвэд" in str(x.get("name") or "").casefold().replace("ё", "е")
                      for v in (x.get("value") if isinstance(x.get("value"), list) else [x.get("value")]) if v})
        docs = (card.get("documents") or {}).get("items") or []
        same = [x for x in docs if norm_number(x.get("number")) == wanted_number]
        exact = [x for x in same if int(x.get("type") or 0) == 1
                 and str(x.get("startDate") or "")[:10] == ISSUE
                 and str(x.get("endDate") or "")[:10] == EXPIRY
                 and x.get("isEndless") is False]
        verdicts = [x.get("verdict") for x in exact]
        valid = (len(exact) == 1 and len(same) == 1 and isinstance(verdicts[0], dict)
                 and verdicts[0].get("verified") is True and verdicts[0].get("reason") == "valid")
        if not tnv or not set(tnv) <= ALLOWED_TNVED or not valid:
            raise RuntimeError("wb_scope_or_document_not_valid:" + offer)
        wb_rows.append({"offer_id": offer, "nmID": str(card.get("nmID")), "tnved": tnv,
                        "existing_exact_certificate_count": len(exact), "verdict": verdicts[0]})

    no_bindings = [x for x in ozon_rows if x["existing_exact_binding_count"] == 0]
    ozon_failures = []
    for row in ozon_rows:
        problems = []
        if not row["identity_matches_assignment"]:
            problems.append("product_id_or_sku_changed")
        if not row["brand_match"]:
            problems.append("brand_mismatch")
        if not row["scope_match"]:
            problems.append("tnved_or_model_out_of_scope")
        if row["is_archived"] is not False:
            problems.append("product_not_confirmed_active")
        if row["existing_exact_binding_count"] != 0:
            problems.append("binding_state_changed_since_gap_audit")
        if problems:
            ozon_failures.append({"offer_id": row["offer_id"], "problems": problems,
                                  "name": row["name"], "tnved": row["tnved"],
                                  "brands": row["brands"], "is_archived": row["is_archived"]})
    safe = len(no_bindings) == 4 and not ozon_failures

    result = {"checked_at_utc": now(), "read_only": True, "document_number": NUMBER,
              "certificate_id": CERTIFICATE_ID, "record_status": record.get("status_code"),
              "type_code": record.get("type_code"), "issue_date": ISSUE, "expire_date": EXPIRY,
              "source_pdf": str(SOURCE), "source_sha256": source_hash,
              "official_manufacturer_source": "https://jazz-way.com/docs/sertifikaty/lampy-svetodiodnye-ss-tr-ts-004-020-28.11.2027.pdf",
              "fsa_public_page_status": "not independently read in this run; marketplace record is approved",
              "existing_ozon_binding_rows": len(bindings), "target_count": 4,
              "ozon_targets": ozon_rows, "wb_targets": wb_rows,
              "all_safe_to_bind_ozon": safe, "ozon_scope_failures": ozon_failures,
              "wb_already_exact_valid": 4,
              "no_mutations": True}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"checked_at_utc": result["checked_at_utc"], "record_status": result["record_status"],
                      "existing_binding_rows": len(bindings), "ozon_missing_targets": len(no_bindings),
                      "all_four_live_scope_checks_pass": safe, "wb_valid": 4,
                      "ozon_failures": ozon_failures,
                      "report": str(OUT)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
