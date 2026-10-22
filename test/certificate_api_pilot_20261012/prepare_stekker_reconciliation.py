"""Read-only live preflight for the explicitly mapped STEKKER certificate group."""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

from api_client import BASE, ROOT, Client, digest, now
from group4_ozon import doc_identity

OUT = BASE / "stekker_reconciliation_plan.json"
CATALOG = BASE / "ozon_new_offers_attributes.json"

EXTENSION_OFFERS = [
    "49591-1", "49972-1", "49970-1", "49977-1", "49991-1", "49979-1",
    "50101-1", "50103-1", "50142-1", "50102-1",
]
INSTALLATION_OFFERS = [
    "49402-1", "49400-1", "49407-1", "49401-1",
    "50067-1", "50068-1", "50070-1",
]

DOCS = [
    {
        "type_code": "certificate_of_conformity",
        "wb_type": 1,
        "number": "ЕАЭС RU C-CN.HB85.B.02314/23",
        "issue_date": "2023-08-30",
        "expire_date": "2028-08-29",
        "source_file": "group_1/documents/stekker/b761c4afd31633cae4ca6315.pdf",
        "source_sha256": "c47c7db036f1df9a620e3dad35d1b202d22b21e0e17c957b65b51a891c24dbad",
        "source_url": "https://feron.ru/postup/certificate/02314_Приборы_электрические_тм_STEKKER_удлинители_удлинитель-шнур_блоки_розеток_со_шнуром_серии_HM_PRF_STD_1.pdf",
        "registry_url": "https://pub.fsa.gov.ru/rss/certificate/view/3306161/baseInfo",
        "offers": EXTENSION_OFFERS,
    },
    {
        "type_code": "declaration",
        "wb_type": 2,
        "number": "ЕАЭС N RU Д-CN.PA07.B.01452/23",
        "issue_date": "2023-08-31",
        "expire_date": "2028-08-30",
        "source_file": "group_1/documents/stekker/cd21f778ad5909efedd47a1f.jpg",
        "source_sha256": "b7101883438c74971ca4840d74f1e95566500923bfb52eed35815d87315a1202",
        "source_url": "https://feron.ru/postup/certificate/01452 Приборы электрические тм STEKKER удлинители, удлинитель-шнур, блоки розеток со шнуро. Декларация по 037_1 (1).jpg",
        "registry_url": None,
        "offers": EXTENSION_OFFERS,
    },
    {
        "type_code": "certificate_of_conformity",
        "wb_type": 1,
        "number": "ЕАЭС RU C-CN.ИП18.В.00156/21",
        "issue_date": "2021-12-24",
        "expire_date": "2026-12-23",
        "source_file": "group_1/documents/stekker/80c7b1ef5128cc88d701f1ad.pdf",
        "source_sha256": "cf2cd9cdb9f02a8018579d6c0e014d83811abf9cc5f7adf35f962c4ad47f569f",
        "source_url": "https://feron.ru/postup/certificate/Розетки, вилки, адаптеры , переходники Штеккер Сертификат.pdf",
        "registry_url": "https://pub.fsa.gov.ru/rss/certificate/view/3020628/baseInfo",
        "offers": INSTALLATION_OFFERS,
    },
    {
        "type_code": "declaration",
        "wb_type": 2,
        "number": "ЕАЭС N RU Д-CN.PA01.B.08463/26",
        "issue_date": "2026-01-14",
        "expire_date": "2031-01-13",
        "source_file": "group_1/documents/stekker/069ca599d5f103b42281b2c6.jpg",
        "source_sha256": "895f75dc1b8ae4ece329d9271d96ec87b5149a07f35aba35b62691b2254065f0",
        "source_url": "https://feron.ru/postup/certificate/08463_Изделия_электроустановочные_ТМ_Stekker_Декларация_по_ТР_037.jpg",
        "registry_url": None,
        "offers": INSTALLATION_OFFERS,
    },
]

WB_FIELDS = (
    "nmID", "vendorCode", "brand", "title", "gtin", "description", "dimensions",
    "characteristics", "sizes", "kizMarked",
)
WB_DOC_FIELDS = (
    "id", "type", "number", "productNumber", "tradeName", "applicant",
    "startDate", "endDate", "isEndless",
)


def live_certificates(client: Client) -> list[dict]:
    rows = []
    page = 1
    while True:
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100})["result"]
        rows.extend(result["certificates"])
        if page >= result["page_count"]:
            break
        page += 1
    if len({str(x["certificate_id"]) for x in rows}) != len(rows):
        raise RuntimeError("Duplicate certificate_id in Ozon list")
    return rows


def same_doc_number(a: str, b: str) -> bool:
    return doc_identity(a or "") == doc_identity(b or "")


