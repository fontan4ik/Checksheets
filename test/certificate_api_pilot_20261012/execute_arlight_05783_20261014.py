"""Create/bind exact Arlight 05783 Ozon targets and attach to existing WB cards."""
from __future__ import annotations

import base64
import collections
import copy
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

from api_client import Client, now
from preflight_arlight_05783_20261014 import (
    EAEU_ODATA, EXPIRY, EXCLUDED_V2, ISSUE, NUMBER, OFFICIAL_PDF_URL,
    OUT as PREFLIGHT, SOURCE, SOURCE_SHA256, TNVED, WB_TNVED_CHAR_ID, norm,
)

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
RUN = BASE / "arlight_05783_execution_20261014.json"
OZON_HOST = "https://api-seller.ozon.ru"
WB_HOST = "https://content-api.wildberries.ru"
WB_UPDATE_FIELDS = ("nmID", "vendorCode", "brand", "title", "description", "dimensions",
                    "characteristics", "sizes", "kizMarked", "gtin")
DOC_FIELDS = ("id", "type", "number", "productNumber", "tradeName", "applicant",
              "startDate", "endDate", "isEndless")
DOC_READ_ONLY_FIELDS = {"verdict", "createdAt", "updatedAt"}


def save(state: dict) -> None:
    state["updated_at_utc"] = now()
    tmp = RUN.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(RUN)


def post(client: Client, platform: str, path: str, payload, *, mutation: bool = False):
    host, headers = ((OZON_HOST, client.ozon_headers) if platform == "ozon"
                     else (WB_HOST, client.wb_headers))
    response = client.http.post(host + path, json=payload, headers=headers, timeout=(15, 180))
    try:
        body = response.json()
    except ValueError:
        body = {"non_json_response": True}
    if not mutation:
        time.sleep(1.05 if platform == "wb" else 0.2)
    return response.status_code, body


def registry_record(client: Client) -> dict:
    query = urlencode({"$filter": f"docId eq '{NUMBER}'", "$top": "1"})
    response = client.http.get(EAEU_ODATA + "?" + query,
                               headers={"Accept": "application/json"}, timeout=(15, 60))
    response.raise_for_status()
    rows = response.json().get("value") or []
    if len(rows) != 1 or norm(rows[0].get("docId")) != norm(NUMBER):
        raise RuntimeError("Fresh official EAEU record is absent or ambiguous")
    record = rows[0]
    if (record.get("docStatusDetails", {}).get("docStatusCode") != "01"
            or str(record.get("docStartDate") or "")[:10] != ISSUE
            or str(record.get("docValidityDate") or "")[:10] != EXPIRY):
        raise RuntimeError("Fresh official EAEU status or dates changed")
    products = (record.get("technicalRegulationObjectDetails") or {}).get("productDetails") or []
    if TNVED not in {str(code) for p in products for code in (p.get("commodityCode") or [])}:
        raise RuntimeError("Fresh official EAEU scope no longer includes the exact Ozon TN VED code")
    return record


def read_ozon_products(client: Client, offers: list[str]):
    products = {}
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        status, body = post(client, "ozon", "/v3/product/info/list", {"offer_id": batch})
        rows = body.get("items") or (body.get("result") or {}).get("items")
        if status != 200 or not isinstance(rows, list):
            raise RuntimeError(f"Ozon product identity read returned HTTP {status}")
        for row in rows:
            offer = str(row.get("offer_id") or "")
            if offer not in batch or offer in products:
                raise RuntimeError("Ozon product read returned an unexpected or duplicate offer")
            products[offer] = row
    if set(products) != set(offers):
        raise RuntimeError(f"Ozon product identity read incomplete: {len(products)}/{len(offers)}")

    status, body = post(client, "ozon", "/v4/product/info/attributes",
                        {"filter": {"offer_id": offers}, "limit": 100})
    rows = body.get("result") or body.get("items")
    if status != 200 or not isinstance(rows, list):
        raise RuntimeError(f"Ozon attributes read returned HTTP {status}")
    attrs = {}
    for row in rows:
        offer = str(row.get("offer_id") or "")
        if offer not in offers or offer in attrs:
            raise RuntimeError("Ozon attributes returned an unexpected or duplicate offer")
        attrs[offer] = row
    if set(attrs) != set(offers):
        raise RuntimeError(f"Ozon attributes read incomplete: {len(attrs)}/{len(offers)}")
    return products, attrs


