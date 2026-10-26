"""Freshly validate and upload the active Arlight 69060/25 declaration to Ozon."""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import re
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, digest, now  # noqa: E402

MANIFEST = HERE / "all_source_certificates_verified_manifest_20261024.json"
HISTORICAL_PREFLIGHT = API / "arlight_69060_preflight_20261012.json"
SOURCE = HERE / "recovered_sources/arlight_69060_25_source.pdf"
EXPECTED_SHA256 = "baeb142abdd28d42ae6cbbe4993134f3726364e94ca66c3b09d913d52b81db04"
NUMBER = "ЕАЭС N RU Д-HK.РА02.В.69060/25"
FSA_URL = "https://pub.fsa.gov.ru/rds/declaration/view/19978046/product"
PREFLIGHT = HERE / "arlight_69060_25_preflight_ozon_20261026.json"
EXECUTION = HERE / "arlight_69060_25_execution_ozon_20261026.json"
JOURNAL = HERE / "arlight_69060_25_mutation_journal_ozon_20261026.jsonl"


def fold(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).upper()
    text = text.translate(str.maketrans({
        "Ё": "Е", "С": "C", "А": "A", "В": "B", "Е": "E", "К": "K",
        "М": "M", "Н": "H", "О": "O", "Р": "P", "Т": "T", "Х": "X", "У": "Y",
    }))
    return re.sub(r"[^0-9A-Z]", "", text)


def atomic_write(path: Path, value: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def journal(event: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at_utc": now(), **event}, ensure_ascii=False) + "\n")
        stream.flush()


def list_certificates(client: Client) -> list[dict]:
    rows: list[dict] = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {
            "page": page, "page_size": 100,
        }).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list is incomplete")
        rows.extend(batch)
        if page >= int(result.get("page_count") or page):
            return rows
    raise RuntimeError("Ozon certificate pagination exceeded 100 pages")


def preflight(client: Client) -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    groups = [g for g in manifest.get("groups", []) if g.get("number") == "RU Д-НK.PА02.B.69060/25"]
    if len(groups) != 1:
        raise RuntimeError("Verified declaration group was missing or duplicated")
    group = groups[0]
    expected_targets = group.get("targets") or []
    if len(expected_targets) != 549 or group.get("source_evidence_verified") is not True:
        raise RuntimeError("The verified source scope changed or is incomplete")
    if (not SOURCE.is_file() or digest(SOURCE) != EXPECTED_SHA256
            or group.get("upload_file", {}).get("sha256") != EXPECTED_SHA256):
        raise RuntimeError("Official manufacturer PDF is missing or its SHA-256 differs")
    today = dt.datetime.now(dt.timezone.utc).date()
    if not dt.date.fromisoformat(group["issue_date"]) <= today <= dt.date.fromisoformat(group["expire_date"]):
        raise RuntimeError("The FSA declaration is outside its effective dates")

    old = json.loads(HISTORICAL_PREFLIGHT.read_text(encoding="utf-8"))
    if (old.get("source_sha256") != EXPECTED_SHA256 or old.get("fsa_registry_status_seen_in_ui") != "Действует"
            or old.get("fsa_registry_url") != FSA_URL or old.get("fsa_registry_tnved_scope") != ["8504408300"]):
        raise RuntimeError("Prior exact-source/FSA scope evidence no longer matches")
    historical_targets = {str(t["offer_id"]): t for t in old.get("targets", [])}
    if set(historical_targets) != {str(t["offer_id"]) for t in expected_targets}:
        raise RuntimeError("The live preflight offer scope and verified manifest differ")

    records = list_certificates(client)
    duplicates = [r for r in records if fold(r.get("certificate_number")) == fold(NUMBER)]
    if duplicates:
        raise RuntimeError(f"Ozon already has this declaration number; reconcile rather than upload: {[x.get('certificate_id') for x in duplicates]}")

    offers = [str(t["offer_id"]) for t in expected_targets]
    products: list[dict] = []
    attributes: list[dict] = []
    for start in range(0, len(offers), 40):
        chunk = offers[start:start + 40]
        response = client.call("ozon", "/v3/product/info/list", {"offer_id": chunk})
        batch = response.get("items")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon product identity response is incomplete")
        products.extend(batch)
        response = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": chunk}, "limit": 1000,
        })
        batch = response.get("result") or []
        if not isinstance(batch, list):
            raise RuntimeError("Ozon attribute response is incomplete")
        attributes.extend(batch)

    products_by_offer = {str(p.get("offer_id")): p for p in products}
    attrs_by_product_id = {str(a.get("id") or a.get("product_id")): a for a in attributes}
    if len(products_by_offer) != len(expected_targets):
        raise RuntimeError(f"Expected 549 unique offers, got {len(products_by_offer)}")
    live_targets = []
    for target in expected_targets:
        offer = str(target["offer_id"])
        product = products_by_offer.get(offer)
        if product is None:
            raise RuntimeError(f"Ozon offer is missing: {offer}")
        product_id = str(product.get("id") or product.get("product_id") or "")
        sku = str(target["sku"])
        sources = {str(x.get("sku") or "") for x in product.get("sources") or []}
        if product_id != str(target["product_id"]) or sku not in sources:
            raise RuntimeError(f"Current Ozon product identity changed for {offer}: {product_id=}, {sources=}")
        attr = attrs_by_product_id.get(product_id)
        if attr is None:
            raise RuntimeError(f"Ozon attributes are missing for {offer}")
        attributes_by_id = {str(x.get("id")): x for x in attr.get("attributes") or []}
        brands = [str(v.get("value") or "").strip() for v in (attributes_by_id.get("85") or {}).get("values") or []]
        tnveds = [str(v.get("value") or "").split(" - ", 1)[0].strip()
                  for v in (attributes_by_id.get("22232") or {}).get("values") or []]
        if brands != ["Arlight"] or tnveds != ["8504408300"]:
            raise RuntimeError(f"Current Ozon brand/TN VED mismatch for {offer}: {brands=}, {tnveds=}")
        evidence = historical_targets[offer]
        if not evidence.get("official_article"):
            raise RuntimeError(f"No official product-scope evidence for {offer}")
        live_targets.append({
            "offer_id": offer, "product_id": product_id, "sku": sku,
            "name": str(product.get("name") or ""), "brand": brands[0], "tnved": tnveds,
            "is_archived": bool(product.get("is_archived")),
            "scope_evidence": evidence.get("official_article"),
        })
    return {
        "checked_at_utc": now(), "read_only": True, "eligible": True, "platform": "Ozon",
        "certificate_number": NUMBER, "certificate_type": "DECLARATION",
        "issue_date": group["issue_date"], "expire_date": group["expire_date"],
        "fsa_record_id": 19978046, "fsa_url": FSA_URL,
        "fsa_status": "Действует; current FSA UI read 2026-10-26",
        "fsa_tnved_scope": ["8504408300"], "source_file": str(SOURCE),
        "source_url": "https://arlight.ru/upload/certificates/F6522803E046324C87BC430F67671163.pdf",
        "source_sha256": digest(SOURCE), "source_size_bytes": SOURCE.stat().st_size,
        "ozon_certificate_records_checked": len(records), "duplicate_number_count": 0,
        "target_count": len(live_targets), "archived_target_count": sum(t["is_archived"] for t in live_targets),
        "targets": live_targets, "local_source_deleted": False, "wb_changed": False,
    }


