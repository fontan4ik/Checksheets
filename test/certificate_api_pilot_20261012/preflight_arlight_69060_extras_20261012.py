"""Fresh read-only scope/identity check for three exact additional 69060/25 offers."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE))
from api_client import Client, now  # noqa: E402
from build_bulk_cleanup_candidates_20261012 import norm  # noqa: E402

OUT = BASE / "arlight_69060_extras_preflight_20261012.json"
LOCAL_MAP = ROOT / "test/certificate_cleanup_20261006/local_map.json"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
BASE_PLAN = BASE / "arlight_69060_preflight_20261012.json"
OZON_VERIFICATION = BASE / "arlight_69060_ozon_verification_20261012.json"
NUMBER = "ЕАЭС N RU Д-HK.РА02.В.69060/25"
CERTIFICATE_ID = 5624646
OCR_HASH = "283c1f57322d9244c0bcc0420500f27d6ede0c41603da00db51865326c550a44"
TARGETS = {
    "011750-1": {"product_id": "4021378835", "sku": "3851174714", "nmID": "946113633",
                 "model": "ARPV-LV12005", "manufacturer_url": "https://arlight.ru/catalog/product/011750/"},
    "026058(1)-1": {"product_id": "5140430749", "sku": "4773472600", "nmID": "1178002281",
                    "model": "ARJ-SP-36-PFC-TRIAC-INS", "manufacturer_url": "https://arlight.ru/catalog/product/026058-1/"},
    "029265(2)-1": {"product_id": "4021379031", "sku": "3851174775", "nmID": "946113547",
                    "model": "ARV-SN48200-SLIM-PFC-B", "manufacturer_url": "https://arlight.ru/catalog/product/029265-2/"},
}


def main() -> None:
    base_plan = json.loads(BASE_PLAN.read_text())
    base_ozon = json.loads(OZON_VERIFICATION.read_text())
    if (not base_plan.get("ready_for_ozon_create_and_binding") or len(base_plan.get("targets", [])) != 549
            or not base_ozon.get("all_bindings_confirmed") or base_ozon.get("certificate_id") != CERTIFICATE_ID):
        raise RuntimeError("The already bound 549-product declaration set is not verified")
    local_map = json.loads(LOCAL_MAP.read_text())
    group = next((x for x in local_map.get("groups", []) if x.get("sha256") == OCR_HASH), None)
    if not group:
        raise RuntimeError("Shared official Arlight declaration PDF group is missing")
    binding = {str(x.get("offer_id")): x for x in group.get("bindings", [])}
    rows = {}
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("SHA256 фактический") == OCR_HASH and row.get("Артикул продавца") in TARGETS:
                rows[row["Артикул продавца"]] = row
    if set(rows) != set(TARGETS):
        raise RuntimeError("Manufacturer assignment rows for the exact three extra offers are incomplete")
    for offer, target in TARGETS.items():
        row = rows[offer]
        if (norm(row.get("Номер/название документа")) != norm(NUMBER)
                or row.get("Бренд подтвержденный") != "Arlight" or row.get("Бренд Ozon") != "Arlight"
                or row.get("SHA256 заявленный") != OCR_HASH
                or target["model"] not in row.get("Название товара Ozon", "")
                and target["model"] not in row.get("Основание сопоставления", "")):
            raise RuntimeError(f"Exact manufacturer/model source row changed for {offer}")
        mapped = binding.get(offer) or {}
        if (mapped.get("ozon_product_ids") != [target["product_id"]]
                or mapped.get("ozon_skus") != [target["sku"]]):
            raise RuntimeError(f"Historical source crosswalk does not match expected Ozon identity: {offer}")

    client = Client()
    product_info = {}
    for offer in TARGETS:
        body = client.call("ozon", "/v3/product/info/list", {"offer_id": [offer]}).get("items") or []
        if len(body) != 1 or str(body[0].get("offer_id")) != offer:
            raise RuntimeError(f"Ozon exact product lookup is incomplete: {offer}")
        current = body[0]
        target = TARGETS[offer]
        # Ozon /v3/product/info/list exposes Product ID under `id` (there is
        # no `product_id` field in this response).
        if (str(current.get("id")) != target["product_id"] or str(current.get("sku")) != target["sku"]
                or current.get("is_archived")):
            raise RuntimeError(f"Current Ozon product identity/archive state mismatch: {offer}")
        product_info[offer] = current
    attributes = {}
    for offer in TARGETS:
        body = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": [offer]}, "limit": 1,
        }).get("result") or []
        if len(body) != 1 or str(body[0].get("offer_id")) != offer:
            raise RuntimeError(f"Ozon attribute read incomplete: {offer}")
        attrs = {str(x.get("id")): x for x in body[0].get("attributes") or []}
        def vals(aid: str) -> list[str]:
            return [str(v.get("value")) for v in (attrs.get(aid) or {}).get("values") or []
                    if v.get("value") not in (None, "")]
        brand, tnved = vals("85"), vals("22232")
        if brand != ["Arlight"] or not any(x.split(" - ", 1)[0].strip() == "8504408300" for x in tnved):
            raise RuntimeError(f"Current Ozon brand/TNVED outside declaration scope: {offer}")
        attributes[offer] = {"brand": brand, "tnved": tnved}

    info = client.call("ozon", "/v1/product/certificate/info", {
        "certificate_number": NUMBER,
    }).get("result", {})
    if (int(info.get("certificate_id", -1)) != CERTIFICATE_ID
            or str(info.get("status_code")) != "approved"
            or str(info.get("issue_date", ""))[:10] != "2025-03-10"
            or str(info.get("expire_date", ""))[:10] != "2030-03-09"):
        raise RuntimeError("Existing Ozon declaration is not approved with the expected live dates")
    bindings = client.ozon_bindings(CERTIFICATE_ID)
    by_sku = {}
    for item in bindings:
        sku = str(item.get("sku"))
        if sku in by_sku:
            raise RuntimeError("Duplicate SKU in current Ozon certificate binding list")
        by_sku[sku] = item
    new_missing = []
    for offer, target in TARGETS.items():
        live = by_sku.get(target["sku"])
        if live and str(live.get("product_id")) != target["product_id"]:
            raise RuntimeError(f"Ozon SKU already bound to a different product ID: {offer}")
        if not live:
            new_missing.append(offer)

    wb_cards = {}
    for offer, target in TARGETS.items():
        cards = client.wb_cards(offer)
        if len(cards) != 1 or str(cards[0].get("nmID")) != target["nmID"]:
            raise RuntimeError(f"WB exact card identity is not unique/current for {offer}")
        docs = (cards[0].get("documents") or {}).get("items") or []
        same = [x for x in docs if norm(x.get("number")) == norm(NUMBER)]
        if same:
            raise RuntimeError(f"WB exact declaration row already exists for {offer}; reconcile first")
        wb_cards[offer] = cards[0]

    result = {
        "checked_at": now(), "read_only": True, "number": NUMBER, "certificate_id": CERTIFICATE_ID,
        "certificate_info": info, "source_pdf_sha256": OCR_HASH,
        "source_map_bindings_verified": len(TARGETS), "manufacturer_article_pages": {
            offer: TARGETS[offer]["manufacturer_url"] for offer in TARGETS},
        "fsa_scope": {"record_id": 19978046, "status": "Действует", "tnved": "8504408300",
                      "series": ["ARPV", "ARJ", "ARV"]},
        "ozon_live_binding_count_before": len(bindings), "ozon_missing_bind_offers": new_missing,
        "wb_cards": {offer: {"nmID": target["nmID"], "vendorCode": offer,
                              "brand": wb_cards[offer].get("brand"),
                              "title": wb_cards[offer].get("title"),
                              "updatedAt": wb_cards[offer].get("updatedAt")}
                     for offer, target in TARGETS.items()},
        "targets": [{"offer_id": offer, **target, "ozon_attributes": attributes[offer]}
                    for offer, target in TARGETS.items()],
    }
    result["ready_to_bind_three"] = len(wb_cards) == 3 and len(attributes) == 3
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    tmp.replace(OUT)
    print(json.dumps({"checked_at": result["checked_at"], "number": NUMBER,
                      "certificate_id": CERTIFICATE_ID, "ozon_live_binding_count_before": len(bindings),
                      "ozon_missing_bind_offers": new_missing, "wb_cards": result["wb_cards"],
                      "ready_to_bind_three": result["ready_to_bind_three"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
