"""Attach verified MOONLIGHT declaration to exact live Ozon and WB targets."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402
from run_all_found_certificates_20261014 import Runner  # noqa: E402

SNAPSHOT = HERE / "live_marketplaces_snapshot_resume_20261022.json"
PDF = ROOT / "output_to_user/certificates/additional_search/brand_research/arlight/followup_2026_10_02_c/docs/moonlight_037_87392_22_official.pdf"
MANIFEST = HERE / "arlight_moonlight_87392_manifest_20261022.json"
STATE = HERE / "arlight_moonlight_87392_execution_20261022.json"
JOURNAL = HERE / "arlight_moonlight_87392_journal_20261022.jsonl"
NUMBER = "ЕАЭС N RU Д-CN.РА08.В.87392/22"
PDF_SHA256 = "cb52ca8a72f07018e22ecf6861cfcf48aad25963c11ab6937efb97a921d99267"
TARGETS = [
    {"offer_id": "025550-1", "product_id": "6345705737", "sku": "5803567812", "brand": "Arlight"},
    {"offer_id": "031017-1", "product_id": "6345705568", "sku": "5803568172", "brand": "Arlight"},
    {"offer_id": "031117-1", "product_id": "6345705339", "sku": "5803568222", "brand": "Arlight"},
]


def main() -> None:
    if any(p.exists() for p in (MANIFEST, STATE, JOURNAL,
                                HERE / "arlight_moonlight_87392_before_20261022.json",
                                HERE / "arlight_moonlight_87392_readback_20261022.json")):
        raise RuntimeError("Execution artifact exists; reconcile current live state before retry")
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if not all(snap.get(k, {}).get("complete") is True for k in
               ("ozon_products", "ozon_certificates", "wb_catalog")):
        raise RuntimeError("Fresh complete Ozon and WB catalog snapshots are required")
    if not PDF.is_file():
        raise RuntimeError("Official declaration PDF is unavailable")
    import hashlib
    pdf_hash = hashlib.sha256(PDF.read_bytes()).hexdigest()
    if pdf_hash != PDF_SHA256:
        raise RuntimeError("Official declaration PDF hash changed")

    ozon_by_offer = {}
    for p in snap["ozon_products"]["products"]:
        ozon_by_offer.setdefault(str(p.get("offer_id") or ""), []).append(p)
    wb_by_offer = {}
    for c in snap["wb_catalog"]["cards"]:
        wb_by_offer.setdefault(str(c.get("vendorCode") or ""), []).append(c)
    for target in TARGETS:
        rows = ozon_by_offer.get(target["offer_id"], [])
        if len(rows) != 1:
            raise RuntimeError("Ozon offer missing/duplicated in current snapshot: " + target["offer_id"])
        p = rows[0]
        if (str(p.get("product_id")) != target["product_id"] or str(p.get("sku")) != target["sku"]
                or p.get("is_archived") is not False or p.get("brand_values") != ["Arlight"]
                or [str(v).split(" - ", 1)[0].strip() for v in p.get("tnved_values") or []] != ["8539519009"]):
            raise RuntimeError("Ozon product identity, brand, activity, or TN VED changed: " + target["offer_id"])
        cards = wb_by_offer.get(target["offer_id"], [])
        if len(cards) != 1:
            raise RuntimeError("WB exact offer missing/duplicated in current snapshot: " + target["offer_id"])
        card = cards[0]
        if (str(card.get("brand") or "").strip().casefold() != "arlight"
                or "MOONLIGHT" not in (str(card.get("title") or "") + " " + str(card.get("description") or "")).upper()):
            raise RuntimeError("WB live identity/brand/model not in verified declaration scope: " + target["offer_id"])

    number_key = norm_number(NUMBER)
    duplicates = [c for c in snap["ozon_certificates"]["certificates"]
                  if norm_number(c.get("certificate_number")) == number_key]
    if duplicates:
        raise RuntimeError("Ozon already has a same-number record; reconcile instead of creating")

    group = {
        "number": NUMBER,
        "type_code": "declaration",
        "accordance_type": "EAEU",
        "country": "RU",
        "issue_date": "2022-12-07",
        "expire_date": "2027-12-06",
        "upload_file": {"path": str(PDF), "sha256": PDF_SHA256},
        "registry_url": "https://pub.fsa.gov.ru/rds/declaration/view/17278483/common",
        "source_evidence_verified": True,
        "allowed_tnved": ["8539519009"],
        "targets": TARGETS,
    }
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(),
                "scope_note": "FSA record 17278483: active EAEU 037/2016 declaration for Arlight MOONLIGHT LED strips; exact original PDF and current live product/card identities checked.",
                "groups": [group]}
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    runner = Runner(Client(), manifest, execute=True, journal=JOURNAL, state=STATE)
    runner.products = snap["ozon_products"]["products"]
    runner.cards = snap["wb_catalog"]["cards"]
    runner.certs = snap["ozon_certificates"]["certificates"]
    runner.checkpoint("fresh_crossplatform_snapshot_loaded")
    runner.process_groups()
    result = runner.state["groups"][-1] if runner.state.get("groups") else {}
    if result.get("status") != "processed" or not result.get("certificate_id"):
        runner.checkpoint("ozon_upload_or_binding_needs_reconciliation")
        raise RuntimeError("Ozon document was not fully processed; WB write withheld")

    cert = next((c for c in runner.certs
                 if str(c.get("certificate_id")) == str(result["certificate_id"])), None)
    if not cert:
        runner.checkpoint("ozon_record_missing_after_processing")
        raise RuntimeError("Ozon certificate record missing after processing")
    bindings = runner.client.ozon_bindings(cert["certificate_id"])
    by_product = {str(b.get("product_id")): b for b in bindings}
    binding_check = []
    for target in TARGETS:
        b = by_product.get(target["product_id"])
        exact = bool(b and str(b.get("sku")) == target["sku"]
                     and b.get("product_status_code") != "declined")
        binding_check.append({"offer_id": target["offer_id"], "product_id": target["product_id"],
                              "sku": target["sku"], "bound": exact,
                              "product_status_code": b.get("product_status_code") if b else None})
    runner.state["exact_ozon_binding_readback"] = binding_check
    runner.checkpoint("ozon_exact_bindings_read_back")
    if not all(row["bound"] for row in binding_check):
        raise RuntimeError("Ozon live readback does not confirm all exact bindings; WB write withheld")

    # The official FSA record specifies TN VED 8539519009 and Ozon's live codes
    # were checked above. WB's cards do not carry a TN VED value, so only its
    # per-card code check is omitted; exact brand, series, and offer are required.
    for source_group in runner.validated_source_groups:
        source_group["allowed_tnved"] = None
    runner.wb_reconcile()
    runner.state["wb_review_left_pending"] = True
    runner.state["local_source_pdf_deleted"] = False
    runner.checkpoint("execution_finished_wb_review_pending")
    print(json.dumps({"group_result": result,
                      "ozon_certificate_status": cert.get("status_code"),
                      "ozon_exact_bindings": binding_check,
                      "wb_counts": runner.state.get("wb_counts"),
                      "wb_readback_counts": runner.state.get("wb_readback_counts"),
                      "skips_for_group": [x for x in runner.state.get("skips", [])
                                           if x.get("number") == NUMBER],
                      "state": str(STATE), "manifest": str(MANIFEST)},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
