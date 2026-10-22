"""Normalize the official Legrand 03134 certificate number on ten exact WB cards."""
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
PREFLIGHT = BASE / "legrand_remaining_preflight_20261013.json"
SUMMARY = ROOT / "output_to_user/certificates/group_3/article_summary.csv"
PDF = ROOT / "output_to_user/certificates/group_3/docs/legrand_SUNO_thermostat_EAC-FR.02.03134.pdf"
OUT = "legrand_03134_wb_execution_20261013.json"
LABEL = "EAC-FR.02.03134"
NUMBER = "ЕАЭС KG 417/032.FR.02.03134"
OLD_NUMBER = "EAC KG 417/032.FR.02.03134"
CERTIFICATE_ID = "5458739"
ISSUE = "2026-03-23"
EXPIRY = "2031-03-22"
TNVED = "8536699008"
DOC_NUMBER_CHAR_ID = 15001136
TNVED_CHAR_ID = 15000001


def list_certificates(client: Client) -> list[dict]:
    records = []
    for page in range(1, 20):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result", {})
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Malformed Ozon certificate list")
        records.extend(batch)
        if len(batch) < 100:
            return records
    raise RuntimeError("Ozon certificate pagination limit exceeded")


def same_characteristics_except_number(before: list[dict], after: list[dict]) -> bool:
    def by_id(rows: list[dict]) -> dict[str, list[dict]]:
        grouped: dict[str, list[dict]] = collections.defaultdict(list)
        for row in rows:
            grouped[str(row.get("id"))].append(row)
        return {key: sorted(value, key=lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True))
                for key, value in grouped.items()}

    old, new = by_id(before), by_id(after)
    if set(old) != set(new):
        return False
    for char_id in old:
        if char_id == str(DOC_NUMBER_CHAR_ID):
            if len(old[char_id]) != 1 or len(new[char_id]) != 1:
                return False
            expected = dict(old[char_id][0])
            expected["value"] = [NUMBER]
            if new[char_id][0] != expected:
                return False
        elif old[char_id] != new[char_id]:
            return False
    return True


