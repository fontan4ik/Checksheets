"""Read-only check of the REXANT PRPPM 2x1.20 mm offer and its official product document."""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from api_client import Client, now  # noqa: E402
from execute_alphacable_02888_20261013 import wb_tnved_codes  # noqa: E402

OUT = BASE / "rexant_prppm_live_preflight_20261013.json"
OFFER = "8138178-1"
PRODUCT_ID = "6503121371"
SKU = "5938247518"
NMID = "1862721129"
TNVED = "8544499509"
CERTIFICATE_IMAGE = (
    "https://rexant.kz/upload/iblock/bf5/l5uvpskzw8lioztpz1skvm1pci8a4ea9/"
    "ROSS-RU.NV56.N02368.jpg"
)
REXANT_PRODUCT_PAGE = "https://rexant.kz/product/provod-prppm-2kh0-90mm-500m-rexant-01-5514-1/"
REXANT_CATEGORY_PAGE = "https://rexant.ru/catalog/oborudovanie-dlya-telefonii1/?showBy=36"


def main() -> None:
    client = Client()
    product_body = client.call("ozon", "/v3/product/info/list", {"offer_id": [OFFER]})
    products = product_body.get("items") or product_body.get("result", {}).get("items")
    if not isinstance(products, list) or len(products) != 1:
        raise RuntimeError("Ozon exact product is missing or ambiguous")
    p = products[0]
    if (str(p.get("offer_id")) != OFFER or str(p.get("id") or p.get("product_id")) != PRODUCT_ID
            or str(p.get("sku")) != SKU or p.get("is_archived")):
        raise RuntimeError("Ozon offer identity changed")
    attrs_body = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": [OFFER]}, "limit": 1})
    attrs_rows = attrs_body.get("result") or attrs_body.get("items")
    if not isinstance(attrs_rows, list) or len(attrs_rows) != 1:
        raise RuntimeError("Ozon exact attributes are missing or ambiguous")
    attrs = {str(x.get("id")): x for x in attrs_rows[0].get("attributes") or []}
    brand = [str(x.get("value") or "") for x in (attrs.get("85") or {}).get("values") or []]
    tnved_values = [str(x.get("value") or "") for x in (attrs.get("22232") or {}).get("values") or []]
    tnved = sorted({x.split(" - ", 1)[0].strip() for x in tnved_values if x.strip()})
    cards = client.wb_cards(OFFER)
    if len(cards) != 1:
        raise RuntimeError("WB exact card is missing or ambiguous")
    card = cards[0]
    if str(card.get("vendorCode")) != OFFER or str(card.get("nmID")) != NMID:
        raise RuntimeError("WB exact identity changed")
    docs = (card.get("documents") or card.get("docs") or {})
    source_doc = {
        "source": CERTIFICATE_IMAGE,
        "official_product_context": [REXANT_PRODUCT_PAGE, REXANT_CATEGORY_PAGE],
        "number": "РОСС RU.НВ56.Н02368",
        "document_kind": "добровольный сертификат ГОСТ Р",
        "issue_date": "2019-12-26",
        "expiry_date": "2024-12-25",
        "scope": "Провода ПРППМ и ПРППМт для телефонной связи/радиофикации; диаметры жил 0,8, 0,9 и 1,2 мм; ТН ВЭД 8554449950.",
        "explicit_limitation": "Сертификат не применяется при обязательной сертификации.",
        "sha256": "19c1f2f4b118058f6db177b374148ede3fbb0ca29f739916b9bf39df535ff026",
        "local_file": str(BASE / "rexant_prppm_02368_official_source.jpg"),
    }
    out = {
        "checked_at_utc": now(), "read_only": True,
        "target": {"offer_id": OFFER, "product_id": PRODUCT_ID, "sku": SKU,
                   "name": p.get("name"), "is_archived": p.get("is_archived"),
                   "ozon_status": p.get("statuses"), "ozon_availabilities": p.get("availabilities"),
                   "brand": brand, "tnved_values": tnved_values, "tnved_codes": tnved},
        "wb_card": {"nmID": card.get("nmID"), "vendorCode": card.get("vendorCode"),
                    "brand": card.get("brand"), "title": card.get("title"),
                    "tnved_codes": sorted(wb_tnved_codes(card)), "documents": docs,
                    "existing_document_rows": docs.get("items") or []},
        "manufacturer_document": source_doc,
        "decision": {
            "exact_product_model_and_code_match": brand == ["REXANT"] and tnved == [TNVED]
                and "ПРППМ" in str(p.get("name") or ""),
            "current_valid_document_proven": False,
            "reason": "The only exact official manufacturer certificate retrieved is voluntary and expired 2024-12-25; no current valid document was confirmed in this pass.",
            "ozon_or_wb_mutations": 0,
            "action": "Skip for now; retain the official source and recheck for a current manufacturer/FSA document before any upload.",
        },
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "decision": out["decision"],
                      "ozon_offer": OFFER, "wb_nmID": NMID}, ensure_ascii=False))


if __name__ == "__main__":
    main()
