"""Submit only the three exact WB cards and independently read them back once."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from api_client import Client, now

BASE = Path(__file__).resolve().parent
PLAN = BASE / "arlight_69060_wb_extras_plan_20261012.json"
RUN = BASE / "arlight_69060_wb_extras_execution_20261012.json"
REPORT = BASE / "arlight_69060_wb_extras_verification_20261012.json"
NUMBER = "ЕАЭС N RU Д-HK.РА02.В.69060/25"
CARD_FIELDS = ("nmID", "vendorCode", "brand", "title", "description", "dimensions",
               "characteristics", "sizes", "kizMarked", "gtin")
DOC_FIELDS = ("id", "type", "number", "productNumber", "tradeName", "applicant",
              "startDate", "endDate", "isEndless")


def save(path: Path, value: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(path)


def norm(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def clean_doc(item: dict) -> dict:
    return {key: item[key] for key in DOC_FIELDS if key in item}


def signature(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def same_card_field(field: str, left: dict, right: dict) -> bool:
    if field == "characteristics":
        return Counter(map(signature, left.get(field) or [])) == Counter(map(signature, right.get(field) or []))
    return left.get(field) == right.get(field)


def main() -> None:
    if RUN.exists() or REPORT.exists():
        raise RuntimeError("WB supplemental write was already attempted; inspect journals before another write")
    plan = json.loads(PLAN.read_text())
    updates = plan.get("updates") or []
    if (plan.get("number") != NUMBER or plan.get("document_type") != 2 or len(updates) != 3
            or plan.get("ozon_target_pairs_confirmed") != 552 or plan.get("local_cleanup_allowed") is not False):
        raise RuntimeError("WB supplemental plan lacks exact, confirmed 552-pair Ozon scope")
    payloads = [x["payload"] for x in updates]
    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) != plan.get("payload_bytes") or hashlib.sha256(encoded).hexdigest() != plan.get("payload_sha256"):
        raise RuntimeError("WB supplemental payload differs from the reviewed plan hash")
    client = Client()
    for entry in updates:
        offer = entry["offer_id"]
        current = client.wb_cards(offer)
        if len(current) != 1:
            raise RuntimeError(f"WB exact prewrite read is not unique: {offer}")
        card = current[0]
        if card.get("vendorCode") != offer or str(card.get("nmID")) != str(entry["nmID"]):
            raise RuntimeError(f"WB exact card identity changed before update: {offer}")
        if any(not same_card_field(field, card, entry["before"]) for field in CARD_FIELDS):
            raise RuntimeError(f"WB card changed since full-card payload creation: {offer}")
        docs = (card.get("documents") or {}).get("items") or []
        if any(norm(d.get("number")) == norm(NUMBER) for d in docs):
            raise RuntimeError(f"WB exact declaration appeared before update: {offer}")

    state = {"started_at": now(), "phase": "prepared", "number": NUMBER, "cards": len(payloads),
             "documents_added": len(payloads), "payload_bytes": len(encoded),
             "payload_sha256": plan["payload_sha256"], "existing_documents_preserved": True,
             "non_document_fields_preserved": True,
             "offers": [{k: x[k] for k in ("offer_id", "product_id", "sku", "nmID")} for x in updates]}
    save(RUN, state)
    state.update({"phase": "sent", "sent_at": now()})
    save(RUN, state)
    try:
        response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
    except Exception as exc:
        state.update({"phase": "uncertain", "error_type": type(exc).__name__, "updated_at": now()})
        save(RUN, state)
        raise RuntimeError("WB update outcome uncertain; read live cards before any retry") from None
    state["response"] = response
    if response.get("error") is not False:
        state.update({"phase": "response_error", "updated_at": now()})
        save(RUN, state)
        raise RuntimeError("WB did not accept the supplemental full-card update")
    state.update({"phase": "accepted_waiting_for_review", "accepted_at": now()})
    save(RUN, state)

    failures = []
    verdicts = Counter()
    exact_rows = {}
    for entry in updates:
        offer = entry["offer_id"]
        rows = client.wb_cards(offer)
        if len(rows) != 1 or rows[0].get("vendorCode") != offer or str(rows[0].get("nmID")) != str(entry["nmID"]):
            failures.append({"offer_id": offer, "error": "readback_identity_mismatch"})
            continue
        after = rows[0]
        before = entry["before"]
        for field in CARD_FIELDS:
            if field == "characteristics":
                old = Counter(map(signature, before.get("characteristics") or []))
                actual = Counter(map(signature, after.get("characteristics") or []))
                additions = actual - old
                allowed = Counter({
                    signature({"id": 15001135, "name": "Номер декларации соответствия", "value": [NUMBER]}): 1,
                    signature({"id": 15001137, "name": "Дата регистрации сертификата/декларации", "value": ["10.03.2025"]}): 1,
                    signature({"id": 15001138, "name": "Дата окончания действия сертификата/декларации", "value": ["09.03.2030"]}): 1,
                })
                if old - actual or additions - allowed:
                    failures.append({"offer_id": offer, "error": "characteristics_changed_outside_expected_document_fields"})
            elif after.get(field) != before.get(field):
                failures.append({"offer_id": offer, "error": "non_document_card_field_changed", "field": field})
        container = after.get("documents") or {}
        if container.get("excludeDocuments") is not False:
            failures.append({"offer_id": offer, "error": "documents_excluded"})
        docs = container.get("items") or []
        matching = [d for d in docs if norm(d.get("number")) == norm(NUMBER)]
        if len(matching) != 1:
            failures.append({"offer_id": offer, "error": "exact_document_row_count", "count": len(matching)})
            continue
        row = matching[0]
        if (int(row.get("type", -1)) != 2 or str(row.get("startDate", ""))[:10] != "2025-03-10"
                or str(row.get("endDate", ""))[:10] != "2030-03-09" or row.get("isEndless") is not False):
            failures.append({"offer_id": offer, "error": "document_metadata_mismatch"})
        old_docs = [clean_doc(d) for d in ((before.get("documents") or {}).get("items") or [])]
        actual_old_docs = [clean_doc(d) for d in docs if norm(d.get("number")) != norm(NUMBER)]
        if Counter(map(signature, old_docs)) != Counter(map(signature, actual_old_docs)):
            failures.append({"offer_id": offer, "error": "existing_document_rows_changed"})
        verdict = row.get("verdict") or {}
        verdicts[signature({"verified": verdict.get("verified"), "status": verdict.get("status"),
                           "reason": verdict.get("reason")})] += 1
        exact_rows[offer] = row

    report = {"checked_at": now(), "number": NUMBER, "certificate_id": plan["ozon_certificate_id"],
              "target_pair_count": 3, "readback_count": len(exact_rows), "verdict_counts": dict(verdicts),
              "failures": failures, "all_exact_rows_present_and_metadata_correct": len(exact_rows) == 3 and not failures,
              "all_rows_valid": len(exact_rows) == 3 and not failures and all(
                  json.loads(key).get("verified") is True and json.loads(key).get("status") == 1
                  and json.loads(key).get("reason") == "valid" for key in verdicts),
              "wb_review_left_to_platform": True, "local_cleanup_allowed": False,
              "document_rows": exact_rows}
    save(REPORT, report)
    state.update({"phase": "readback_complete" if report["all_exact_rows_present_and_metadata_correct"]
                  else "readback_incomplete", "finished_at": now(), "verification_path": str(REPORT)})
    save(RUN, state)
    print(json.dumps({k: report[k] for k in (
        "number", "certificate_id", "target_pair_count", "readback_count", "verdict_counts",
        "failures", "all_exact_rows_present_and_metadata_correct", "all_rows_valid",
        "wb_review_left_to_platform", "local_cleanup_allowed")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
