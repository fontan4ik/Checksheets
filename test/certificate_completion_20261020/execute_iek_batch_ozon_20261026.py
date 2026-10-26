"""Preflight and upload verified IEK declarations to Ozon, once, with readback."""
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
RECOVERED_71483 = HERE / "recovered_sources/iek_71483_26_source.pdf"
PREFLIGHT = HERE / "iek_batch_preflight_ozon_20261026_v2.json"
EXECUTION = HERE / "iek_batch_execution_ozon_20261026_v2.json"
JOURNAL = HERE / "iek_batch_mutation_journal_ozon_20261026_v2.jsonl"

REGISTRY_NUMBERS = {
    "RU Д-RU.РА08.В.54504/26": "ЕАЭС N RU Д-RU.РА08.В.54504/26",
    "RU Д-RU.РА04.В.27570/26": "ЕАЭС N RU Д-RU.РА04.В.27570/26",
    "RU Д-CN.РА02.В.71483/26": "ЕАЭС N RU Д-CN.РА02.В.71483/26",
}

FSA_URLS = {
    "RU Д-RU.РА08.В.54504/26": "https://pub.fsa.gov.ru/rds/declaration/view/21675817/product",
    "RU Д-RU.РА04.В.27570/26": "https://pub.fsa.gov.ru/rds/declaration/view/21426775/product",
    "RU Д-CN.РА02.В.71483/26": "https://pub.fsa.gov.ru/rds/declaration/view/21246408/product",
}


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


def resolve_source(group: dict) -> Path:
    if group["number"] == "RU Д-CN.РА02.В.71483/26":
        return RECOVERED_71483
    expected = group["upload_file"]
    source = Path(expected["path"])
    if source.is_file():
        return source
    raw = str(expected["path"])
    marker = "/Checksheets/"
    if marker in raw:
        candidate = ROOT / raw.split(marker, 1)[1]
        if candidate.is_file():
            return candidate
    raise RuntimeError(f"Source PDF is not available for {group['number']}")


def get_groups() -> dict[str, dict]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    wanted = {"RU Д-RU.РА08.В.54504/26", "RU Д-RU.РА04.В.27570/26", "RU Д-CN.РА02.В.71483/26"}
    groups = {item["number"]: item for item in manifest.get("groups", []) if item.get("number") in wanted}
    if set(groups) != wanted:
        raise RuntimeError("Verified manifest is missing one or more IEK declarations")
    recent_skus = {str(t["sku"]) for t in groups["RU Д-RU.РА08.В.54504/26"]["targets"]}
    older_unique = [t for t in groups["RU Д-RU.РА04.В.27570/26"]["targets"] if str(t["sku"]) not in recent_skus]
    if len(older_unique) != 1:
        raise RuntimeError(f"Expected one 27570/26 SKU not covered by 54504/26, got {len(older_unique)}")
    groups["RU Д-RU.РА04.В.27570/26"] = dict(groups["RU Д-RU.РА04.В.27570/26"])
    groups["RU Д-RU.РА04.В.27570/26"]["targets"] = older_unique
    return groups


def live_product_rows(client: Client, targets: list[dict], allowed_tnved: list[str]) -> list[dict]:
    offers = [str(t["offer_id"]) for t in targets]
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
        batch = (response.get("result") or [])
        if not isinstance(batch, list):
            raise RuntimeError("Ozon product attribute response is incomplete")
        attributes.extend(batch)

    product_by_offer = {str(p.get("offer_id")): p for p in products}
    attr_by_id = {str(a.get("id") or a.get("product_id")): a for a in attributes}
    if len(product_by_offer) != len(targets):
        raise RuntimeError(f"Expected {len(targets)} unique Ozon offers; got {len(product_by_offer)}")
    result: list[dict] = []
    for target in targets:
        offer = str(target["offer_id"])
        product = product_by_offer.get(offer)
        expected_product_id = str(target["product_id"])
        expected_sku = str(target["sku"])
        if product is None:
            raise RuntimeError(f"Ozon offer is missing: {offer}")
        product_id = str(product.get("id") or product.get("product_id") or "")
        sources = product.get("sources") or []
        skus = {str(x.get("sku") or "") for x in sources}
        skus.discard("")
        if product_id != expected_product_id or expected_sku not in skus or product.get("is_archived") is not False:
            raise RuntimeError(f"Ozon identity or active status changed for {offer}: {product_id=}, {skus=}, archived={product.get('is_archived')}")
        attr_row = attr_by_id.get(expected_product_id)
        if attr_row is None:
            raise RuntimeError(f"Ozon attributes are missing for {offer}")
        attrs = {str(item.get("id")): item for item in attr_row.get("attributes") or []}
        brands = [str(v.get("value") or "").strip() for v in (attrs.get("85") or {}).get("values") or []]
        tnveds = [str(v.get("value") or "").split(" - ", 1)[0].strip()
                  for v in (attrs.get("22232") or {}).get("values") or []]
        if brands != [str(target["brand"])] or not tnveds or any(code not in allowed_tnved for code in tnveds):
            raise RuntimeError(f"Ozon brand/TN VED mismatch for {offer}: {brands=}, {tnveds=}, expected brand={target['brand']}, codes={allowed_tnved}")
        result.append({
            "offer_id": offer, "product_id": product_id, "sku": expected_sku,
            "name": str(product.get("name") or ""), "brand": brands[0], "tnved": tnveds,
        })
    return result


