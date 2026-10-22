"""Fresh WB verification of already-linked Arlight declaration 69060/25."""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
import run_all_found_certificates_20261014 as runner  # noqa: E402

MANIFEST = HERE / "expanded_found_certificates_manifest_20261020.json"
SOURCE_PREFLIGHT = API / "arlight_69060_preflight_20261012.json"
OZON_PREFLIGHT = HERE / "arlight_69060_crossplatform_preflight_live_20261021.json"
OUT = HERE / "arlight_69060_wb_live_readback_20261021.json"
NUMBER = "RU Д-НK.PА02.B.69060/25"
ALLOWED_FAMILIES = ("ARPV", "ARDV", "HTS", "ARV", "ARS", "JTS", "HTPS", "ARJ", "ARPJ")


def save(d: dict) -> None:
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2))
    tmp.replace(OUT)


def norm_date(value) -> str:
    return str(value or "")[:10]


def main() -> None:
    ozon = json.loads(OZON_PREFLIGHT.read_text())
    checked = dt.datetime.fromisoformat(ozon["checked_at_utc"].replace("Z", "+00:00"))
    age = (dt.datetime.now(dt.timezone.utc) - checked).total_seconds()
    if ozon.get("complete") is not True or age < 0 or age > 1800:
        raise RuntimeError("Ozon preflight is missing, incomplete, or older than 30 minutes")
    if ozon["ozon"].get("eligible") != 549 or ozon["ozon"].get("target_binding_status_counts") != {"approved": 549}:
        raise RuntimeError("Ozon exact approved-link evidence changed or is incomplete")
    if len(ozon["ozon"].get("exact_document_records") or []) != 1:
        raise RuntimeError("Ozon exact declaration record absent or duplicated")
    record = ozon["ozon"]["exact_document_records"][0]
    if record.get("status_code") != "approved" or record.get("type_code") != "declaration":
        raise RuntimeError("Ozon declaration status/type changed")

    manifest = json.loads(MANIFEST.read_text())
    group = next(g for g in manifest["groups"] if g.get("number") == NUMBER)
    expected = {str(t["offer_id"]): t for t in group["targets"]}
    source = json.loads(SOURCE_PREFLIGHT.read_text())
    source_targets = {str(t["offer_id"]): t for t in source.get("targets", [])}
    if len(expected) != 549 or len(source_targets) != 549 or set(expected) != set(source_targets):
        raise RuntimeError("Source-assignment crosswalk does not exactly match the target manifest")

    result = {
        "checked_at_utc": now(), "read_only": True, "complete": False,
        "number": NUMBER,
        "basis": {
            "ozon_preflight_checked_at": ozon["checked_at_utc"],
            "ozon_certificate_id": record.get("certificate_id"),
            "ozon_status": record.get("status_code"),
            "ozon_approved_target_bindings": 549,
            "source_crosswalk": str(SOURCE_PREFLIGHT),
            "source_crosswalk_target_count": len(source_targets),
            "wb_catalog_method": "complete WB catalog pagination, then exact vendorCode + source nmID match",
        },
        "wildberries": {"complete": False, "targets": []},
    }
    client = Client()
    cards: list[dict] = []
    cursor: dict = {"limit": 100}
    seen: set[tuple] = set()
    pages = 0
    while True:
        body = client.call("wb", "/content/v2/get/cards/list", {"settings": {
            "sort": {"ascending": True}, "cursor": cursor,
            "filter": {"withPhoto": -1},
        }})
        batch = body.get("cards")
        returned = body.get("cursor") or {}
        if body.get("error") or not isinstance(batch, list) or returned.get("total") != len(batch):
            raise RuntimeError("WB catalog response/page count incomplete")
        cards.extend(batch)
        pages += 1
        if pages % 30 == 0:
            print(json.dumps({"phase": "wb_full_catalog", "pages": pages, "cards": len(cards)}, ensure_ascii=False), flush=True)
        if len(batch) < 100:
            break
        signature = (returned.get("updatedAt"), returned.get("nmID"))
        if None in signature or signature in seen:
            raise RuntimeError("WB catalog pagination cursor missing or repeated")
        seen.add(signature)
        cursor = {"limit": 100, "updatedAt": signature[0], "nmID": signature[1]}
        time.sleep(0.65)
    raw_rows = len(cards)
    cards, equivalent_duplicates = runner.deduplicate_equivalent_wb_rows(cards)
    by_offer: dict[str, list[dict]] = {}
    for card in cards:
        by_offer.setdefault(str(card.get("vendorCode") or ""), []).append(card)

    target_results = []
    for offer, target in expected.items():
        src = source_targets[offer]
        rows = by_offer.get(offer, [])
        nm_id = str(src.get("wb_nmID") or "")
        exact = [c for c in rows if str(c.get("nmID") or "") == nm_id]
        card = exact[0] if len(rows) == 1 and len(exact) == 1 else {}
        problems = []
        if len(rows) != 1 or len(exact) != 1:
            problems.append("exact_vendor_code_or_source_nmID_missing_or_ambiguous")
        family_matches = [family for family in ALLOWED_FAMILIES
                          if family in str(src.get("name") or "").upper()]
        if not family_matches:
            problems.append("source_model_not_in_declared_series")
        scope_error = runner.wb_scope_error(card, group, target) if card else None
        if scope_error:
            problems.append(scope_error)
        docs = ((card.get("documents") or {}).get("items") or []) if card else []
        doc_rows = [d for d in docs if runner.norm_number(d.get("number")) == runner.norm_number(NUMBER)]
        correct_rows = [d for d in doc_rows if d.get("type") == runner.OZON_TO_WB_TYPE["declaration"]
                        and norm_date(d.get("startDate")) == "2025-03-10"
                        and norm_date(d.get("endDate")) == "2030-03-09"]
        if len(correct_rows) != 1:
            problems.append("exact_WB_document_row_missing_duplicate_or_conflicting")
        verdict = (correct_rows[0].get("verdict") or {}) if len(correct_rows) == 1 else {}
        valid = verdict.get("verified") is True and verdict.get("status") == 1 and verdict.get("reason") == "valid"
        if not valid:
            problems.append("WB_verdict_not_confirmed_valid")
        target_results.append({
            "offer_id": offer, "product_id": str(target.get("product_id")), "sku": str(target.get("sku")),
            "wb_nmID": nm_id, "source_name": src.get("name"),
            "source_article_basis": src.get("official_article"),
            "model_family_match": family_matches,
            "brand": card.get("brand") if card else None,
            "tnved_values": [str(c.get("value")) for c in (card.get("characteristics") or [])
                             if "тнвэд" in "".join(str(c.get("name") or "").casefold().split())
                             or "тнвед" in "".join(str(c.get("name") or "").casefold().split())] if card else [],
            "document_rows": correct_rows,
            "verdict_valid": valid,
            "eligible_and_confirmed": not problems,
            "problems": problems,
        })

    counts = Counter()
    for row in target_results:
        counts["eligible_and_confirmed" if row["eligible_and_confirmed"] else "has_problem"] += 1
        counts["valid_WB_verdict" if row["verdict_valid"] else "invalid_or_unconfirmed_verdict"] += 1
        counts["exact_doc_row" if row["document_rows"] else "no_exact_doc_row"] += 1
    problem_reasons = Counter(problem for row in target_results for problem in row["problems"])
    result["wildberries"] = {
        "complete": True, "checked_at_utc": now(), "catalog_pages": pages,
        "catalog_raw_rows": raw_rows, "catalog_unique_rows": len(cards),
        "equivalent_duplicates_removed": equivalent_duplicates,
        "target_count": len(target_results), "counts": dict(counts),
        "problem_reasons": dict(problem_reasons), "targets": target_results,
    }
    result["complete"] = True
    result["summary"] = {
        "ozon_approved_exact_bindings": 549,
        "wb_exact_cards_with_valid_document": sum(r["eligible_and_confirmed"] for r in target_results),
        "wb_targets": len(target_results),
        "wb_problem_reasons": dict(problem_reasons),
        "declaration_uploaded_to_both_platforms_for_all_targets": not problem_reasons and len(target_results) == 549,
    }
    save(result)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
