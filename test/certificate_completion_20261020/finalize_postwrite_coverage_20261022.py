#!/usr/bin/env python3
"""Finalize delayed cross-platform readbacks and update the incremental coverage journal."""
from __future__ import annotations

import collections
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read(name: str) -> dict:
    return json.loads((HERE / name).read_text())


def save(name: str, value: dict) -> None:
    path = HERE / name
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def wb_exact_valid(row: dict, number: str, issue: str, expiry: str, wb_type: int) -> bool:
    if row.get("status") != "verified_exact" or row.get("exact_metadata") is not True:
        return False
    docs = row.get("documents") or []
    matches = [d for d in docs if d.get("number") == number]
    if len(matches) != 1:
        return False
    doc = matches[0]
    verdict = doc.get("verdict") or row.get("verdict") or {}
    return (
        str(doc.get("type")) == str(wb_type)
        and str(doc.get("startDate", ""))[:10] == issue
        and str(doc.get("endDate", ""))[:10] == expiry
        and isinstance(verdict, dict)
        and verdict.get("verified") is True
        and verdict.get("reason") == "valid"
    )


def merge_wb(rows: list[dict], number: str, issue: str, expiry: str, expected: int,
             wb_type: int) -> list[dict]:
    by_offer: dict[str, dict] = {}
    for row in rows:
        offer = str(row.get("offer_id") or "")
        if not offer:
            continue
        prior = by_offer.get(offer)
        if prior is None or wb_exact_valid(row, number, issue, expiry, wb_type):
            by_offer[offer] = row
    if len(by_offer) != expected:
        raise RuntimeError(f"WB distinct card count mismatch: expected={expected}, got={len(by_offer)}")
    bad = [offer for offer, row in by_offer.items() if not wb_exact_valid(row, number, issue, expiry, wb_type)]
    if bad:
        raise RuntimeError(f"WB exact-valid readback incomplete for {len(bad)} cards: {bad[:10]}")
    return [by_offer[k] for k in sorted(by_offer)]


def finalize_gauss(prefix: str, number: str, issue: str, expiry: str,
                   ozon_expected: int, wb_expected: int, ozon_id: int,
                   wb_type: int) -> dict:
    initial = read(f"{prefix}_wb_readback_20261022.json")
    delayed = read(f"{prefix}_wb_delayed_readback_20261022.json") if prefix == "gauss_02947" else read(f"{prefix}_delayed_readback_20261022.json")
    delayed_rows = delayed.get("results") or delayed.get("wb_results") or []
    wb_rows = merge_wb(initial["results"] + delayed_rows, number, issue, expiry, wb_expected, wb_type)
    if prefix == "gauss_02947":
        ozon = read("gauss_02947_ozon_delayed_readback_20261022.json")
    else:
        ozon = delayed
    if ozon.get("record_status", ozon.get("ozon_record_status")) != "approved":
        raise RuntimeError(prefix + ": Ozon document is not approved")
    if ozon.get("expected", ozon.get("ozon_expected")) != ozon_expected:
        raise RuntimeError(prefix + ": Ozon expected target count changed")
    if ozon.get("visible_exact", ozon.get("ozon_visible_exact")) != ozon_expected:
        raise RuntimeError(prefix + ": Ozon exact binding readback incomplete")
    counts = collections.Counter(
        str(((r.get("documents") or [{}])[0].get("verdict") or {}).get("reason") or "unknown")
        for r in wb_rows
    )
    final = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "number": number,
        "ozon": {
            "certificate_id": ozon_id,
            "document_status": "approved",
            "expected_exact_bindings": ozon_expected,
            "visible_exact_bindings": ozon_expected,
            "binding_status_counts": {"approved": ozon_expected},
            "missing_or_conflicting": 0,
        },
        "wb": {
            "expected_exact_cards": wb_expected,
            "visible_exact_cards_with_valid_document_verdict": len(wb_rows),
            "document_verdict_counts": dict(counts),
            "review_left_pending": True,
            "metadata_manually_changed_by_agent": False,
        },
        "local_source_deleted": False,
        "source_artifacts": [
            f"{prefix}_execution_20261022.json",
            ("gauss_02947_ozon_delayed_readback_20261022.json" if prefix == "gauss_02947" else "gauss_15079_delayed_readback_20261022.json"),
            f"{prefix}_wb_readback_20261022.json",
            ("gauss_02947_wb_delayed_readback_20261022.json" if prefix == "gauss_02947" else "gauss_15079_delayed_readback_20261022.json"),
        ],
        "wb_rows": wb_rows,
    }
    out = f"{prefix}_final_crossplatform_readback_20261022.json"
    save(out, final)
    state_path = HERE / f"{prefix}_execution_20261022.json"
    state = json.loads(state_path.read_text())
    state["phase"] = "cross_marketplace_readback_complete"
    state["finished_at_utc"] = final["checked_at_utc"]
    state["final_readback_artifact"] = out
    state["ozon_final_status_counts"] = {"approved": ozon_expected}
    state["wb_final_exact_valid_cards"] = len(wb_rows)
    state["local_source_deleted"] = False
    save(state_path.name, state)
    return final