def preflight(client: Client) -> dict:
    groups = get_groups()
    records = list_certificates(client)
    result_docs = []
    today = dt.datetime.now(dt.timezone.utc).date()
    previous_attempt = {
        "manifest_number": "RU Д-RU.РА04.В.27570/26",
        "ozon_number_attempted": "RU Д-RU.РА04.В.27570/26",
        "response": "INCOMPLETE", "invalid_parameter": "NUMBER",
        "certificate_id": None, "binding_attempted": False,
        "record_not_created_by_attempt": True,
        "canonical_record_preexisted_with_ids": [5530976, 5447907],
    }
    for manifest_number, group in groups.items():
        number = REGISTRY_NUMBERS[manifest_number]
        source = resolve_source(group)
        expected_hash = group["upload_file"]["sha256"]
        if not source.is_file() or digest(source) != expected_hash:
            raise RuntimeError(f"Source PDF SHA-256 mismatch for {number}")
        if group.get("source_evidence_verified") is not True:
            raise RuntimeError(f"Source scope was not verified for {number}")
        if not dt.date.fromisoformat(group["issue_date"]) <= today <= dt.date.fromisoformat(group["expire_date"]):
            raise RuntimeError(f"The document is not currently within its declared validity period: {number}")
        matches = [r for r in records if fold(r.get("certificate_number")) == fold(number)]
        if matches:
            raise RuntimeError(f"Ozon already has {number}; refusing duplicate create: {[x.get('certificate_id') for x in matches]}")
        live = live_product_rows(client, group["targets"], group.get("allowed_tnved") or [])
        result_docs.append({
            "number": number, "manifest_number": manifest_number,
            "certificate_type": "DECLARATION", "country": group["country"],
            "accordance_type": group["accordance_type"], "issue_date": group["issue_date"],
            "expire_date": group["expire_date"], "fsa_url": FSA_URLS[manifest_number],
            "fsa_active_status_verified_in_ui": True, "source_file": str(source),
            "source_sha256": digest(source), "source_size_bytes": source.stat().st_size,
            "target_count": len(live), "targets": live,
        })
    return {
        "checked_at_utc": now(), "read_only": True, "eligible": True, "platform": "Ozon",
        "live_certificate_record_count": len(records), "documents": result_docs,
        "total_target_bindings": sum(x["target_count"] for x in result_docs),
        "previous_attempt_reconciled": previous_attempt,
        "local_source_deleted": False, "wb_changed": False,
    }


def read_status(client: Client, number: str, certificate_id: str, target_rows: list[dict]) -> dict:
    bindings = client.ozon_bindings(certificate_id)
    expected = {str(t["sku"]): str(t["product_id"]) for t in target_rows}
    found: dict[str, dict] = {}
    outside: list[dict] = []
    for row in bindings:
        sku = str(row.get("sku") or "")
        if sku not in expected:
            outside.append({"sku": sku, "product_id": str(row.get("product_id") or "")})
        else:
            found[sku] = row
    wrong_ids = [{"sku": sku, "expected_product_id": pid, "actual_product_id": str(found[sku].get("product_id") or "")}
                 for sku, pid in expected.items() if sku in found and str(found[sku].get("product_id") or "") != pid]
    missing = sorted(set(expected) - set(found))
    record = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": number}).get("result") or {}
    counts = Counter(str(row.get("product_status_code") or "") for row in found.values())
    return {
        "certificate_id": int(certificate_id), "stored_number": record.get("certificate_number"),
        "record_status": record.get("status_code"), "products_count": record.get("products_count"),
        "binding_count": len(bindings), "target_count": len(expected), "found_target_count": len(found),
        "missing_skus": missing, "outside_target_bindings": outside, "wrong_product_ids": wrong_ids,
        "target_binding_status_counts": dict(counts),
        "all_targets_bound": not missing and not wrong_ids and len(found) == len(expected),
        "all_targets_approved": not missing and not wrong_ids and len(found) == len(expected) and counts == {"approved": len(expected)},
    }


