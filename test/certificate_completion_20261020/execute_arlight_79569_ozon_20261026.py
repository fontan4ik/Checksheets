"""Upload Arlight declaration 79569/26 once and verify its Ozon binding."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, digest, now  # noqa: E402

PREFLIGHT = HERE / "arlight_79569_ozon_preflight_20261026.json"
OUT = HERE / "arlight_79569_ozon_execution_20261026.json"
JOURNAL = HERE / "arlight_79569_ozon_mutation_journal_20261026.jsonl"
NUMBER = "ЕАЭС N RU Д-CN.РА01.В.79569/26"


def norm(value: object) -> str:
    char_map = str.maketrans({"А":"A", "В":"B", "Е":"E", "К":"K", "М":"M", "Н":"H", "О":"O", "Р":"P", "С":"C", "Т":"T", "У":"Y", "Х":"X", "Я":"R", "Д":"D"})
    text = unicodedata.normalize("NFKC", str(value or "")).upper().translate(char_map)
    return re.sub(r"[^0-9A-Z]", "", text)


def log(event: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at_utc": now(), **event}, ensure_ascii=False) + "\n")


def list_certificates(client: Client) -> list[dict]:
    rows: list[dict] = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list is incomplete")
        rows.extend(batch)
        if len(batch) < 100:
            return rows
    raise RuntimeError("Ozon certificate pagination limit exceeded")


def main() -> None:
    if JOURNAL.exists() or OUT.exists():
        raise RuntimeError("Mutation journal or execution result already exists; reconcile live Ozon state first")
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if preflight.get("read_only") is not True or preflight.get("upload_eligible") is not True or preflight.get("target_count") != 1:
        raise RuntimeError("Read-only preflight did not pass for exactly one target")
    source = Path(preflight["source_file"])
    if not source.is_file() or digest(source) != preflight.get("source_sha256"):
        raise RuntimeError("Signed PDF is missing or its hash changed since preflight")
    if norm(preflight.get("document_number")) != norm(NUMBER):
        raise RuntimeError("Document number differs from the preflight")
    expiry = dt.date.fromisoformat(preflight["expire_date"])
    if dt.date.today() > expiry:
        raise RuntimeError("Declaration expired since the read-only preflight")

    client = Client()
    if any(norm(row.get("certificate_number")) == norm(NUMBER) for row in list_certificates(client)):
        raise RuntimeError("Ozon already contains this declaration; reconcile instead of creating a duplicate")
    target = preflight["targets"][0]
    fresh_products = client.call("ozon", "/v3/product/info/list", {"offer_id": [target["offer_id"]]}).get("items")
    fresh_attrs = client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": [target["offer_id"]]}, "limit": 1}).get("result")
    if not isinstance(fresh_products, list) or len(fresh_products) != 1 or not isinstance(fresh_attrs, list) or len(fresh_attrs) != 1:
        raise RuntimeError("Fresh Ozon target read is incomplete")
    product = fresh_products[0]
    attrs_by_id = {str(item.get("id")): item for item in fresh_attrs[0].get("attributes") or []}
    brands = [str(item.get("value") or "").strip() for item in (attrs_by_id.get("85") or {}).get("values") or []]
    tnved = [str(item.get("value") or "").split(" - ", 1)[0].strip() for item in (attrs_by_id.get("22232") or {}).get("values") or []]
    live_pid = str(product.get("id") or product.get("product_id") or "")
    live_sku = str(product.get("sku") or "")
    if live_pid != str(target["product_id"]) or live_sku != str(target["sku"]) or product.get("is_archived") is not False:
        raise RuntimeError("Target product identity or active state changed after preflight")
    if brands != ["Arlight"] or tnved != [preflight["fsa_tnved"]] or "SR-DOOR-SWITCH" not in str(product.get("name") or "").upper():
        raise RuntimeError("Fresh Ozon brand/model/TNVED is outside the FSA document scope")

    params = {
        "name": "Декларация о соответствии № " + NUMBER,
        "certificate_type": "DECLARATION",
        "certificate_country": "RU",
        "accordance_type": "EAEU",
        "number": NUMBER,
        "issue_date": preflight["issue_date"] + "T00:00:00Z",
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [target["sku"]],
        "product_type": "UNKNOWN",
        "files": [{"file_content": base64.b64encode(source.read_bytes()).decode("ascii"), "name": source.name}],
        "link_to_registry": preflight["fsa_record_url"],
    }
    payload = {"params": params}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > 9_500_000:
        raise RuntimeError("Ozon create payload exceeded its safety limit")
    log({"phase": "prepared", "operation": "create", "endpoint": "/v2/product/certificate/create",
         "request_sha256": hashlib.sha256(encoded).hexdigest(), "document_number": NUMBER,
         "source_sha256": digest(source), "target_offer": target["offer_id"], "target_product_id": target["product_id"],
         "target_sku": target["sku"]})

    # Do not retry this call. If the response is uncertain, reconcile against live Ozon before another mutation.
    created = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
    states = [row.get("state") for row in created.get("params", []) if isinstance(row, dict)]
    certificate_id = str(created.get("certificate_id") or "")
    log({"phase": "create_response", "certificate_id": certificate_id, "status": created.get("status"), "param_states": states})
    if not certificate_id or created.get("status") != "COMPLETED" or not states or set(states) != {"VALID"}:
        raise RuntimeError("Ozon did not validate document creation; reconcile live Ozon before further action")

    before = client.ozon_bindings(certificate_id)
    by_product = {str(row.get("product_id")): row for row in before}
    seed = by_product.get(str(target["product_id"]))
    if seed and str(seed.get("sku")) != str(target["sku"]):
        raise RuntimeError("Created declaration has a target product identity conflict")
    if seed and seed.get("product_status_code") == "declined":
        raise RuntimeError("Ozon declined the initial product binding; do not retry automatically")
    bind_response = None
    if not seed:
        bind_payload = {"certificate_id": int(certificate_id), "skus": [target["sku"]]}
        bind_bytes = json.dumps(bind_payload, ensure_ascii=False, separators=(",", ":")).encode()
        log({"phase": "prepared", "operation": "bind", "endpoint": "/v1/product/certificate/bind",
             "request_sha256": hashlib.sha256(bind_bytes).hexdigest(), "certificate_id": certificate_id,
             "skus": bind_payload["skus"]})
        bind_response = client.call("ozon", "/v1/product/certificate/bind", bind_payload, mutation=True)
        log({"phase": "bind_response", "certificate_id": certificate_id, "result": bind_response.get("result")})
        if bind_response.get("result") is not True:
            raise RuntimeError("Ozon did not confirm the binding; reconcile live state before retry")

    bindings_after = client.ozon_bindings(certificate_id)
    exact = [row for row in bindings_after if str(row.get("product_id")) == str(target["product_id"]) and str(row.get("sku")) == str(target["sku"])]
    if len(exact) != 1 or exact[0].get("product_status_code") == "declined":
        raise RuntimeError("Exact target binding is missing, duplicated, or declined")
    certs_after = list_certificates(client)
    matches = [row for row in certs_after if norm(row.get("certificate_number")) == norm(NUMBER)]
    if len(matches) != 1:
        raise RuntimeError("Ozon declaration is not unique after upload; stop and reconcile")
    record = matches[0]
    statuses = {status: sum(1 for row in bindings_after if row.get("product_status_code") == status)
                for status in sorted({str(row.get("product_status_code")) for row in bindings_after})}
    result = {
        "checked_at_utc": now(),
        "complete": True,
        "platform": "Ozon",
        "certificate_id": str(certificate_id),
        "certificate_number": NUMBER,
        "ozon_status": record.get("status_code"),
        "rejection_reason_code": record.get("rejection_reason_code"),
        "verification_comment": record.get("verification_comment"),
        "issue_date": record.get("issue_date"),
        "expire_date": record.get("expire_date"),
        "target_count": 1,
        "target_binding": {**target, "binding_status": exact[0].get("product_status_code")},
        "binding_count_after": len(bindings_after),
        "binding_status_counts": statuses,
        "source_sha256": digest(source),
        "source_file": str(source),
        "create_param_states": states,
        "bind_response_confirmed": (bind_response or {}).get("result") is True,
        "fsa_record_url": preflight["fsa_record_url"],
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log({"phase": "readback_complete", "certificate_id": certificate_id, "ozon_status": result["ozon_status"],
         "target_binding_status": exact[0].get("product_status_code"), "binding_status_counts": statuses})
    print(json.dumps({"execution": str(OUT), "certificate_id": certificate_id,
                      "ozon_status": result["ozon_status"], "target_binding_status": exact[0].get("product_status_code"),
                      "target_count": 1, "binding_status_counts": statuses}, ensure_ascii=False))


if __name__ == "__main__":
    main()
