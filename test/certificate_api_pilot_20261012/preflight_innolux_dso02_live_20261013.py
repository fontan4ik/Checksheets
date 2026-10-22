"""Fresh read-only Ozon/WB scope and identity check for four INNOLUX DSO-02 offers."""
from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path

from api_client import BASE, Client, now, save

OUT = "innolux_dso02_live_preflight_20261013.json"
CERT_NUMBER = "ЕАЭС RU С-RU.НВ28.В.00092/24"
DECL_NUMBER = "ЕАЭС N RU Д-RU.РА10.В.67971/24"
EXPECTED = {
    "92304-1": ("6014255019", "5515769224"),
    "92305-1": ("6014258718", "5515768612"),
    "92306-1": ("6014256275", "5515766267"),
    "92311-1": ("6014256401", "5515769519"),
}
OZON_SCOPE_CODES = {"9405110013", "9405110033"}
WB_CHAR_TNVED = 15000001
CERT_PDF = Path("/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets/output_to_user/certificates/additional_search/brand_research/innolux/followup_2026_10_02_b/docs/compliance/RU_C-RU_NV28_V_00092_24_registry_extract.pdf")
DECL_PDF = Path("/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets/output_to_user/certificates/additional_search/brand_research/innolux/followup_2026_10_02_b/docs/compliance/RU_D-RU_RA10_V_67971_24_registry_extract.pdf")


def norm(value: object) -> str:
    table = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
                           "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
                           "Ё": "E", "Э": "E", "Д": "D", "П": "P"})
    return "".join(ch for ch in str(value or "").upper().translate(table) if ch.isalnum())


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ozon_products(client: Client) -> dict[str, dict]:
    offers = list(EXPECTED)
    response = client.call("ozon", "/v3/product/info/list", {"offer_id": offers})
    items = response.get("items") or response.get("result", {}).get("items")
    if not isinstance(items, list):
        raise RuntimeError("Ozon product list response is malformed")
    rows = {str(x.get("offer_id") or ""): x for x in items}
    if set(rows) != set(offers) or len(rows) != len(items):
        raise RuntimeError("Ozon live product identity set is incomplete or duplicated")
    return rows


def ozon_attrs(client: Client, offer: str) -> dict:
    response = client.call("ozon", "/v4/product/info/attributes",
                           {"filter": {"offer_id": [offer]}, "limit": 1})
    items = response.get("result") or response.get("items")
    if not isinstance(items, list) or len(items) != 1 or str(items[0].get("offer_id")) != offer:
        raise RuntimeError(f"Ozon attribute response missing or ambiguous for {offer}")
    values = {str(x.get("id")): x for x in items[0].get("attributes") or []}
    brand = [str(x.get("value") or "") for x in (values.get("85") or {}).get("values") or []]
    tnved_values = [str(x.get("value") or "") for x in (values.get("22232") or {}).get("values") or []]
    return {"brand_values": brand,
            "tnved_values": tnved_values,
            "tnved_codes": sorted({x.split(" - ", 1)[0].strip() for x in tnved_values if x.strip()})}


def list_ozon_certificates(client: Client) -> list[dict]:
    result: list[dict] = []
    for page in range(1, 101):
        data = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result", {})
        batch = data.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list is malformed")
        result.extend(batch)
        if len(batch) < 100:
            if len({str(x.get("certificate_id")) for x in result}) != len(result):
                raise RuntimeError("Ozon certificate list contains duplicate IDs")
            return result
    raise RuntimeError("Ozon certificate pagination exceeded limit")


