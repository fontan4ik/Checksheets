"""Build a current coverage report, reconciling verified 04824/22 write readbacks."""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE / "live_marketplaces_snapshot_latest_reconciled_20261023.json"
EXECUTION = HERE / "arlight_04824_crossplatform_execution_20261023.json"
DELAYED = HERE / "arlight_04824_wb_delayed_recheck_20261023.json"
MERGED = HERE / "live_marketplaces_snapshot_latest_postwrite_reconciled_20261023.json"


def main() -> None:
    snapshot = json.loads(BASE.read_text(encoding="utf-8"))
    execution = json.loads(EXECUTION.read_text(encoding="utf-8"))
    delayed = json.loads(DELAYED.read_text(encoding="utf-8"))
    if (snapshot.get("complete") is not True or delayed.get("read_only") is not True
            or delayed.get("target_count") != 120 or delayed.get("fully_preserved_count") != 120):
        raise RuntimeError("complete_snapshot_or_delayed_readback_required")

    certs = snapshot["ozon_certificates"]["certificates"]
    cert_id = str(execution["ozon"]["certificate_id"])
    if any(str(row.get("certificate_id")) == cert_id for row in certs):
        raise RuntimeError("postwrite_ozon_record_already_in_base_snapshot")
    ozon_readback = execution["ozon"]["readback"]
    if len(ozon_readback) != 120 or any(not row.get("present") or not row.get("sku_matches") for row in ozon_readback):
        raise RuntimeError("ozon_readback_not_complete_and_exact")
    certs.append({
        "certificate_id": int(cert_id), "certificate_name": "Сертификат соответствия № ЕАЭС RU С-HK.АБ53.В.04824/22",
        "certificate_number": "ЕАЭС RU С-HK.АБ53.В.04824/22", "type_code": "certificate_of_conformity",
        "status_code": execution["ozon"]["record_status"], "accordance_type_code": "EAEU",
        "rejection_reason_code": None, "issue_date": "2022-06-20", "expire_date": "2027-06-19",
        "products_count": len(ozon_readback), "verification_comment": None,
        "live_bindings": [{"product_id": int(row["product_id"]),
                            "product_status_code": row["status"], "sku": int(row["sku"])}
                           for row in ozon_readback],
        "live_binding_count": len(ozon_readback),
    })
    snapshot["ozon_certificates"]["records"] = len(certs)
    snapshot["ozon_certificates"]["total_bindings"] = sum(len(c.get("live_bindings") or []) for c in certs)
    snapshot["ozon_certificates"].setdefault("status_counts", {})[execution["ozon"]["record_status"]] = (
        snapshot["ozon_certificates"].setdefault("status_counts", {}).get(execution["ozon"]["record_status"], 0) + 1)

    delayed_by_offer = {row["offer_id"]: row for row in delayed["rows"]}
    cards_by_offer = {}
    for card in snapshot["wb_catalog"]["cards"]:
        offer = str(card.get("vendorCode") or "")
        if offer in delayed_by_offer:
            cards_by_offer.setdefault(offer, []).append(card)
    if len(cards_by_offer) != 120 or any(len(rows) != 1 for rows in cards_by_offer.values()):
        raise RuntimeError("wb_snapshot_target_cards_missing_or_ambiguous")
    merged_docs = 0
    for offer, audit in delayed_by_offer.items():
        if not audit.get("exact_metadata_visible"):
            continue
        card = cards_by_offer[offer][0]
        if str(card.get("nmID")) != audit.get("nmID") or not audit.get("identity_matches"):
            raise RuntimeError("wb_card_identity_conflict:" + offer)
        items = (card.setdefault("documents", {}).setdefault("items", []))
        document_id = audit.get("document_id")
        number = "ЕАЭС RU С-HK.АБ53.В.04824/22"
        already = [item for item in items if str(item.get("id")) == str(document_id)
                   or str(item.get("number")) == number]
        if already:
            raise RuntimeError("target_document_already_in_base_snapshot:" + offer)
        items.append({"id": document_id, "type": 1, "number": number,
                      "startDate": "2022-06-20T00:00:00Z", "endDate": "2027-06-19T00:00:00Z",
                      "isEndless": False, "verdict": audit.get("verdict") or {}})
        merged_docs += 1
    if merged_docs != delayed.get("exact_metadata_count"):
        raise RuntimeError("merged_wb_document_count_mismatch")
    snapshot["wb_catalog"]["checked_at"] = delayed["checked_at_utc"]
    snapshot["merged_postwrite_readbacks"] = {
        "ozon_record_id": cert_id, "ozon_readback_checked_at": execution["finished_at"],
        "ozon_binding_count": len(ozon_readback), "ozon_product_status_counts": execution["ozon"]["readback_status_counts"],
        "wb_document_number": "ЕАЭС RU С-HK.АБ53.В.04824/22",
        "wb_target_readback_checked_at": delayed["checked_at_utc"],
        "wb_target_count": delayed["target_count"], "wb_exact_metadata_count": merged_docs,
        "wb_verdict_counts": delayed["verdict_counts"],
    }
    MERGED.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    source = (HERE / "build_current_coverage_report_postwrite_20261023.py").read_text(encoding="utf-8")
    source = source.replace('live_marketplaces_snapshot_postwrite_ozon_20261023.json', MERGED.name)
    source = source.replace('current_coverage_report_postwrite_20261023.json', 'current_coverage_report_latest_20261023.json')
    source = source.replace('verified_group_edges_current_postwrite_20261023.csv', 'verified_group_edges_current_latest_20261023.csv')
    source = source.replace(
        'elif len(exact) != 1:\n                    ozon_state = "missing_or_duplicate_exact_ozon_record"\n                else:\n                    cert = exact[0]',
        'elif not exact:\n                    ozon_state = "missing_or_duplicate_exact_ozon_record"\n'
        '                elif len(exact) > 1:\n'
        '                    target_bindings = [(c, b) for c in exact for b in (c.get("live_bindings") or [])\n'
        '                                       if str(b.get("product_id")) == str(target["product_id"])]\n'
        '                    if any(str(b.get("sku")) != str(target["sku"]) for _, b in target_bindings):\n'
        '                        ozon_state = "binding_identity_conflict"\n'
        '                    elif any(c.get("status_code") == "approved" and b.get("product_status_code") == "approved"\n'
        '                             for c, b in target_bindings):\n'
        '                        ozon_state = "approved_link"\n'
        '                    elif any(b.get("product_status_code") == "declined" for _, b in target_bindings):\n'
        '                        ozon_state = "declined_link"\n'
        '                    elif target_bindings:\n'
        '                        ozon_state = "pending_link_or_document"\n'
        '                    elif any(c.get("status_code") != "approved" for c in exact):\n'
        '                        ozon_state = "document_not_approved"\n'
        '                    else:\n'
        '                        ozon_state = "missing_binding"\n'
        '                else:\n                    cert = exact[0]')
    target_script = HERE / "_build_current_coverage_report_latest_worker_20261023.py"
    target_script.write_text(source, encoding="utf-8")
    print(json.dumps({"merged_snapshot": str(MERGED), "wb_target_docs_merged": merged_docs,
                      "ozon_target_bindings_merged": len(ozon_readback)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
