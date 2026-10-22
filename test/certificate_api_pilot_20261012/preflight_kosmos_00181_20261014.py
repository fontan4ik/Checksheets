"""Read-only exact Ozon/WB preflight for Kosmos certificate 00181/25."""
from __future__ import annotations

import csv
import datetime as dt
import json
import re
from pathlib import Path

from api_client import BASE, ROOT, Client, digest
from preflight_stekker_05795_20261014 import (
    read_ozon_attributes, read_ozon_certificates, read_ozon_products, read_wb_cards,
)

NUMBER = "ЕАЭС RU С-CN.НВ28.В.00181/25"
SUFFIX = "0018125"
FSA_ID = 3586393
FSA_URL = "https://pub.fsa.gov.ru/rss/certificate/view/3586393/product"
SHA256 = "00006bd5e6aa882ea41baea4a6168bc4a2df938ff94628388a31e3d44bd6a3c9"
MASTER = ROOT / "output_to_user/certificates/document_catalog_master.csv"
MANIFEST = ROOT / "output_to_user/certificates/additional_search/manifest.csv"
EXTRACT = ROOT / "output_to_user/certificates/additional_search/brand_research/kosmos/followup_2026_10_02/docs/kosmos_004_020_00181_25_fsa_extract.pdf"
OUT = BASE / "kosmos_00181_live_preflight_20261014.json"
ALLOWED_TNVED = {"8539520003", "8539520009"}


def digits(value: object) -> str:
    return re.sub(r"[^0-9]", "", str(value or ""))


def offer_model(offer: str) -> str:
    return re.sub(r"-(?:5|10)$", "", offer, flags=re.I)


def read_source() -> tuple[list[str], dict, dict[str, dict]]:
    with MASTER.open(newline="", encoding="utf-8-sig") as stream:
        master_rows = [x for x in csv.DictReader(stream) if x.get("SHA256", "").lower() == SHA256]
    if len(master_rows) != 1:
        raise RuntimeError(f"Expected one master row for the FSA extract, found {len(master_rows)}")
    row = master_rows[0]
    offers = sorted(set(x.strip() for x in row["Артикулы"].split(";") if x.strip()))
    if len(offers) != int(row["Связанных артикулов"]) or len(offers) != 58:
        raise RuntimeError("Master row does not contain 58 unique offers")
    source_paths = [ROOT / x.strip() for x in row["Файл/файлы проекта"].split(";") if x.strip()]
    source = next((x for x in source_paths if x.is_file() and not x.is_symlink()), None)
    if not source or digest(source) != SHA256:
        raise RuntimeError("Official FSA extract missing or SHA-256 changed")
    with MANIFEST.open(newline="", encoding="utf-8-sig") as stream:
        mappings = [x for x in csv.DictReader(stream)
                    if digits(x.get("Документ/номер", "")).endswith(SUFFIX)]
    by_offer = {x["Артикул продавца"]: x for x in mappings}
    if len(mappings) != 58 or set(by_offer) != set(offers):
        raise RuntimeError("Exact product-to-FSA model mapping does not cover all 58 offers")
    return offers, {"path": str(source), "sha256": digest(source), "bytes": source.stat().st_size,
                    "fsa_model_extract": str(EXTRACT)}, by_offer


def main() -> None:
    offers, source, mappings = read_source()
    client = Client()
    products = read_ozon_products(client, offers)
    read_ozon_attributes(client, offers, products)
    info_by_offer = {x["offer_id"]: x for x in products}
    model_checks = []
    for offer, mapping in mappings.items():
        model = offer_model(offer)
        rationale = mapping.get("Основание сопоставления", "")
        item = info_by_offer[offer]
        name = item.get("name") or ""
        model_checks.append({"offer_id": offer, "source_model": model,
                             "model_in_fsa_basis": "exact seller model" in rationale.casefold(),
                             "model_in_live_ozon_name": model.casefold() in name.casefold(),
                             "source_basis": rationale})
    certs = read_ozon_certificates(client)
    matches = [x for x in certs if digits(x.get("certificate_number")).endswith(SUFFIX)]
    exact_lookup = client.http.post(
        "https://api-seller.ozon.ru/v1/product/certificate/info",
        json={"certificate_number": NUMBER}, headers=client.ozon_headers, timeout=(15, 60)
    )
    status = exact_lookup.status_code
    # Preserve only the non-sensitive error code from the exact-number lookup.
    try:
        lookup = exact_lookup.json()
    except ValueError:
        lookup = {}
    if status == 200:
        lookup = {"resolved": True}
    else:
        lookup = {"inconclusive": True}

    wb = []
    for offer in offers:
        cards = [x for x in read_wb_cards(client, offer) if x.get("vendorCode") == offer]
        wb.append({"offer_id": offer, "cards": cards})
    output = {
        "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "read_only": True, "number": NUMBER, "document_type": "certificate_of_conformity",
        "issue_date": "2025-06-23", "expire_date": "2030-06-22",
        "fsa_record_id": FSA_ID, "fsa_url": FSA_URL, "fsa_status_live_browser": "Действует",
        "fsa_tnved_codes": sorted(ALLOWED_TNVED),
        "source": source, "offers": offers,
        "ozon_products": products, "ozon_model_checks": model_checks,
        "ozon_exact_number_matches": matches,
        "ozon_exact_number_lookup": {"http_status": status,
                                     "code": lookup.get("code") if isinstance(lookup, dict) else None,
                                     "resolved": bool(lookup.get("resolved")) if isinstance(lookup, dict) else None},
        "wb_cards_by_offer": wb,
    }
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp.replace(OUT)
    print(json.dumps({
        "checked_at_utc": output["checked_at_utc"], "offers": len(offers),
        "ozon_products": len(products),
        "ozon_brand_values": sorted({v for x in products for v in x["brand_values"]}),
        "ozon_tnved_counts": {code: sum(any(v.split(" - ", 1)[0].strip() == code for v in x["tnved_values"])
                                               for x in products) for code in sorted(ALLOWED_TNVED)},
        "ozon_out_of_scope_or_missing_tnved": sum(not any(v.split(" - ", 1)[0].strip() in ALLOWED_TNVED
                                                           for v in x["tnved_values"]) for x in products),
        "ozon_model_matches": sum(x["model_in_live_ozon_name"] for x in model_checks),
        "ozon_fsa_source_model_matches": sum(x["model_in_fsa_basis"] for x in model_checks),
        "ozon_exact_number_matches": len(matches),
        "ozon_exact_lookup_http": status, "ozon_exact_lookup_code": output["ozon_exact_number_lookup"]["code"],
        "wb_one_exact_card": sum(len(x["cards"]) == 1 for x in wb),
        "wb_missing_card": sum(not x["cards"] for x in wb),
        "wb_duplicate_card": sum(len(x["cards"]) > 1 for x in wb),
        "wb_brand_values": sorted({str(c.get("brand")) for r in wb for c in r["cards"]}),
        "wb_target_number_rows": sum(1 for r in wb for c in r["cards"]
                                     for d in ((c.get("documents") or {}).get("items") or [])
                                     if digits(d.get("number")).endswith(SUFFIX)),
        "output": str(OUT),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
