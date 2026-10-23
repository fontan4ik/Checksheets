"""Fresh read-only reconciliation of all known IEK 66430/26 local targets."""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import sys
from collections import Counter, defaultdict

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import copy_documents, norm_number  # noqa: E402

ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
MANIFEST = HERE / "ready_found_documents_manifest_20261023.json"
PREFLIGHT = HERE / "iek_66430_crossplatform_preflight_20261023.json"
OUT = HERE / "iek_66430_full_live_reconciliation_20261023.json"
NUMBER = "ЕАЭС N RU Д-CN.РА02.В.66430/26"
ISSUE = "2026-03-18"
EXPIRY = "2027-10-17"
FSA_ID = 21245281
SOURCE_SHA256 = "a09742c42dba8a9066f8e7ba26ad624a9b9a7a0c3901b6ca1a5285bdd1b39caf"
ALLOWED_TNVED = {"8536201007"}


def values(row: dict, attr_id: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(v.get("value") or "").strip()
            for v in (attrs.get(str(attr_id)) or {}).get("values") or []
            if str(v.get("value") or "").strip()]


def tnved(raw: list[str]) -> list[str]:
    return sorted({str(x).split(" - ", 1)[0].strip() for x in raw if str(x).strip()})


def card_tnved(card: dict) -> list[str]:
    found = []
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        for x in raw if isinstance(raw, list) else [raw]:
            if x:
                found.append(str(x).split(" - ", 1)[0].strip())
    return sorted(set(found))


def read_certificates(client: Client) -> list[dict]:
    result = []
    for page in range(1, 101):
        payload = client.call("ozon", "/v1/product/certificate/list",
                              {"page": page, "page_size": 100}).get("result") or {}
        batch = payload.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        result.extend(batch)
        if not batch or page >= int(payload.get("page_count") or 0):
            return result
    raise RuntimeError("ozon_certificate_page_limit")