def values(row: dict, attribute_id: str) -> list[str]:
    return [str(v.get("value") or "") for a in (row.get("attributes") or [])
            if str(a.get("id")) == attribute_id for v in (a.get("values") or [])
            if v.get("value") not in (None, "")]


def read_certificates(client: Client) -> list[dict]:
    rows = []
    for page in range(1, 101):
        status, body = post(client, "ozon", "/v1/product/certificate/list",
                            {"page": page, "page_size": 100})
        batch = (body.get("result") or {}).get("certificates")
        if status != 200 or not isinstance(batch, list):
            raise RuntimeError(f"Ozon certificate list returned HTTP {status}")
        rows.extend(batch)
        if len(batch) < 100:
            return rows
    raise RuntimeError("Ozon certificate list exceeded 100 pages")


def read_ozon_number(client: Client) -> dict:
    status, body = post(client, "ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER})
    if status == 404 and body.get("code") == 5:
        return {"http_status": status, "exact_record_absent": True}
    if status == 200 and isinstance(body.get("result"), dict):
        record = body["result"]
        return {"http_status": status, "exact_record_absent": False,
                "certificate_id": str(record.get("certificate_id") or ""),
                "certificate_number": record.get("certificate_number"),
                "status_code": record.get("status_code"), "type_code": record.get("type_code"),
                "accordance_type_code": record.get("accordance_type_code"),
                "issue_date": record.get("issue_date"), "expire_date": record.get("expire_date")}
    return {"http_status": status, "exact_record_absent": False,
            "error_code": body.get("code"), "message": str(body.get("message") or "")[:250]}


def read_bindings(client: Client, certificate_id: int) -> list[dict]:
    items, last_id, expected, seen = [], 0, None, set()
    while True:
        status, body = post(client, "ozon", "/v1/product/certificate/products/list", {
            "certificate_id": certificate_id, "last_id": last_id, "limit": 1000,
        })
        result = body.get("result") or {}
        batch, count = result.get("items"), result.get("count")
        if status != 200 or not isinstance(batch, list) or not isinstance(count, int):
            raise RuntimeError(f"Ozon binding read returned HTTP {status} or malformed data")
        if expected is None:
            expected = count
        elif expected != count:
            raise RuntimeError("Ozon binding count changed while paging")
        for row in batch:
            pid = str(row.get("product_id") or "")
            if not pid or pid in seen:
                raise RuntimeError("Ozon bindings contain a missing or repeated product ID")
            seen.add(pid)
        items.extend(batch)
        if len(items) == expected:
            return items
        if not batch or len(items) > expected:
            raise RuntimeError("Ozon binding pagination is incomplete")
        last_id = int(batch[-1]["product_id"])


def read_wb_cards(client: Client, offer: str) -> list[dict]:
    cards, cursor, seen = [], {"limit": 100}, set()
    for _ in range(100):
        status, body = post(client, "wb", "/content/v2/get/cards/list", {"settings": {
            "sort": {"ascending": True}, "cursor": cursor,
            "filter": {"withPhoto": -1, "textSearch": offer},
        }})
        if status != 200 or body.get("error") or not isinstance(body.get("cards"), list):
            raise RuntimeError(f"WB exact full-card read returned HTTP {status} for {offer}")
        batch, returned = body["cards"], body.get("cursor") or {}
        if returned.get("total") != len(batch):
            raise RuntimeError(f"WB card cursor count mismatch for {offer}")
        cards.extend(c for c in batch if str(c.get("vendorCode") or "") == offer)
        if len(batch) < 100:
            return cards
        signature = (str(returned.get("updatedAt") or ""), str(returned.get("nmID") or ""))
        if not all(signature) or signature in seen:
            raise RuntimeError(f"WB card pagination repeated for {offer}")
        seen.add(signature)
        cursor = {"limit": 100, "updatedAt": signature[0], "nmID": int(signature[1])}
    raise RuntimeError(f"WB card pagination exceeded for {offer}")


def clean_docs(card: dict) -> list[dict]:
    docs = (card.get("documents") or {}).get("items") or []
    out = []
    for row in docs:
        unknown = set(row) - set(DOC_FIELDS) - DOC_READ_ONLY_FIELDS
        if unknown:
            raise RuntimeError("WB document row has unknown fields: " + ", ".join(sorted(unknown)))
        out.append({key: copy.deepcopy(row[key]) for key in DOC_FIELDS if key in row})
    return out


def card_payload(card: dict) -> dict:
    payload = {key: copy.deepcopy(card[key]) for key in WB_UPDATE_FIELDS if key in card}
    required = set(WB_UPDATE_FIELDS[:-1])
    if required - payload.keys():
        raise RuntimeError("WB card missing fields required for full update: " + ", ".join(sorted(required - payload.keys())))
    docs = (card.get("documents") or card.get("docs") or {})
    if docs.get("excludeDocuments") is True:
        raise RuntimeError("WB card began excluding documents; stop and reconcile before edit")
    declaration = {"type": 2, "number": NUMBER, "startDate": ISSUE + "T00:00:00Z",
                   "endDate": EXPIRY + "T00:00:00Z", "isEndless": False}
    payload["documents"] = {"items": clean_docs(card) + [declaration], "excludeDocuments": False}
    return payload


def wb_codes(card: dict) -> list[str]:
    return sorted({str(v).split(" ", 1)[0].strip()
                   for c in (card.get("characteristics") or [])
                   if str(c.get("id")) == WB_TNVED_CHAR_ID
                   for v in (c.get("value") or []) if str(v).strip()})


def main() -> None:
    if RUN.exists():
        raise RuntimeError("Execution journal already exists; reconcile it before any retry")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if pre.get("eligible_for_write") is not True or pre.get("errors") or pre.get("complete") is not True:
        raise RuntimeError("Fresh preflight does not authorize the exact write set")
    checked = dt.datetime.fromisoformat(pre["checked_at_utc"])
    if (dt.datetime.now(dt.timezone.utc) - checked).total_seconds() > 600:
        raise RuntimeError("Preflight is more than ten minutes old; rerun before write")
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("Local official PDF has changed since preflight")

    targets = pre["targets"]
    if len(targets) != 21 or len({x["offer_id"] for x in targets}) != 21:
        raise RuntimeError("Preflight does not contain 21 exact unique Ozon targets")
    if {x["offer_id"] for x in pre.get("excluded_v2", [])} - EXCLUDED_V2:
        raise RuntimeError("Unexpected revision-(2) exclusion row appeared")

    client = Client()
    registry = registry_record(client)
    offers = sorted(x["offer_id"] for x in targets)
    products, attrs = read_ozon_products(client, offers)
    current = []
    for old in targets:
        offer = old["offer_id"]
        product, attr = products[offer], attrs[offer]
        pid, sku = str(product.get("id") or product.get("product_id") or ""), str(product.get("sku") or "")
        brand = values(attr, "85")
        tnved_values = values(attr, "22232")
        codes = sorted({v.split(" - ", 1)[0].strip() for v in tnved_values if v.strip()})
        if (pid != old["product_id"] or sku != old["sku"] or product.get("is_archived") is not False
                or brand != ["Arlight"] or codes != [TNVED]):
            raise RuntimeError("Fresh Ozon identity/scope changed for " + offer)
        current.append({"offer_id": offer, "product_id": pid, "sku": sku,
                        "name": product.get("name"), "brand_values": brand, "tnved_codes": codes})

    certs = read_certificates(client)
    exact_certs = [c for c in certs if norm(c.get("certificate_number") or c.get("number")) == norm(NUMBER)]
    exact_lookup = read_ozon_number(client)
    if exact_certs or not exact_lookup.get("exact_record_absent"):
        raise RuntimeError("Ozon exact 05783 record appeared after preflight; reconcile without creating another")

    wb_payloads, wb_before = [], []
    pre_by_offer = {x["offer_id"]: x for x in targets}
    for target in targets:
        offer = target["offer_id"]
        cards = read_wb_cards(client, offer)
        expected_cards = target.get("wb_cards") or []
        if len(cards) != len(expected_cards):
            raise RuntimeError(f"WB card count changed for {offer}: {len(expected_cards)} -> {len(cards)}")
        if not cards:
            continue  # In particular, do not create missing WB card 039022(1)-1.
        if len(cards) != 1 or len(expected_cards) != 1:
            raise RuntimeError("WB exact vendor code became ambiguous: " + offer)
        card = cards[0]
        prior = expected_cards[0]
        if str(card.get("nmID") or "") != prior["nmID"] or card.get("brand") != "Arlight":
            raise RuntimeError("WB card identity or brand changed for " + offer)
        if wb_codes(card) != [TNVED]:
            raise RuntimeError("WB card TN VED changed or is ambiguous for " + offer)
        doc_container = card.get("documents") or card.get("docs") or {}
        existing = doc_container.get("items") or []
        if any(norm(d.get("number")) == norm(NUMBER) for d in existing):
            raise RuntimeError("WB 05783 row appeared after preflight; reconcile before write: " + offer)
        payload = card_payload(card)
        wb_payloads.append(payload)
        wb_before.append({"offer_id": offer, "nmID": str(card["nmID"]), "card_before": card,
                          "payload_sha256": hashlib.sha256(json.dumps(
                              payload, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")).encode()).hexdigest()})
    if len(wb_payloads) != 20 or len(wb_before) != 20:
        raise RuntimeError(f"Expected exactly 20 existing WB cards; prepared {len(wb_payloads)}")

    sku_by_offer = {x["offer_id"]: x["sku"] for x in current}
    if len(set(sku_by_offer.values())) != 21 or "0" in sku_by_offer.values():
        raise RuntimeError("Ozon target SKU set is duplicated or contains zero")
    registry_url = ("https://tech.eaeunion.org/tech/registers/35-1/ru/registryList/"
                    "conformityDocs/view/" + str(registry.get("Id")) + "/common")
    expiry = dt.date.fromisoformat(EXPIRY)
    seed_offer = offers[0]
    params = {
        "name": "Декларация о соответствии № BY/112 11.01. ТР037 004.02 05783",
        "certificate_type": "DECLARATION", "certificate_country": "BY",
        "accordance_type": "EAEU", "number": NUMBER,
        "issue_date": ISSUE + "T00:00:00Z",
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [sku_by_offer[seed_offer]], "product_type": "UNKNOWN",
        "link_to_registry": registry_url,
        "files": [{"file_content": base64.b64encode(SOURCE.read_bytes()).decode("ascii"),
                   "name": SOURCE.name}],
    }
    create_body_bytes = json.dumps({"params": params}, ensure_ascii=False,
                                   separators=(",", ":")).encode("utf-8")
    if len(create_body_bytes) >= 15_000_000:
        raise RuntimeError("Ozon upload payload exceeds the verified request size")

    state = {
        "started_at_utc": now(), "phase": "prewrite_verified", "number": NUMBER,
        "official_registry_url": registry_url, "official_registry_status": "01",
        "source_pdf": {"path": str(SOURCE), "sha256": SOURCE_SHA256,
                       "bytes": SOURCE.stat().st_size},
        "ozon_target_count": len(current), "ozon_targets": current,
        "ozon_exact_prewrite_absent": True, "wb_target_count": len(wb_payloads),
        "wb_missing_exact_offer": "039022(1)-1", "wb_payloads": wb_payloads,
        "wb_before": wb_before, "excluded_revision_2_offers": sorted(EXCLUDED_V2),
        "ozon_create_payload_bytes": len(create_body_bytes),
        "ozon_create_payload_sha256": hashlib.sha256(create_body_bytes).hexdigest(),
        "ozon_create_attempts": 0, "wb_update_attempts": 0,
        "local_cleanup_allowed": False,
    }
    save(state)

    state.update({"phase": "ozon_create_sent", "ozon_create_attempts": 1,
                  "ozon_create_sent_at_utc": now()})
    save(state)
    create_status, create_response, create_error = 0, {}, None
    try:
        create_status, create_response = post(client, "ozon", "/v2/product/certificate/create",
                                             {"params": params}, mutation=True)
    except Exception as exc:
        create_error = type(exc).__name__
    state["ozon_create_response"] = {
        "http_status": create_status, "certificate_id": create_response.get("certificate_id"),
        "status": create_response.get("status"), "params": create_response.get("params"),
        "error_type": create_error,
    }
    state["phase"] = "ozon_create_response_received" if create_status else "ozon_create_uncertain_reconcile_only"
    save(state)

    record = None
    for attempt in range(6):
        lookup = read_ozon_number(client)
        if not lookup.get("exact_record_absent") and lookup.get("certificate_id"):
            record = lookup
            break
        if attempt < 5:
            time.sleep(2)
    if not record:
        state.update({"phase": "ozon_create_not_visible_no_retry", "ozon_exact_record_after": lookup})
        save(state)
        raise RuntimeError("Ozon create is not independently visible; stopped without resending")
    if (norm(record.get("certificate_number")) != norm(NUMBER)
            or record.get("type_code") not in {"declaration", "declaration_of_conformity"}
            or str(record.get("accordance_type_code") or "").upper() != "EAEU"
            or str(record.get("issue_date") or "")[:10] != ISSUE
            or str(record.get("expire_date") or "")[:10] != EXPIRY
            or str(record.get("status_code") or "").lower() in {"declined", "rejected", "cancelled", "invalid"}):
        state.update({"phase": "ozon_create_record_conflict", "ozon_exact_record_after": record})
        save(state)
        raise RuntimeError("Ozon exact record has an unexpected identity, dates, type, or status")
    certificate_id = int(record["certificate_id"])
    bindings_before = read_bindings(client, certificate_id)
    desired_pairs = {(x["product_id"], x["sku"]) for x in current}
    seen_pairs = [(str(x.get("product_id") or ""), str(x.get("sku") or "")) for x in bindings_before]
    if len(seen_pairs) != len(set(seen_pairs)) or set(seen_pairs) - desired_pairs:
        state.update({"phase": "ozon_initial_binding_conflict", "certificate_id": certificate_id,
                      "ozon_initial_bindings": bindings_before})
        save(state)
        raise RuntimeError("Ozon record contains duplicate or out-of-scope bindings")
    bound_pairs = set(seen_pairs)
    missing_skus = [sku for pid, sku in sorted(desired_pairs) if (pid, sku) not in bound_pairs]
    state.update({"phase": "ozon_bind_prepared", "certificate_id": certificate_id,
                  "ozon_record_status": record.get("status_code"),
                  "ozon_initial_binding_count": len(bindings_before),
                  "ozon_missing_binding_count": len(missing_skus),
                  "ozon_missing_skus": missing_skus})
    save(state)
    if missing_skus:
        state.update({"phase": "ozon_bind_sent", "ozon_bind_attempts": 1,
                      "ozon_bind_sent_at_utc": now()})
        save(state)
        bind_status, bind_response, bind_error = 0, {}, None
        try:
            bind_status, bind_response = post(client, "ozon", "/v1/product/certificate/bind",
                                              {"certificate_id": certificate_id, "skus": missing_skus},
                                              mutation=True)
        except Exception as exc:
            bind_error = type(exc).__name__
        state["ozon_bind_response"] = {"http_status": bind_status,
                                       "result": bind_response.get("result"),
                                       "error_type": bind_error,
                                       "requested_sku_count": len(missing_skus)}
        save(state)
    bindings_after = read_bindings(client, certificate_id)
    after_pairs = [(str(x.get("product_id") or ""), str(x.get("sku") or "")) for x in bindings_after]
    if len(after_pairs) != len(set(after_pairs)) or set(after_pairs) != desired_pairs:
        state.update({"phase": "ozon_binding_readback_incomplete", "ozon_bindings_after": bindings_after,
                      "ozon_binding_pair_count": len(set(after_pairs)),
                      "ozon_expected_pair_count": len(desired_pairs)})
        save(state)
        raise RuntimeError("Ozon post-bind readback does not contain exactly all 21 target pairs")
    state.update({"phase": "ozon_bindings_verified", "ozon_bindings_after": bindings_after,
                  "ozon_binding_pair_count": len(set(after_pairs)),
                  "ozon_binding_status_counts": dict(collections.Counter(
                      str(x.get("product_status_code") or x.get("status") or "UNKNOWN")
                      for x in bindings_after))})
    save(state)

    # One full-card update preserves all existing card fields and document rows.
    payload_hash = hashlib.sha256(json.dumps(wb_payloads, ensure_ascii=False, sort_keys=True,
                                             separators=(",", ":")).encode()).hexdigest()
    if len(wb_payloads) != 20 or payload_hash != hashlib.sha256(json.dumps(
            state["wb_payloads"], ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest():
        raise RuntimeError("WB payload count/hash changed before mutation")
    state.update({"phase": "wb_update_sent", "wb_update_attempts": 1,
                  "wb_update_sent_at_utc": now(), "wb_payload_sha256": payload_hash})
    save(state)
    wb_status, wb_response, wb_error = 0, {}, None
    try:
        wb_status, wb_response = post(client, "wb", "/content/v2/cards/update", wb_payloads, mutation=True)
    except Exception as exc:
        wb_error = type(exc).__name__
    state["wb_update_response"] = {"http_status": wb_status, "error": wb_response.get("error"),
                                   "errorText": wb_response.get("errorText"),
                                   "additionalErrors": wb_response.get("additionalErrors"),
                                   "error_type": wb_error}
    state["phase"] = "wb_update_response_received" if wb_status else "wb_update_uncertain_reconcile_only"
    save(state)

    wb_readback = []
    for before in wb_before:
        offer = before["offer_id"]
        cards = read_wb_cards(client, offer)
        if len(cards) != 1 or str(cards[0].get("nmID") or "") != before["nmID"]:
            wb_readback.append({"offer_id": offer, "nmID": before["nmID"],
                                "card_count": len(cards), "row_count": 0, "verdicts": []})
            continue
        card = cards[0]
        docs = (card.get("documents") or card.get("docs") or {}).get("items") or []
        rows = [d for d in docs if int(d.get("type") or 0) == 2 and norm(d.get("number")) == norm(NUMBER)]
        exact = [d for d in rows if str(d.get("startDate") or "")[:10] == ISSUE
                 and str(d.get("endDate") or "")[:10] == EXPIRY]
        verdicts = [((d.get("verdict") or {}).get("status"),
                     (d.get("verdict") or {}).get("reason")) for d in rows]
        wb_readback.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                            "row_count": len(rows), "exact_metadata_count": len(exact),
                            "verdicts": verdicts,
                            "excludeDocuments": (card.get("documents") or card.get("docs") or {}).get("excludeDocuments"),
                            "tnved_codes": wb_codes(card)})
    state.update({"phase": "wb_immediate_readback_complete", "wb_readback": wb_readback,
                  "wb_exact_row_count": sum(x.get("exact_metadata_count") == 1 for x in wb_readback),
                  "wb_review_remains_pending": True, "local_cleanup_allowed": False,
                  "finished_at_utc": now()})
    save(state)
    print(json.dumps({"phase": state["phase"], "number": NUMBER,
                      "certificate_id": certificate_id,
                      "ozon_exact_pairs": state["ozon_binding_pair_count"],
                      "ozon_binding_status_counts": state["ozon_binding_status_counts"],
                      "wb_cards_updated": len(wb_payloads),
                      "wb_exact_rows_immediate": state["wb_exact_row_count"],
                      "wb_update_http_status": wb_status,
                      "wb_error": wb_response.get("error"),
                      "local_cleanup_allowed": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