def main() -> None:
    client = Client()
    products = ozon_products(client)
    attributes = {offer: ozon_attrs(client, offer) for offer in EXPECTED}
    certificates = list_ozon_certificates(client)
    docs = {"004_020_certificate": [], "037_declaration": []}
    for record, key, wanted in ((x, "004_020_certificate", CERT_NUMBER) for x in certificates):
        if norm(record.get("certificate_number")) == norm(wanted):
            docs[key].append(record)
    for record, key, wanted in ((x, "037_declaration", DECL_NUMBER) for x in certificates):
        if norm(record.get("certificate_number")) == norm(wanted):
            docs[key].append(record)
    for key in docs:
        for record in docs[key]:
            bindings = client.ozon_bindings(record["certificate_id"])
            record["live_target_pairs"] = sorted([
                (str(x.get("product_id") or ""), str(x.get("sku") or ""))
                for x in bindings if str(x.get("product_id") or "") in {p[0] for p in EXPECTED.values()}
            ])
            record["binding_status_counts"] = dict(collections.Counter(
                str(x.get("product_status_code") or "") for x in bindings))
            record.pop("certificate_file", None)
            record.pop("file_content", None)
    targets = []
    for offer, (pid, sku) in EXPECTED.items():
        product = products[offer]
        live_pid = str(product.get("id") or product.get("product_id") or "")
        live_sku = str(product.get("sku") or "")
        cards = client.wb_cards(offer)
        wb = []
        for card in cards:
            chars = card.get("characteristics") or []
            tnved_rows = [x for x in chars if int(x.get("id", -1)) == WB_CHAR_TNVED]
            tnved_values = [str(v) for row in tnved_rows for v in (row.get("value") or [])]
            docs_container = card.get("documents") or card.get("docs") or {}
            wb.append({"nmID": str(card.get("nmID") or ""),
                       "vendorCode": str(card.get("vendorCode") or ""),
                       "brand": card.get("brand"), "subjectID": card.get("subjectID"),
                       "subjectName": card.get("subjectName"),
                       "tnved_values": tnved_values,
                       "tnved_codes": sorted({x.split(" ", 1)[0].strip() for x in tnved_values if x.strip()}),
                       "excludeDocuments": docs_container.get("excludeDocuments"),
                       "documents": [{"type": x.get("type"), "number": x.get("number"),
                                      "startDate": x.get("startDate"), "endDate": x.get("endDate"),
                                      "verdict": x.get("verdict")}
                                     for x in docs_container.get("items") or []]})
        targets.append({"offer_id": offer, "expected_product_id": pid, "live_product_id": live_pid,
                        "expected_sku": sku, "live_sku": live_sku,
                        "identity_exact": live_pid == pid and live_sku == sku,
                        "live_name": product.get("name"), "is_archived": product.get("is_archived"),
                        "brand": attributes[offer]["brand_values"],
                        "ozon_tnved_values": attributes[offer]["tnved_values"],
                        "ozon_tnved_codes": attributes[offer]["tnved_codes"],
                        "ozon_tnved_in_fsa_scope": bool(set(attributes[offer]["tnved_codes"]) & OZON_SCOPE_CODES),
                        "wb_card_count": len(wb), "wb_cards": wb})
    state = {
        "checked_at_utc": now(), "read_only": True,
        "certificate_number": CERT_NUMBER, "declaration_number": DECL_NUMBER,
        "fsa_records_last_verified_in_official_api_extracts": "2026-10-02",
        "fsa_certificate_extract": {"path": str(CERT_PDF), "sha256": digest(CERT_PDF),
                                    "record_status": "Действует", "expires": "2029-11-07",
                                    "tnved_scope": sorted(OZON_SCOPE_CODES),
                                    "series_explicitly_includes": "ДСО-02"},
        "fsa_declaration_extract": {"path": str(DECL_PDF), "sha256": digest(DECL_PDF),
                                    "record_status": "Действует", "expires": "2029-11-18",
                                    "tnved_scope": sorted(OZON_SCOPE_CODES),
                                    "series_explicitly_includes": "ДСО-02"},
        "ozon_live_certificate_list_count": len(certificates),
        "ozon_matching_records": docs,
        "target_count": len(targets), "targets": targets,
        "scope_code_conflict_target_count": sum(bool(x["ozon_tnved_codes"])
                                                   and not x["ozon_tnved_in_fsa_scope"] for x in targets),
        "no_write_reason": "Live Ozon TN VED must intersect FSA scope; current listing uses 9405190039 while FSA extracts list 9405110013/9405110033. No code changes or certificate writes made.",
    }
    save(OUT, state)
    print(json.dumps({"artifact": str(BASE / OUT), "checked_at_utc": state["checked_at_utc"],
                      "matching_ozon_record_counts": {k: len(v) for k, v in docs.items()},
                      "targets": [{"offer_id": x["offer_id"], "identity_exact": x["identity_exact"],
                                   "ozon_tnved_codes": x["ozon_tnved_codes"],
                                   "ozon_tnved_in_fsa_scope": x["ozon_tnved_in_fsa_scope"],
                                   "wb_card_count": x["wb_card_count"],
                                   "wb_tnved_codes": [c["tnved_codes"] for c in x["wb_cards"]]}
                                  for x in targets],
                      "scope_code_conflict_target_count": state["scope_code_conflict_target_count"],
                      "no_write_reason": state["no_write_reason"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
