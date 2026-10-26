"""Upload IN HOME declaration 17512/24 to Ozon and bind its exact GX53 targets."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "certificate_api_pilot_20261012"
sys.path.insert(0, str(BASE))
from api_client import Client, digest, now  # noqa: E402

HERE = Path(__file__).resolve().parent
PREFLIGHT = HERE / "inhome_17512_ozon_preflight_20261026.json"
OUT = HERE / "inhome_17512_ozon_execution_20261026.json"
JOURNAL = HERE / "inhome_17512_ozon_mutation_journal_20261026.jsonl"
NUMBER = "ЕАЭС N RU Д-CN.РА06.В.17512/24"
CHAR_MAP = str.maketrans({"А":"A", "В":"B", "Е":"E", "К":"K", "М":"M", "Н":"H", "О":"O", "Р":"P", "С":"C", "Т":"T", "У":"Y", "Х":"X", "Я":"R", "Д":"D"})


def norm(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).upper().translate(CHAR_MAP)
    return re.sub(r"[^0-9A-Z]", "", text)


def log(event: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at_utc": now(), **event}, ensure_ascii=False) + "\n")


def list_certs(client: Client) -> list[dict]:
    records: list[dict] = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list response incomplete")
        records.extend(batch)
        if len(batch) < 100:
            return records
    raise RuntimeError("Ozon certificate pagination limit exceeded")


def fresh_targets(client: Client, targets: list[dict]) -> list[dict]:
    offers = [row["offer_id"] for row in targets]
    product_rows = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items")
    attribute_rows = client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": offers}, "limit": len(offers)}).get("result")
    if not isinstance(product_rows, list) or not isinstance(attribute_rows, list):
        raise RuntimeError("Fresh Ozon product read incomplete")
    by_offer = {str(row.get("offer_id")): row for row in product_rows}
    attrs_by_offer = {str(row.get("offer_id")): row for row in attribute_rows}
    if set(by_offer) != set(offers) or set(attrs_by_offer) != set(offers):
        raise RuntimeError("Fresh Ozon product identity set differs from preflight")

    checked = []
    for target in targets:
        product = by_offer[target["offer_id"]]
        attrs = attrs_by_offer[target["offer_id"]]
        by_id = {str(item.get("id")): item for item in attrs.get("attributes") or []}
        brands = [str(value.get("value") or "").strip() for value in (by_id.get("85") or {}).get("values") or []]
        tnved = [str(value.get("value") or "").split(" - ", 1)[0].strip() for value in (by_id.get("22232") or {}).get("values") or []]
        row = {
            **target,
            "live_product_id": str(product.get("id") or product.get("product_id") or ""),
            "live_sku": str(product.get("sku") or ""),
            "is_archived": product.get("is_archived"),
            "name": product.get("name"),
            "brand_values": brands,
            "tnved_codes": tnved,
        }
        if row["live_product_id"] != target["product_id"] or row["live_sku"] != target["sku"] or row["is_archived"] is not False:
            raise RuntimeError("Target identity/archive changed: " + target["offer_id"])
        if brands != ["IN HOME"] or tnved != ["8539520009"] or "GX53" not in str(row["name"]).upper():
            raise RuntimeError("Live brand, model, or TNVED is outside FSA scope: " + target["offer_id"])
        checked.append(row)
    return checked


def main() -> None:
    if JOURNAL.exists():
        raise RuntimeError("Mutation journal already exists; reconcile before any further action")
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if preflight.get("upload_eligible") is not True or preflight.get("read_only") is not True:
        raise RuntimeError("Read-only preflight did not pass")
    source = Path(preflight["source_file"])
    if not source.is_file() or digest(source) != preflight.get("source_sha256"):
        raise RuntimeError("Source PDF missing or hash changed since preflight")
    if norm(NUMBER) != norm(preflight.get("document_number")):
        raise RuntimeError("Document number differs from preflight")
    if dt.date.today() > dt.date.fromisoformat(preflight["expire_date"]):
        raise RuntimeError("Declaration expired since preflight")

    client = Client()
    certificates = list_certs(client)
    if any(norm(row.get("certificate_number")) == norm(NUMBER) for row in certificates):
        raise RuntimeError("Matching Ozon declaration appeared; reconcile instead of creating another")
    targets = preflight["targets"]
    fresh_targets(client, targets)
    expiry = dt.date.fromisoformat(preflight["expire_date"])
    params = {
        "name": "Декларация о соответствии № " + NUMBER,
        "certificate_type": "DECLARATION",
        "certificate_country": "RU",
        "accordance_type": "EAEU",
        "number": NUMBER,
        "issue_date": preflight["issue_date"] + "T00:00:00Z",
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [targets[0]["sku"]],
        "product_type": "UNKNOWN",
        "files": [{"file_content": base64.b64encode(source.read_bytes()).decode("ascii"), "name": source.name}],
        "link_to_registry": preflight["fsa_record_url"],
    }
    payload = {"params": params}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > 9_500_000:
        raise RuntimeError("Ozon create payload is unexpectedly large")
    log({"phase": "prepared", "operation": "create", "endpoint": "/v2/product/certificate/create",
         "request_sha256": hashlib.sha256(encoded).hexdigest(), "document_number": NUMBER,
         "source_sha256": digest(source), "target_skus": [row["sku"] for row in targets], "seed_sku": targets[0]["sku"]})
    created = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
    states = [row.get("state") for row in created.get("params", []) if isinstance(row, dict)]
    certificate_id = str(created.get("certificate_id") or "")
    log({"phase": "response", "operation": "create", "certificate_id": certificate_id,
         "status": created.get("status"), "param_states": states})
    if not certificate_id or created.get("status") != "COMPLETED" or not states or set(states) != {"VALID"}:
        raise RuntimeError("Ozon create response was not validated; reconcile live state before retry")

    bindings_before = client.ozon_bindings(certificate_id)
    targets_by_product = {row["product_id"]: row for row in targets}
    before_by_product = {str(row.get("product_id")): row for row in bindings_before}
    for product_id, binding in before_by_product.items():
        expected = targets_by_product.get(product_id)
        if expected and str(binding.get("sku")) != expected["sku"]:
            raise RuntimeError("Binding identity conflict immediately after create")
        if expected and binding.get("product_status_code") == "declined":
            raise RuntimeError("Seed product binding was declined; reconcile before any further mutation")

    missing = [row for row in targets if row["product_id"] not in before_by_product]
    bind_response = None
    if missing:
        bind_payload = {"certificate_id": int(certificate_id), "skus": [row["sku"] for row in missing]}
        bind_encoded = json.dumps(bind_payload, ensure_ascii=False, separators=(",", ":")).encode()
        log({"phase": "prepared", "operation": "bind", "endpoint": "/v1/product/certificate/bind",
             "request_sha256": hashlib.sha256(bind_encoded).hexdigest(), "certificate_id": certificate_id,
             "skus": bind_payload["skus"]})
        bind_response = client.call("ozon", "/v1/product/certificate/bind", bind_payload, mutation=True)
        log({"phase": "response", "operation": "bind", "certificate_id": certificate_id,
             "result": bind_response.get("result")})
        if bind_response.get("result") is not True:
            raise RuntimeError("Ozon did not confirm binding; reconcile before retry")

    bindings_after = client.ozon_bindings(certificate_id)
    by_product = {str(row.get("product_id")): row for row in bindings_after}
    verified = []
    for target in targets:
        binding = by_product.get(target["product_id"])
        verified.append({**target, "binding_found": binding is not None,
                         "binding_sku": str((binding or {}).get("sku") or ""),
                         "binding_status": (binding or {}).get("product_status_code")})
    if not all(row["binding_found"] and row["binding_sku"] == row["sku"] and row["binding_status"] != "declined" for row in verified):
        raise RuntimeError("Binding readback incomplete or declined")

    certs_after = list_certs(client)
    matching = [row for row in certs_after if norm(row.get("certificate_number")) == norm(NUMBER)]
    if len(matching) != 1:
        raise RuntimeError("Created Ozon declaration is not unique on readback")
    record = matching[0]
    statuses = {status: sum(1 for row in bindings_after if row.get("product_status_code") == status)
                for status in sorted({str(row.get("product_status_code")) for row in bindings_after})}
    result = {
        "checked_at_utc": now(),
        "complete": True,
        "platform": "Ozon",
        "fsa_record_url": preflight["fsa_record_url"],
        "certificate_id": certificate_id,
        "certificate_number": NUMBER,
        "ozon_status": record.get("status_code"),
        "rejection_reason_code": record.get("rejection_reason_code"),
        "verification_comment": record.get("verification_comment"),
        "issue_date": record.get("issue_date"),
        "expire_date": record.get("expire_date"),
        "target_count": len(targets),
        "target_bindings": verified,
        "binding_count_before_bind": len(bindings_before),
        "binding_count_after": len(bindings_after),
        "binding_status_counts": statuses,
        "source_sha256": digest(source),
        "source_file": str(source),
        "bind_response_confirmed": (bind_response or {}).get("result") is True,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"execution": str(OUT), "certificate_id": certificate_id,
                      "ozon_status": result["ozon_status"], "target_count": len(targets),
                      "binding_status_counts": statuses}, ensure_ascii=False))


if __name__ == "__main__":
    main()
