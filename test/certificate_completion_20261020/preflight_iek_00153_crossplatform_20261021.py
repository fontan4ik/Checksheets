"""Read-only live preflight for the three Schneider Electric 00153/25 offers."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, digest, now  # noqa: E402
import run_all_found_certificates_20261014 as runner  # noqa: E402

MANIFEST = HERE / "expanded_found_certificates_manifest_20261020.json"
PLAN = API / "group4_ozon_plan.json"
OUT = HERE / "iek_00153_crossplatform_preflight_live_20261021.json"
NUMBER = "ЕАЭС RU C-RU.АТ21.В.00153/25"


def write(d: dict) -> None:
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    temp.replace(OUT)


def main() -> None:
    manifest = json.loads(MANIFEST.read_text())
    groups = [g for g in manifest.get("groups", []) if g.get("number") == NUMBER]
    if len(groups) != 1:
        raise RuntimeError("manifest group missing or duplicate")
    group = groups[0]
    file = group.get("upload_file") or {}
    source = Path(file.get("path") or "")
    if (not source.is_file() or digest(source) != file.get("sha256")
            or group.get("source_evidence_verified") is not True):
        raise RuntimeError("source evidence or local PDF hash failed")
    if not (dt.date.fromisoformat(group["issue_date"]) <= dt.datetime.now(dt.timezone.utc).date()
            <= dt.date.fromisoformat(group["expire_date"])):
        raise RuntimeError("certificate date range is not current")
    targets = group.get("targets") or []
    if len(targets) != 3:
        raise RuntimeError("unexpected target count")

    plan = json.loads(PLAN.read_text())
    actions = [x for x in plan.get("actions", []) if x.get("number") == NUMBER]
    if len(actions) != 1 or actions[0].get("file_sha256") != file.get("sha256"):
        raise RuntimeError("original source assignment plan changed")
    action = actions[0]
    if set(action.get("offers", {})) != {t["offer_id"] for t in targets}:
        raise RuntimeError("exact product assignment no longer matches")

    result = {
        "checked_at_utc": now(), "read_only": True, "complete": False,
        "number": NUMBER, "issue_date": group["issue_date"], "expiry_date": group["expire_date"],
        "source_evidence": {"source_verified": True, "source_url": action.get("source_url"),
                            "evidence": action.get("evidence"), "path": str(source),
                            "sha256": digest(source), "bytes": source.stat().st_size},
        "targets": [], "ozon": {"complete": False}, "wildberries": {"complete": False},
    }
    client = Client()
    ozon_targets = []
    for target in targets:
        offer = str(target["offer_id"])
        products = client.call("ozon", "/v3/product/info/list", {"offer_id": [offer]}).get("items") or []
        attrs = client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": [offer]}, "limit": 1}).get("result") or []
        problems = []
        product = products[0] if len(products) == 1 else {}
        attrrow = attrs[0] if len(attrs) == 1 else {}
        amap = {str(x.get("id")): x for x in attrrow.get("attributes") or []}
        brand = [str(x.get("value") or "").strip() for x in amap.get("85", {}).get("values", [])]
        if len(products) != 1:
            problems.append("product_missing_or_duplicate")
        elif product.get("is_archived") is not False or str(product.get("product_id") or product.get("id") or "") != str(target["product_id"]) or str(product.get("sku") or "") != str(target["sku"]):
            problems.append("ozon_identity_or_active_state_changed")
        if len(attrs) != 1 or len(brand) != 1 or brand[0].casefold() != "schneider electric":
            problems.append("ozon_brand_or_attributes_not_exact")
        ozon_targets.append({"offer_id": offer, "product_id": str(target["product_id"]),
                             "sku": str(target["sku"]), "live_name": product.get("name"),
                             "brand_values": brand, "eligible": not problems, "problems": problems})

    records = runner.Runner(client, {"groups": []}, execute=False).list_certificate_metadata()
    exact_records = [x for x in records if runner.norm_number(x.get("certificate_number")) == runner.norm_number(NUMBER)]
    record_result = []
    for record in exact_records:
        record_result.append({k: record.get(k) for k in ("certificate_id", "certificate_number", "type_code",
                                                         "accordance_type_code", "issue_date", "expire_date", "status_code")})
    if len(exact_records) == 1:
        bindings = client.ozon_bindings(exact_records[0]["certificate_id"])
        result["ozon"]["binding_rows"] = bindings
        result["ozon"]["binding_status_counts"] = dict(Counter(str(x.get("product_status_code") or "unknown") for x in bindings))
    result["ozon"].update({"complete": True, "checked_at_utc": now(), "exact_records": record_result,
                           "targets": ozon_targets,
                           "eligible_targets": sum(x["eligible"] for x in ozon_targets)})

    wb_targets = []
    for target in targets:
        offer = str(target["offer_id"])
        cards = client.wb_cards(offer)
        exact = [c for c in cards if c.get("vendorCode") == offer]
        card = exact[0] if len(exact) == 1 else {}
        docs = ((card.get("documents") or {}).get("items") or []) if card else []
        same = [x for x in docs if runner.norm_number(x.get("number")) == runner.norm_number(NUMBER)]
        conflict = any(runner.doc_key(x) != runner.doc_key({"type": runner.OZON_TO_WB_TYPE[group["type_code"]], "number": NUMBER})
                       or str(x.get("startDate", ""))[:10] != group["issue_date"]
                       or str(x.get("endDate", ""))[:10] != group["expire_date"] for x in same)
        eligible = len(exact) == 1 and card.get("brand", "").casefold() == "schneider electric" and not conflict
        wb_targets.append({"offer_id": offer, "nmID": card.get("nmID") if card else None,
                           "vendorCode": card.get("vendorCode") if card else None,
                           "brand": card.get("brand") if card else None,
                           "document_already_present": bool(same), "document_conflict": conflict,
                           "eligible": eligible})
    result["wildberries"].update({"complete": True, "checked_at_utc": now(), "targets": wb_targets,
                                  "eligible_targets": sum(x["eligible"] for x in wb_targets),
                                  "already_present": sum(x["document_already_present"] for x in wb_targets)})
    result["complete"] = True
    result["summary"] = {
        "source_evidence_verified": True,
        "ozon_current_active_brand_matches": result["ozon"]["eligible_targets"],
        "ozon_exact_document_record_count": len(exact_records),
        "ozon_binding_status_counts": result["ozon"].get("binding_status_counts", {}),
        "wb_exact_brand_matches": result["wildberries"]["eligible_targets"],
        "wb_exact_documents_already_present": result["wildberries"]["already_present"],
    }
    write(result)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
