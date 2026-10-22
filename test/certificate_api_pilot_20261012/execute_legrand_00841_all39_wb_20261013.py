"""Correct the old marketplace spelling on exact Legrand 00841 WB cards."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from api_client import Client, now, save  # noqa: E402
from feron_53483_crossplatform_20261013 import CARD_FIELDS, clean_wb_doc, norm  # noqa: E402

ROOT = BASE.parents[1]
SUMMARY = ROOT / "output_to_user/certificates/group_3/article_summary.csv"
LOCAL_PDF = ROOT / "output_to_user/certificates/group_3/docs/legrand_RX3_TX3_EAC-FR.02.00841.pdf"
PREFLIGHT = BASE / "legrand_00841_all39_preflight_20261013.json"
OUT = "legrand_00841_all39_wb_execution_20261013.json"
NUMBER = "ЕАЭС KG 417/032.FR.02.00841"
OLD_NUMBER = "EAC KG 417/032.FR.02.00841"
CERTIFICATE_ID = "5458718"
ISSUE = "2025-10-28"
EXPIRY = "2030-10-27"
TNVED = "8536201007"
DOC_NUMBER_CHAR_ID = 15001136


def listed_certificates(client: Client) -> list[dict]:
    items = []
    for page in range(1, 20):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result", {})
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Malformed Ozon certificate list")
        items.extend(batch)
        if len(batch) < 100:
            return items
    raise RuntimeError("Ozon certificate pagination exceeded limit")


def same_characteristics_except_number(before: list[dict], after: list[dict]) -> bool:
    def by_id(rows: list[dict]) -> dict[str, list[dict]]:
        grouped: dict[str, list[dict]] = collections.defaultdict(list)
        for row in rows:
            grouped[str(row.get("id"))].append(row)
        return {key: sorted(value, key=lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True))
                for key, value in grouped.items()}

    before_map = by_id(before)
    after_map = by_id(after)
    if set(before_map) != set(after_map):
        return False
    for char_id in before_map:
        if char_id == str(DOC_NUMBER_CHAR_ID):
            b, a = before_map[char_id], after_map[char_id]
            if len(b) != 1 or len(a) != 1:
                return False
            expected = dict(b[0])
            expected["value"] = [NUMBER]
            if a[0] != expected:
                return False
        elif before_map[char_id] != after_map[char_id]:
            return False
    return True


def main() -> None:
    out_path = BASE / OUT
    if out_path.exists():
        raise RuntimeError("Execution journal exists; reconcile it before any further write")
    if not LOCAL_PDF.is_file():
        raise RuntimeError("Official local source PDF is missing")
    pdf_hash = hashlib.sha256(LOCAL_PDF.read_bytes()).hexdigest()
    with SUMMARY.open(encoding="utf-8-sig", newline="") as stream:
        rows = [r for r in csv.DictReader(stream) if r.get("Документ/номер") == "EAC-FR.02.00841"]
    if len(rows) != 39 or len({r["Артикул продавца"] for r in rows}) != 39:
        raise RuntimeError("Local exact offer mapping changed")
    offers = [r["Артикул продавца"] for r in rows]
    expected = {r["Артикул продавца"]: {
        "product_id": str(r["Ozon Product ID"]), "sku": str(r["Ozon SKU"])} for r in rows}
    client = Client()

    # Refresh all Ozon identities and attributes immediately before any WB update.
    response = client.call("ozon", "/v3/product/info/list", {"offer_id": offers})
    products = response.get("items") or response.get("result", {}).get("items")
    if not isinstance(products, list) or len(products) != len(offers):
        raise RuntimeError("Fresh Ozon product response is incomplete")
    by_offer = {str(p.get("offer_id") or ""): p for p in products}
    if set(by_offer) != set(offers) or len(by_offer) != len(offers):
        raise RuntimeError("Fresh Ozon offers are missing or duplicated")
    attr_response = client.call("ozon", "/v4/product/info/attributes",
                                {"filter": {"offer_id": offers}, "limit": 100})
    attr_rows = attr_response.get("result") or attr_response.get("items")
    if not isinstance(attr_rows, list) or {str(x.get("offer_id")) for x in attr_rows} != set(offers):
        raise RuntimeError("Fresh Ozon attributes are incomplete")
    attrs = {str(x["offer_id"]): {str(a.get("id")): a for a in x.get("attributes") or []}
             for x in attr_rows}

    cert_matches = [x for x in listed_certificates(client)
                    if str(x.get("certificate_id")) == CERTIFICATE_ID]
    if (len(cert_matches) != 1 or cert_matches[0].get("status_code") != "approved"
            or cert_matches[0].get("type_code") != "certificate_of_conformity"):
        raise RuntimeError("Ozon certificate status or type changed")
    bindings = client.ozon_bindings(int(CERTIFICATE_ID))
    by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for binding in bindings:
        by_sku[str(binding.get("sku") or "")].append(binding)
    for offer, identity in expected.items():
        product = by_offer[offer]
        if (str(product.get("id") or product.get("product_id") or "") != identity["product_id"]
                or str(product.get("sku") or "") != identity["sku"] or product.get("is_archived")):
            raise RuntimeError("Ozon product identity/status changed: " + offer)
        brand_values = [str(x.get("value") or "") for x in (attrs[offer].get("85") or {}).get("values") or []]
        tnved_values = [str(x.get("value") or "") for x in (attrs[offer].get("22232") or {}).get("values") or []]
        codes = sorted({x.split(" - ", 1)[0].strip() for x in tnved_values if x.strip()})
        exact = by_sku.get(identity["sku"], [])
        if brand_values != ["Legrand"] or codes != [TNVED]:
            raise RuntimeError("Ozon brand/TN VED changed: " + offer)
        if (len(exact) != 1 or str(exact[0].get("product_id")) != identity["product_id"]
                or exact[0].get("product_status_code") != "approved"):
            raise RuntimeError("Ozon exact approved binding changed: " + offer)

    targets = []
    payloads = []
    before_cards = {}
    for row in rows:
        offer = row["Артикул продавца"]
        cards = client.wb_cards(offer)
        if len(cards) != 1 or str(cards[0].get("vendorCode") or "") != offer:
            raise RuntimeError("WB exact card missing/duplicated: " + offer)
        card = cards[0]
        nm_id = str(card.get("nmID") or "")
        if not nm_id or card.get("brand") != "Legrand":
            raise RuntimeError("WB identity/brand changed: " + offer)
        tnved = sorted({str(v).strip().split(" ", 1)[0]
                        for ch in card.get("characteristics") or []
                        if int(ch.get("id") or -1) == 15000001
                        for v in ch.get("value") or [] if str(v).strip()})
        if tnved != [TNVED]:
            raise RuntimeError("WB TN VED changed: " + offer)
        docs = card.get("documents") or card.get("docs") or {}
        if docs.get("excludeDocuments") is not False:
            raise RuntimeError("WB card excludes documents: " + offer)
        items = docs.get("items") or []
        matches = [d for d in items if int(d.get("type") or 0) == 1
                   and str(d.get("number") or "") in (OLD_NUMBER, NUMBER)]
        if len(matches) != 1:
            raise RuntimeError("WB 00841 row missing/duplicated: " + offer)
        old_doc = matches[0]
        if (str(old_doc.get("startDate") or "")[:10] != ISSUE
                or str(old_doc.get("endDate") or "")[:10] != EXPIRY):
            raise RuntimeError("WB document dates changed: " + offer)
        char_rows = [x for x in card.get("characteristics") or []
                     if int(x.get("id") or -1) == DOC_NUMBER_CHAR_ID]
        if len(char_rows) != 1 or char_rows[0].get("value") not in ([OLD_NUMBER], [NUMBER]):
            raise RuntimeError("WB number characteristic missing/conflicting: " + offer)
        state = old_doc.get("verdict") or {}
        is_valid = (old_doc.get("number") == NUMBER and state.get("verified") is True
                    and state.get("status") == 1 and state.get("reason") == "valid")
        targets.append({"offer": offer, "product_id": expected[offer]["product_id"],
                        "sku": expected[offer]["sku"], "nmID": nm_id,
                        "before_number": old_doc.get("number"), "before_verdict": state,
                        "already_valid": is_valid, "preserved_document_count": len(items)})
        if is_valid:
            continue
        if not all(k in card for k in CARD_FIELDS[:-1]):
            raise RuntimeError("WB full-card fields missing: " + offer)
        new_items = []
        for item in items:
            clean = clean_wb_doc(item)
            if clean.get("type") == 1 and clean.get("number") == old_doc.get("number"):
                clean["number"] = NUMBER
            new_items.append(clean)
        payload = {k: card[k] for k in CARD_FIELDS if k in card}
        payload["documents"] = {"items": new_items, "excludeDocuments": False}
        payload["characteristics"] = [
            ({**x, "value": [NUMBER]} if int(x.get("id") or -1) == DOC_NUMBER_CHAR_ID else x)
            for x in card.get("characteristics") or []
        ]
        if not same_characteristics_except_number(card.get("characteristics") or [], payload["characteristics"]):
            raise RuntimeError("Prepared characteristics change fields beyond document number: " + offer)
        for key in CARD_FIELDS:
            if key not in ("characteristics",) and key in card and payload.get(key) != card.get(key):
                raise RuntimeError("Prepared card changes unrelated field " + key + ": " + offer)
        payloads.append(payload)
        before_cards[offer] = card

    if not payloads:
        result = {"checked_at_utc": now(), "phase": "already_complete", "target_count": len(targets),
                  "mutation_attempts": 0, "targets": targets}
        save(OUT, result)
        print(json.dumps({"phase": result["phase"], "targets": len(targets)}, ensure_ascii=False))
        return
    payload_bytes = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode()
    if len(payloads) > 3000 or len(payload_bytes) > 10_000_000:
        raise RuntimeError("WB batch exceeds documented limit")
    state = {"prepared_at_utc": now(), "phase": "prepared", "source_sha256": hashlib.sha256(LOCAL_PDF.read_bytes()).hexdigest(),
             "official_source_url": "https://assets.legrand.com/pim/Certif/LGNOBFKRPB.PDF",
             "certificate_id": CERTIFICATE_ID, "certificate_status": "approved", "number": NUMBER,
             "old_number": OLD_NUMBER, "dates": {"issue": ISSUE, "expiry": EXPIRY},
             "target_count": len(targets), "to_correct": len(payloads), "already_valid": len(targets)-len(payloads),
             "ozon_binding_status_counts": {"approved": len(bindings)}, "targets": targets,
             "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(), "payload_bytes": len(payload_bytes),
             "mutation_attempts": 0, "response": None, "readback": None,
             "before_cards": before_cards}
    save(OUT, state)
    state.update({"phase": "mutation_started", "mutation_attempts": 1, "sent_at_utc": now()})
    save(OUT, state)
    try:
        response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
    except Exception as exc:
        state.update({"phase": "mutation_uncertain", "error_type": type(exc).__name__, "finished_at_utc": now()})
        save(OUT, state)
        raise RuntimeError("WB result uncertain; read cards before considering any retry") from None
    state["response"] = response
    if response.get("error") is not False:
        state.update({"phase": "rejected_readback_required", "finished_at_utc": now()})
        save(OUT, state)
        raise RuntimeError("WB rejected batch; reconcile live cards before any retry")
    state["phase"] = "accepted_waiting_for_readback"
    save(OUT, state)

    after_cards = {}
    for attempt in range(4):
        after_cards = {}
        for target in targets:
            offer = target["offer"]
            cards = client.wb_cards(offer)
            if len(cards) == 1 and str(cards[0].get("nmID") or "") == target["nmID"]:
                after_cards[offer] = cards[0]
        done = len(after_cards) == len(targets)
        if done:
            for target in targets:
                card = after_cards[target["offer"]]
                match = [d for d in ((card.get("documents") or {}).get("items") or [])
                         if int(d.get("type") or 0) == 1 and d.get("number") == NUMBER]
                verdict = (match[0].get("verdict") or {}) if len(match) == 1 else {}
                if not (verdict.get("verified") is True and verdict.get("status") == 1
                        and verdict.get("reason") == "valid"):
                    done = False
                    break
        if done:
            break
        if attempt < 3:
            time.sleep(8)

    read_rows = []
    for target in targets:
        offer = target["offer"]
        after = after_cards.get(offer)
        if after is None:
            read_rows.append({"offer": offer, "state": "card_not_readable"})
            continue
        before = before_cards.get(offer)
        docs_after = after.get("documents") or {}
        items_after = docs_after.get("items") or []
        matches = [d for d in items_after if int(d.get("type") or 0) == 1 and d.get("number") == NUMBER]
        verdict = (matches[0].get("verdict") or {}) if len(matches) == 1 else {}
        if before is not None:
            other_fields_same = all(after.get(k) == before.get(k) for k in CARD_FIELDS if k in before and k != "characteristics")
            characteristics_same = same_characteristics_except_number(before.get("characteristics") or [], after.get("characteristics") or [])
            before_doc_keys = {(int(d.get("type") or 0), norm(d.get("number")), str(d.get("startDate") or "")[:10],
                                str(d.get("endDate") or "")[:10]) for d in (before.get("documents") or {}).get("items") or []}
            after_doc_keys = {(int(d.get("type") or 0), norm(d.get("number")), str(d.get("startDate") or "")[:10],
                               str(d.get("endDate") or "")[:10]) for d in items_after}
            preexisting_docs_preserved = all(
                key in after_doc_keys or (key[0] == 1 and key[1] == norm(OLD_NUMBER)
                                          and key[2] == ISSUE and key[3] == EXPIRY)
                for key in before_doc_keys)
        else:
            other_fields_same = characteristics_same = preexisting_docs_preserved = True
        read_rows.append({"offer": offer, "nmID": target["nmID"],
                          "document_row_count": len(matches), "document_verdict": verdict,
                          "state": "valid" if len(matches) == 1 and verdict.get("verified") is True
                          and verdict.get("status") == 1 and verdict.get("reason") == "valid" else "pending_or_invalid",
                          "other_full_card_fields_preserved": other_fields_same,
                          "all_unrelated_characteristics_preserved": characteristics_same,
                          "preexisting_documents_preserved": preexisting_docs_preserved,
                          "excludeDocuments": docs_after.get("excludeDocuments")})
    state["readback"] = {"checked_at_utc": now(), "card_count": len(after_cards), "rows": read_rows,
                         "document_states": dict(collections.Counter(x.get("state") for x in read_rows)),
                         "all_documents_valid": len(read_rows) == len(targets) and all(x.get("state") == "valid" for x in read_rows),
                         "all_non_document_fields_preserved": all(x.get("other_full_card_fields_preserved")
                                                                  and x.get("all_unrelated_characteristics_preserved")
                                                                  for x in read_rows),
                         "all_preexisting_documents_preserved": all(x.get("preexisting_documents_preserved") for x in read_rows)}
    state.update({"phase": "readback_complete" if state["readback"]["all_documents_valid"] else "readback_pending",
                  "finished_at_utc": now()})
    save(OUT, state)
    print(json.dumps({"phase": state["phase"], "to_correct": len(payloads), "readback": state["readback"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
