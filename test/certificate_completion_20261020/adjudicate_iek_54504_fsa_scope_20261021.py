"""Reconcile the fresh API preflight against the official FSA product scope."""
from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
RAW = HERE / "iek_54504_preflight_live_20261021.json"
OUT = HERE / "iek_54504_preflight_adjudicated_20261021.json"
ALLOWED_BRANDS = {"IEK", "Generica"}
ALLOWED_TNVED = {"9403700008"}


def main() -> None:
    if OUT.exists():
        raise RuntimeError("adjudication_output_exists")
    data = json.loads(RAW.read_text(encoding="utf-8"))
    if data.get("read_only") is not True or data.get("number") != "RU Д-RU.РА08.В.54504/26":
        raise RuntimeError("raw_preflight_identity_mismatch")
    if data.get("official_fsa", {}).get("status") != "active":
        raise RuntimeError("fsa_status_not_active")
    if set(data.get("official_fsa", {}).get("tnved") or []) != ALLOWED_TNVED:
        raise RuntimeError("fsa_tnved_scope_mismatch")
    # Confirmed in the current FSA common/product tabs (record 21675817).
    data["official_fsa"]["brands"] = sorted(ALLOWED_BRANDS)

    for target in data["ozon_targets"]:
        brand = target.get("brand_values") or []
        target["brand_matches_fsa_scope"] = len(brand) == 1 and brand[0] in ALLOWED_BRANDS
        target["tnved_matches_fsa_scope"] = bool(target.get("tnved_codes")) and set(target["tnved_codes"]) <= ALLOWED_TNVED

    existing_exact = sum(x.get("already_exact") is True for x in data["wb_targets"])
    wb_missing = sum(x.get("problem") == "missing_or_duplicate_exact_wb_card" for x in data["wb_targets"])
    wb_conflicts = [x for x in data["wb_targets"] if x.get("same_number_rows") and not x.get("already_exact")]
    data["ozon_brand_counts"] = {
        brand: sum(x.get("brand_values") == [brand] for x in data["ozon_targets"])
        for brand in sorted(ALLOWED_BRANDS)
    }
    data["wb_reconciliation"] = {
        "exact_metadata_rows_already_present": existing_exact,
        "no_exact_card_or_duplicate_card": wb_missing,
        "same_number_metadata_conflicts": len(wb_conflicts),
        "wb_update_needed_for_existing_cards": False,
        "wb_review_left_pending": True,
    }
    data["ozon_preflight_safe"] = (
        len(data["ozon_targets"]) == 76
        and all(x.get("product_id_matches") and x.get("sku_matches")
                and x.get("live_archived") is False and x.get("brand_matches_fsa_scope")
                and x.get("tnved_matches_fsa_scope") for x in data["ozon_targets"])
        and data.get("ozon_exact_lookup_absence_confirmed") is True
        and not data.get("ozon_exact_record_matches")
    )
    data["eligible_for_ozon_create_and_binding"] = data["ozon_preflight_safe"]
    data["local_file_deleted"] = False
    data["adjudication_basis"] = (
        "Official FSA product tab names IEK and GENERICA, exact article families are recorded in the "
        "official IEK XML assignment manifest, and all 76 current Ozon offers have TNVED 9403700008. "
        "WB already has exact document number/type/dates on 64 exact cards; 12 offers have no exact WB card."
    )
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(OUT)
    print(json.dumps({k: data[k] for k in ["ozon_preflight_safe", "eligible_for_ozon_create_and_binding",
                                          "ozon_brand_counts", "wb_reconciliation", "source_pdf_sha256"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