def finalize_jazzway() -> dict:
    number = "ЕАЭС N RU Д-HK.РА08.В.37909/22"
    execution = read("jazzway_37909_uncovered_execution_20261022.json")
    ozon = read("jazzway_37909_ozon_delayed_readback_20261022.json")
    wb_first = read("jazzway_37909_uncovered_wb_readback_20261022.json")
    wb_retry = read("jazzway_37909_uncovered_wb_retry_readback_20261022.json")
    wb_delayed = read("jazzway_37909_wb_final_delayed_readback_20261022.json")
    if ozon.get("record_status") != "approved" or ozon.get("expected_targets") != 109 or ozon.get("visible_exact_targets") != 109 or ozon.get("target_status_counts") != {"approved": 109}:
        raise RuntimeError("Jazzway Ozon delayed readback incomplete")
    wb_rows = merge_wb(wb_first["results"] + wb_retry["results"] + wb_delayed["results"], number,
                       "2022-11-21", "2027-11-20", 106, 2)
    final = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "number": number,
        "ozon": {"certificate_id": 5458891, "document_status": "approved", "expected_exact_bindings": 109,
                 "visible_exact_bindings": 109, "binding_status_counts": {"approved": 109}, "missing_or_conflicting": 0},
        "wb": {"expected_exact_cards": 106, "visible_exact_cards_with_valid_document_verdict": 106,
               "document_verdict_counts": {"valid": 106}, "review_left_pending": True,
               "metadata_manually_changed_by_agent": False},
        "local_source_deleted": False,
        "source_artifacts": ["jazzway_37909_uncovered_execution_20261022.json",
                             "jazzway_37909_ozon_delayed_readback_20261022.json",
                             "jazzway_37909_uncovered_wb_readback_20261022.json",
                             "jazzway_37909_uncovered_wb_retry_readback_20261022.json",
                             "jazzway_37909_wb_final_delayed_readback_20261022.json"],
        "wb_rows": wb_rows,
    }
    out = "jazzway_37909_final_crossplatform_readback_20261022.json"
    save(out, final)
    execution["phase"] = "cross_marketplace_readback_complete"
    execution["finished_at_utc"] = final["checked_at_utc"]
    execution["final_readback_artifact"] = out
    execution["ozon_final_status_counts"] = {"approved": 109}
    execution["wb_final_exact_valid_cards"] = 106
    execution["local_source_deleted"] = False
    save("jazzway_37909_uncovered_execution_20261022.json", execution)
    return final


