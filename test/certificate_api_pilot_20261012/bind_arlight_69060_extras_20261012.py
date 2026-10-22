"""Bind three freshly verified Arlight offers to the existing approved Ozon declaration."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE))
from api_client import Client, now  # noqa: E402
from build_bulk_cleanup_candidates_20261012 import norm  # noqa: E402

PRECHECK = BASE / "arlight_69060_extras_preflight_20261012.json"
BASE_PREFLIGHT = BASE / "arlight_69060_preflight_20261012.json"
BASE_VERIFY = BASE / "arlight_69060_ozon_verification_20261012.json"
EXECUTION = BASE / "arlight_69060_extras_execution_20261012.json"
VERIFICATION = BASE / "arlight_69060_aggregate_verification_20261012.json"
NUMBER = "ЕАЭС N RU Д-HK.РА02.В.69060/25"
CERTIFICATE_ID = 5624646
TARGETS = {
    "011750-1": {"product_id": "4021378835", "sku": "3851174714", "nmID": "946113633"},
    "026058(1)-1": {"product_id": "5140430749", "sku": "4773472600", "nmID": "1178002281"},
    "029265(2)-1": {"product_id": "4021379031", "sku": "3851174775", "nmID": "946113547"},
}


def save(path: Path, value: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(path)


def main() -> None:
    if EXECUTION.exists() or VERIFICATION.exists():
        raise RuntimeError("Supplemental journal exists; inspect it and reconcile live state before another write")
    pre = json.loads(PRECHECK.read_text())
    original = json.loads(BASE_VERIFY.read_text())
    base_plan = json.loads(BASE_PREFLIGHT.read_text())
    if (not pre.get("ready_to_bind_three") or pre.get("certificate_id") != CERTIFICATE_ID
            or pre.get("number") != NUMBER or set(pre.get("ozon_missing_bind_offers") or []) != set(TARGETS)
            or original.get("all_bindings_confirmed") is not True
            or original.get("target_sku_count") != 549 or not base_plan.get("ready_for_ozon_create_and_binding")
            or len(base_plan.get("targets") or []) != 549):
        raise RuntimeError("Existing 549-link declaration set or supplemental preflight is not verified")

    client = Client()
    info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER}).get("result", {})
    if (int(info.get("certificate_id", -1)) != CERTIFICATE_ID or info.get("status_code") != "approved"
            or str(info.get("issue_date", ""))[:10] != "2025-03-10"
            or str(info.get("expire_date", ""))[:10] != "2030-03-09"):
        raise RuntimeError("The existing Ozon declaration is not currently approved with verified dates")

    offer_rows = {}
    for offer, target in TARGETS.items():
        items = client.call("ozon", "/v3/product/info/list", {"offer_id": [offer]}).get("items") or []
        if len(items) != 1 or items[0].get("offer_id") != offer:
            raise RuntimeError(f"Ozon offer lookup mismatch: {offer}")
        row = items[0]
        if (str(row.get("id") or row.get("product_id")) != target["product_id"]
                or str(row.get("sku")) != target["sku"] or row.get("is_archived")):
            raise RuntimeError(f"Ozon product ID/SKU/archive state changed: {offer}")
        attrs_rows = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": [offer]}, "limit": 1,
        }).get("result") or []
        if len(attrs_rows) != 1 or attrs_rows[0].get("offer_id") != offer:
            raise RuntimeError(f"Ozon attribute read mismatch: {offer}")
        attrs = {str(x.get("id")): x for x in attrs_rows[0].get("attributes") or []}
        values = lambda key: [str(v.get("value")) for v in (attrs.get(key) or {}).get("values") or []]
        if values("85") != ["Arlight"] or not any(
                x.split(" - ", 1)[0].strip() == "8504408300" for x in values("22232")):
            raise RuntimeError(f"Ozon brand/TN VED is outside verified declaration scope: {offer}")
        cards = client.wb_cards(offer)
        if len(cards) != 1 or str(cards[0].get("nmID")) != target["nmID"]:
            raise RuntimeError(f"WB exact card identity changed or is not unique: {offer}")
        wb_docs = (cards[0].get("documents") or {}).get("items") or []
        if any(norm(d.get("number")) == norm(NUMBER) for d in wb_docs):
            raise RuntimeError(f"WB row appeared since preflight; reconcile it before continuing: {offer}")
        offer_rows[offer] = {"product_info": row, "attributes": {"brand": values("85"), "tnved": values("22232")},
                             "wb_nmID": str(cards[0].get("nmID"))}

    bindings = client.ozon_bindings(CERTIFICATE_ID)
    by_sku: dict[str, list[dict]] = defaultdict(list)
    for row in bindings:
        by_sku[str(row.get("sku"))].append(row)
    if len(bindings) != 549 or len(by_sku) != 549 or any(len(v) != 1 for v in by_sku.values()):
        raise RuntimeError("Live Ozon binding set changed from the independently verified 549 rows")
    for target in TARGETS.values():
        if target["sku"] in by_sku:
            raise RuntimeError("Supplemental SKU is already bound; reconcile instead of binding again")

    original_targets = base_plan["targets"]
    base_map = {str(x["sku"]): str(x["product_id"]) for x in original_targets}
    if (len(base_map) != 549 or set(base_map) != set(by_sku)
            or any(str(by_sku[sku][0].get("product_id")) != pid for sku, pid in base_map.items())):
        raise RuntimeError("Existing Ozon bindings differ from the verified 549 exact product pairs")
    extra_map = {v["sku"]: v["product_id"] for v in TARGETS.values()}
    if set(extra_map) & set(base_map):
        raise RuntimeError("Supplemental SKU overlaps the existing 549-product set")

    request = {"certificate_id": CERTIFICATE_ID,
               "skus": sorted(v["sku"] for v in TARGETS.values())}
    state = {"started_at": now(), "phase": "prepared", "number": NUMBER,
             "certificate_id": CERTIFICATE_ID, "expected_target_count_before": 549,
             "offers": [{"offer_id": o, **t, "wb_nmID": TARGETS[o]["nmID"]} for o, t in TARGETS.items()],
             "source_pdf_sha256": pre.get("source_pdf_sha256"), "request": request}
    save(EXECUTION, state)
    state.update({"phase": "sent", "sent_at": now()})
    save(EXECUTION, state)
    try:
        response = client.call("ozon", "/v1/product/certificate/bind", request, mutation=True)
    except Exception as exc:
        state.update({"phase": "uncertain", "error_type": type(exc).__name__, "updated_at": now()})
        save(EXECUTION, state)
        raise RuntimeError("Ozon bind outcome is uncertain; read live bindings before any retry") from None
    state["response"] = response
    state["phase"] = "accepted" if response.get("result") is True else "rejected"
    state["updated_at"] = now()
    save(EXECUTION, state)
    if state["phase"] != "accepted":
        raise RuntimeError("Ozon did not accept all supplemental bindings; reconcile live state")

    after_info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER}).get("result", {})
    after = client.ozon_bindings(CERTIFICATE_ID)
    after_by_sku: dict[str, list[dict]] = defaultdict(list)
    for row in after:
        after_by_sku[str(row.get("sku"))].append(row)
    expected = {**base_map, **extra_map}
    missing = sorted(set(expected) - set(after_by_sku))
    unexpected = sorted(set(after_by_sku) - set(expected))
    duplicates = sorted(sku for sku, rows in after_by_sku.items() if len(rows) != 1)
    mismatches = sorted(sku for sku, pid in expected.items() if sku in after_by_sku and
                        {str(x.get("product_id")) for x in after_by_sku[sku]} != {str(pid)})
    statuses = Counter(str(rows[0].get("product_status_code")) for sku, rows in after_by_sku.items()
                       if sku in expected and len(rows) == 1)
    report = {
        "checked_at": now(), "number": NUMBER, "certificate_id": CERTIFICATE_ID,
        "certificate_info": after_info, "target_offer_count": 552, "target_sku_count": len(expected),
        "binding_row_count": len(after), "covered_target_sku_count": len(set(expected) & set(after_by_sku)),
        "missing_skus": missing, "unexpected_skus": unexpected, "duplicate_skus": duplicates,
        "product_identity_mismatches": mismatches, "product_status_counts": dict(statuses),
        "all_target_pairs_linked": not (missing or unexpected or duplicates or mismatches),
        "certificate_status": after_info.get("status_code"),
        "certificate_approved": after_info.get("status_code") == "approved",
        "base_verified_pair_count": 549,
        "supplemental_pairs": [{"offer_id": o, **t, **offer_rows[o]["attributes"]} for o, t in TARGETS.items()],
        "wb_metadata_not_yet_updated_for_supplemental_pairs": True,
        "local_cleanup_allowed": False,
    }
    report["all_bindings_confirmed"] = report["all_target_pairs_linked"] and report["certificate_approved"]
    save(VERIFICATION, report)
    state.update({"phase": "verified" if report["all_bindings_confirmed"] else "readback_incomplete",
                  "finished_at": now(), "verification_path": str(VERIFICATION)})
    save(EXECUTION, state)
    print(json.dumps({k: report[k] for k in (
        "number", "certificate_id", "target_offer_count", "binding_row_count", "covered_target_sku_count",
        "missing_skus", "unexpected_skus", "duplicate_skus", "product_identity_mismatches",
        "product_status_counts", "certificate_approved", "all_bindings_confirmed",
        "wb_metadata_not_yet_updated_for_supplemental_pairs", "local_cleanup_allowed")},
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