def main() -> None:
    if OUT.exists():
        raise RuntimeError("output_exists")
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assigned = [r for r in rows if "66430/26" in str(r.get("Номер/название документа") or "")
                and r.get("SHA256 фактический") == SOURCE_SHA256]
    offers: dict[str, dict] = {}
    for row in assigned:
        offer = str(row.get("Артикул продавца") or "").strip()
        if not offer:
            raise RuntimeError("assignment_missing_offer")
        offers[offer] = {"offer_id": offer, "brand_assignment": row.get("Бренд подтвержденный"),
                         "assignment_applicability": row.get("Применимость"),
                         "assignment_basis": row.get("Основание сопоставления")}
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    group = next(g for g in manifest["groups"] if norm_number(g["number"]) == norm_number(NUMBER))
    for target in group.get("targets") or []:
        offers.setdefault(str(target["offer_id"]), {"offer_id": str(target["offer_id"]),
                                                     "brand_assignment": target.get("brand"),
                                                     "assignment_applicability": "expanded current-catalog target",
                                                     "assignment_basis": target.get("scope_evidence")})
    if len(offers) != 24:
        raise RuntimeError(f"unexpected_unique_target_count:{len(offers)}")
    source = pathlib.Path(group["upload_file"]["path"])
    if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("source_file_missing_or_hash_changed")

    client = Client()
    offer_ids = sorted(offers)
    product_rows = client.call("ozon", "/v3/product/info/list", {"offer_id": offer_ids}).get("items")
    attr_rows = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": offer_ids}, "limit": len(offer_ids)
    }).get("result")
    if not isinstance(product_rows, list) or not isinstance(attr_rows, list):
        raise RuntimeError("ozon_live_product_or_attributes_incomplete")
    pmap = {str(x.get("offer_id") or ""): x for x in product_rows}
    amap = {str(x.get("offer_id") or ""): x for x in attr_rows}
    if set(pmap) != set(offer_ids) or set(amap) != set(offer_ids):
        raise RuntimeError("ozon_live_offer_set_mismatch")

    matches = [record for record in read_certificates(client)
               if norm_number(record.get("certificate_number")) == norm_number(NUMBER)
               and record.get("type_code") == "declaration"]
    certificate_ids = [int(record["certificate_id"]) for record in matches]
    if set(certificate_ids) != {5520308, 5448146}:
        raise RuntimeError("exact_ozon_record_set_changed")
    record_data = {}
    for record in matches:
        cid = int(record["certificate_id"])
        bindings = client.ozon_bindings(cid)
        record_data[str(cid)] = {"record": record, "bindings": bindings}

    product_bindings = defaultdict(list)
    for cid, details in record_data.items():
        for binding in details["bindings"]:
            product_bindings[str(binding.get("product_id") or "")].append({
                "certificate_id": cid,
                "product_status_code": binding.get("product_status_code"),
                "sku": str(binding.get("sku") or ""),
            })

    live_targets = []
    wb_count = Counter()
    for offer, assignment in sorted(offers.items()):
        product = pmap[offer]
        attr = amap[offer]
        product_id = str(product.get("product_id") or product.get("id") or "")
        sku = str(product.get("sku") or "")
        brand_values = values(attr, 85)
        tnved_values = values(attr, 22232)
        codes = tnved(tnved_values)
        bindings = product_bindings.get(product_id, [])
        ozon_matches = [b for b in bindings if b["sku"] == sku and
                        record_data[b["certificate_id"]]["record"].get("status_code") == "approved" and
                        norm_number(record_data[b["certificate_id"]]["record"].get("certificate_number")) == norm_number(NUMBER) and
                        record_data[b["certificate_id"]]["record"].get("type_code") == "declaration"]

        cards = [card for card in client.wb_cards(offer)
                 if str(card.get("vendorCode") or "") == offer]
        wb_rows = []
        for card in cards:
            docs = copy_documents(card)
            same = [doc for doc in docs if norm_number(doc.get("number")) == norm_number(NUMBER)]
            exact = (len(same) == 1 and int(same[0].get("type") or 0) == 2
                     and str(same[0].get("startDate", ""))[:10] == ISSUE
                     and str(same[0].get("endDate", ""))[:10] == EXPIRY)
            card_codes = card_tnved(card)
            wb_rows.append({"nmID": str(card.get("nmID") or ""), "brand": card.get("brand"),
                            "tnved_codes": card_codes, "documents_for_number": same,
                            "exact_metadata_present": exact,
                            "brand_matches": str(card.get("brand") or "").strip().casefold() == "iek",
                            "tnved_matches_fsa_or_blank": not card_codes or set(card_codes) <= ALLOWED_TNVED})
        wb_count[str(len(cards))] += 1
        live_targets.append({**assignment, "product_id": product_id, "sku": sku,
                             "live_name": product.get("name"), "archived": product.get("is_archived"),
                             "brand_values": brand_values, "tnved_values": tnved_values,
                             "tnved_codes": codes,
                             "ozon_identity_and_scope_match": (
                                 product_id != "" and brand_values == ["IEK"] and
                                 bool(codes and set(codes) <= ALLOWED_TNVED)),
                             "ozon_certificate_bindings": bindings,
                             "ozon_exact_approved_binding": len(ozon_matches) == 1,
                             "wb_exact_card_count": len(cards), "wb_cards": wb_rows})

    conditions = {
        "assignment_and_expanded_target_count": len(live_targets) == 24,
        "all_targets_exist_and_in_scope_on_ozon": all(
            x["ozon_identity_and_scope_match"] and x["archived"] is False for x in live_targets),
        "all_targets_exact_approved_ozon_binding": all(x["ozon_exact_approved_binding"] for x in live_targets),
        "all_targets_one_exact_wb_card": all(x["wb_exact_card_count"] == 1 for x in live_targets),
        "all_wb_target_cards_have_exact_doc_metadata": all(
            len(x["wb_cards"]) == 1 and x["wb_cards"][0]["exact_metadata_present"] for x in live_targets),
        "all_wb_targets_brand_and_tnved_safe": all(
            len(x["wb_cards"]) == 1 and x["wb_cards"][0]["brand_matches"] and
            x["wb_cards"][0]["tnved_matches_fsa_or_blank"] for x in live_targets),
    }
    output = {
        "checked_at_utc": now(), "read_only": True, "number": NUMBER,
        "official_fsa": {"record_id": FSA_ID, "status": "Действует", "issue_date": ISSUE,
                         "expiry_date": EXPIRY, "applicant": "ПАО ИЭК ХОЛДИНГ",
                         "product_scope": "IEK KARAT differential circuit breakers, types АВДТ32/АВДТ34; serial production",
                         "tnved": sorted(ALLOWED_TNVED),
                         "url": f"https://pub.fsa.gov.ru/rds/declaration/view/{FSA_ID}/product"},
        "source_file": str(source), "source_file_sha256": SOURCE_SHA256,
        "source_copy_count_in_project": 1, "assignment_row_count": len(assigned),
        "manifest_expanded_target_count": len(group.get("targets") or []),
        "unique_reconciled_target_count": len(live_targets), "ozon_records": record_data,
        "target_readbacks": live_targets, "conditions": conditions,
        "all_linkages_confirmed": all(conditions.values()),
        "local_file_deleted": False,
        "limitation": "WB API confirms exact card metadata; its read endpoint does not expose the moderation verdict.",
    }
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(OUT)
    print(json.dumps({"checked_at_utc": output["checked_at_utc"], "number": NUMBER,
                      "target_count": len(live_targets), "conditions": conditions,
                      "all_linkages_confirmed": output["all_linkages_confirmed"],
                      "ozon_record_ids": {k: {"status": v["record"].get("status_code"),
                                             "products_count": v["record"].get("products_count"),
                                             "binding_count": len(v["bindings"])} for k,v in record_data.items()},
                      "source_file_sha256": SOURCE_SHA256}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