def read_status(client: Client, certificate_id: str, targets: list[dict]) -> dict:
    bindings = client.ozon_bindings(certificate_id)
    expected = {str(t["sku"]): str(t["product_id"]) for t in targets}
    found: dict[str, dict] = {}
    outside = []
    for item in bindings:
        sku = str(item.get("sku") or "")
        if sku in expected:
            found[sku] = item
        else:
            outside.append({"sku": sku, "product_id": str(item.get("product_id") or "")})
    missing = sorted(set(expected) - set(found))
    wrong_ids = [{"sku": sku, "expected_product_id": pid,
                  "actual_product_id": str(found[sku].get("product_id") or "")}
                 for sku, pid in expected.items() if sku in found
                 and str(found[sku].get("product_id") or "") != pid]
    info = client.call("ozon", "/v1/product/certificate/info", {
        "certificate_number": NUMBER,
    }).get("result") or {}
    counts = Counter(str(x.get("product_status_code") or "") for x in found.values())
    return {
        "certificate_id": int(certificate_id), "stored_number": info.get("certificate_number"),
        "record_status": info.get("status_code"), "products_count": info.get("products_count"),
        "binding_count": len(bindings), "target_count": len(expected), "found_target_count": len(found),
        "missing_skus": missing, "outside_target_bindings": outside, "wrong_product_ids": wrong_ids,
        "target_binding_status_counts": dict(counts),
        "all_targets_bound": not missing and not wrong_ids and len(found) == len(expected),
        "all_targets_approved": not missing and not wrong_ids and len(found) == len(expected)
            and counts == {"approved": len(expected)},
    }


