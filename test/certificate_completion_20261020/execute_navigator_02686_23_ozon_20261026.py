"""Preflight and, with --execute, upload Navigator recirculator certificate to Ozon."""
from __future__ import annotations

import argparse
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

NUMBER = "ЕАЭС RU С-RU.НВ93.В.02686/23"
OFFER = "14669-1"
PRODUCT_ID = "6023629936"
SKU = "5523801992"
MODEL = "NUR-01-230-G13-WH"
TNVED = "8421392008"
ISSUE = "2023-02-06"
EXPIRY = "2028-02-05"
FSA_RECORD_ID = 3203635
FSA_URL = f"https://pub.fsa.gov.ru/rss/certificate/view/{FSA_RECORD_ID}/product"
SOURCE = ROOT / "output_to_user/certificates/additional_search/brand_research/navigator/followup_2026_10_02_c/documents/originals/Navigator_certificate_EAEC_C-RU.NV93.B.02686-23.pdf"
EXPECTED_SHA256 = "6e44c0d7b53a9f9a06a0a94104e4d33430528db8050210ee3a4581de4831eae7"
PREFLIGHT = HERE / "navigator_02686_23_preflight_ozon_20261026.json"
EXECUTION = HERE / "navigator_02686_23_execution_ozon_20261026.json"
JOURNAL = HERE / "navigator_02686_23_mutation_journal_ozon_20261026.jsonl"
SNAPSHOT = ROOT / "test/certificate_api_pilot_20261012/ozon_live.json"


def normalized(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).upper()
    return re.sub(r"[^0-9A-ZА-ЯЁ]", "", text.translate(str.maketrans({"Ё": "Е"})))


def atomic_write(path: Path, value: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def journal(event: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at_utc": now(), **event}, ensure_ascii=False) + "\n")
        stream.flush()


def certificates(client: Client) -> list[dict]:
    rows: list[dict] = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list is incomplete")
        rows.extend(batch)
        if page >= int(result.get("page_count") or page):
            return rows
    raise RuntimeError("Ozon certificate pagination exceeded 100 pages")


def product_preflight(client: Client) -> dict:
    product_result = client.call("ozon", "/v3/product/info/list", {"offer_id": [OFFER]}).get("items")
    if not isinstance(product_result, list) or len(product_result) != 1:
        raise RuntimeError("Expected one current Ozon product for the exact offer")
    product = product_result[0]
    product_id = str(product.get("product_id") or product.get("id") or "")
    sources = product.get("sources") or []
    skus = {str(source.get("sku") or "") for source in sources}
    skus.discard("")
    if product_id != PRODUCT_ID or skus != {SKU} or product.get("is_archived") is not False:
        raise RuntimeError(f"Ozon product identity changed: {product_id=}, {skus=}, archived={product.get('is_archived')}")

    attr_rows = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": [OFFER]}, "limit": 10,
    }).get("result")
    if not isinstance(attr_rows, list) or len(attr_rows) != 1:
        raise RuntimeError("Expected one current Ozon attributes row")
    attr_row = attr_rows[0]
    if str(attr_row.get("id") or attr_row.get("product_id") or "") != PRODUCT_ID:
        raise RuntimeError("Ozon attribute row belongs to a different product")
    attrs = {str(item.get("id")): item for item in attr_row.get("attributes") or []}
    brands = [str(value.get("value") or "").strip() for value in (attrs.get("85") or {}).get("values") or []]
    tnved_values = [str(value.get("value") or "").split(" - ", 1)[0].strip()
                    for value in (attrs.get("22232") or {}).get("values") or []]
    name = str(product.get("name") or "")
    if brands != ["Navigator"] or tnved_values != [TNVED] or MODEL not in name:
        raise RuntimeError(f"Live brand/model/TN VED scope mismatch: {brands=}, {tnved_values=}, {name=}")
    return {"offer_id": OFFER, "product_id": product_id, "sku": SKU, "name": name,
            "brand_values": brands, "tnved_values": tnved_values, "model": MODEL}


def preflight(client: Client) -> dict:
    if not SOURCE.is_file() or digest(SOURCE) != EXPECTED_SHA256:
        raise RuntimeError("The source PDF is missing or differs from the reviewed SHA-256")
    target = product_preflight(client)
    rows = certificates(client)
    duplicates = [item for item in rows if normalized(item.get("certificate_number")) == normalized(NUMBER)]
    if duplicates:
        raise RuntimeError(f"Ozon already has this certificate number: {[x.get('certificate_id') for x in duplicates]}")
    if not SNAPSHOT.is_file():
        raise RuntimeError("Full live Ozon certificate/binding audit is missing")
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if not snapshot.get("complete") or len(snapshot.get("certificates") or []) != len(rows):
        raise RuntimeError("Full live Ozon binding audit is incomplete or differs from the current certificate list")
    bound = []
    for cert in snapshot["certificates"]:
        for binding in cert.get("live_bindings") or []:
            if str(binding.get("product_id") or "") == PRODUCT_ID:
                bound.append({"certificate_id": cert.get("certificate_id"),
                              "certificate_number": cert.get("certificate_number"),
                              "record_status": cert.get("status_code"),
                              "binding_status": binding.get("product_status_code")})
    if bound:
        raise RuntimeError(f"The target product already has an Ozon certificate binding; reconcile first: {bound}")

    result = {
        "checked_at_utc": now(), "read_only": True, "upload_eligible": True, "platform": "Ozon",
        "brand": "Navigator", "certificate_number": NUMBER, "certificate_type": "certificate_of_conformity",
        "accordance_type": "EAEU", "issue_date": ISSUE, "expire_date": EXPIRY,
        "fsa_record_id": FSA_RECORD_ID, "fsa_url": FSA_URL,
        "fsa_status": "Действует; verified in FSA UI 2026-10-26",
        "fsa_product_scope": "Navigator NUR series, exact model NUR-01-230-G13-WH; TN VED 8421392008; TR TS 004/2011 and 020/2011; serial release; no lot sample-date cutoff stated in record",
        "source_file": str(SOURCE), "source_sha256": digest(SOURCE), "source_size_bytes": SOURCE.stat().st_size,
        "ozon_catalog_checked_at": dt.datetime.now(dt.timezone.utc).isoformat(), "target_count": 1,
        "targets": [target], "ozon_certificate_records_checked": len(rows),
        "duplicate_number_count": 0, "preexisting_product_bindings": [], "local_source_deleted": False,
        "wb_changed": False,
    }
    atomic_write(PREFLIGHT, result)
    return result


