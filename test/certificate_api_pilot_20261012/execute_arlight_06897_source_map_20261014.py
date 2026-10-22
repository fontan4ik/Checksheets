"""Bind all verified Arlight 06897 offers on Ozon and attach rows on WB."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE))
from api_client import Client, now  # noqa: E402
from preflight_arlight_06897_exact_20261014 import (  # noqa: E402
    EXPIRY, ISSUE, NUMBER, SOURCE_SHA256, TNVED, api_post as ozon_post,
    live_ozon_number_lookup, norm, read_ozon_certificates, read_ozon_offers,
)

PREFLIGHT = BASE / "arlight_06897_source_map_live_preflight_20261014.json"
PRIOR_PREFLIGHT = BASE / "arlight_06897_exact_live_preflight_20261014.json"
RUN = BASE / "arlight_06897_source_map_execution_20261014.json"
WB_RUN = BASE / "arlight_06897_source_map_wb_readback_20261014.json"
PDF = ROOT / "output_to_user/certificates/group_1/documents/arlight/5F2ED782CCE4CB4CBA510758C10E647A.pdf"
CERTIFICATE_ID = 5664376
OZON_HOST = "https://api-seller.ozon.ru"
WB_HOST = "https://content-api.wildberries.ru"
WB_UPDATE_FIELDS = ("nmID", "vendorCode", "brand", "title", "description", "dimensions",
                    "characteristics", "sizes", "kizMarked", "gtin")
DOC_FIELDS = ("id", "type", "number", "productNumber", "tradeName", "applicant",
              "startDate", "endDate", "isEndless")
DOC_READ_ONLY_FIELDS = {"verdict", "createdAt", "updatedAt"}
DOC_CHARACTERISTIC_IDS = {15001135, 15001136, 15001137, 15001138}
WB_TNVED_CHAR_ID = 15000001


def save(path: Path, value: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def direct_post(client: Client, platform: str, path: str, payload, *, mutation=False):
    host, headers = ((OZON_HOST, client.ozon_headers) if platform == "ozon"
                     else (WB_HOST, client.wb_headers))
    response = client.http.post(host + path, json=payload, headers=headers, timeout=(15, 180))
    try:
        body = response.json()
    except ValueError:
        body = {"non_json_response": True}
    if not mutation and platform == "ozon":
        time.sleep(0.2)
    return response.status_code, body


def wb_read(client: Client, path: str, payload: dict) -> tuple[int, dict]:
    for attempt in range(7):
        status, body = direct_post(client, "wb", path, payload)
        if status == 429 or status in (500, 502, 503, 504):
            if attempt == 6:
                raise RuntimeError(f"WB read remained transient after retries: HTTP {status}")
            delay = min(60.0, 2.0 ** (attempt + 1))
            print(f"WB read HTTP {status}; waiting {delay:g}s", flush=True)
            time.sleep(delay)
            continue
        time.sleep(1.05)
        return status, body
    raise RuntimeError("Unreachable WB read retry state")


def read_bindings(client: Client) -> list[dict]:
    rows, last_id, count, seen = [], 0, None, set()
    while True:
        status, body = ozon_post(client, "ozon", "/v1/product/certificate/products/list",
                                 {"certificate_id": CERTIFICATE_ID, "last_id": last_id, "limit": 500})
        if status != 200:
            raise RuntimeError(f"Ozon binding read failed: HTTP {status}")
        result = body.get("result") or {}
        batch, current_count = result.get("items"), result.get("count")
        if not isinstance(batch, list) or not isinstance(current_count, int):
            raise RuntimeError("Ozon binding response omitted items/count")
        if count is None:
            count = current_count
        elif count != current_count:
            raise RuntimeError("Ozon binding count changed during readback")
        rows.extend(batch)
        if len(rows) == count:
            pairs = [(str(x.get("product_id") or ""), str(x.get("sku") or "")) for x in rows]
            if len(pairs) != len(set(pairs)):
                raise RuntimeError("Ozon returned duplicate binding pairs")
            return rows
        if len(rows) > count or not batch:
            raise RuntimeError("Ozon binding pagination incomplete")
        next_id = max(int(x.get("product_id") or 0) for x in batch)
        if next_id <= last_id or next_id in seen:
            raise RuntimeError("Ozon binding cursor repeated")
        seen.add(next_id)
        last_id = next_id


def read_one_wb_card(client: Client, offer: str) -> dict:
    cards, cursor, seen = [], {"limit": 100}, set()
    for _ in range(100):
        status, body = wb_read(client, "/content/v2/get/cards/list", {"settings": {
            "sort": {"ascending": True}, "cursor": cursor,
            "filter": {"withPhoto": -1, "textSearch": offer}}})
        if status != 200 or body.get("error") or not isinstance(body.get("cards"), list):
            raise RuntimeError(f"WB card read failed for {offer}: HTTP {status}")
        batch = body["cards"]
        page = body.get("cursor") or {}
        if page.get("total") != len(batch):
            raise RuntimeError(f"WB cursor count mismatch for {offer}")
        cards.extend(x for x in batch if str(x.get("vendorCode") or "") == offer)
        if len(batch) < 100:
            break
        marker = (str(page.get("updatedAt") or ""), str(page.get("nmID") or ""))
        if not all(marker) or marker in seen:
            raise RuntimeError(f"WB cursor repeated or incomplete for {offer}")
        seen.add(marker)
        cursor = {"limit": 100, "updatedAt": marker[0], "nmID": int(marker[1])}
    else:
        raise RuntimeError(f"WB card pagination exceeded for {offer}")
    if len(cards) != 1:
        raise RuntimeError(f"Expected exactly one WB card for {offer}, found {len(cards)}")
    return cards[0]


def card_docs(card: dict) -> list[dict]:
    docs = (card.get("documents") or {}).get("items") or []
    if not isinstance(docs, list):
        raise RuntimeError("WB documents.items is malformed")
    return docs


def card_payload(card: dict) -> dict:
    payload = {key: copy.deepcopy(card[key]) for key in WB_UPDATE_FIELDS if key in card}
    required = set(WB_UPDATE_FIELDS[:-1])
    if required - payload.keys():
        raise RuntimeError("WB full-card payload omitted required fields: " + ", ".join(sorted(required - payload.keys())))
    docs_container = card.get("documents") or {}
    existing = card_docs(card)
    if any(norm(d.get("number")) == norm(NUMBER) for d in existing):
        raise RuntimeError("WB declaration appeared after preflight; refresh exact card before changing")
    cleaned = []
    for doc in existing:
        unknown = set(doc) - set(DOC_FIELDS) - DOC_READ_ONLY_FIELDS
        if unknown:
            raise RuntimeError("WB document contains unsupported fields: " + ", ".join(sorted(unknown)))
        cleaned.append({key: copy.deepcopy(doc[key]) for key in DOC_FIELDS if key in doc})
    declaration = {"type": 2, "number": NUMBER, "startDate": ISSUE + "T00:00:00Z",
                   "endDate": EXPIRY + "T00:00:00Z", "isEndless": False}
    payload["documents"] = {"items": cleaned + [declaration], "excludeDocuments": False}
    return payload


def comparable_card(card: dict) -> dict:
    result = {k: v for k, v in card.items() if k not in {"documents", "updatedAt"}}
    result["characteristics"] = sorted(
        [x for x in card.get("characteristics") or [] if x.get("id") not in DOC_CHARACTERISTIC_IDS],
        key=lambda x: x.get("id", 0))
    return result


def tnv_codes(card: dict) -> list[str]:
    return sorted({str(v).split(" ", 1)[0].strip()
                   for ch in card.get("characteristics") or []
                   if str(ch.get("id")) == str(WB_TNVED_CHAR_ID)
                   for v in ch.get("value") or [] if str(v).strip()})


def main() -> None:
    if RUN.exists() or WB_RUN.exists():
        raise RuntimeError("An execution/readback artifact already exists; reconcile live state before retry")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    prior = json.loads(PRIOR_PREFLIGHT.read_text(encoding="utf-8"))
    checked = dt.datetime.fromisoformat(pre["checked_at_utc"])
    if (dt.datetime.now(dt.timezone.utc) - checked).total_seconds() > 600:
        raise RuntimeError("WB preflight is older than ten minutes; rerun it before writing")
    if (pre.get("complete") is not True or pre.get("marketplace_mutation_allowed") is not True
            or pre.get("both_ready_count") != 491 or pre.get("source_count") != 491
            or pre.get("ozon_missing_binding_count") != 491
            or pre.get("wb_mutation_needed_count") != 491):
        raise RuntimeError("Full 491-offer preflight did not authorize the exact batch")
    if hashlib.sha256(PDF.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("Local official declaration PDF changed")
    targets = pre["targets"]
    offers = [str(x["offer_id"]) for x in targets]
    if len(offers) != 491 or len(set(offers)) != 491:
        raise RuntimeError("Offer list is not 491 unique source-mapped rows")
    prior_pairs = {(str(x["product_id"]), str(x["sku"])) for x in prior["targets"]}
    if len(prior_pairs) != 12 or prior.get("number") != NUMBER:
        raise RuntimeError("Earlier verified 12-offer group is absent or inconsistent")

    client = Client()
    products, attrs = read_ozon_offers(client, offers)
    current_rows = []
    for target in targets:
        offer = target["offer_id"]
        product, row_attrs = products[offer], attrs[offer]
        brand = [str(v.get("value") or "") for v in (row_attrs.get("85") or {}).get("values") or []]
        raw_tnv = [str(v.get("value") or "") for v in (row_attrs.get("22232") or {}).get("values") or []]
        codes = sorted({v.split(" - ", 1)[0].strip() for v in raw_tnv if v.strip()})
        pid = str(product.get("id") or product.get("product_id") or "")
        sku = str(product.get("sku") or "")
        if (pid, sku) != (target["product_id"], target["sku"]) or product.get("is_archived") is not False:
            raise RuntimeError(f"Ozon target identity/active status changed for {offer}")
        if brand != ["Arlight"] or codes != [TNVED]:
            raise RuntimeError(f"Ozon brand or TN VED changed for {offer}")
        current_rows.append({"offer_id": offer, "product_id": pid, "sku": sku,
                             "brand": brand, "tnved_codes": codes})
    if len({x["sku"] for x in current_rows}) != 491:
        raise RuntimeError("Ozon SKU set is not unique")

    certs = read_ozon_certificates(client)
    exact = [x for x in certs if norm(x.get("certificate_number") or x.get("number")) == norm(NUMBER)]
    lookup = live_ozon_number_lookup(client)
    if (len(exact) != 1 or int(exact[0].get("certificate_id") or -1) != CERTIFICATE_ID
            or lookup.get("exact_record_absent") is not False
            or int(lookup.get("certificate_id") or -1) != CERTIFICATE_ID
            or lookup.get("status_code") != "approved" or lookup.get("type_code") != "declaration"
            or str(lookup.get("issue_date") or "")[:10] != ISSUE
            or str(lookup.get("expire_date") or "")[:10] != EXPIRY):
        raise RuntimeError("Ozon 06897 declaration record changed or is not approved")
    before = read_bindings(client)
    before_pairs = {(str(x.get("product_id") or ""), str(x.get("sku") or "")) for x in before}
    if before_pairs != prior_pairs:
        raise RuntimeError("Ozon existing 12 bindings differ from the previously verified exact group")
    desired_pairs = {(x["product_id"], x["sku"]) for x in current_rows}
    if desired_pairs & before_pairs:
        raise RuntimeError("Some proposed 491 SKUs became bound after preflight; reconcile before writing")
    if len(current_rows) > 500:
        raise RuntimeError("Ozon bind request exceeds the guarded 500-SKU batch")

    wb_payloads, wb_before = [], []
    for i, target in enumerate(targets, 1):
        card_rows = target.get("wb_cards") or []
        if len(card_rows) != 1 or target.get("wb_ready") is not True or target.get("wb_blockers"):
            raise RuntimeError(f"WB preflight target is not uniquely safe: {target['offer_id']}")
        card = card_rows[0].get("wb_card_raw")
        if not isinstance(card, dict):
            raise RuntimeError(f"Full WB card is missing for {target['offer_id']}")
        if (str(card.get("nmID") or "") != str(card_rows[0]["nmID"])
                or str(card.get("vendorCode") or "") != target["offer_id"]
                or card.get("brand") != "Arlight" or tnv_codes(card) != [TNVED]):
            raise RuntimeError(f"WB identity/brand/TN VED changed inside saved card {target['offer_id']}")
        if target.get("wb_document_present") is not False:
            raise RuntimeError(f"WB 06897 row appeared after preflight for {target['offer_id']}")
        payload = card_payload(card)
        if any(payload.get(k) != card.get(k) for k in WB_UPDATE_FIELDS if k in card):
            raise RuntimeError(f"WB update payload changes an unrelated field for {target['offer_id']}")
        wb_payloads.append(payload)
        wb_before.append({"offer_id": target["offer_id"], "nmID": str(card["nmID"]),
                          "card_before": card, "payload_sha256": hashlib.sha256(
                              json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()})
        if i % 100 == 0:
            print(f"Prepared {i}/491 full WB card payloads", flush=True)
    encoded_wb = json.dumps(wb_payloads, ensure_ascii=False, separators=(",", ":")).encode()
    if len(wb_payloads) != 491 or len(encoded_wb) > 10_000_000:
        raise RuntimeError("WB full-card payload count/size exceeds the guarded limit")
    wb_sha = hashlib.sha256(encoded_wb).hexdigest()

    run = {"started_at_utc": now(), "phase": "ozon_bind_prepared", "number": NUMBER,
           "certificate_id": CERTIFICATE_ID, "source_pdf_sha256": SOURCE_SHA256,
           "ozon_bind_target_count": len(current_rows), "ozon_prior_binding_count": len(before),
           "ozon_prior_pairs": sorted([list(x) for x in before_pairs]),
           "ozon_target_rows": current_rows, "ozon_prewrite_lookup": lookup,
           "wb_target_count": len(wb_payloads), "wb_payload_bytes": len(encoded_wb),
           "wb_payload_sha256": wb_sha, "wb_payloads": wb_payloads, "wb_before": wb_before,
           "wb_documents_added": len(wb_payloads), "wb_excludeDocuments_set_false": sum(
               1 for x in targets if x["wb_cards"][0]["excludeDocuments"] is True),
           "local_cleanup_allowed": False}
    save(RUN, run)

    run.update({"phase": "ozon_bind_sent", "ozon_bind_sent_at_utc": now(), "ozon_bind_attempts": 1})
    save(RUN, run)
    bind_status, bind_body, bind_error = 0, {}, None
    try:
        bind_status, bind_body = direct_post(client, "ozon", "/v1/product/certificate/bind",
                                             {"certificate_id": CERTIFICATE_ID,
                                              "skus": [x["sku"] for x in current_rows]}, mutation=True)
    except Exception as exc:
        bind_error = type(exc).__name__
    run["ozon_bind_response"] = {"http_status": bind_status,
                                "result": bind_body.get("result"), "error_type": bind_error}
    run["phase"] = "ozon_bind_response_received" if bind_status else "ozon_bind_uncertain_reconcile_only"
    save(RUN, run)

    record_after = live_ozon_number_lookup(client)
    bindings_after = read_bindings(client)
    after_pairs = {(str(x.get("product_id") or ""), str(x.get("sku") or "")) for x in bindings_after}
    expected_pairs = prior_pairs | desired_pairs
    if record_after.get("certificate_id") != CERTIFICATE_ID or after_pairs != expected_pairs:
        run.update({"phase": "ozon_bind_readback_incomplete", "ozon_record_after": record_after,
                    "ozon_binding_count_after": len(bindings_after),
                    "ozon_binding_pairs_after": sorted([list(x) for x in after_pairs]),
                    "local_cleanup_allowed": False})
        save(RUN, run)
        raise RuntimeError("Ozon binding readback differs from all 503 exact product/SKU pairs")
    run.update({"phase": "ozon_bind_verified", "ozon_record_after": record_after,
                "ozon_binding_count_after": len(bindings_after),
                "ozon_binding_status_counts": dict(__import__("collections").Counter(
                    str(x.get("product_status_code") or x.get("status") or "UNKNOWN") for x in bindings_after)),
                "ozon_new_target_statuses": [{"product_id": str(x.get("product_id") or ""),
                                               "sku": str(x.get("sku") or ""),
                                               "status": x.get("product_status_code") or x.get("status")}
                                              for x in bindings_after if (str(x.get("product_id") or ""),
                                                                          str(x.get("sku") or "")) in desired_pairs],
                "ozon_readback_exact_pair_count": len(after_pairs), "local_cleanup_allowed": False})
    save(RUN, run)
    print(json.dumps({k: v for k, v in run.items() if k not in ("wb_payloads", "wb_before", "ozon_target_rows", "ozon_new_target_statuses", "ozon_binding_pairs_after")}, ensure_ascii=False, indent=2), flush=True)

    # The single batched full-card edit is safe only after Ozon's independent exact readback.
    run.update({"phase": "wb_update_prepared", "wb_mutation_attempts": 0,
                "wb_payload_sha256_rechecked": hashlib.sha256(encoded_wb).hexdigest()})
    if run["wb_payload_sha256_rechecked"] != wb_sha:
        raise RuntimeError("WB payload hash changed before write")
    save(RUN, run)
    run.update({"phase": "wb_update_sent", "wb_mutation_attempts": 1, "wb_update_sent_at_utc": now()})
    save(RUN, run)
    wb_status, wb_body, wb_error = 0, {}, None
    try:
        wb_status, wb_body = direct_post(client, "wb", "/content/v2/cards/update", wb_payloads, mutation=True)
    except Exception as exc:
        wb_error = type(exc).__name__
    run["wb_update_response"] = {"http_status": wb_status,
                                "error": wb_body.get("error"), "errorText": wb_body.get("errorText"),
                                "additionalErrors": wb_body.get("additionalErrors"),
                                "error_type": wb_error}
    run["phase"] = "wb_update_response_received" if wb_status else "wb_update_uncertain_reconcile_only"
    save(RUN, run)
    if wb_status != 200 or wb_body.get("error") is not False:
        raise RuntimeError("WB did not confirm the 491-card update; reconcile exact cards before retry")

    results = []
    for i, row in enumerate(wb_before, 1):
        offer, before_card = row["offer_id"], row["card_before"]
        after = read_one_wb_card(client, offer)
        docs = card_docs(after)
        matches = [d for d in docs if norm(d.get("number")) == norm(NUMBER)]
        visible = (len(matches) == 1 and int(matches[0].get("type") or 0) == 2
                   and str(matches[0].get("startDate") or "")[:10] == ISSUE
                   and str(matches[0].get("endDate") or "")[:10] == EXPIRY
                   and matches[0].get("isEndless") is False)
        preserved = comparable_card(before_card) == comparable_card(after)
        result = {"offer_id": offer, "nmID": str(after.get("nmID") or ""),
                  "declaration_visible": visible, "all_other_card_fields_preserved": preserved,
                  "excludeDocuments": (after.get("documents") or {}).get("excludeDocuments"),
                  "verdict": matches[0].get("verdict") if matches else None,
                  "document_rows": [{k: d.get(k) for k in ("type", "number", "startDate", "endDate", "isEndless", "verdict") if k in d}
                                    for d in docs]}
        results.append(result)
        if i % 10 == 0 or i == len(wb_before):
            summary = {"checked_at_utc": now(), "complete": False, "completed": i,
                       "results": results, "local_cleanup_allowed": False}
            save(WB_RUN, summary)
            print(f"WB exact readback {i}/491", flush=True)

    doc_visible_count = sum(x["declaration_visible"] for x in results)
    preserved_count = sum(x["all_other_card_fields_preserved"] for x in results)
    flag_count = sum(x["excludeDocuments"] is False for x in results)
    verdicts = __import__("collections").Counter(
        str((x.get("verdict") or {}).get("reason") or (x.get("verdict") or {}).get("status") or "NO_VERDICT")
        for x in results)
    final = {"checked_at_utc": now(), "complete": True, "number": NUMBER,
             "wb_target_count": len(results), "declaration_visible_count": doc_visible_count,
             "all_other_card_fields_preserved_count": preserved_count,
             "excludeDocuments_false_count": flag_count, "wb_verdict_counts": dict(verdicts),
             "results": results,
             "state": ("readback_complete_pending_wb_review"
                       if doc_visible_count == len(results) and preserved_count == len(results)
                       and flag_count == len(results) else "readback_needs_reconciliation"),
             "local_cleanup_allowed": False}
    save(WB_RUN, final)
    run.update({"phase": "both_marketplaces_bound_wb_review_pending" if final["state"] == "readback_complete_pending_wb_review"
                else "wb_readback_needs_reconciliation",
                "wb_readback_state": final["state"], "wb_declaration_visible_count": doc_visible_count,
                "wb_other_fields_preserved_count": preserved_count, "wb_verdict_counts": dict(verdicts),
                "finished_at_utc": now(), "local_cleanup_allowed": False})
    save(RUN, run)
    print(json.dumps({k: v for k, v in final.items() if k != "results"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