def execute(client: Client, pf: dict) -> dict:
    if not pf.get("eligible"):
        raise RuntimeError("Preflight is not eligible")
    if JOURNAL.exists() or EXECUTION.exists():
        raise RuntimeError("Execution journal/output already exists; reconcile before any retry")
    targets = pf["targets"]
    skus = [str(t["sku"]) for t in targets]
    if len(skus) != len(set(skus)):
        raise RuntimeError("Duplicate target SKUs in the validated scope")
    if any(fold(x.get("certificate_number")) == fold(NUMBER) for x in list_certificates(client)):
        raise RuntimeError("The certificate appeared after preflight; refusing duplicate creation")
    expiry = dt.date.fromisoformat(pf["expire_date"])
    params = {
        "name": "Декларация о соответствии № " + NUMBER,
        "certificate_type": "DECLARATION", "certificate_country": "RU",
        "accordance_type": "EAEU", "number": NUMBER,
        "issue_date": pf["issue_date"] + "T00:00:00Z",
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [skus[0]], "product_type": "UNKNOWN",
        "files": [{"file_content": base64.b64encode(Path(pf["source_file"]).read_bytes()).decode("ascii"),
                   "name": Path(pf["source_file"]).name}],
        "link_to_registry": pf["fsa_url"],
    }
    payload = {"params": params}
    payload_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    journal({"phase": "prepared", "operation": "create", "number": NUMBER,
             "endpoint": "/v2/product/certificate/create", "payload_sha256": payload_hash,
             "source_sha256": pf["source_sha256"], "target_count": len(skus), "seed_sku": skus[0]})
    try:
        created = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
    except Exception as exc:
        journal({"phase": "create_uncertain", "number": NUMBER, "error_type": type(exc).__name__})
        matches = [x for x in list_certificates(client) if fold(x.get("certificate_number")) == fold(NUMBER)]
        if len(matches) != 1:
            raise RuntimeError("Ozon create outcome uncertain; reconciled once and did not retry") from exc
        created = {"certificate_id": str(matches[0]["certificate_id"]), "status": "RECONCILED", "params": []}
    cert_id = str(created.get("certificate_id") or "")
    states = [x.get("state") for x in created.get("params") or [] if isinstance(x, dict)]
    journal({"phase": "create_response", "number": NUMBER, "certificate_id": cert_id,
             "status": created.get("status"), "parameter_states": states,
             "response_parameters": created.get("params") or []})
    if not cert_id or created.get("status") not in {"COMPLETED", "RECONCILED"} or (states and set(states) != {"VALID"}):
        raise RuntimeError(f"Ozon did not validate the create; stop for reconciliation: {created}")

    existing = client.ozon_bindings(cert_id)
    expected_by_sku = {str(t["sku"]): str(t["product_id"]) for t in targets}
    unexpected = [x for x in existing if str(x.get("sku")) not in expected_by_sku]
    if unexpected:
        raise RuntimeError(f"Ozon attached unexpected SKUs: {unexpected}")
    bound = {str(x.get("sku")) for x in existing}
    missing = [sku for sku in skus if sku not in bound]
    bind_responses = []
    for index, start in enumerate(range(0, len(missing), 200), start=1):
        chunk = missing[start:start + 200]
        payload = {"certificate_id": int(cert_id), "skus": chunk}
        bind_hash = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
        journal({"phase": "prepared", "operation": "bind", "number": NUMBER, "batch": index,
                 "endpoint": "/v1/product/certificate/bind", "certificate_id": cert_id,
                 "payload_sha256": bind_hash, "sku_count": len(chunk), "skus": chunk})
        response = client.call("ozon", "/v1/product/certificate/bind", payload, mutation=True)
        bind_responses.append(response)
        journal({"phase": "bind_response", "number": NUMBER, "certificate_id": cert_id,
                 "batch": index, "sku_count": len(chunk), "response": response})

    deadline = time.monotonic() + 300
    readback = read_status(client, cert_id, targets)
    while not readback["all_targets_approved"] and time.monotonic() < deadline:
        if not readback["all_targets_bound"] and readback["missing_skus"]:
            raise RuntimeError(f"Ozon did not expose all bindings; stop and reconcile without retry: {readback}")
        time.sleep(10)
        readback = read_status(client, cert_id, targets)
    result = {
        "finished_at_utc": now(), "platform": "Ozon", "number": NUMBER,
        "certificate_id": int(cert_id), "create_status": created.get("status"),
        "create_parameter_states": states, "bind_responses": bind_responses,
        "readback": readback, "source_sha256": pf["source_sha256"],
        "target_count": len(targets), "local_source_deleted": False, "wb_changed": False,
    }
    atomic_write(EXECUTION, result)
    journal({"phase": "final_readback", **result})
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Create and bind after fresh preflight")
    args = parser.parse_args()
    client = Client()
    pf = preflight(client)
    atomic_write(PREFLIGHT, pf)
    if args.execute:
        result = execute(client, pf)
        print(json.dumps({"preflight": {k: pf[k] for k in ["eligible", "certificate_number", "ozon_certificate_records_checked", "target_count", "archived_target_count"]},
                          "execution": result}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({k: v for k, v in pf.items() if k != "targets"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
