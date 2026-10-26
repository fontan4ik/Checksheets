#!/usr/bin/env python3
"""Upload the four source-verified Feron documents still absent from Ozon.

Exact FSA product model/article scope and live Ozon offer/product/SKU/brand are
rechecked before each write. Ozon's current TN VED attribute differs from the
official registry code for these groups; that discrepancy is recorded rather
than hidden. The exact models and series were confirmed against the active FSA
records. Archived offers are retained in the binding target set because the
user asked to cover all cards. No WB call or local file deletion is performed.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

MANIFEST = HERE / "feron_remaining_found_valid_manifest_20261020.json"
OUT = HERE / "feron_remaining_ozon_scope_review_execution_20261026_v2.json"
JOURNAL = HERE / "feron_remaining_ozon_scope_review_mutation_journal_20261026_v2.jsonl"
TARGET_SUFFIXES = ("00767/22", "01377/22", "54291/25", "58098/25")
EXPECTED_SERIES = {
    "00767/22": "TM",
    "01377/22": "EM",
    "54291/25": "STLB01",
    "58098/25": "EK",
}
ALLOWED_CREATE_STATUSES = {"approved", "pending", "checking", "in_review", "awaiting_verification"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save(path: Path, value: object) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def journal(row: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at_utc": now(), **row}, ensure_ascii=False) + "\n")
        stream.flush()


def list_certificates(client: Client) -> list[dict]:
    records = []
    expected_pages = None
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        if expected_pages is None:
            expected_pages = int(result.get("page_count") or 0)
        records.extend(batch)
        if page >= expected_pages:
            return records
    raise RuntimeError("ozon_certificate_page_bound_exceeded")


def values(row: dict, attribute_id: int) -> list[str]:
    attrs = {str(item.get("id")): item for item in row.get("attributes") or []}
    return [str(item.get("value") or "").strip()
            for item in (attrs.get(str(attribute_id)) or {}).get("values") or []
            if str(item.get("value") or "").strip()]


def live_products(client: Client, offers: list[str]) -> tuple[dict[str, dict], dict[str, dict]]:
    products: dict[str, dict] = {}
    attrs: dict[str, dict] = {}
    for start in range(0, len(offers), 40):
        batch = offers[start:start + 40]
        product_rows = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or []
        attr_rows = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": 100
        }).get("result") or []
        for row in product_rows:
            products.setdefault(str(row.get("offer_id") or ""), row)
        for row in attr_rows:
            attrs.setdefault(str(row.get("offer_id") or ""), row)
    return products, attrs


def get_exact_record(records: list[dict], number: str) -> list[dict]:
    key = norm_number(number)
    return [row for row in records if norm_number(row.get("certificate_number")) == key]


def validate_target(group: dict, target: dict, product: dict, attr: dict) -> dict:
    offer = str(target["offer_id"])
    expected_id = str(target["product_id"])
    expected_sku = str(target["sku"])
    got_id = str(product.get("product_id") or product.get("id") or "")
    got_sku = str(product.get("sku") or "")
    brand = values(attr, 85)
    live_tnved = [value.split(" - ", 1)[0].strip() for value in values(attr, 22232)]
    article = str(target.get("source_article") or "").lstrip("0")
    title = str(product.get("name") or "")
    normalized_title = title.casefold().replace("ё", "е")
    article_present = bool(article and article in normalized_title)
    source_title = str(target.get("source_title") or "")
    model_tokens = re.findall(r"(?i)\b(?:TM|EM|STLB|EK)[ -]?\d+\b", source_title)
    normalize_model = lambda value: re.sub(r"[^a-z0-9]", "", value.casefold())
    model_matches = [token for token in model_tokens if normalize_model(token) in normalize_model(title)]
    series = EXPECTED_SERIES[next(x for x in TARGET_SUFFIXES if group["number"].endswith(x))]
    series_present = series.casefold() in normalized_title
    if (got_id != expected_id or got_sku != expected_sku or brand != ["Feron"]
            or not (article_present or model_matches) or not series_present or not live_tnved):
        raise RuntimeError(f"live_target_identity_or_model_mismatch:{offer}")
    return {
        "offer_id": offer, "product_id": expected_id, "sku": expected_sku,
        "archived": product.get("is_archived"), "brand": brand,
        "live_tnved": live_tnved, "official_tnved": group.get("allowed_tnved"),
        "tnved_mismatch": not set(live_tnved) <= set(map(str, group.get("allowed_tnved") or [])),
        "article_match": article_present, "model_tokens": model_tokens,
        "model_matches": model_matches, "series_match": series_present,
        "name": title,
    }


def create_payload(group: dict, seed_sku: str, source: Path) -> dict:
    expiry = dt.date.fromisoformat(group["expire_date"][:10])
    type_code = group["type_code"]
    payload_params = {
        "name": f"Документ {group['number']}",
        "certificate_type": "CERTIFICATE_OF_CONFORMITY" if type_code == "certificate_of_conformity" else "DECLARATION",
        "certificate_country": group["country"],
        "accordance_type": "EAEU",
        "number": group["number"],
        "issue_date": group["issue_date"][:10] + "T00:00:00Z",
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [seed_sku],
        "product_type": "UNKNOWN",
        "files": [{"file_content": base64.b64encode(source.read_bytes()).decode("ascii"), "name": source.name}],
    }
    if group.get("link_to_registry"):
        payload_params["link_to_registry"] = group["link_to_registry"]
    return {"params": payload_params}


def main() -> None:
    if OUT.exists() or JOURNAL.exists():
        raise RuntimeError("execution_artifacts_exist_reconcile_before_retry")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    groups = [group for group in manifest.get("groups") or []
              if any(group.get("number", "").endswith(suffix) for suffix in TARGET_SUFFIXES)]
    if len(groups) != len(TARGET_SUFFIXES) or any(group.get("source_evidence_verified") is not True for group in groups):
        raise RuntimeError("manifest_groups_or_fsa_evidence_changed")
    for group in groups:
        source = Path(group["upload_file"]["path"])
        if not source.is_file() or sha256(source) != group["upload_file"]["sha256"]:
            raise RuntimeError("source_file_hash_missing_or_changed:" + group["number"])

    state = {
        "started_at_utc": now(), "read_only_preflight_complete": False,
        "platform": "Ozon", "groups": [], "local_files_deleted": False,
        "wb_changed": False,
    }
    save(OUT, state)
    client = Client()
    offers_by_group = {group["number"]: [str(t["offer_id"]) for t in group["targets"]] for group in groups}
    all_offers = list(dict.fromkeys(offer for offers in offers_by_group.values() for offer in offers))
    products, attrs = live_products(client, all_offers)
    certificates = list_certificates(client)

    preflight = []
    for group in groups:
        number = group["number"]
        existing = get_exact_record(certificates, number)
        if existing:
            raise RuntimeError(f"document_already_exists_reconcile_without_duplicate:{number}")
        checked_targets = []
        for target in group["targets"]:
            offer = str(target["offer_id"])
            if offer not in products or offer not in attrs:
                raise RuntimeError(f"live_offer_missing:{number}:{offer}")
            checked_targets.append(validate_target(group, target, products[offer], attrs[offer]))
        source = Path(group["upload_file"]["path"])
        preflight.append({
            "number": number, "type_code": group["type_code"],
            "issue_date": group["issue_date"], "expire_date": group["expire_date"],
            "official_registry_url": group.get("source_url"),
            "fsa_evidence_verified": group["source_evidence_verified"],
            "source_sha256": sha256(source), "target_count": len(checked_targets),
            "target_identity_model_matches": len(checked_targets),
            "tnved_mismatch_count": sum(row["tnved_mismatch"] for row in checked_targets),
            "targets": checked_targets,
        })
    state["preflight"] = preflight
    state["read_only_preflight_complete"] = True
    state["live_certificate_count_before"] = len(certificates)
    save(OUT, state)

    # Mutate one document at a time. Every write is journaled; no write retries.
    for group, check in zip(groups, preflight):
        number = group["number"]
        source = Path(group["upload_file"]["path"])
        live_certificates = list_certificates(client)
        if get_exact_record(live_certificates, number):
            raise RuntimeError(f"document_appeared_before_create_reconcile:{number}")
        seed = next((row for row in check["targets"] if row["archived"] is False), check["targets"][0])
        payload = create_payload(group, seed["sku"], source)
        payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        entry = {"number": number, "operation": "create", "payload_sha256": payload_hash,
                 "source_sha256": sha256(source), "seed_sku": seed["sku"], "target_count": len(check["targets"])}
        journal({"phase": "prepared", **entry})
        response = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
        summary = {"certificate_id": response.get("certificate_id"), "status": response.get("status"),
                   "params": response.get("params")}
        journal({"phase": "create_response", **entry, "response": summary})
        states = [item.get("state") for item in response.get("params", []) if isinstance(item, dict)]
        if (not response.get("certificate_id") or response.get("status") != "COMPLETED"
                or not states or set(states) != {"VALID"}):
            after = list_certificates(client)
            matched = get_exact_record(after, number)
            result = {"number": number, "status": "create_not_completed", "response": summary,
                      "matching_records_after_create": [{"certificate_id": x.get("certificate_id"), "status_code": x.get("status_code")} for x in matched]}
            state["groups"].append(result)
            save(OUT, state)
            if matched:
                raise RuntimeError(f"create_outcome_requires_manual_reconciliation:{number}")
            continue
        certificate_id = int(response["certificate_id"])
        records_after_create = list_certificates(client)
        exact_records = get_exact_record(records_after_create, number)
        if len(exact_records) != 1:
            raise RuntimeError(f"created_record_not_unique_on_readback:{number}")
        record = exact_records[0]
        if (int(record.get("certificate_id") or 0) != certificate_id
                or record.get("type_code") != group["type_code"]
                or str(record.get("accordance_type_code") or "").upper() != "EAEU"
                or str(record.get("issue_date", ""))[:10] != group["issue_date"][:10]
                or str(record.get("expire_date", ""))[:10] != group["expire_date"][:10]
                or record.get("status_code") not in ALLOWED_CREATE_STATUSES):
            raise RuntimeError(f"created_record_metadata_or_status_mismatch:{number}")

        bindings = client.ozon_bindings(certificate_id)
        by_product = {str(row.get("product_id") or ""): row for row in bindings}
        missing = []
        for target in group["targets"]:
            product_id = str(target["product_id"])
            current = by_product.get(product_id)
            if current:
                if str(current.get("sku") or "") != str(target["sku"]):
                    raise RuntimeError(f"binding_product_id_conflict:{number}:{target['offer_id']}")
            else:
                missing.append(str(target["sku"]))
        bind_payload = {"certificate_id": certificate_id, "skus": sorted(set(missing))}
        if missing:
            bind_hash = hashlib.sha256(json.dumps(bind_payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
            journal({"phase": "prepared", "operation": "bind", "number": number,
                     "certificate_id": certificate_id, "payload_sha256": bind_hash,
                     "sku_count": len(bind_payload["skus"]), "skus": bind_payload["skus"]})
            bind_response = client.call("ozon", "/v1/product/certificate/bind", bind_payload, mutation=True)
            journal({"phase": "bind_response", "number": number, "certificate_id": certificate_id,
                     "response": bind_response})
        else:
            bind_response = {"result": True, "note": "all_targets_already_bound_on_create"}

        readback = client.ozon_bindings(certificate_id)
        by_product = {str(row.get("product_id") or ""): row for row in readback}
        target_rows = []
        for target in group["targets"]:
            row = by_product.get(str(target["product_id"]))
            target_rows.append({
                "offer_id": target["offer_id"], "product_id": str(target["product_id"]),
                "sku": str(target["sku"]), "found": bool(row),
                "identity_match": bool(row and str(row.get("sku") or "") == str(target["sku"])),
                "binding_status": row.get("product_status_code") if row else None,
            })
        result = {
            "number": number, "certificate_id": certificate_id,
            "record_status": record.get("status_code"), "create_response": summary,
            "bind_response": bind_response, "target_count": len(target_rows),
            "found_exact_bindings": sum(row["found"] and row["identity_match"] for row in target_rows),
            "binding_status_counts": {}, "targets": target_rows,
        }
        for row in target_rows:
            if row["found"] and row["identity_match"]:
                status = str(row.get("binding_status") or "unknown")
                result["binding_status_counts"][status] = result["binding_status_counts"].get(status, 0) + 1
        result["readback_complete"] = result["found_exact_bindings"] == result["target_count"]
        state["groups"].append(result)
        save(OUT, state)
        journal({"phase": "readback", "number": number, "certificate_id": certificate_id,
                 "record_status": record.get("status_code"), "found_exact_bindings": result["found_exact_bindings"],
                 "target_count": result["target_count"], "binding_status_counts": result["binding_status_counts"]})

    state["finished_at_utc"] = now()
    state["local_files_deleted"] = False
    state["wb_changed"] = False
    save(OUT, state)
    print(json.dumps({
        "output": str(OUT), "journal": str(JOURNAL),
        "live_certificate_count_before": state.get("live_certificate_count_before"),
        "groups": [{k: row.get(k) for k in ("number", "certificate_id", "status", "record_status", "target_count", "found_exact_bindings", "binding_status_counts", "readback_complete")} for row in state["groups"]],
        "local_files_deleted": False, "wb_changed": False,
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