def main() -> None:
    out_path = BASE / OUT
    if out_path.exists():
        raise RuntimeError("Execution journal already exists; reconcile before any further write")
    if not PDF.is_file():
        raise RuntimeError("Local signed certificate PDF missing")
    manifest = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    spec = manifest["documents"][LABEL]
    if not spec["summary"]["all_preflight_safe"] or spec["summary"]["correction_eligible_count"] != 10:
        raise RuntimeError("Saved read-only preflight does not approve exactly ten exact corrections")
    expected_hash = spec["summary"]["local_pdf_sha256"]
    if hashlib.sha256(PDF.read_bytes()).hexdigest() != expected_hash:
        raise RuntimeError("Source PDF hash changed")
    with SUMMARY.open(encoding="utf-8-sig", newline="") as stream:
        rows = [r for r in csv.DictReader(stream)
                if r.get("Бренд") == "Legrand" and LABEL in (r.get("Документ/номер") or "")]
    if len(rows) != 10:
        raise RuntimeError("Local target set changed")
    targets = {r["Артикул продавца"]: {
        "product_id": str(r["Ozon Product ID"]), "sku": str(r["Ozon SKU"])} for r in rows}
    if len(targets) != 10:
        raise RuntimeError("Duplicate local offer mapping")
    client = Client()

    # Refresh exact Ozon identities, attributes, record and product links before writing WB.
    products_response = client.call("ozon", "/v3/product/info/list", {"offer_id": list(targets)})
    products = products_response.get("items") or products_response.get("result", {}).get("items")
    if not isinstance(products, list) or len(products) != 10:
        raise RuntimeError("Fresh Ozon product response incomplete")
    by_offer = {str(x.get("offer_id") or ""): x for x in products}
    if set(by_offer) != set(targets) or len(by_offer) != 10:
        raise RuntimeError("Ozon offers missing/duplicated")
    attr_response = client.call("ozon", "/v4/product/info/attributes",
                                {"filter": {"offer_id": list(targets)}, "limit": 100})
    attr_rows = attr_response.get("result") or attr_response.get("items")
    if not isinstance(attr_rows, list) or {str(x.get("offer_id")) for x in attr_rows} != set(targets):
        raise RuntimeError("Fresh Ozon attributes incomplete")
    attrs = {str(x["offer_id"]): {str(a.get("id")): a for a in x.get("attributes") or []}
             for x in attr_rows}
    records = [x for x in list_certificates(client) if str(x.get("certificate_id")) == CERTIFICATE_ID]
    if (len(records) != 1 or records[0].get("status_code") != "approved"
            or records[0].get("type_code") != "certificate_of_conformity"
            or str(records[0].get("certificate_number")) != NUMBER
            or str(records[0].get("issue_date", ""))[:10] != ISSUE
            or str(records[0].get("expire_date", ""))[:10] != EXPIRY):
        raise RuntimeError("Ozon certificate record no longer matches the signed PDF")
    bindings = client.ozon_bindings(int(CERTIFICATE_ID))
    by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for b in bindings:
        by_sku[str(b.get("sku") or "")].append(b)
    for offer, identity in targets.items():
        product = by_offer[offer]
        if (str(product.get("id") or product.get("product_id") or "") != identity["product_id"]
                or str(product.get("sku") or "") != identity["sku"] or product.get("is_archived")):
            raise RuntimeError("Ozon Product ID/SKU changed: " + offer)
        brand = [str(v.get("value") or "") for v in (attrs[offer].get("85") or {}).get("values") or []]
        tnved = [str(v.get("value") or "") for v in (attrs[offer].get("22232") or {}).get("values") or []]
        codes = sorted({v.split(" - ", 1)[0].strip() for v in tnved if v.strip()})
        if brand != ["Legrand"] or codes != [TNVED]:
            raise RuntimeError("Ozon brand/TN VED no longer matches official scope: " + offer)
        exact = by_sku.get(identity["sku"], [])
        if (len(exact) != 1 or str(exact[0].get("product_id")) != identity["product_id"]
                or exact[0].get("product_status_code") != "approved"):
            raise RuntimeError("Ozon exact product/SKU link is not uniquely approved: " + offer)

    payloads = []
    before_cards = {}
    wb_targets = []
    for target in spec["targets"]:
        offer = target["offer"]
        cards = client.wb_cards(offer)
        if len(cards) != 1 or str(cards[0].get("vendorCode") or "") != offer:
            raise RuntimeError("WB exact card missing/duplicated: " + offer)
        card = cards[0]
        if str(card.get("nmID") or "") != target["nmID"] or card.get("brand") != "Legrand":
            raise RuntimeError("WB identity/brand changed: " + offer)
        tnved = sorted({str(v).strip().split(" ", 1)[0]
                        for ch in card.get("characteristics") or []
                        if int(ch.get("id") or -1) == TNVED_CHAR_ID
                        for v in ch.get("value") or [] if str(v).strip()})
        if tnved != [TNVED]:
            raise RuntimeError("WB TN VED outside signed scope: " + offer)
        docs = card.get("documents") or card.get("docs") or {}
        if docs.get("excludeDocuments") is not False:
            raise RuntimeError("WB card excludes documents: " + offer)
        items = docs.get("items") or []
        matching = [d for d in items if int(d.get("type") or 0) == 1
                    and str(d.get("number") or "") in (OLD_NUMBER, NUMBER)]
        if len(matching) != 1:
            raise RuntimeError("WB 03134 row missing/duplicated: " + offer)
        old_doc = matching[0]
        if (str(old_doc.get("startDate") or "")[:10] != ISSUE
                or str(old_doc.get("endDate") or "")[:10] != EXPIRY):
            raise RuntimeError("WB document dates differ from official certificate: " + offer)
        chars = card.get("characteristics") or []
        number_chars = [c for c in chars if int(c.get("id") or -1) == DOC_NUMBER_CHAR_ID]
        if len(number_chars) != 1 or number_chars[0].get("value") not in ([OLD_NUMBER], [NUMBER]):
            raise RuntimeError("WB certificate-number characteristic missing/conflicting: " + offer)
        already_valid = (old_doc.get("number") == NUMBER
                         and old_doc.get("verdict", {}).get("verified") is True
                         and old_doc.get("verdict", {}).get("status") == 1
                         and old_doc.get("verdict", {}).get("reason") == "valid")
        wb_targets.append({"offer": offer, "nmID": target["nmID"],
                           "before_number": old_doc.get("number"), "already_valid": already_valid,
                           "before_verdict": old_doc.get("verdict"), "documents_count": len(items)})
        if already_valid:
            continue
        if not all(key in card for key in CARD_FIELDS[:-1]):
            raise RuntimeError("WB full-card fields missing: " + offer)
        new_items = []
        for item in items:
            clean = clean_wb_doc(item)
            if clean.get("type") == 1 and clean.get("number") == old_doc.get("number"):
                clean["number"] = NUMBER
            new_items.append(clean)
        payload = {key: card[key] for key in CARD_FIELDS if key in card}
        payload["documents"] = {"items": new_items, "excludeDocuments": False}
        payload["characteristics"] = [
            ({**c, "value": [NUMBER]} if int(c.get("id") or -1) == DOC_NUMBER_CHAR_ID else c)
            for c in chars
        ]
        if not same_characteristics_except_number(chars, payload["characteristics"]):
            raise RuntimeError("Prepared card changes unrelated characteristics: " + offer)
        for key in CARD_FIELDS:
            if key != "characteristics" and key in card and payload.get(key) != card.get(key):
                raise RuntimeError("Prepared payload changes unrelated field " + key + ": " + offer)
        payloads.append(payload)
        before_cards[offer] = card

    if len(payloads) != 10:
        raise RuntimeError("Target set changed; expected one correction on each of ten cards")
    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > 10_000_000:
        raise RuntimeError("WB batch exceeds documented limit")
    state = {"prepared_at_utc": now(), "phase": "prepared", "certificate_id": CERTIFICATE_ID,
             "number": NUMBER, "old_number": OLD_NUMBER, "issue_date": ISSUE, "expiry_date": EXPIRY,
             "local_pdf_sha256": expected_hash, "target_count": len(wb_targets), "to_correct": len(payloads),
             "ozon_binding_status_counts": dict(collections.Counter(b.get("product_status_code") for b in bindings)),
             "wb_targets": wb_targets, "payload_sha256": hashlib.sha256(encoded).hexdigest(),
             "payload_bytes": len(encoded), "mutation_attempts": 0, "response": None, "readback": None,
             "before_cards": before_cards}
    save(OUT, state)
    state.update({"phase": "mutation_started", "mutation_attempts": 1, "sent_at_utc": now()})
    save(OUT, state)
    try:
        response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
    except Exception as exc:
        state.update({"phase": "mutation_uncertain", "error_type": type(exc).__name__, "finished_at_utc": now()})
        save(OUT, state)
        raise RuntimeError("WB outcome uncertain; reconcile before any retry") from None
    state["response"] = response
    if response.get("error") is not False:
        state.update({"phase": "rejected_readback_required", "finished_at_utc": now()})
        save(OUT, state)
        raise RuntimeError("WB rejected batch; reconcile before any retry")
    state["phase"] = "accepted_waiting_for_readback"
    save(OUT, state)

    after_cards = {}
    for attempt in range(4):
        after_cards = {}
        for target in wb_targets:
            cards = client.wb_cards(target["offer"])
            if len(cards) == 1 and str(cards[0].get("nmID") or "") == target["nmID"]:
                after_cards[target["offer"]] = cards[0]
        done = len(after_cards) == len(wb_targets)
        if done:
            for offer, card in after_cards.items():
                match = [d for d in (card.get("documents") or {}).get("items") or []
                         if int(d.get("type") or 0) == 1 and d.get("number") == NUMBER]
                verdict = match[0].get("verdict") or {} if len(match) == 1 else {}
                if not (verdict.get("verified") is True and verdict.get("status") == 1
                        and verdict.get("reason") == "valid"):
                    done = False
                    break
        if done:
            break
        if attempt < 3:
            time.sleep(8)

    readback = []
    for target in wb_targets:
        offer = target["offer"]
        card = after_cards.get(offer)
        if card is None:
            readback.append({"offer": offer, "state": "card_not_readable"})
            continue
        before = before_cards[offer]
        docs = card.get("documents") or {}
        items = docs.get("items") or []
        match = [d for d in items if int(d.get("type") or 0) == 1 and d.get("number") == NUMBER]
        verdict = (match[0].get("verdict") or {}) if len(match) == 1 else {}
        non_doc_fields_same = all(card.get(k) == before.get(k) for k in CARD_FIELDS
                                  if k in before and k != "characteristics")
        chars_same = same_characteristics_except_number(before.get("characteristics") or [],
                                                        card.get("characteristics") or [])
        before_docs = (before.get("documents") or {}).get("items") or []
        before_keys = {(int(d.get("type") or 0), norm(d.get("number")), str(d.get("startDate") or "")[:10],
                        str(d.get("endDate") or "")[:10]) for d in before_docs}
        after_keys = {(int(d.get("type") or 0), norm(d.get("number")), str(d.get("startDate") or "")[:10],
                       str(d.get("endDate") or "")[:10]) for d in items}
        old_key = (1, norm(OLD_NUMBER), ISSUE, EXPIRY)
        docs_preserved = all(key in after_keys or key == old_key for key in before_keys)
        readback.append({"offer": offer, "nmID": target["nmID"], "state": "valid" if len(match) == 1
                         and verdict.get("verified") is True and verdict.get("status") == 1
                         and verdict.get("reason") == "valid" else "pending_or_invalid",
                         "document_verdict": verdict, "other_full_card_fields_preserved": non_doc_fields_same,
                         "unrelated_characteristics_preserved": chars_same,
                         "preexisting_documents_preserved": docs_preserved,
                         "excludeDocuments": docs.get("excludeDocuments")})
    state["readback"] = {"checked_at_utc": now(), "card_count": len(after_cards), "rows": readback,
                         "document_states": dict(collections.Counter(r["state"] for r in readback)),
                         "all_documents_valid": len(readback) == 10 and all(r["state"] == "valid" for r in readback),
                         "all_other_fields_preserved": all(r.get("other_full_card_fields_preserved")
                                                            and r.get("unrelated_characteristics_preserved")
                                                            for r in readback),
                         "all_preexisting_documents_preserved": all(r.get("preexisting_documents_preserved")
                                                                    for r in readback)}
    state.update({"phase": "readback_complete" if state["readback"]["all_documents_valid"] else "readback_pending",
                  "finished_at_utc": now()})
    save(OUT, state)
    print(json.dumps({"phase": state["phase"], "response": response, "readback": state["readback"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
