"""Safely add Arlight declaration 41382/26 to exact WB cards missing it.

The certificate 00356/26 is intentionally excluded: its production-date limit
cannot be verified for the individual lots. All reads and writes here bypass
the shared API body log; the result file contains only audit evidence needed
for reconciliation.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
import sys
import time
from pathlib import Path

from api_client import Client, now

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
PLAN = BASE / "all_groups_wb_gap_plan_20261014.json"
OZON_CATALOG = BASE / "ozon_catalog_scoped_recheck_20261014.json"
OZON_LIVE = BASE / "ozon_live_recheck_20261014.json"
FSA_PREFLIGHT = BASE / "arlight_41382_ozon_preflight_scoped_20261012.json"
FSA_CERTIFICATE = BASE / "arlight_41382_ozon_preflight_scoped_20261012.json"
OUTPUT = BASE / "arlight_41382_declaration_wb_execution_20261014.json"
NUMBER = "ЕАЭС N RU Д-RU.РА08.В.41382/26"
CERTIFICATE_ID = "5625289"
ISSUE = "2026-09-16"
EXPIRY = "2031-09-15"
ALLOWED_CODES = {"9405110013", "9405110033", "9405110039", "9405420039"}
ALLOWED_FAMILIES = {"SP", "IM", "MS", "LTD", "LGD", "DL", "ALT", "CL", "LT", "LTM"}
WB_UPDATE_FIELDS = (
    "nmID", "vendorCode", "brand", "title", "description", "dimensions",
    "characteristics", "sizes", "kizMarked", "gtin",
)
DOC_CHARACTERISTIC_IDS = {15001135, 15001136, 15001137, 15001138}
DOC_FIELDS = ("id", "type", "number", "productNumber", "tradeName", "applicant",
              "startDate", "endDate", "isEndless")
DOC_READ_ONLY_FIELDS = {"verdict", "createdAt", "updatedAt"}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def norm_number(value: str) -> str:
    text = re.sub(r"^(?:ЕАЭС|EAEU|EAEC|EAC)\s*", "", str(value or "").strip().upper())
    text = re.sub(r"^(?:N|№)\s*", "", text)
    table = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "H",
                           "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
                           "У": "Y", "Х": "X", "Ё": "E", "Э": "E", "Д": "D",
                           "П": "P"})
    return "".join(ch for ch in text.translate(table) if ch.isalnum())


def api(client: Client, platform: str, path: str, payload: dict, *, mutation=False):
    host, headers = (("https://api-seller.ozon.ru", client.ozon_headers)
                    if platform == "ozon" else
                    ("https://content-api.wildberries.ru", client.wb_headers))
    response = client.http.post(host + path, json=payload, headers=headers, timeout=(15, 120))
    if response.status_code != 200:
        try:
            body = response.json()
        except ValueError:
            body = {}
        raise ApiFailure(platform, path, response.status_code, body)
    try:
        body = response.json()
    except ValueError:
        raise RuntimeError(f"{platform} {path} returned a non-JSON response") from None
    if platform == "wb":
        time.sleep(0.66)
    else:
        time.sleep(0.21)
    return body


class ApiFailure(RuntimeError):
    def __init__(self, platform, path, status, body):
        super().__init__(f"{platform} {path} returned HTTP {status}")
        self.platform, self.path, self.status, self.body = platform, path, status, body


def read_ozon_bindings(client: Client, cert_id: int) -> list[dict]:
    result, last_id, expected = [], 0, None
    seen = set()
    while True:
        body = api(client, "ozon", "/v1/product/certificate/products/list", {
            "certificate_id": cert_id, "last_id": last_id, "limit": 1000,
        })
        page = body.get("result") or {}
        batch, count = page.get("items"), page.get("count")
        if not isinstance(batch, list) or not isinstance(count, int):
            raise RuntimeError("Ozon binding response is incomplete")
        if expected is None:
            expected = count
        elif count != expected:
            raise RuntimeError("Ozon binding count changed during pagination")
        for row in batch:
            product_id = str(row.get("product_id") or "")
            if not product_id or product_id in seen:
                raise RuntimeError("Ozon binding page contains a missing or repeated product_id")
            seen.add(product_id)
        result.extend(batch)
        if len(result) == expected:
            return result
        if not batch or len(result) > expected:
            raise RuntimeError("Ozon binding pagination did not complete")
        last_id = batch[-1]["product_id"]


def read_exact_wb_cards(client: Client, offer: str) -> list[dict]:
    cards, cursor, seen = [], {"limit": 100}, set()
    while True:
        body = api(client, "wb", "/content/v2/get/cards/list", {"settings": {
            "sort": {"ascending": True}, "cursor": cursor,
            "filter": {"withPhoto": -1, "textSearch": offer},
        }})
        if body.get("error") or not isinstance(body.get("cards"), list):
            raise RuntimeError(f"WB exact-card read failed for {offer}")
        batch = body["cards"]
        cursor_out = body.get("cursor") or {}
        if cursor_out.get("total") != len(batch):
            raise RuntimeError(f"WB cursor count mismatch for {offer}")
        cards.extend(card for card in batch if card.get("vendorCode") == offer)
        if len(batch) < 100:
            return cards
        signature = (cursor_out.get("updatedAt"), cursor_out.get("nmID"))
        if None in signature or signature in seen:
            raise RuntimeError(f"WB pagination repeated or incomplete for {offer}")
        seen.add(signature)
        cursor = {"limit": 100, "updatedAt": signature[0], "nmID": signature[1]}


def card_doc_items(card: dict) -> list[dict]:
    value = (card.get("documents") or {}).get("items") or []
    if not isinstance(value, list):
        raise RuntimeError("WB card documents.items is not a list")
    return value


def wb_key(doc: dict):
    return int(doc.get("type", 0)), norm_number(doc.get("number", ""))


def card_payload(card: dict, declaration: dict) -> dict:
    payload = {key: copy.deepcopy(card[key]) for key in WB_UPDATE_FIELDS if key in card}
    if not {"nmID", "vendorCode"}.issubset(payload):
        raise RuntimeError("WB card is missing required identity fields")
    required = set(WB_UPDATE_FIELDS[:-1])
    if required - payload.keys():
        raise RuntimeError("WB card omitted fields required for a full-card update: "
                           + ", ".join(sorted(required - payload.keys())))
    docs_obj = card.get("documents") or {}
    if docs_obj.get("excludeDocuments") is True:
        raise RuntimeError("WB card explicitly excludes documents; refusing to override")
    cleaned_docs = []
    for item in card_doc_items(card):
        unknown = set(item) - set(DOC_FIELDS) - DOC_READ_ONLY_FIELDS
        if unknown:
            raise RuntimeError("WB document row contains unknown fields: " + ", ".join(sorted(unknown)))
        cleaned_docs.append({key: copy.deepcopy(item[key]) for key in DOC_FIELDS if key in item})
    payload["documents"] = {
        "items": cleaned_docs + [declaration],
        "excludeDocuments": bool(docs_obj.get("excludeDocuments", False)),
    }
    return payload


def comparable(card: dict) -> dict:
    out = {k: v for k, v in card.items() if k not in {"documents", "updatedAt"}}
    characteristics = [x for x in (card.get("characteristics") or [])
                       if x.get("id") not in DOC_CHARACTERISTIC_IDS]
    out["characteristics"] = sorted(characteristics, key=lambda x: x.get("id", 0))
    return out


def concise_document(doc: dict) -> dict:
    return {k: doc.get(k) for k in ("type", "number", "startDate", "endDate", "isEndless", "verdict")
            if k in doc}


def main(execute: bool) -> None:
    plan, catalog, live = load(PLAN), load(OZON_CATALOG), load(OZON_LIVE)
    source = load(FSA_PREFLIGHT)
    if not (catalog.get("complete") and live.get("complete")):
        raise RuntimeError("Complete current Ozon snapshots are required")
    cert = next((x for x in live.get("certificates", [])
                 if str(x.get("certificate_id")) == CERTIFICATE_ID), None)
    if not cert or cert.get("status_code") != "approved":
        raise RuntimeError("Expected approved Ozon declaration is not present in the fresh snapshot")
    if norm_number(cert.get("certificate_number")) != norm_number(NUMBER):
        raise RuntimeError("Ozon certificate ID and declaration number do not match")
    if cert.get("type_code") != "declaration" or cert.get("accordance_type_code") != "EAEU":
        raise RuntimeError("Ozon declaration type or accordance type changed")
    if cert.get("issue_date", "")[:10] != ISSUE or cert.get("expire_date", "")[:10] != EXPIRY:
        raise RuntimeError("Ozon declaration dates differ from the official FSA record")

    source_targets = {x["offer_id"]: x for x in source.get("targets", [])
                      if x.get("tnved_in_scope") is True}
    catalog_by_offer = {x["offer_id"]: x for x in catalog.get("products", [])}
    target_rows = [x for x in plan.get("updates", [])
                   if any(int(d.get("type", 0)) == 2 and norm_number(d.get("number")) == norm_number(NUMBER)
                          for d in x.get("additions", []))]
    if len(target_rows) != 62 or len({x.get("offer_id") for x in target_rows}) != 62:
        raise RuntimeError(f"Expected 62 unique declaration candidates; found {len(target_rows)}")
    source_file = Path(source["source_file"])
    if not source_file.is_file() or hashlib.sha256(source_file.read_bytes()).hexdigest() != source.get("source_sha256"):
        raise RuntimeError("Official-source declaration file changed; refusing WB attachment")
    if source.get("fsa_record_id") != 21895502 or source.get("fsa_status") != "Действует":
        raise RuntimeError("Official FSA record evidence is not current/active")
    if set(source.get("fsa_tnved_codes", [])) != ALLOWED_CODES:
        raise RuntimeError("FSA TN VED codes do not match the verified scope")
    if not source.get("official_manufacturer_download_verified") or source.get("source_map_issues"):
        raise RuntimeError("Manufacturer source mapping is not fully verified")

    client = Client()
    info_body = api(client, "ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER})
    info = info_body.get("result") or {}
    if (str(info.get("certificate_id")) != CERTIFICATE_ID
            or info.get("status_code", info.get("certificate_status")) != "approved"
            or norm_number(info.get("certificate_number")) != norm_number(NUMBER)):
        raise RuntimeError("Fresh Ozon certificate detail does not confirm the expected approved declaration")
    bindings = read_ozon_bindings(client, int(CERTIFICATE_ID))
    binding_by_identity = {(str(x.get("sku")), str(x.get("product_id"))): x for x in bindings}
    if len(binding_by_identity) != len(bindings):
        raise RuntimeError("Duplicate Ozon binding identities returned")

    prepared = []
    issues = []
    for row in target_rows:
        offer = row["offer_id"]
        src = source_targets.get(offer)
        product = catalog_by_offer.get(offer)
        if not src or not product:
            issues.append({"offer_id": offer, "reason": "missing exact manufacturer or current Ozon product match"})
            continue
        families = set(src.get("model_families", []))
        codes = {str(v).split(" - ", 1)[0].strip() for v in product.get("tnved_values", [])}
        brands = {str(v).split(" - ", 1)[0].strip().casefold() for v in product.get("brand_values", [])}
        if (not families or not families.issubset(ALLOWED_FAMILIES) or "arlight" not in brands
                or not (codes & ALLOWED_CODES) or str(src.get("wb_nmID")) != str(row.get("nmID"))):
            issues.append({"offer_id": offer, "reason": "current product family, brand, TN VED, or WB identity drift"})
            continue
        sku, product_id = str(row.get("sku")), str(row.get("product_id"))
        binding = binding_by_identity.get((sku, product_id))
        if not binding or binding.get("product_status_code") != "approved":
            issues.append({"offer_id": offer, "reason": "current Ozon approved declaration binding missing"})
            continue

        exact_cards = read_exact_wb_cards(client, offer)
        if len(exact_cards) != 1:
            issues.append({"offer_id": offer, "reason": f"expected one exact WB card, found {len(exact_cards)}"})
            continue
        card = exact_cards[0]
        if str(card.get("nmID")) != str(row.get("nmID")):
            issues.append({"offer_id": offer, "reason": "exact WB card nmID changed"})
            continue
        exact_doc = {"type": 2, "number": NUMBER, "startDate": ISSUE + "T00:00:00Z",
                     "endDate": EXPIRY + "T00:00:00Z", "isEndless": False}
        existing = card_doc_items(card)
        same_number = [d for d in existing if norm_number(d.get("number")) == norm_number(NUMBER)]
        if same_number:
            matching = [d for d in same_number if int(d.get("type", 0)) == 2
                        and str(d.get("startDate", ""))[:10] == ISSUE
                        and str(d.get("endDate", ""))[:10] == EXPIRY]
            if matching and len(matching) == len(same_number):
                prepared.append({"offer_id": offer, "sku": sku, "product_id": product_id,
                                 "nmID": card.get("nmID"), "before": card,
                                 "state": "already_present", "payload": None,
                                 "expected": exact_doc})
                continue
            issues.append({"offer_id": offer, "reason": "same declaration number exists with conflicting type or dates"})
            continue
        try:
            payload = card_payload(card, exact_doc)
        except RuntimeError as exc:
            issues.append({"offer_id": offer, "reason": str(exc)})
            continue
        prepared.append({"offer_id": offer, "sku": sku, "product_id": product_id,
                         "nmID": card.get("nmID"), "before": card,
                         "state": "ready", "payload": payload, "expected": exact_doc})

    if issues or len(prepared) != 62:
        OUTPUT.write_text(json.dumps({"checked_at": now(), "state": "blocked_preflight",
            "target_count": 62, "prepared_count": len(prepared), "issues": issues},
            ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError(f"Preflight blocked: {len(issues)} issue(s); no WB mutation sent")

    writes = [x for x in prepared if x["state"] == "ready"]
    state = {"checked_at": now(), "state": "preflight_passed", "number": NUMBER,
             "ozon_certificate_id": CERTIFICATE_ID, "ozon_certificate_status": "approved",
             "fsa_record_id": 21895502, "target_count": 62,
             "already_present_count": len(prepared) - len(writes), "planned_write_count": len(writes),
             "certificate_00356_excluded": True,
             "exclusion_reason": "FSA production date starts 07.2026; individual item lot dates are unknown",
             "issues": [], "results": []}
    if not execute:
        OUTPUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in state.items() if k != "results"}, ensure_ascii=False))
        return

    if OUTPUT.exists():
        prior = load(OUTPUT)
        recovery_path = BASE / "arlight_41382_declaration_wb_after_400_readback_20261014.json"
        recovery = load(recovery_path) if recovery_path.exists() else {}
        if (prior.get("state") != "mutation_sent"
                or recovery.get("exact_card_count") != 62
                or recovery.get("declaration_visible_count") != 0):
            raise RuntimeError("Prior WB attempt exists without a complete zero-change exact readback; refusing retry")
        state["previous_attempts"] = [{"http_status": 400,
                                       "exact_card_count": 62,
                                       "declaration_visible_count": 0,
                                       "reconciled_at": recovery.get("checked_at")}]

    if writes:
        payload = [x["payload"] for x in writes]
        request_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
        if len(payload) > 3000 or request_bytes > 10_000_000:
            raise RuntimeError("WB request exceeds documented limits; no mutation sent")
        state["state"] = "mutation_sent"
        state["mutation_started_at"] = now()
        state["mutation_card_count"] = len(payload)
        state["mutation_request_bytes"] = request_bytes
        OUTPUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        # This is a single non-retried mutation. Any uncertain response is reconciled by exact reads.
        try:
            response = api(client, "wb", "/content/v2/cards/update", payload, mutation=True)
        except ApiFailure as exc:
            body = exc.body if isinstance(exc.body, dict) else {}
            state["mutation_response"] = {"http_status": exc.status,
                **{k: body.get(k) for k in ("error", "errorText", "additionalErrors", "data") if k in body}}
            state["mutation_finished_at"] = now()
            state["state"] = "response_needs_reconciliation"
            OUTPUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            raise RuntimeError(f"WB rejected update with HTTP {exc.status}; response saved for diagnosis") from None
        state["mutation_response"] = {k: response.get(k) for k in ("error", "errorText", "additionalErrors", "data") if k in response}
        state["mutation_finished_at"] = now()
        state["state"] = "accepted_readback_pending" if response.get("error") is False else "response_needs_reconciliation"
        OUTPUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        if response.get("error") is not False:
            raise RuntimeError("WB response was not accepted; exact live reconciliation required before retry")

    results = []
    all_visible = True
    all_fields_preserved = True
    all_old_docs_preserved = True
    for row in prepared:
        card_after_rows = read_exact_wb_cards(client, row["offer_id"])
        after = card_after_rows[0] if len(card_after_rows) == 1 else None
        expected = row["expected"]
        visible = bool(after) and any(
            wb_key(doc) == (2, norm_number(NUMBER))
            and str(doc.get("startDate", ""))[:10] == ISSUE
            and str(doc.get("endDate", ""))[:10] == EXPIRY
            for doc in card_doc_items(after))
        fields_preserved = bool(after) and comparable(row["before"]) == comparable(after)
        before_docs = {wb_key(d): d for d in card_doc_items(row["before"])}
        after_docs = {wb_key(d): d for d in card_doc_items(after or {})}
        old_docs_preserved = all(
            key in after_docs
            and str(after_docs[key].get("startDate", ""))[:10] == str(doc.get("startDate", ""))[:10]
            and str(after_docs[key].get("endDate", ""))[:10] == str(doc.get("endDate", ""))[:10]
            for key, doc in before_docs.items())
        verdict = next((d.get("verdict") for d in card_doc_items(after or {})
                        if wb_key(d) == (2, norm_number(NUMBER))), None)
        all_visible &= visible
        all_fields_preserved &= fields_preserved
        all_old_docs_preserved &= old_docs_preserved
        results.append({"offer_id": row["offer_id"], "sku": row["sku"], "product_id": row["product_id"],
                        "nmID": row["nmID"], "previously_present": row["state"] == "already_present",
                        "declaration_visible": visible, "unrelated_fields_preserved": fields_preserved,
                        "preexisting_documents_preserved": old_docs_preserved,
                        "exclude_documents_after": ((after or {}).get("documents") or {}).get("excludeDocuments"),
                        "declaration_verdict": verdict,
                        "before_documents": [concise_document(d) for d in card_doc_items(row["before"])],
                        "after_documents": [concise_document(d) for d in card_doc_items(after or {})]})
    state["checked_at"] = now()
    state["state"] = ("readback_complete_pending_wb_review" if all_visible and all_fields_preserved and all_old_docs_preserved
                       else "readback_needs_review")
    state["readback"] = {"cards_checked": len(results), "all_declarations_visible": all_visible,
                         "all_unrelated_fields_preserved": all_fields_preserved,
                         "all_preexisting_documents_preserved": all_old_docs_preserved,
                         "verdict_counts": {str(v): sum(1 for r in results if r["declaration_verdict"] == v)
                                            for v in {str(r["declaration_verdict"]) for r in results}},
                         "results": results}
    OUTPUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in state.items() if k != "readback"}, ensure_ascii=False))
    print(json.dumps({k: v for k, v in state.get("readback", {}).items() if k != "results"}, ensure_ascii=False))


if __name__ == "__main__":
    main(execute="--execute" in sys.argv[1:])
