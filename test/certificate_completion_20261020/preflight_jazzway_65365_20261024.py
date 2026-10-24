from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

NUMBER = "ЕАЭС N RU Д-HK.РА03.В.65365/24"
ISSUE = "2024-04-16"
EXPIRY = "2029-04-15"
FSA_ID = "18827994"
FILE = ROOT / "output_to_user/certificates/group_2/JAZZWAY/documents/svetilniki-ppl-psp-pled-vstraivaemye-ds-tr-ts-037-15.04.2029_6a2674d63d15.pdf"
SHA256 = "6a2674d63d159f0d6230f48ff468f84cd2dcce4dc8cd028e4436f8e05fba6597"
OUT = HERE / "jazzway_65365_crossplatform_preflight_20261024.json"


def attr_values(row: dict, attr_id: str) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    values = (attrs.get(attr_id) or {}).get("values") or []
    return [str(x.get("value") or "").strip() for x in values if str(x.get("value") or "").strip()]


def codes(values: list[str]) -> list[str]:
    return sorted({str(v).split(" - ", 1)[0].strip() for v in values if str(v).strip()})


def list_certificates(client: Client) -> list[dict]:
    rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        rows.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("ozon_certificate_list_page_limit")


def wb_codes(card: dict) -> list[str]:
    out = []
    for ch in card.get("characteristics") or []:
        label = "".join(str(ch.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in label and "тнвед" not in label:
            continue
        value = ch.get("value")
        out.extend(value if isinstance(value, list) else [value])
    return codes([str(x) for x in out if x])


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_artifact_exists_reconcile_before_overwrite")
    if not FILE.is_file() or hashlib.sha256(FILE.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("source_pdf_missing_or_hash_mismatch")
    assignments = []
    with (ROOT / "output_to_user/certificates/document_assignments.csv").open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("Номер/название документа") != NUMBER:
                continue
            assignments.append({
                "offer_id": str(row.get("Артикул продавца") or "").strip(),
                "brand": str(row.get("Бренд подтвержденный") or "").strip(),
                "applicability": row.get("Применимость"),
                "coverage_status": row.get("Статус покрытия артикула"),
                "model_code": row.get("Артикул/код заказа JazzWay"),
                "source_file": row.get("Локальный файл"),
                "source_sha256": row.get("SHA256 фактический"),
                "official_product_url": row.get("URL карточки/основания"),
            })
    if len(assignments) != 50 or len({x["offer_id"] for x in assignments}) != 50:
        raise RuntimeError(f"assignment_scope_changed:{len(assignments)}")
    if any(x["brand"].casefold() != "jazzway" or x["applicability"] not in
           {"Подтверждено статусом покрытия", "Подтверждено источником"}
           or x["source_sha256"] != SHA256 for x in assignments):
        raise RuntimeError("assignment_rows_not_uniformly_confirmed")
    offers = sorted(x["offer_id"] for x in assignments)

    client = Client()
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items") or []
    attrs = client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": offers}, "limit": len(offers)}).get("result") or []
    if len(products) != len(offers) or len(attrs) != len(offers):
        raise RuntimeError("fresh_ozon_product_or_attribute_count_mismatch")
    by_offer = {str(x.get("offer_id") or ""): x for x in products}
    attr_by_offer = {str(x.get("offer_id") or ""): x for x in attrs}
    if set(by_offer) != set(offers) or set(attr_by_offer) != set(offers):
        raise RuntimeError("fresh_ozon_offer_set_mismatch")
    ozon = []
    for offer in offers:
        p, a = by_offer[offer], attr_by_offer[offer]
        brand = attr_values(a, "85")
        tnved = codes(attr_values(a, "22232"))
        row = {"offer_id": offer, "product_id": str(p.get("product_id") or p.get("id") or ""),
               "sku": str(p.get("sku") or ""), "is_archived": p.get("is_archived"),
               "brand": brand, "tnved": tnved, "name": p.get("name")}
        row["safe"] = bool(p.get("is_archived") is False and row["product_id"] and row["sku"]
                           and brand == ["Jazzway"] and tnved == ["9405110033"])
        ozon.append(row)

    certs = list_certificates(client)
    exact_records = [x for x in certs if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    wb = []
    for index, offer in enumerate(offers, 1):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) > 1:
            wb.append({"offer_id": offer, "exact_card_count": len(cards), "safe": False, "reason": "duplicate_exact_cards"})
            continue
        card = cards[0] if cards else None
        existing = [x for x in (((card or {}).get("documents") or {}).get("items") or [])
                    if norm_number(x.get("number")) == norm_number(NUMBER)]
        expected_existing = [x for x in existing if str(x.get("type")) == "2"
                             and str(x.get("startDate") or "")[:10] == ISSUE
                             and str(x.get("endDate") or "")[:10] == EXPIRY
                             and x.get("isEndless") is False]
        tnved = wb_codes(card) if card else []
        row = {"offer_id": offer, "exact_card_count": len(cards),
               "nmID": str(card.get("nmID") or "") if card else None,
               "brand": str(card.get("brand") or "") if card else None,
               "tnved": tnved, "existing_same_number_docs": existing,
               "already_exact": len(existing) == 1 and len(expected_existing) == 1,
               "safe": bool(card and str(card.get("brand") or "").casefold() in {"jazzway", "jazz way"}
                            and tnved == ["9405110033"] and len(existing) <= 1
                            and (not existing or len(expected_existing) == 1))}
        wb.append(row)
        if index % 20 == 0:
            print(f"read_wb_cards={index}/{len(offers)}", flush=True)

    bindings = []
    for rec in exact_records:
        bindings.extend(client.ozon_bindings(int(rec["certificate_id"])))
    ozon_pairs = {(str(x.get("product_id") or ""), str(x.get("sku") or "")) for x in bindings}
    for row in ozon:
        row["already_bound"] = (row["product_id"], row["sku"]) in ozon_pairs

    result = {
        "checked_at_utc": now(), "read_only": True,
        "document": {"number": NUMBER, "type": "declaration", "fsa_record_id": FSA_ID,
                     "fsa_url": f"https://pub.fsa.gov.ru/rds/declaration/view/{FSA_ID}/common",
                     "fsa_status": "Действует", "issue_date": ISSUE, "expire_date": EXPIRY,
                     "fsa_tnved": ["9405110033"], "sample_date_condition": "Продукция, изготовленная с даты изготовления отобранных образцов: 12.2023",
                     "source_file": str(FILE.relative_to(ROOT)), "source_sha256": SHA256,
                     "source_official_url": "https://jazz-way.com/docs/sertifikaty/svetilniki-ppl-psp-pled-vstraivaemye-ds-tr-ts-037-15.04.2029.pdf"},
        "assignment_count": len(assignments), "assignment_rows": assignments,
        "ozon_target_count": len(ozon), "ozon_tnved_counts": dict(Counter(c for x in ozon for c in x["tnved"])),
        "ozon_safe_count": sum(x["safe"] for x in ozon), "ozon_already_bound_count": sum(x["already_bound"] for x in ozon),
        "ozon_exact_records": [{k: rec.get(k) for k in ("certificate_id", "certificate_number", "type_code", "status_code", "issue_date", "expire_date", "products_count")} for rec in exact_records],
        "ozon_targets": ozon,
        "wb_target_count": len(wb), "wb_safe_count": sum(x.get("safe", False) for x in wb),
        "wb_already_exact_count": sum(x.get("already_exact", False) for x in wb),
        "wb_tnved_counts": dict(Counter(c for x in wb for c in x.get("tnved", []))), "wb_targets": wb,
        "no_mutations": True, "local_file_deleted": False,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "checked_at_utc": result["checked_at_utc"],
                      "ozon": {"targets": len(ozon), "safe": result["ozon_safe_count"],
                               "already_bound": result["ozon_already_bound_count"],
                               "tnved_counts": result["ozon_tnved_counts"],
                               "exact_records": result["ozon_exact_records"]},
                      "wb": {"targets": len(wb), "safe": result["wb_safe_count"],
                             "already_exact": result["wb_already_exact_count"],
                             "tnved_counts": result["wb_tnved_counts"]},
                      "no_mutations": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