def execute(client: Client, pf: dict) -> dict:
    if not pf.get("eligible"):
        raise RuntimeError("Preflight is not eligible")
    if JOURNAL.exists() or EXECUTION.exists():
        raise RuntimeError("Execution journal/output already exists; reconcile before any retry")
    final_docs = []
    for doc in pf["documents"]:
        number = doc["number"]
        source = Path(doc["source_file"])
        targets = doc["targets"]
        skus = [str(t["sku"]) for t in targets]
        if len(skus) != len(set(skus)):
            raise RuntimeError(f"Duplicate target SKU in {number}")
        # Repeat the duplicate check immediately before the one create mutation.
        existing = [x for x in list_certificates(client) if fold(x.get("certificate_number")) == fold(number)]
        if existing:
            raise RuntimeError(f"{number} appeared after preflight; no write made: {[x.get('certificate_id') for x in existing]}")
        expiry = dt.date.fromisoformat(doc["expire_date"])
        params = {
            "name": "Декларация о соответствии № " + number,
            "certificate_type": "DECLARATION", "certificate_country": doc["country"],
            "accordance_type": doc["accordance_type"], "number": number,
            "issue_date": doc["issue_date"] + "T00:00:00Z",
            "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
            "skus": [skus[0]], "product_type": "UNKNOWN",
            "files": [{"file_content": base64.b64encode(source.read_bytes()).decode("ascii"), "name": source.name}],
            "link_to_registry": doc["fsa_url"],
        }
        payload = {"params": params}
        payload_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        journal({"phase": "prepared", "operation": "create", "number": number,
                 "endpoint": "/v2/product/certificate/create", "payload_sha256": payload_hash,
                 "source_sha256": doc["source_sha256"], "target_skus": skus})
        try:
            created = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
        except Exception as exc:
            journal({"phase": "create_uncertain", "number": number, "error_type": type(exc).__name__})
            matches = [x for x in list_certificates(client) if fold(x.get("certificate_number")) == fold(number)]
            if len(matches) != 1:
                raise RuntimeError(f"Create outcome for {number} is uncertain; no retry was made") from exc
            created = {"certificate_id": str(matches[0]["certificate_id"]), "status": "RECONCILED", "params": []}
        cert_id = str(created.get("certificate_id") or "")
        states = [x.get("state") for x in created.get("params") or [] if isinstance(x, dict)]
        journal({"phase": "create_response", "number": number, "certificate_id": cert_id,
                 "status": created.get("status"), "parameter_states": states})
        if not cert_id or created.get("status") not in {"COMPLETED", "RECONCILED"} or (states and set(states) != {"VALID"}):
            raise RuntimeError(f"Ozon did not validate create for {number}; stop for reconciliation")

        current = client.ozon_bindings(cert_id)
        expected_by_sku = {str(t["sku"]): str(t["product_id"]) for t in targets}
        unexpected = [b for b in current if str(b.get("sku")) not in expected_by_sku]
        if unexpected:
            raise RuntimeError(f"Ozon attached unexpected SKUs to {number}: {unexpected}")
        current_skus = {str(b.get("sku")) for b in current}
        missing = [sku for sku in skus if sku not in current_skus]
        bind_response = None
        if missing:
            bind_payload = {"certificate_id": int(cert_id), "skus": missing}
            bind_hash = hashlib.sha256(json.dumps(bind_payload, separators=(",", ":")).encode()).hexdigest()
            journal({"phase": "prepared", "operation": "bind", "number": number,
                     "endpoint": "/v1/product/certificate/bind", "certificate_id": cert_id,
                     "payload_sha256": bind_hash, "skus": missing})
            bind_response = client.call("ozon", "/v1/product/certificate/bind", bind_payload, mutation=True)
            journal({"phase": "bind_response", "number": number, "certificate_id": cert_id,
                     "response": bind_response, "sku_count": len(missing)})

        deadline = time.monotonic() + 180
        readback = read_status(client, number, cert_id, targets)
        while not readback["all_targets_approved"] and time.monotonic() < deadline:
            if not readback["all_targets_bound"] and readback["missing_skus"]:
                raise RuntimeError(f"Ozon did not expose all bindings after one bind request for {number}; stopping without retry")
            time.sleep(10)
            readback = read_status(client, number, cert_id, targets)
        result_doc = {
            "number": number, "create_status": created.get("status"), "create_parameter_states": states,
            "bind_response": bind_response, "readback": readback, "source_sha256": doc["source_sha256"],
            "source_deleted": False,
        }
        final_docs.append(result_doc)
        journal({"phase": "final_readback", **result_doc})
        atomic_write(EXECUTION, {"checked_at_utc": now(), "platform": "Ozon", "documents": final_docs,
                                 "local_source_deleted": False, "wb_changed": False,
                                 "all_targets_bound": all(x["readback"]["all_targets_bound"] for x in final_docs),
                                 "all_targets_approved": all(x["readback"]["all_targets_approved"] for x in final_docs)})
    return json.loads(EXECUTION.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Create only after a fresh eligible preflight")
    args = parser.parse_args()
    client = Client()
    pf = preflight(client)
    atomic_write(PREFLIGHT, pf)
    if args.execute:
        result = execute(client, pf)
        print(json.dumps({"preflight": {"eligible": pf["eligible"], "live_certificate_record_count": pf["live_certificate_record_count"],
                           "total_target_bindings": pf["total_target_bindings"]}, "execution": result}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(pf, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
