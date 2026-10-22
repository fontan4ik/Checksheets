"""Upload the current, exact-scope IEK/ITK national fire-safety certificate.

Dry-run by default. The PDF is an official IEK-hosted source file. No WB
updates or local file deletions are performed by this script.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, digest, now  # noqa: E402
import run_all_found_certificates_20261014 as runner_module  # noqa: E402

AUDIT = HERE / "iek_missing_official_docs_audit_20261020.json"
SNAPSHOT = HERE / "live_marketplaces_snapshot_complete_20261020.json"
JOURNAL = HERE / "reconciliation_journal.jsonl"
NUMBERS = ("RU С-RU.АЮ64.В.00560/25", "RU С-RU.АЮ64.В.00631/26")


def atomic(path: Path, value: object) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)


def append_journal(rows: list[dict]) -> None:
    with JOURNAL.open("a") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def build_manifest(number: str) -> dict:
    audit = json.loads(AUDIT.read_text())
    snapshot = json.loads(SNAPSHOT.read_text())
    if snapshot.get("complete") is not True:
        raise RuntimeError("Marketplace snapshot is incomplete")
    rows = [row for row in audit["documents"] if row.get("number") == number]
    if len(rows) != 1:
        raise RuntimeError("Expected one official source row for the certificate")
    row = rows[0]
    today = date.today().isoformat()
    if row.get("ozon_type_code") != "certificate_of_conformity" or row.get("accordance_type") != "NATIONAL":
        raise RuntimeError("Source document does not map to a national certificate")
    if (row.get("issue_date") or "")[:10] > today or (row.get("expire_date") or "")[:10] < today:
        raise RuntimeError("National certificate is not currently valid")
    file = Path(row["local_pdf"])
    if not file.is_file() or digest(file) != row.get("downloaded_sha256") or file.stat().st_size > 9_500_000:
        raise RuntimeError("Official PDF/hash/size check failed")
    if not file.read_bytes().startswith(b"%PDF-"):
        raise RuntimeError("Official document URL did not provide a PDF")

    targets = []
    for offer in row.get("offers") or []:
        if offer.get("tnved") != "8544492000":
            continue
        if offer.get("brand") != "ITK":
            raise RuntimeError("Unexpected source brand")
        targets.append({
            "offer_id": offer["offer_id"],
            "product_id": str(offer["product_id"]),
            "sku": str(offer["sku"]),
            "brand": "ITK",
            "source_url": offer["product_url"],
            "source_first_sale": offer.get("first_sale"),
            "source_tnved": offer.get("tnved"),
            "source_name": offer.get("name"),
        })
    if len(targets) != 6:
        raise RuntimeError(f"Expected six official ITK cable targets, got {len(targets)}")
    return {
        "number": number,
        "type_code": "certificate_of_conformity",
        "accordance_type": "NATIONAL",
        "country": "RU",
        "issue_date": row["issue_date"],
        "expire_date": row["expire_date"],
        "allowed_tnved": ["8544492000"],
        "source_url": row["url"],
        "source_evidence_verified": True,
        "source_evidence_files": [str(file)],
        "upload_file": {"path": str(file), "sha256": row["downloaded_sha256"]},
        "targets": targets,
        "basis": "Mandatory Russian fire-safety conformity certificate (123-FZ); exact cable family and 5e/6 product types named in official PDF; official current IEK product pages link this certificate; PDF states serial production and current validity.",
        "wb_mutation": False,
        "local_file_cleanup": False,
    }


def read_target_live(client: Client, manifest: dict) -> dict:
    targets = manifest["targets"]
    offers = [target["offer_id"] for target in targets]
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items") or []
    by_offer = {}
    for row in products:
        by_offer.setdefault(str(row.get("offer_id")), []).append(row)
    attrrows = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": offers}, "limit": 100,
    }).get("result") or []
    attrs_by_offer = {}
    for row in attrrows:
        attrs_by_offer.setdefault(str(row.get("offer_id")), []).append(row)
    verified = []
    for target in targets:
        rows = by_offer.get(target["offer_id"], [])
        arows = attrs_by_offer.get(target["offer_id"], [])
        if len(rows) != 1 or len(arows) != 1:
            raise RuntimeError(f"Live Ozon product/attribute response incomplete: {target['offer_id']}")
        product = rows[0]
        product_id = str(product.get("product_id") or product.get("id") or "")
        product_sku = str(product.get("sku") or ((product.get("sources") or [{}])[0].get("sku")) or "")
        if product.get("is_archived") is not False or product_id != target["product_id"] or product_sku != target["sku"]:
            raise RuntimeError(f"Live Ozon product identity changed: {target['offer_id']}")
        attrs = {str(a.get("id")): a for a in arows[0].get("attributes") or []}
        brands = [str(x.get("value") or "").strip() for x in (attrs.get("85") or {}).get("values") or []]
        codes = [str(x.get("value") or "").split(" - ", 1)[0].strip() for x in (attrs.get("22232") or {}).get("values") or []]
        if brands != [target["brand"]] or codes != target["allowed_code_list"]:
            raise RuntimeError(f"Live Ozon brand/TN VED differs from official source: {target['offer_id']}")
        verified.append({"offer_id": target["offer_id"], "product_id": target["product_id"],
                         "sku": target["sku"], "brand": brands[0], "tnved": codes})
    return {"products": verified, "count": len(verified)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--number", choices=NUMBERS, default="RU С-RU.АЮ64.В.00631/26")
    args = parser.parse_args()
    number = args.number
    suffix = "00631_2026" if number.endswith("00631/26") else "00560_2025"
    state_path = HERE / ("iek_national_fire_cert_state_20261020.json" if suffix == "00631_2026"
                         else "iek_national_fire_cert_00560_state_20261020.json")
    out_path = HERE / ("iek_national_fire_cert_preflight_20261020.json" if suffix == "00631_2026"
                       else "iek_national_fire_cert_00560_preflight_20261020.json")
    manifest = build_manifest(number)
    for target in manifest["targets"]:
        target["allowed_code_list"] = ["8544492000"]
    client = Client()
    live = read_target_live(client, manifest)
    certs = runner_module.Runner(client, {"groups": []}, execute=False,
                                 journal=HERE / "national_verify_only.jsonl",
                                 state=HERE / "national_verify_only_state.json").list_certificate_metadata()
    matches = [c for c in certs if runner_module.norm_number(c.get("certificate_number")) == runner_module.norm_number(number)]
    if len(matches) > 1:
        raise RuntimeError("Duplicate matching Ozon documents already exist")
    if matches:
        raise RuntimeError("The source-number document already exists in Ozon; reconcile instead of creating a duplicate")

    preflight = {"checked_at": now(), "execute": args.execute, "manifest": manifest,
                 "live_target_preflight": live, "matching_ozon_records": len(matches),
                 "wb_update": False, "local_file_cleanup": False}
    atomic(out_path, preflight)
    if not args.execute:
        print(json.dumps({"execute": False, "number": number, "targets": len(live["products"]),
                          "live_preflight": live["products"], "manifest": str(out_path)}, ensure_ascii=False))
        return

    used = set()
    if JOURNAL.exists():
        for line in JOURNAL.read_text().splitlines():
            row = json.loads(line)
            if row.get("key"):
                used.add(row["key"])
    create_key = "ozon:create-national:" + runner_module.norm_number(number)
    if create_key in used:
        raise RuntimeError("A prior create outcome exists; reconcile live state before retry")
    local_file = Path(manifest["upload_file"]["path"])
    expired = date.fromisoformat(manifest["expire_date"][:10])
    params = {
        "name": "Документ " + number,
        "certificate_type": "CERTIFICATE_OF_CONFORMITY",
        "certificate_country": "RU",
        "accordance_type": "NATIONAL",
        "number": number,
        "issue_date": runner_module.wb_datetime(manifest["issue_date"]),
        "expired_date": {"date": {"day": expired.day, "month": expired.month, "year": expired.year}},
        "skus": [str(manifest["targets"][0]["sku"])],
        "product_type": "UNKNOWN",
        "files": [{"file_content": base64.b64encode(local_file.read_bytes()).decode(), "name": local_file.name}],
    }
    if len(json.dumps({"params": params}).encode()) > 9_500_000:
        raise RuntimeError("Ozon create request exceeds the conservative size limit")
    append_journal([{"key": create_key, "phase": "prepared", "at": now(),
                     "platform": "ozon", "endpoint": "/v2/product/certificate/create",
                     "request_sha256": hashlib.sha256(json.dumps({"params": params}, sort_keys=True).encode()).hexdigest()}])
    created = client.call("ozon", "/v2/product/certificate/create", {"params": params}, mutation=True)
    append_journal([{"key": create_key, "phase": "response", "at": now(), "response": created}])
    states = {row.get("name"): row.get("state") for row in created.get("params", []) if isinstance(row, dict)}
    if created.get("status") != "COMPLETED" or not created.get("certificate_id") or not states or set(states.values()) != {"VALID"}:
        atomic(state_path, {"created_response": created, "phase": "create_not_fully_valid", "verified": False})
        raise SystemExit("Ozon did not validate all document fields; stop and inspect the saved response.")

    certificate_id = int(created["certificate_id"])
    bindings = client.ozon_bindings(certificate_id)
    by_product = {str(row.get("product_id")): row for row in bindings}
    missing = []
    for target in manifest["targets"]:
        prior = by_product.get(target["product_id"])
        if prior and str(prior.get("sku")) != target["sku"]:
            raise RuntimeError("Existing certificate binding identity conflict")
        if prior and prior.get("product_status_code") == "declined":
            continue
        if not prior:
            missing.append(target)
    if missing:
        skus = sorted(target["sku"] for target in missing)
        bind_key = "ozon:bind-national:" + str(certificate_id) + ":" + hashlib.sha256(",".join(skus).encode()).hexdigest()
        if bind_key in used:
            raise RuntimeError("A prior binding outcome exists; reconcile live state before retry")
        append_journal([{"key": "ozon:bind-national-sku:" + str(certificate_id) + ":" + sku,
                         "phase": "prepared", "at": now()} for sku in skus] +
                       [{"key": bind_key, "phase": "prepared", "at": now(), "platform": "ozon",
                         "endpoint": "/v1/product/certificate/bind"}])
        bind_result = client.call("ozon", "/v1/product/certificate/bind", {
            "certificate_id": certificate_id, "skus": skus,
        }, mutation=True)
        append_journal([{"key": bind_key, "phase": "response", "at": now(), "response": bind_result}])
    else:
        bind_result = None

    after_bindings = client.ozon_bindings(certificate_id)
    after_by_product = {str(row.get("product_id")): row for row in after_bindings}
    verified = []
    for target in manifest["targets"]:
        item = after_by_product.get(target["product_id"])
        verified.append({"offer_id": target["offer_id"], "product_id": target["product_id"],
                         "sku": target["sku"],
                         "exact_binding_visible": bool(item and str(item.get("sku")) == target["sku"]),
                         "product_status_code": item.get("product_status_code") if item else None})
    all_visible = all(item["exact_binding_visible"] for item in verified)
    record = next((c for c in runner_module.Runner(client, {"groups": []}, execute=False,
                  journal=HERE / "national_verify_only2.jsonl", state=HERE / "national_verify_only_state2.json").list_certificate_metadata()
                  if str(c.get("certificate_id")) == str(certificate_id)), None)
    result = {"checked_at": now(), "phase": "verified" if all_visible else "partial_or_uncertain",
              "certificate_id": certificate_id, "create_response": created,
              "bind_response": bind_result, "record_visible": bool(record),
              "record_status_code": record.get("status_code") if record else None,
              "record_type_code": record.get("type_code") if record else None,
              "record_accordance_type_code": record.get("accordance_type_code") if record else None,
              "expected_bindings": len(verified), "verified_binding_count": sum(x["exact_binding_visible"] for x in verified),
              "product_status_counts": {status: sum(x["product_status_code"] == status for x in verified)
                                        for status in sorted({x["product_status_code"] for x in verified if x["product_status_code"]})},
              "bindings": verified, "local_file_deleted": False, "wb_review_left_pending": True}
    atomic(state_path, result)
    print(json.dumps({key: value for key, value in result.items() if key not in ("create_response", "bind_response", "bindings")}, ensure_ascii=False))
    if not all_visible:
        raise SystemExit("Some Ozon links are not visible; reconcile live state before retry.")


if __name__ == "__main__":
    main()