def main() -> None:
    catalog = json.loads(CATALOG.read_text())
    catalog_rows = {x["offer_id"]: x for x in catalog["products"]}
    expected_offers = sorted(set(EXTENSION_OFFERS + INSTALLATION_OFFERS))
    if len(expected_offers) != 17 or any(x not in catalog_rows for x in expected_offers):
        raise RuntimeError("Expected exact 17-offer target set is incomplete in the saved catalog")

    client = Client()
    info = client.call("ozon", "/v3/product/info/list", {"offer_id": expected_offers})["items"]
    live_products = {str(x.get("offer_id")): x for x in info}
    if len(info) != len(expected_offers) or set(live_products) != set(expected_offers):
        raise RuntimeError("Fresh Ozon info did not return all 17 unique offers")
    products = {}
    for offer in expected_offers:
        old, current = catalog_rows[offer], live_products[offer]
        pid = str(current.get("id") or current.get("product_id") or "")
        sku = str(current.get("sku") or "")
        if (pid != str(old["product_id"]) or sku != str(old["sku"]) or
                current.get("is_archived") or not current.get("name")):
            raise RuntimeError(f"Fresh Ozon identity mismatch or archived offer: {offer}")
        products[offer] = {
            "product_id": pid, "sku": sku, "name": current["name"],
            "brand": old.get("brand"), "model": old.get("model"),
            "wb_nmIDs": [],
        }

    certificates = live_certificates(client)
    doc_results = []
    for spec in DOCS:
        source = ROOT / "output_to_user/certificates" / spec["source_file"]
        if not source.is_file() or source.is_symlink() or digest(source) != spec["source_sha256"]:
            raise RuntimeError(f"Source file missing, symlinked, or changed: {source}")
        if spec["expire_date"] <= "2026-10-12":
            raise RuntimeError(f"Document expired on the task date: {spec['number']}")
        matches = [x for x in certificates if same_doc_number(
            x.get("certificate_number", ""), spec["number"])]
        if len(matches) > 1:
            raise RuntimeError(f"Multiple Ozon records have the same full document number: {spec['number']}")
        record = matches[0] if matches else None
        action = "create"
        exact_bindings = []
        if record:
            expected_type = spec["type_code"]
            if (record.get("type_code") != expected_type or
                    str(record.get("issue_date", ""))[:10] != spec["issue_date"] or
                    str(record.get("expire_date", ""))[:10] != spec["expire_date"] or
                    record.get("accordance_type_code") != "EAEU"):
                raise RuntimeError(f"Existing Ozon metadata conflicts for {spec['number']}")
            if record.get("status_code") != "approved":
                raise RuntimeError(f"Existing Ozon record is not approved; do not duplicate: {spec['number']}")
            bindings = client.ozon_bindings(record["certificate_id"])
            all_pairs = {(str(x.get("product_id")), str(x.get("sku"))) for x in bindings}
            exact_bindings = [
                {"offer_id": offer, "present": (
                    products[offer]["product_id"], products[offer]["sku"]) in all_pairs}
                for offer in spec["offers"]
            ]
            action = "bind_missing" if any(not x["present"] for x in exact_bindings) else "already_bound"

        doc_results.append({
            **spec,
            "absolute_source_file": str(source),
            "file_bytes": source.stat().st_size,
            "ozon_action": action,
            "ozon_live_record": record,
            "ozon_existing_target_bindings": exact_bindings,
            "target_pairs": [
                {"offer_id": offer, "product_id": products[offer]["product_id"],
                 "sku": products[offer]["sku"]}
                for offer in spec["offers"]
            ],
        })

    wb_cards = {}
    all_nmids = set()
    for offer in expected_offers:
        cards = client.wb_cards(offer)
        exact = [x for x in cards if x.get("vendorCode") == offer]
        if not exact:
            raise RuntimeError(f"No exact Wildberries card for {offer}; stop before writing either platform")
        ids = sorted({str(x.get("nmID")) for x in exact})
        if any(not x or x == "None" for x in ids) or all_nmids.intersection(ids):
            raise RuntimeError(f"Duplicate or missing WB nmID for {offer}")
        all_nmids.update(ids)
        products[offer]["wb_nmIDs"] = ids
        wb_cards[offer] = exact

    plan = {
        "checked_at": now(),
        "source_catalog_checked_at": catalog.get("checked_at"),
        "ozon_product_info_checked_at": now(),
        "ozon_certificates_checked_at": now(),
        "wb_cards_checked_at": now(),
        "complete": True,
        "scope": "Only exact STEKKER extension leads and plug/socket splitters whose series are printed in the active documents.",
        "withheld_documents": [
            {
                "number": "ЕАЭС KG 417/053.CN.02.09004",
                "reason": "Issued by Kyrgyzstan body Expert-Line; KCA states on 2026-05-22 that Russia suspended the effectiveness in Russia of documents issued by Expert-Line for 12 months. Do not upload absent separate Russian recognition proof.",
                "source": "https://kca.gov.kg/news/103",
            }
        ],
        "products": products,
        "documents": doc_results,
        "wb_cards": wb_cards,
        "target_offer_count": len(products),
        "target_wb_card_count": sum(len(x) for x in wb_cards.values()),
        "ozon_actions": dict(collections.Counter(x["ozon_action"] for x in doc_results)),
    }
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    tmp.replace(OUT)
    print(json.dumps({
        "target_offers": plan["target_offer_count"],
        "target_wb_cards": plan["target_wb_card_count"],
        "ozon_document_actions": plan["ozon_actions"],
        "documents": [
            {"number": x["number"], "offer_count": len(x["offers"]),
             "ozon_action": x["ozon_action"], "file_bytes": x["file_bytes"]}
            for x in doc_results
        ],
        "plan": str(OUT),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
