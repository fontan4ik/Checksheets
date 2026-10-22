"""Create the verified Arlight 06897 Ozon declaration and bind its exact 12 offers.

WB already contains one exact declaration row on every target card. This script
re-reads those rows and leaves them untouched, avoiding duplicate card metadata.
The logged-call wrapper is bypassed so authenticated headers and document bytes
are never written to api_calls.jsonl. Writes are single-shot and reconciled by
exact-number readback if a response is uncertain.
"""
from __future__ import annotations

import base64
import collections
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
    EXPIRY, NUMBER, OUT as PREFLIGHT, PDF, SOURCE_SHA256, TNVED, norm,
)

ISSUE = "2024-09-03"
FSA_URL = "https://tech.eaeunion.org/tech/registers/35-1/ru/registryList/conformityDocs/view/66d6d7ce30dcf805187f602c"
OZON_HOST = "https://api-seller.ozon.ru"
WB_HOST = "https://content-api.wildberries.ru"
WB_TNVED_CHAR_ID = 15000001
RUN = BASE / "arlight_06897_execution_20261014.json"
VERIFY = BASE / "arlight_06897_independent_readback_20261014.json"
WB_CARD_FIELDS = ("nmID", "vendorCode", "brand", "title", "gtin", "description",
                  "dimensions", "characteristics", "sizes", "kizMarked")


