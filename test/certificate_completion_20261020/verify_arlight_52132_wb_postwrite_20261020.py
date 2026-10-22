"""Full live WB catalog readback for Arlight declaration 52132/25."""
from __future__ import annotations

import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    OZON_TO_WB_TYPE, comparable_card, copy_documents, doc_key, norm_number,
    wb_datetime,
)

NUMBER = "ЕАЭС N RU Д-CN.РА09.В.52132/25"
ALLOWED = {"9405110013", "9405110033", "9405110039",
           "9405420012", "9405420032", "9405420039"}
BEFORE = HERE / "arlight_52132_wb_before_cards_20261020.json"
STATE = HERE / "arlight_52132_wb_execution_state_20261020.json"
WB_PREFLIGHT = HERE / "arlight_52132_wb_preflight_live_20261020.json"
OZON_PREFLIGHT = HERE / "arlight_52132_ozon_preflight_live_20261020.json"
OUT = HERE / "arlight_52132_wb_postwrite_readback_20261020.json"


def save(path: pathlib.Path, value: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(path)


def read_full(client: Client, wanted: set[str]) -> tuple[dict, int, int]:
    cursor = {"limit": 100}
    seen = set()
    found: dict[str, list[dict]] = collections.defaultdict(list)
    pages = count = 0
    while True:
        body = client.call("wb", "/content/v2/get/cards/list", {
            "settings": {"sort": {"ascending": True}, "cursor": cursor,
                         "filter": {"withPhoto": -1}}
        })
        batch = body.get("cards")
        if body.get("error") or not isinstance(batch, list):
            raise RuntimeError("invalid_wb_full_catalog_readback")
        pages += 1
        count += len(batch)
        for card in batch:
            offer = str(card.get("vendorCode") or "")
            if offer in wanted:
                found[offer].append(card)
        if len(batch) < 100:
            break
        c = body.get("cursor") or {}
        sig = (c.get("updatedAt"), c.get("nmID"))
        if None in sig or sig in seen:
            raise RuntimeError("repeated_or_incomplete_wb_readback_cursor")
        seen.add(sig)
        cursor = {"limit": 100, "updatedAt": sig[0], "nmID": sig[1]}
        if pages % 50 == 0:
            print(json.dumps({"phase": "final_readback", "pages": pages,
                              "cards": count,
                              "target_cards_found": sum(map(len, found.values()))}), flush=True)
    return found, pages, count


def tnved(card: dict) -> list[str]:
    result = []
    for char in card.get("characteristics") or []:
        name = "".join(str(char.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = char.get("value")
        result.extend(str(v or "").split(" - ", 1)[0].strip()
                      for v in (raw if isinstance(raw, list) else [raw]))
    return sorted(set(result))


def main() -> None:
    if OUT.exists():
        raise RuntimeError("readback_output_already_exists")
    initial = json.loads(BEFORE.read_text())
    state = json.loads(STATE.read_text())
    pre = json.loads(WB_PREFLIGHT.read_text())
    ozon = json.loads(OZON_PREFLIGHT.read_text())
    previous = initial["cards"]
    wanted = set(previous)
    preflight = {x["offer_id"]: x for x in pre["targets"]}
    source = {x["offer_id"]: x for x in ozon["targets"]}
    if len(wanted) != 929 or len(preflight) != 929 or len(source) != 929:
        raise RuntimeError("unexpected_candidate_target_count")

    found, pages, count = read_full(Client(), wanted)
    if set(found) != wanted:
        raise RuntimeError("wb_readback_target_set_incomplete")

    expected = {"type": OZON_TO_WB_TYPE["declaration"], "number": NUMBER,
                "startDate": wb_datetime("2025-10-22"),
                "endDate": wb_datetime("2030-10-20"), "isEndless": False}
    rows = []
    doc_counts = collections.Counter()
    scope_counts = collections.Counter()
    fields_preserved = 0
    prior_docs_preserved = 0
    eligible_applied = 0
    outside_has_doc = 0
    for offer in sorted(wanted):
        cards = found[offer]
        if len(cards) != 1:
            rows.append({"offer_id": offer, "state": "duplicate_or_missing_current_card",
                         "exact_card_count": len(cards)})
            continue
        card = cards[0]
        initial_card = previous[offer]
        docs = copy_documents(card)
        same = [d for d in docs if norm_number(d.get("number")) == norm_number(NUMBER)]
        exact = [d for d in same if doc_key(d) == doc_key(expected)
                 and str(d.get("startDate", ""))[:10] == expected["startDate"][:10]
                 and str(d.get("endDate", ""))[:10] == expected["endDate"][:10]]
        has_exact = len(exact) == 1 and len(same) == 1
        if same and not has_exact:
            doc_state = "same_number_conflict"
        elif has_exact:
            doc_state = "exact_visible"
        else:
            doc_state = "missing"
        doc_counts[doc_state] += 1

        wb_codes = tnved(card)
        if len(wb_codes) == 1 and wb_codes[0] in ALLOWED:
            basis = "wb_tnved_allowed"
        elif not wb_codes and len(source[offer].get("tnved") or []) == 1 \
                and source[offer]["tnved"][0] in ALLOWED:
            basis = "exact_ozon_offer_tnved_fallback_for_blank_wb"
        else:
            basis = "out_of_scope_or_unconfirmed"
        scope_counts[basis] += 1
        eligible = basis != "out_of_scope_or_unconfirmed"
        if eligible and has_exact:
            eligible_applied += 1
        if not eligible and same:
            outside_has_doc += 1
        before_set = {(doc_key(d), str(d.get("startDate", ""))[:10],
                       str(d.get("endDate", ""))[:10]) for d in copy_documents(initial_card)}
        after_set = {(doc_key(d), str(d.get("startDate", ""))[:10],
                      str(d.get("endDate", ""))[:10]) for d in docs}
        prior_preserved = before_set <= after_set
        fields_preserved_row = comparable_card(card) == comparable_card(initial_card)
        prior_docs_preserved += int(prior_preserved)
        fields_preserved += int(fields_preserved_row)

        verdict = card.get("documents") or {}
        target_items = [d for d in (verdict.get("items") or [])
                        if norm_number(d.get("number")) == norm_number(NUMBER)]
        rows.append({
            "offer_id": offer, "nmID": card.get("nmID"), "brand": card.get("brand"),
            "exact_document_visible": has_exact, "document_rows_for_number": len(same),
            "document_state": doc_state, "current_wb_tnved": wb_codes,
            "scope_basis": basis, "eligible_by_current_scope": eligible,
            "all_preexisting_documents_preserved": prior_preserved,
            "other_card_fields_preserved": fields_preserved_row,
            "overall_verdict": verdict.get("overallVerdict"),
            "document_item_state_fields": [{k: v for k, v in d.items()
                                            if k not in {"number", "startDate", "endDate"}}
                                           for d in target_items],
        })

    output = {
        "checked_at": now(), "read_only": True, "number": NUMBER,
        "type_code": "declaration", "issue_date": expected["startDate"],
        "expire_date": expected["endDate"], "full_catalog_pages": pages,
        "full_catalog_cards_read": count, "expected_target_cards": 929,
        "target_cards_read": sum(len(x) == 1 for x in found.values()),
        "document_state_counts": dict(doc_counts),
        "scope_basis_counts": dict(scope_counts),
        "eligible_target_cards_with_exact_document": eligible_applied,
        "eligible_target_cards_expected": 867,
        "cards_with_other_fields_preserved": fields_preserved,
        "cards_with_all_preexisting_documents_preserved": prior_docs_preserved,
        "out_of_scope_cards_with_new_document": outside_has_doc,
        "wb_initial_successful_batches": len(state.get("batches", [])),
        "wb_recovery_batches_accepted": len((state.get("recovery") or {}).get("batches", [])),
        "wb_review_left_pending": True, "local_files_deleted": False,
        "rows": rows,
    }
    output["verified_complete"] = (
        output["target_cards_read"] == 929
        and eligible_applied == 867
        and doc_counts == {"exact_visible": 867, "missing": 62}
        and fields_preserved == 929
        and prior_docs_preserved == 929
        and outside_has_doc == 0
    )
    save(OUT, output)
    print(json.dumps({k: v for k, v in output.items() if k != "rows"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