def main() -> None:
    gauss_02947 = finalize_gauss("gauss_02947", "ЕАЭС RU C-CN.HB54.B.02947/22", "2022-06-08", "2027-06-07", 133, 141, 5948463, 1)
    gauss_15079 = finalize_gauss("gauss_15079", "ЕАЭС N RU Д-CN.PA04.В.15079/22", "2022-06-10", "2027-06-08", 127, 135, 5948665, 2)
    jazzway = finalize_jazzway()

    addendum = read("postwrite_coverage_addendum_20261022.json")
    writes = addendum.setdefault("post_snapshot_writes", [])
    recorded = {x.get("document_number") for x in writes}
    entries = [
        {
            "brand": "Gauss", "document_number": "ЕАЭС RU C-CN.HB54.B.02947/22", "type": "certificate_of_conformity",
            "source_sha256": "c1bae8dcead5bd3086090af159f5655a2460dbaa093140bac6068a4d64788108",
            "ozon_certificate_id": 5948463, "ozon_record_status": "approved", "ozon_exact_bindings": 133,
            "ozon_binding_status_counts": {"approved": 133}, "wb_exact_cards": 141, "wb_valid_cards": 141,
            "wb_review_metadata_manually_changed": False, "local_source_pdf_deleted": False,
            "verification_artifacts": ["gauss_02947_live_preflight_20261022.json", "gauss_02947_final_crossplatform_readback_20261022.json"]
        },
        {
            "brand": "Gauss", "document_number": "ЕАЭС N RU Д-CN.PA04.В.15079/22", "type": "declaration",
            "source_sha256": "af19f822882e35ad0da1ed741deba0e5c6868eb744c09712a95e3aa5dd75b9ee",
            "ozon_certificate_id": 5948665, "ozon_record_status": "approved", "ozon_exact_bindings": 127,
            "ozon_binding_status_counts": {"approved": 127}, "wb_exact_cards": 135, "wb_valid_cards": 135,
            "wb_review_metadata_manually_changed": False, "local_source_pdf_deleted": False,
            "verification_artifacts": ["gauss_15079_live_preflight_20261022.json", "gauss_15079_final_crossplatform_readback_20261022.json"]
        },
        {
            "brand": "Jazzway", "document_number": "ЕАЭС N RU Д-HK.РА08.В.37909/22", "type": "declaration",
            "source_sha256": "ac05304912cfc122dfe810a85f16a4f801e680da3b6ccf93bff2707cfa8335ae",
            "ozon_certificate_id": 5458891, "ozon_record_status": "approved", "ozon_exact_bindings": 109,
            "ozon_binding_status_counts": {"approved": 109}, "wb_exact_cards": 106, "wb_valid_cards": 106,
            "wb_review_metadata_manually_changed": False, "local_source_pdf_deleted": False,
            "verification_artifacts": ["jazzway_37909_uncovered_preflight_20261022.json", "jazzway_37909_final_crossplatform_readback_20261022.json"]
        },
        {
            "brand": "Arlight", "document_number": "ЕАЭС N RU Д-CN.РА09.В.52132/25", "type": "declaration",
            "source_sha256": "1af35bb24d9f014ea59b14ffbd88f42b705a4f5fb285e57a683d24542c26c225",
            "ozon_certificate_id": 5920271, "ozon_record_status": "approved", "ozon_preexisting_exact_bindings": 929,
            "ozon_new_safe_bindings": 0, "ozon_scope_held_targets": 443,
            "wb_safe_target_cards": 396, "wb_exact_valid_cards": 357, "wb_unresolved_cards": 39,
            "wb_review_metadata_manually_changed": False, "local_source_pdf_deleted": False,
            "limitation": "Ozon TN VED 9405190039 is out of declaration scope. WB accepts update responses but does not persist metadata on 39 subjectID 9215 desk-lamp cards despite delayed and individual retries.",
            "verification_artifacts": ["arlight_52132_uncovered_preflight_20261022.json", "arlight_52132_wb_uncovered_readback_20261022.json", "arlight_52132_wb_delayed_recheck_20261022.json", "arlight_52132_wb_individual_retry_20261022.json"]
        }
    ]
    for entry in entries:
        if entry["document_number"] not in recorded:
            writes.append(entry)
            recorded.add(entry["document_number"])

    addendum.setdefault("current_live_reconciliations", {})["iek_remaining_20261022"] = {
        "source_verified_groups": 19, "target_edges": 134, "ozon_exact_bindings": 134,
        "ozon_binding_status_counts": {"approved": 134}, "wb_offer_rows_checked": 134,
        "wb_unique_offers_checked": 107, "wb_exact_cards_found": 0,
        "wb_result_counts": {"wb_card_missing": 134}, "mutation_attempted": False,
        "local_source_files_deleted": False,
        "limitation": "No exact IEK/ITK WB offer-card mapping was found. Similar Navigator items have a different brand and TN VED, so they were excluded.",
        "verification_artifact": "iek_remaining_live_preflight_20261022.json"
    }
    addendum["checked_at_utc"] = datetime.now(timezone.utc).isoformat()
    addendum["local_source_pdfs_deleted"] = False
    addendum["complete"] = False
    addendum["limitation"] = (addendum.get("limitation", "") + " Incremental writes after the baseline are enumerated above; global product totals remain the baseline until a new complete live snapshot is collected. Arlight 52132 has 39 WB metadata persistence failures; IEK has 134 approved Ozon links but no exact WB cards. Local sources remain because cross-platform coverage is incomplete.").strip()
    save("postwrite_coverage_addendum_20261022.json", addendum)

    print(json.dumps({
        "finalized": {
            "gauss_02947": {"ozon": gauss_02947["ozon"], "wb": gauss_02947["wb"]},
            "gauss_15079": {"ozon": gauss_15079["ozon"], "wb": gauss_15079["wb"]},
            "jazzway_37909": {"ozon": jazzway["ozon"], "wb": jazzway["wb"]},
        },
        "journal_post_snapshot_entries": len(writes),
        "current_live_reconciliations": list(addendum["current_live_reconciliations"]),
        "local_source_pdfs_deleted": False,
        "complete": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