def execute(client: Client, pf: dict) -> dict:
    if not pf.get("upload_eligible") or digest(SOURCE) != pf.get("source_sha256"):
        raise RuntimeError("Preflight is not eligible or source changed")
    if JOURNAL.exists() or EXECUTION.exists():
        raise RuntimeError("Execution journal/output already exists; reconcile before any retry")
    # Re-read number immediately before the one non-retried create request.
    if any(normalized(c.get("certificate_number")) == normalized(NUMBER) for c in certificates(client)):
        raise RuntimeError("The certificate appeared in Ozon after preflight; refusing duplicate creation")
    expiry = dt.date.fromisoformat(EXPIRY)
    params = {
        "name": "Сертификат соответствия № " + NUMBER,
        "certificate_type": "CERTIFICATE_OF_CONFORMITY",
        "certificate_country": "RU", "accordance_type": "EAEU", "number": NUMBER,
        "issue_date": ISSUE + "T00:00:00Z",
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [SKU], "product_type": "UNKNOWN",
        "files": [{"file_content": base64.b64encode(SOURCE.read_bytes()).decode("ascii"), "name": SOURCE.name}],
        "link_to_registry": FSA_URL,
    }
    payload = {"params": params}
    payload_sha = hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    journal({"phase": "prepared", "operation": "create", "endpoint": "/v2/product/certificate/create",
             "number": NUMBER, "payload_sha256": payload_sha, "source_sha256": pf["source_sha256"], "skus": [SKU]})
    try:
        created = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
    except Exception as exc:
        journal({"phase": "create_uncertain", "number": NUMBER, "error_type": type(exc).__name__})
        matches = [c for c in certificates(client) if normalized(c.get("certificate_number")) == normalized(NUMBER)]
        if len(matches) != 1:
            raise RuntimeError("Ozon create outcome is uncertain; no retry was made") from exc
        created = {"certificate_id": str(matches[0]["certificate_id"]), "status": "RECONCILED", "params": []}
    cert_id = str(created.get("certificate_id") or "")
    states = [row.get("state") for row in created.get("params") or [] if isinstance(row, dict)]
    journal({"phase": "create_response", "number": NUMBER, "certificate_id": cert_id,
             "status": created.get("status"), "parameter_states": states})
    if not cert_id or created.get("status") not in {"COMPLETED", "RECONCILED"} or (states and set(states) != {"VALID"}):
        result = {"finished_at_utc": now(), "outcome": "create_not_validated", "created_response": created,
                  "source_deleted": False, "wb_changed": False}
        atomic_write(EXECUTION, result)
        raise RuntimeError("Ozon did not validate the upload; stop for reconciliation")

    bindings = client.ozon_bindings(cert_id)
    by_product = {str(row.get("product_id")): row for row in bindings}
    target = pf["targets"][0]
    current = by_product.get(PRODUCT_ID)
    bind_response = None
    if current and str(current.get("sku")) != SKU:
        raise RuntimeError("Ozon attached an unexpected SKU to the new certificate")
    if not current:
        bind_payload = {"certificate_id": int(cert_id), "skus": [SKU]}
        bind_sha = hashlib.sha256(json.dumps(bind_payload, separators=(",", ":")).encode()).hexdigest()
        journal({"phase": "prepared", "operation": "bind", "endpoint": "/v1/product/certificate/bind",
                 "number": NUMBER, "certificate_id": cert_id, "payload_sha256": bind_sha, "skus": [SKU]})
        bind_response = client.call("ozon", "/v1/product/certificate/bind", bind_payload, mutation=True)
        journal({"phase": "bind_response", "number": NUMBER, "certificate_id": cert_id, "response": bind_response})
    live_bindings = client.ozon_bindings(cert_id)
    record = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER}).get("result") or {}
    exact = [row for row in live_bindings if str(row.get("product_id")) == PRODUCT_ID and str(row.get("sku")) == SKU]
    result = {
        "finished_at_utc": now(), "outcome": "uploaded_and_bound" if len(exact) == 1 else "uploaded_binding_not_confirmed",
        "certificate_id": cert_id, "record_status": record.get("status_code"),
        "certificate_number_returned": record.get("certificate_number"), "products_count": record.get("products_count"),
        "binding_count": len(live_bindings), "exact_target_binding_count": len(exact),
        "target_binding_status": exact[0].get("product_status_code") if exact else None,
        "binding_response": bind_response, "create_response_status": created.get("status"),
        "source_sha256": pf["source_sha256"], "source_deleted": False, "wb_changed": False,
        "target": target,
    }
    atomic_write(EXECUTION, result)
    journal({"phase": "final_readback", **result})
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Create Ozon record and bind after fresh preflight")
    args = parser.parse_args()
    client = Client()
    pf = preflight(client)
    if args.execute:
        result = execute(client, pf)
        print(json.dumps({"preflight_eligible": True, "execution": result}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(pf, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
