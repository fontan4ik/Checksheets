"""Reconcile fresh full WB cards against the official scope for Arlight 52132/25."""
from __future__ import annotations

import collections
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
OZON_PATH = BASE / "arlight_52132_ozon_preflight_20261012.json"
WB_PATH = BASE / "arlight_52132_wb_fullcards_before_20261012.json"
OUT = BASE / "arlight_52132_wb_scope_verification_final_20261012.json"


def norm(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def tnved_values(card: dict) -> list[str]:
    values = []
    for item in card.get("characteristics") or []:
        if int(item.get("id", -1)) != 15000001 and str(item.get("name", "")).strip().lower() != "тнвэд":
            continue
        raw = item.get("value")
        values.extend(str(value).split(" - ", 1)[0].strip()
                      for value in (raw if isinstance(raw, list) else [raw])
                      if value not in (None, ""))
    return sorted(set(values))


def main() -> None:
    if OUT.exists():
        raise RuntimeError("Output already exists; inspect before replacing")
    ozon = json.loads(OZON_PATH.read_text())
    wb = json.loads(WB_PATH.read_text())
    if (not wb.get("complete") or wb.get("full_catalog_cards") != 19962
            or wb.get("duplicate_nmids") != 0):
        raise RuntimeError("Fresh complete unique WB full-catalog read is required")
    allowed = set(ozon["fsa_tnved_codes"])
    ozon_targets = {row["offer_id"]: row for row in ozon["targets"]
                    if not row["preflight_issues"] and row["tnved_in_scope"]}
    cards = wb.get("cards_by_offer") or {}
    if set(cards) != set(ozon_targets):
        raise RuntimeError("WB full-card target set does not exactly match Ozon candidates")

    entries = []
    reasons = collections.Counter()
    evidence_bases = collections.Counter()
    wb_codes = collections.Counter()
    existing_rows = []
    for offer, source in sorted(ozon_targets.items()):
        card = cards[offer]
        codes = tnved_values(card)
        wb_codes[",".join(codes) if codes else "<missing>"] += 1
        issues = []
        if card.get("vendorCode") != offer or str(card.get("nmID")) != str(source["wb_nmID"]):
            issues.append("exact_wb_identity_mismatch")
        if card.get("brand") != "Arlight":
            issues.append("wb_brand_not_exact_Arlight")
        warnings = []
        if len(codes) != 1:
            ozon_codes = source["tnved_codes"]
            if not codes and len(ozon_codes) == 1 and ozon_codes[0] in allowed:
                warnings.append("wb_tnved_blank; exact matching Ozon article has an allowed single code")
                evidence_bases["ozon_tnved_fallback_wb_blank"] += 1
            else:
                issues.append("wb_tnved_missing_or_ambiguous")
        elif codes[0] not in allowed:
            issues.append("wb_tnved_outside_fsa_scope")
        else:
            evidence_bases["wb_tnved_allowed"] += 1
        doc_rows = [doc for doc in ((card.get("documents") or {}).get("items") or [])
                    if "5213225" in norm(doc.get("number"))]
        if doc_rows:
            existing_rows.append({"offer_id": offer, "nmID": str(card["nmID"]), "rows": doc_rows})
        for issue in issues:
            reasons[issue] += 1
        entries.append({
            "offer_id": offer,
            "product_id": source["product_id"],
            "sku": source["sku"],
            "wb_nmID": str(card["nmID"]),
            "product_name": source["product_name"],
            "wb_title": card.get("title"),
            "ozon_tnved_codes": source["tnved_codes"],
            "wb_tnved_codes": codes,
            "wb_brand": card.get("brand"),
            "eligible_for_wb_binding": not issues,
            "scope_warnings": warnings,
            "exclusion_reasons": issues,
            "preexisting_document_rows": doc_rows,
        })

    eligible = [row for row in entries if row["eligible_for_wb_binding"]]
    output = {
        "read_only": True,
        "number": ozon["number"],
        "document_type": "declaration",
        "source_sha256": ozon["local_source_sha256"],
        "fsa_tnved_codes": sorted(allowed),
        "ozon_preflight_checked_at_utc": ozon["checked_at_utc"],
        "wb_full_catalog_checked_at_utc": wb["checked_at"],
        "wb_full_catalog_cards": wb["full_catalog_cards"],
        "wb_duplicate_nmids": wb["duplicate_nmids"],
        "ozon_candidates": len(ozon_targets),
        "wb_cards_exactly_verified": len(cards),
        "wb_eligible_count": len(eligible),
        "wb_excluded_count": len(entries) - len(eligible),
        "wb_exclusion_reason_counts": dict(reasons),
        "wb_scope_evidence_basis_counts": dict(evidence_bases),
        "wb_tnved_counts": dict(wb_codes),
        "existing_exact_number_rows": len(existing_rows),
        "existing_exact_number_row_details": existing_rows,
        "local_cleanup_allowed": False,
        "eligible_targets": eligible,
        "excluded_targets": [row for row in entries if not row["eligible_for_wb_binding"]],
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps({key: output[key] for key in (
        "number", "wb_full_catalog_checked_at_utc", "ozon_candidates",
        "wb_cards_exactly_verified", "wb_eligible_count", "wb_excluded_count",
        "wb_exclusion_reason_counts", "wb_scope_evidence_basis_counts", "wb_tnved_counts",
        "existing_exact_number_rows",
        "local_cleanup_allowed",
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()
