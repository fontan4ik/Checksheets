#!/usr/bin/env python3
"""Fresh, read-only preflight for STEKKER certificate 02314/23 targets."""
from __future__ import annotations
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

NUMBER = "ЕАЭС RU С-CN.НВ85.В.02314/23"
OFFERS = ["39197-1", "39199-1", "39200-1", "39522-1", "39523-1"]
SOURCE = ROOT / "output_to_user/certificates/additional_search/brand_research/stekker/stekker_hm_cert_02314_23.pdf"
OUT = HERE / "stekker_02314_crossplatform_preflight_20261022.json"
ISSUE, EXPIRY = "2023-08-30", "2028-08-29"
TNV = "8544429009"


def values(row: dict, attr_id: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(x.get("value") or "").strip()
            for x in (attrs.get(str(attr_id)) or {}).get("values") or []
            if str(x.get("value") or "").strip()]


def card_tnved(card: dict) -> list[str]:
    codes = []
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        codes.extend(str(v or "").split(" - ", 1)[0].strip()
                     for v in (raw if isinstance(raw, list) else [raw]) if v)
    return sorted(set(codes))


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_output_exists_review_before_retry")
    if not SOURCE.is_file():
        raise RuntimeError("signed_source_pdf_missing")
    source_sha = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    c = Client()
    products = c.call("ozon", "/v3/product/info/list", {"offer_id": OFFERS}).get("items") or []
    attrs = c.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": OFFERS}, "limit": len(OFFERS)
    }).get("result") or []
    if len(products) != len(OFFERS) or len(attrs) != len(OFFERS):
        raise RuntimeError("ozon_exact_product_snapshot_incomplete")
    pmap = {str(x.get("offer_id") or ""): x for x in products}
    amap = {str(x.get("offer_id") or ""): x for x in attrs}
    if set(pmap) != set(OFFERS) or set(amap) != set(OFFERS):
        raise RuntimeError("ozon_offer_set_changed")

    certs = []
    for page in range(1, 101):
        result = c.call("ozon", "/v1/product/certificate/list", {
            "page": page, "page_size": 100
        }).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_snapshot_incomplete")
        certs.extend(batch)
        if page >= int(result.get("page_count") or 0):
            break
    else:
        raise RuntimeError("ozon_certificate_pages_exceeded")
    matches = [x for x in certs
               if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(matches) != 1:
        raise RuntimeError(f"ozon_exact_certificate_record_count:{len(matches)}")
    cert = matches[0]
    if (cert.get("type_code") != "certificate_of_conformity"
            or cert.get("status_code") != "approved"
            or str(cert.get("issue_date", ""))[:10] != ISSUE
            or str(cert.get("expire_date", ""))[:10] != EXPIRY):
        raise RuntimeError("ozon_record_metadata_or_approval_conflict")
    bindings = c.ozon_bindings(int(cert["certificate_id"]))
    by_product = {str(x.get("product_id")): x for x in bindings}

    target_rows = []
    for offer in OFFERS:
        p, a = pmap[offer], amap[offer]
        product_id = str(p.get("product_id") or p.get("id") or "")
        sku = str(p.get("sku") or "")
        brand = values(a, 85)
        tnved_values = values(a, 22232)
        tnved_codes = sorted({str(v).split(" - ", 1)[0].strip() for v in tnved_values})
        wb = c.wb_cards(offer)
        if len(wb) != 1:
            raise RuntimeError(f"wb_exact_card_count:{offer}:{len(wb)}")
        card = wb[0]
        wb_tnved = card_tnved(card)
        if (p.get("is_archived") is not False or brand != ["Stekker"]
                or "удлинитель" not in str(p.get("name") or "").casefold()
                or "HM" not in str(p.get("name") or "")
                or str(card.get("vendorCode") or "") != offer
                or str(card.get("brand") or "").strip().casefold() != "stekker"
                or wb_tnved != [TNV]):
            raise RuntimeError(f"live_product_or_wb_scope_conflict:{offer}")
        binding = by_product.get(product_id)
        if binding and str(binding.get("sku")) != sku:
            raise RuntimeError(f"ozon_binding_identity_conflict:{offer}")
        same = [x for x in (((card.get("documents") or {}).get("items")) or [])
                if norm_number(x.get("number")) == norm_number(NUMBER)]
        if same:
            raise RuntimeError(f"wb_same_number_already_present_inspect:{offer}")
        tnved_matches = tnved_codes == [TNV]
        target_rows.append({
            "offer_id": offer, "product_id": product_id, "sku": sku,
            "product_name": p.get("name"), "brand_values": brand,
            "ozon_tnved_values": tnved_values, "ozon_tnved_matches_certificate": tnved_matches,
            "ozon_existing_binding": binding,
            "wb_nmID": str(card.get("nmID") or ""), "wb_brand": card.get("brand"),
            "wb_title": card.get("title"), "wb_tnved": wb_tnved,
            "wb_existing_document_count": len((((card.get("documents") or {}).get("items")) or [])),
            "wb_card": card,
        })

    ozon_targets = [x for x in target_rows if x["ozon_tnved_matches_certificate"]]
    if len(ozon_targets) != 1 or ozon_targets[0]["offer_id"] != "39523-1":
        raise RuntimeError("unexpected_ozon_in_scope_target_set")
    out = {
        "checked_at_utc": now(), "read_only": True,
        "number": cert.get("certificate_number"),
        "ozon_certificate": {k: cert.get(k) for k in (
            "certificate_id", "certificate_number", "type_code", "status_code",
            "issue_date", "expire_date", "products_count")},
        "source_pdf": str(SOURCE), "source_pdf_sha256": source_sha,
        "official_source_url": "https://feron.ru/postup/certificate/02314_%D0%9F%D1%80%D0%B8%D0%B1%D0%BE%D1%80%D1%8B_%D1%8D%D0%BB%D0%B5%D0%BA%D1%82%D1%80%D0%B8%D1%87%D0%B5%D1%81%D0%BA%D0%B8%D0%B5_%D1%82%D0%BC_STEKKER_%D1%83%D0%B4%D0%BB%D0%B8%D0%BD%D0%B8%D1%82%D0%B5%D0%BB%D0%B8_%D1%83%D0%B4%D0%BB%D0%B8%D0%BD%D0%B8%D1%82%D0%B5%D0%BB%D1%8C-%D1%88%D0%BD%D1%83%D1%80_%D0%B1%D0%BB%D0%BE%D0%BA%D0%B8_%D1%80%D0%BE%D0%B7%D0%B5%D1%82%D0%BE%D0%BA_%D1%81%D0%BE_%D1%88%D0%BD%D1%83%D1%80%D0%BE%D0%BC_%D1%81%D0%B5%D1%80%D0%B8%D0%B8_HM_PRF_STD_1.pdf",
        "official_scope": "STEKKER extension cords, cord extension sets and socket blocks with cord, series HM, PRF, STD; EAEU TN VED 8544429009; conformity certificate valid 2023-08-30 through 2028-08-29",
        "ozon_target_offers": [x["offer_id"] for x in ozon_targets],
        "ozon_tnved_mismatch_offers": [x["offer_id"] for x in target_rows if not x["ozon_tnved_matches_certificate"]],
        "wb_target_offers": OFFERS,
        "targets": target_rows,
        "local_file_deleted": False,
    }
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(OUT)
    print(json.dumps({k: out[k] for k in ("checked_at_utc", "number", "ozon_certificate",
        "source_pdf_sha256", "ozon_target_offers", "ozon_tnved_mismatch_offers", "wb_target_offers")},
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