def save(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def direct_post(client: Client, platform: str, path: str, payload: dict | list,
                *, mutation: bool = False) -> tuple[int, dict]:
    host, headers = (OZON_HOST, client.ozon_headers) if platform == "ozon" else (WB_HOST, client.wb_headers)
    response = client.http.post(host + path, json=payload, headers=headers, timeout=(15, 120))
    try:
        body = response.json()
    except ValueError:
        body = {"non_json_response": True}
    if not mutation and response.status_code in (429, 500, 502, 503, 504):
        raise RuntimeError(f"Read response requires a bounded retry: {platform} {path} HTTP {response.status_code}")
    time.sleep(0.2 if platform == "ozon" else 0.55)
    return response.status_code, body


def live_lookup(client: Client) -> tuple[int, dict]:
    return direct_post(client, "ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER})


def list_certificates(client: Client) -> list[dict]:
    rows = []
    for page in range(1, 101):
        status, body = direct_post(client, "ozon", "/v1/product/certificate/list",
                                  {"page": page, "page_size": 100})
        if status != 200:
            raise RuntimeError(f"Ozon certificate list returned HTTP {status}")
        batch = (body.get("result") or {}).get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list is malformed")
        rows.extend(batch)
        if len(batch) < 100:
            ids = [str(x.get("certificate_id") or "") for x in rows]
            if len(ids) != len(set(ids)):
                raise RuntimeError("Ozon certificate list has repeated certificate IDs")
            return rows
    raise RuntimeError("Ozon certificate pagination exceeded 100 pages")


def live_record(client: Client, attempts: int = 1) -> dict | None:
    for attempt in range(attempts):
        status, body = live_lookup(client)
        if status == 200 and isinstance(body.get("result"), dict):
            return body["result"]
        if status == 404 and body.get("code") == 5:
            if attempt + 1 < attempts:
                time.sleep(2)
                continue
            return None
        raise RuntimeError(f"Ozon exact-number lookup is inconclusive (HTTP {status})")
    return None


def read_bindings(client: Client, certificate_id: int) -> list[dict]:
    rows = []
    expected_count = None
    last_id = 0
    seen_cursor = set()
    while True:
        status, body = direct_post(client, "ozon", "/v1/product/certificate/products/list",
                                  {"certificate_id": certificate_id, "last_id": last_id, "limit": 500})
        if status != 200:
            raise RuntimeError(f"Ozon bindings read returned HTTP {status}")
        result = body.get("result") or {}
        batch, count = result.get("items"), result.get("count")
        if not isinstance(batch, list) or not isinstance(count, int):
            raise RuntimeError("Ozon binding page omitted items/count")
        if expected_count is None:
            expected_count = count
        elif count != expected_count:
            raise RuntimeError("Ozon binding count changed during pagination")
        rows.extend(batch)
        if len(rows) == expected_count:
            pairs = [(str(x.get("product_id") or ""), str(x.get("sku") or "")) for x in rows]
            if len(pairs) != len(set(pairs)):
                raise RuntimeError("Ozon returned duplicate product/SKU binding pairs")
            return rows
        if len(rows) > expected_count or not batch:
            raise RuntimeError("Ozon binding pagination incomplete")
        next_id = max(int(x.get("product_id") or 0) for x in batch)
        if next_id <= last_id or next_id in seen_cursor:
            raise RuntimeError("Ozon binding cursor repeated")
        seen_cursor.add(next_id)
        last_id = next_id


def read_products_attrs(client: Client, offers: list[str]) -> tuple[dict[str, dict], dict[str, dict]]:
    products = {}
    status, body = direct_post(client, "ozon", "/v3/product/info/list", {"offer_id": offers})
    rows = body.get("items") or body.get("result", {}).get("items")
    if status != 200 or not isinstance(rows, list):
        raise RuntimeError(f"Ozon product identity read failed (HTTP {status})")
    for row in rows:
        offer = str(row.get("offer_id") or "")
        if offer not in offers or offer in products:
            raise RuntimeError("Ozon returned an unexpected or repeated target offer")
        products[offer] = row
    if set(products) != set(offers):
        raise RuntimeError("Ozon current target identity set is incomplete")

    status, body = direct_post(client, "ozon", "/v4/product/info/attributes",
                               {"filter": {"offer_id": offers}, "limit": 100})
    attr_rows = body.get("result") or body.get("items")
    if status != 200 or not isinstance(attr_rows, list):
        raise RuntimeError(f"Ozon product attribute read failed (HTTP {status})")
    attrs = {}
    for row in attr_rows:
        offer = str(row.get("offer_id") or "")
        if offer not in offers or offer in attrs:
            raise RuntimeError("Ozon returned an unexpected or repeated target attribute row")
        attrs[offer] = {str(x.get("id")): x for x in row.get("attributes") or []}
    if set(attrs) != set(offers):
        raise RuntimeError("Ozon current target attribute set is incomplete")
    return products, attrs


def ozon_target(products: dict[str, dict], attrs: dict[str, dict], offers: list[str]) -> list[dict]:
    rows = []
    for offer in offers:
        p = products[offer]
        brand = [str(v.get("value") or "") for v in (attrs[offer].get("85") or {}).get("values") or []]
        tnv_values = [str(v.get("value") or "") for v in (attrs[offer].get("22232") or {}).get("values") or []]
        tnv = sorted({v.split(" - ", 1)[0].strip() for v in tnv_values if v.strip()})
        pid, sku = str(p.get("id") or p.get("product_id") or ""), str(p.get("sku") or "")
        if p.get("is_archived") is not False or brand != ["Arlight"] or tnv != [TNVED] or not pid or not sku or sku == "0":
            raise RuntimeError(f"Fresh Ozon identity, brand, or scope changed for {offer}")
        rows.append({"offer_id": offer, "product_id": pid, "sku": sku,
                     "brand": brand, "tnved_codes": tnv, "name": p.get("name")})
    if len({x["product_id"] for x in rows}) != len(rows) or len({x["sku"] for x in rows}) != len(rows):
        raise RuntimeError("Fresh Ozon product ID/SKU map is ambiguous")
    return rows


def read_wb_card(client: Client, offer: str) -> dict:
    cards = []
    cursor = {"limit": 100}
    seen = set()
    for _ in range(100):
        status, body = direct_post(client, "wb", "/content/v2/get/cards/list", {"settings": {
            "sort": {"ascending": True}, "cursor": cursor,
            "filter": {"withPhoto": -1, "textSearch": offer}}})
        if status != 200 or body.get("error"):
            raise RuntimeError(f"WB card read failed for {offer} (HTTP {status})")
        batch = body.get("cards")
        if not isinstance(batch, list):
            raise RuntimeError(f"WB card list is malformed for {offer}")
        cards.extend(x for x in batch if str(x.get("vendorCode") or "") == offer)
        page = body.get("cursor") or {}
        if page.get("total") != len(batch):
            raise RuntimeError(f"WB cursor count mismatch for {offer}")
        if len(batch) < 100:
            break
        marker = (str(page.get("updatedAt") or ""), str(page.get("nmID") or ""))
        if not all(marker) or marker in seen:
            raise RuntimeError(f"WB pagination repeated or incomplete for {offer}")
        seen.add(marker)
        cursor = {"limit": 100, "updatedAt": marker[0], "nmID": int(marker[1])}
    else:
        raise RuntimeError(f"WB card pagination exceeded for {offer}")
    if len(cards) != 1:
        raise RuntimeError(f"WB target {offer} has {len(cards)} exact cards, expected one")
    return cards[0]


def validate_existing_wb_doc(card: dict, offer: str, expected_nmid: str) -> dict:
    if str(card.get("vendorCode") or "") != offer or str(card.get("nmID") or "") != expected_nmid:
        raise RuntimeError(f"WB card identity changed for {offer}")
    if card.get("brand") != "Arlight":
        raise RuntimeError(f"WB brand changed for {offer}")
    codes = sorted({str(v).split(" ", 1)[0].strip()
                    for row in card.get("characteristics") or []
                    if str(row.get("id")) == str(WB_TNVED_CHAR_ID)
                    for v in row.get("value") or [] if str(v).strip()})
    if codes != [TNVED]:
        raise RuntimeError(f"WB TN VED changed for {offer}")
    container = card.get("documents") or card.get("docs") or {}
    if container.get("excludeDocuments") is not False:
        raise RuntimeError(f"WB documents are excluded on {offer}")
    docs = [d for d in container.get("items") or [] if norm(d.get("number")) == norm(NUMBER)]
    if len(docs) != 1:
        raise RuntimeError(f"WB exact declaration count changed for {offer}")
    doc = docs[0]
    if (int(doc.get("type") or 0) != 2 or str(doc.get("startDate") or "")[:10] != ISSUE
            or str(doc.get("endDate") or "")[:10] != EXPIRY or doc.get("isEndless") is not False):
        raise RuntimeError(f"WB declaration metadata conflict for {offer}")
    verdict = doc.get("verdict") or {}
    return {"offer_id": offer, "nmID": str(card.get("nmID") or ""),
            "exact_document_present": True, "document_number": doc.get("number"),
            "type": doc.get("type"), "issue_date": str(doc.get("startDate") or "")[:10],
            "expiry_date": str(doc.get("endDate") or "")[:10],
            "verdict": verdict, "wb_mutation_needed": False}


def main() -> None:
    if RUN.exists() or VERIFY.exists():
        raise RuntimeError("Execution evidence already exists; inspect it and reconcile live state before any retry")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    checked = dt.datetime.fromisoformat(pre["checked_at_utc"])
    if (dt.datetime.now(dt.timezone.utc) - checked).total_seconds() > 600:
        raise RuntimeError("Preflight is older than ten minutes; rerun it before any write")
    if pre.get("preflight_eligible") is not True or pre.get("errors"):
        raise RuntimeError("Saved preflight does not approve this exact source group")
    if pre.get("source_assignment_count") != 12 or len(pre.get("targets") or []) != 12:
        raise RuntimeError("Expected exactly 12 evidence-backed offers")
    source = Path(pre["source_pdf"]["path"])
    if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("Official local source scan changed")
    client = Client()
    offers = [str(x["offer_id"]) for x in pre["targets"]]
    target_before = {str(x["offer_id"]): x for x in pre["targets"]}

    # Immediate pre-write reconciliation: exact number absent, live offer identities
    # still match the fresh preflight, and all WB rows already exist with exact metadata.
    products, attrs = read_products_attrs(client, offers)
    ozon_rows = ozon_target(products, attrs, offers)
    for row in ozon_rows:
        old = target_before[row["offer_id"]]
        if (row["product_id"], row["sku"]) != (old["product_id"], old["sku"]):
            raise RuntimeError("Fresh Ozon Product ID/SKU changed since preflight")
    certs = list_certificates(client)
    exact = [x for x in certs if norm(x.get("certificate_number") or x.get("number")) == norm(NUMBER)]
    lookup_status, lookup_body = live_lookup(client)
    if exact or lookup_status != 404 or lookup_body.get("code") != 5:
        raise RuntimeError("Ozon exact-number absence is no longer confirmed; reconcile before writing")

    wb_before = {}
    for offer in offers:
        card = read_wb_card(client, offer)
        wb_before[offer] = validate_existing_wb_doc(card, offer, str(target_before[offer]["wb_cards"][0]["nmID"]))

    seed = ozon_rows[0]
    expiry = dt.date.fromisoformat(EXPIRY)
    params = {
        "name": "Декларация о соответствии № BY/112 11.01. ТР037 004.02 06897",
        "certificate_type": "DECLARATION", "certificate_country": "BY",
        "accordance_type": "EAEU", "number": NUMBER,
        "issue_date": ISSUE + "T00:00:00Z",
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [seed["sku"]], "product_type": "UNKNOWN", "link_to_registry": FSA_URL,
        "files": [{"file_content": base64.b64encode(source.read_bytes()).decode("ascii"), "name": source.name}],
    }
    request = json.dumps({"params": params}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(request) >= 15_000_000:
        raise RuntimeError("Ozon request exceeds the verified payload limit")
    state = {"started_at_utc": now(), "phase": "ozon_create_prepared", "number": NUMBER,
             "official_eaeu_registry_url": FSA_URL,
             "source_pdf": {"path": str(source), "sha256": SOURCE_SHA256,
                            "bytes": source.stat().st_size},
             "target_count": len(ozon_rows), "target_offers": ozon_rows,
             "seed_sku": seed["sku"], "ozon_duplicate_check": {
                 "certificate_list_exact_matches": len(exact), "info_http_status": lookup_status,
                 "info_error_code": lookup_body.get("code")},
             "wb_existing_exact_rows": list(wb_before.values()), "wb_mutations_sent": 0,
             "ozon_create_payload_bytes": len(request),
             "ozon_create_payload_sha256": hashlib.sha256(request).hexdigest(),
             "local_cleanup_allowed": False, "mutation_attempts": 0}
    save(RUN, state)

    # Single-shot create. If response is ambiguous, only live exact-number readback
    # is used to reconcile; the script never resends create automatically.
    state.update({"phase": "ozon_create_started", "mutation_attempts": 1, "create_sent_at_utc": now()})
    save(RUN, state)
    create_status = 0
    create_body: dict = {}
    create_error = None
    try:
        create_status, create_body = direct_post(client, "ozon", "/v2/product/certificate/create",
                                                  {"params": params}, mutation=True)
    except Exception as exc:
        create_error = type(exc).__name__
    state["ozon_create_response"] = {"http_status": create_status,
                                     "certificate_id": create_body.get("certificate_id"),
                                     "status": create_body.get("status"),
                                     "params": create_body.get("params"),
                                     "error_type": create_error}
    state["phase"] = "ozon_create_response_received" if create_status else "ozon_create_uncertain_reconcile_only"
    save(RUN, state)

    record = None
    for attempt in range(6):
        record = live_record(client, attempts=1)
        if record:
            break
        if attempt < 5:
            time.sleep(2)
    if not record:
        state.update({"phase": "ozon_create_not_visible_no_retry", "finished_at_utc": now()})
        save(RUN, state)
        raise RuntimeError("Created declaration is not visible; no duplicate create was attempted")
    certificate_id = int(record["certificate_id"])
    if (str(record.get("certificate_number") or "") and norm(record.get("certificate_number")) != norm(NUMBER)):
        raise RuntimeError("Ozon exact lookup returned a conflicting certificate number")
    if (record.get("type_code") != "declaration" or str(record.get("issue_date") or "")[:10] != ISSUE
            or str(record.get("expire_date") or "")[:10] != EXPIRY):
        state.update({"phase": "ozon_record_metadata_conflict_no_bind", "certificate_id": certificate_id,
                      "record": record, "finished_at_utc": now()})
        save(RUN, state)
        raise RuntimeError("Ozon declaration type/dates differ from the official record; no binding sent")
    if record.get("status_code") in {"declined", "rejected", "cancelled", "invalid"}:
        state.update({"phase": "ozon_record_declined_no_bind", "certificate_id": certificate_id,
                      "record_status": record.get("status_code"), "finished_at_utc": now()})
        save(RUN, state)
        raise RuntimeError("Ozon declined the record; no product bindings sent")

    bindings_before = read_bindings(client, certificate_id)
    target_pairs = {(x["product_id"], x["sku"]) for x in ozon_rows}
    by_pair = {(str(x.get("product_id") or ""), str(x.get("sku") or "")): x for x in bindings_before}
    if len(by_pair) != len(bindings_before):
        raise RuntimeError("Ozon existing bindings contain duplicate product/SKU pairs")
    if set(by_pair) - target_pairs:
        raise RuntimeError("Ozon declaration has an outside binding; stop without adding targets")
    missing = sorted(set(target_pairs) - set(by_pair))
    state.update({"phase": "ozon_binding_prepared", "certificate_id": certificate_id,
                  "record_status_before_bind": record.get("status_code"),
                  "initial_binding_count": len(bindings_before), "missing_binding_count": len(missing),
                  "missing_skus": sorted(pair[1] for pair in target_pairs if pair not in by_pair)})
    save(RUN, state)
    if missing:
        missing_skus = [sku for _, sku in missing]
        state.update({"phase": "ozon_bind_started", "bind_attempts": 1, "bind_sent_at_utc": now()})
        save(RUN, state)
        bind_status, bind_body = 0, {}
        bind_error = None
        try:
            bind_status, bind_body = direct_post(client, "ozon", "/v1/product/certificate/bind",
                                                  {"certificate_id": certificate_id, "skus": missing_skus},
                                                  mutation=True)
        except Exception as exc:
            bind_error = type(exc).__name__
        state["ozon_bind_response"] = {"http_status": bind_status, "result": bind_body.get("result"),
                                       "error_type": bind_error, "requested_sku_count": len(missing_skus)}
        state["phase"] = "ozon_bind_response_received" if bind_status else "ozon_bind_uncertain_reconcile_only"
        save(RUN, state)

    # Independent live readback after create and one possible bind call.
    final_record = live_record(client, attempts=5)
    if not final_record or int(final_record.get("certificate_id") or -1) != certificate_id:
        raise RuntimeError("Ozon exact-number record readback is missing or changed")
    bindings_after = read_bindings(client, certificate_id)
    by_pair_after = {(str(x.get("product_id") or ""), str(x.get("sku") or "")): x for x in bindings_after}
    if len(by_pair_after) != len(bindings_after):
        raise RuntimeError("Ozon final readback contains duplicate product/SKU pairs")
    exact_pairs = sorted(set(by_pair_after) & target_pairs)
    outside = sorted(set(by_pair_after) - target_pairs)
    product_statuses = collections.Counter(str(by_pair_after[p].get("product_status_code") or "") for p in exact_pairs)
    state.update({"phase": "ozon_readback_complete", "record_status_after_bind": final_record.get("status_code"),
                  "total_bindings_after": len(bindings_after), "exact_target_pairs_visible": len(exact_pairs),
                  "exact_target_pairs_expected": len(target_pairs), "outside_bindings_after": outside,
                  "product_status_counts": dict(product_statuses), "finished_at_utc": now()})
    save(RUN, state)

    # WB already had the exact number/type/dates on each card. Re-read all cards
    # after Ozon's write and record the marketplace's existing validation verdict.
    wb_after = {}
    for offer in offers:
        card = read_wb_card(client, offer)
        expected_nmid = str(target_before[offer]["wb_cards"][0]["nmID"])
        wb_after[offer] = validate_existing_wb_doc(card, offer, expected_nmid)
    wb_verdicts = collections.Counter(str((x.get("verdict") or {}).get("reason") or "NO_VERDICT")
                                       for x in wb_after.values())
    wb_exact = len(wb_after) == len(offers) and all(x["exact_document_present"] for x in wb_after.values())
    verification = {
        "checked_at_utc": now(), "independent_readback": True, "document_number": NUMBER,
        "ozon": {"certificate_id": certificate_id, "record_status": final_record.get("status_code"),
                 "type_code": final_record.get("type_code"), "issue_date": str(final_record.get("issue_date") or "")[:10],
                 "expiry_date": str(final_record.get("expire_date") or "")[:10],
                 "target_pairs_visible": len(exact_pairs), "target_pairs_expected": len(target_pairs),
                 "outside_bindings": outside, "product_status_counts": dict(product_statuses),
                 "all_target_pairs_visible": len(exact_pairs) == len(target_pairs) and not outside},
        "wildberries": {"exact_cards_checked": len(wb_after), "cards_expected": len(offers),
                        "exact_document_rows_present": wb_exact, "document_row_count": len(wb_after),
                        "verdict_reasons": dict(wb_verdicts), "rows": list(wb_after.values()),
                        "mutations_sent": 0},
        "local_source": {"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                         "deleted": False},
        "local_cleanup_allowed": False,
    }
    save(VERIFY, verification)
    state.update({"phase": "verified", "independent_readback_path": str(VERIFY),
                  "ozon_all_target_pairs_visible": verification["ozon"]["all_target_pairs_visible"],
                  "wb_exact_rows_present": wb_exact, "wb_verdict_reasons": dict(wb_verdicts),
                  "local_cleanup_allowed": False, "finished_at_utc": now()})
    save(RUN, state)
    print(json.dumps({"execution": str(RUN), "verification": str(VERIFY), "phase": state["phase"],
                      "ozon": verification["ozon"], "wildberries": {k: v for k, v in verification["wildberries"].items() if k != "rows"},
                      "source_deleted": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
