"""Correct the legacy non-canonical 06897 number on the original 12 WB cards."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from api_client import Client, now  # noqa: E402
from execute_arlight_06897_source_map_20261014 import (  # noqa: E402
    DOC_FIELDS,
    DOC_READ_ONLY_FIELDS,
    EXPIRY,
    ISSUE,
    NUMBER,
    TNVED,
    card_docs,
    comparable_card,
    direct_post,
    norm,
    read_one_wb_card,
    tnv_codes,
)

EXACT_PREFLIGHT = BASE / "arlight_06897_exact_live_preflight_20261014.json"
OZON_READBACK = BASE / "arlight_06897_source_map_final_ozon_readback_20261014.json"
OUT = BASE / "arlight_06897_original12_wb_canonical_number_20261014.json"
WB_FIELDS = ("nmID", "vendorCode", "brand", "title", "description", "dimensions",
             "characteristics", "sizes", "kizMarked", "gtin")


def save(value: dict) -> None:
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(OUT)


def main() -> None:
    exact = json.loads(EXACT_PREFLIGHT.read_text())
    ozon = json.loads(OZON_READBACK.read_text())
    if exact.get("source_assignment_count") != 12 or exact.get("preflight_eligible") is not True:
        raise RuntimeError("The exact 12-offer manufacturer-verified preflight is unavailable")
    if (ozon.get("exact_pair_set_match") is not True
            or ozon.get("all_binding_status_counts") != {"approved": 503}):
        raise RuntimeError("The shared Ozon record and new 491 bindings are not fully approved")

    client = Client()
    targets, payloads, before = [], [], []
    for target in exact["targets"]:
        offer = target["offer_id"]
        prior_wb = target.get("wb_cards") or []
        if len(prior_wb) != 1:
            raise RuntimeError(f"Original preflight no longer identifies one WB card for {offer}")
        card = read_one_wb_card(client, offer)
        if (str(card.get("vendorCode") or "") != offer
                or str(card.get("nmID") or "") != str(prior_wb[0].get("nmID") or "")
                or card.get("brand") != "Arlight" or tnv_codes(card) != [TNVED]):
            raise RuntimeError(f"WB identity, brand, or TN VED changed for {offer}")
        docs = card_docs(card)
        matches = [d for d in docs if norm(d.get("number")) == norm(NUMBER)]
        if len(matches) != 1:
            raise RuntimeError(f"Expected exactly one 06897 row on {offer}, found {len(matches)}")
        old_doc = matches[0]
        if (int(old_doc.get("type") or 0) != 2
                or str(old_doc.get("startDate") or "")[:10] != ISSUE
                or str(old_doc.get("endDate") or "")[:10] != EXPIRY
                or old_doc.get("isEndless") is not False):
            raise RuntimeError(f"The existing WB 06897 row has unexpected type/dates on {offer}")
        if old_doc.get("number") == NUMBER:
            raise RuntimeError(f"The canonical 06897 number is already present on {offer}")

        clean_docs = []
        for doc in docs:
            unknown = set(doc) - set(DOC_FIELDS) - DOC_READ_ONLY_FIELDS
            if unknown:
                raise RuntimeError(f"Unsupported document fields on {offer}: {sorted(unknown)}")
            clean = {key: copy.deepcopy(doc[key]) for key in DOC_FIELDS if key in doc}
            if norm(doc.get("number")) == norm(NUMBER):
                clean["number"] = NUMBER
                clean["type"] = 2
                clean["startDate"] = ISSUE + "T00:00:00Z"
                clean["endDate"] = EXPIRY + "T00:00:00Z"
                clean["isEndless"] = False
            clean_docs.append(clean)
        payload = {key: copy.deepcopy(card[key]) for key in WB_FIELDS if key in card}
        required = set(WB_FIELDS[:-1])
        if required - payload.keys():
            raise RuntimeError(f"Full-card payload missing fields on {offer}: {sorted(required - payload.keys())}")
        payload["documents"] = {"items": clean_docs, "excludeDocuments": False}
        if any(payload.get(key) != card.get(key) for key in WB_FIELDS if key in card):
            raise RuntimeError(f"The retry changes an unrelated WB card field on {offer}")
        targets.append(offer)
        payloads.append(payload)
        before.append({"offer_id": offer, "nmID": str(card["nmID"]), "card": card,
                       "old_number": old_doc.get("number")})

    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode()
    result = {"started_at_utc": now(), "read_only_preflight_complete": True,
              "target_count": len(targets), "targets": targets,
              "old_number_values": sorted({x["old_number"] for x in before}),
              "canonical_number": NUMBER, "payload_bytes": len(encoded),
              "payload_sha256": hashlib.sha256(encoded).hexdigest(),
              "mutation_attempts": 1, "local_cleanup_allowed": False}
    save(result)
    status, body, error_type = 0, {}, None
    try:
        status, body = direct_post(client, "wb", "/content/v2/cards/update", payloads, mutation=True)
    except Exception as exc:
        error_type = type(exc).__name__
    result["sent_at_utc"] = now()
    result["response"] = {"http_status": status, "error": body.get("error"),
                          "errorText": body.get("errorText"),
                          "additionalErrors": body.get("additionalErrors"),
                          "error_type": error_type}
    if status != 200 or body.get("error") is not False:
        result["state"] = "uncertain_reconcile_only"
        save(result)
        print(json.dumps({k: v for k, v in result.items() if k != "targets"}, ensure_ascii=False, indent=2))
        return

    readback = []
    for index, old in enumerate(before, 1):
        card = read_one_wb_card(client, old["offer_id"])
        rows = [d for d in card_docs(card) if norm(d.get("number")) == norm(NUMBER)]
        canonical_matches = [d for d in rows if d.get("number") == NUMBER]
        visible = (len(rows) == len(canonical_matches) == 1
                   and int(canonical_matches[0].get("type") or 0) == 2
                   and str(canonical_matches[0].get("startDate") or "")[:10] == ISSUE
                   and str(canonical_matches[0].get("endDate") or "")[:10] == EXPIRY
                   and canonical_matches[0].get("isEndless") is False)
        readback.append({"offer_id": old["offer_id"], "nmID": str(card.get("nmID") or ""),
                         "canonical_row_visible": visible,
                         "all_other_card_fields_preserved": comparable_card(old["card"]) == comparable_card(card),
                         "excludeDocuments": (card.get("documents") or {}).get("excludeDocuments"),
                         "verdict": canonical_matches[0].get("verdict") if canonical_matches else None,
                         "row_count": len(rows)})
        print(f"WB exact-number readback {index}/12 {old['offer_id']}: visible={visible}", flush=True)

    result.update({"checked_at_utc": now(), "readback_complete": True, "readback": readback,
                   "canonical_row_visible_count": sum(x["canonical_row_visible"] for x in readback),
                   "other_fields_preserved_count": sum(x["all_other_card_fields_preserved"] for x in readback),
                   "verdict_counts": {},
                   "state": ("canonical_row_visible_pending_wb_verdict"
                             if all(x["canonical_row_visible"] for x in readback)
                             else "canonical_row_readback_needs_reconciliation")})
    from collections import Counter
    result["verdict_counts"] = dict(Counter(
        str((x.get("verdict") or {}).get("reason") or "NO_VERDICT") for x in readback))
    save(result)
    print(json.dumps({k: v for k, v in result.items() if k not in ("targets", "readback")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
