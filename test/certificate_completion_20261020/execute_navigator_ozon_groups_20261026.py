"""Preflight and upload two scope-verified Navigator declarations to Ozon."""
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
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, digest, now  # noqa: E402

ASSIGNMENTS = HERE / "all_confirmed_source_assignments_live_reconciled_20261023.csv"
SNAPSHOT = HERE / "live_marketplaces_snapshot_export_20261026.json"
REPORT = HERE / "confirmed_source_gaps_allbrand_postreconcile_final_20261023.json"
JOURNAL = HERE / "navigator_pair_ozon_mutation_journal_20261026.jsonl"
OUT = HERE / "navigator_pair_ozon_execution_20261026.json"

DOCS = [
    {
        "key": "navigator_28059_22",
        "brand": "Navigator",
        "number": "ЕАЭС N RU Д-CN.РА07.В.28059/22",
        "number_suffix": "28059/22",
        "type_code": "declaration",
        "accordance_type": "EAEU",
        "issue_date": "2022-10-11",
        "expire_date": "2027-10-10",
        "fsa_record_id": 17103225,
        "fsa_url": "https://pub.fsa.gov.ru/rds/declaration/view/17103225/product",
        "fsa_tnved": "8531809500",
        "fsa_scope": "Navigator/ОНЛАЙТ wireless bells, NDB/ODB models, EAEU TR 037/2016; serial production, no sample-date cutoff",
        "models": {
            "61267-1": "NDB-A-DC01-1V1-WH",
            "61268-1": "NDB-A-DC02-1V1-WH",
            "61270-1": "NDB-D-AC02-1V1-WH",
            "61272-1": "NDB-D-DC02-1V1-S",
            "61696-1": "NDB-A-DC03-1V1-WH",
            "80508-1": "NDB-D-AC05-1V1-BL",
            "80510-1": "NDB-D-DC06-1V1-S",
            "80512-1": "NDB-D-DC06-1V1-BL",
        },
        "source_rel": "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_declaration_61267_218475e95d52.pdf",
    },
    {
        "key": "navigator_05668_24",
        "brand": "Navigator",
        "number": "РОСС RU Д-CN.РА01.В.05668/24",
        "number_suffix": "05668/24",
        "type_code": "declaration",
        "accordance_type": "national",
        "issue_date": "2024-02-14",
        "expire_date": "2029-02-13",
        "fsa_record_id": 18636547,
        "fsa_url": "https://pub.fsa.gov.ru/rds/declaration/view/18636547/product",
        "fsa_tnved": "8507500000",
        "fsa_scope": "Navigator NHR nickel-metal hydride rechargeable batteries; exact models, serial production",
        "models": {
            "94461-1": "NHR-800-HR03-BP2",
            "94465-1": "NHR-2700-HR6-BP2",
            "94785-1": "NHR-2200-HR6-RTU-BP2",
        },
        "source_rel": "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_declaration_94461_01b914d7e222.pdf",
    },
]


def norm(value: object) -> str:
    char_map = str.maketrans({"А":"A", "В":"B", "Е":"E", "К":"K", "М":"M", "Н":"H", "О":"O", "Р":"P", "С":"C", "Т":"T", "У":"Y", "Х":"X", "Я":"R", "Д":"D"})
    text = unicodedata.normalize("NFKC", str(value or "")).upper().translate(char_map)
    return re.sub(r"[^0-9A-Z]", "", text)


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


def sku_from_product(product: dict) -> str:
    values = [str(s.get("sku")) for s in product.get("sources") or [] if s.get("sku") is not None]
    return values[0] if len(set(values)) == 1 else ""


def append_journal(event: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at_utc": now(), **event}, ensure_ascii=False) + "\n")


def fresh_target_rows(client: Client, doc: dict, assignment_rows: list[dict]) -> list[dict]:
    expected_offers = list(doc["models"])
    rows = [r for r in assignment_rows if r.get("brand") == doc["brand"] and norm(r.get("number")) == norm(doc["number"])
            and r.get("offer_id") in doc["models"]]
    if len(rows) != len(expected_offers) or {r.get("offer_id") for r in rows} != set(expected_offers):
        raise RuntimeError(f"Assignment rows do not exactly cover the target offers for {doc['number']}")
    if any(r.get("type") != "declaration" or r.get("source_type_conflict") == "True" or r.get("source_file_exists") != "True" for r in rows):
        raise RuntimeError(f"Source assignment type/file check failed for {doc['number']}")
    offers = sorted(expected_offers)
    products_response = client.call("ozon", "/v3/product/info/list", {"offer_id": offers})
    products = products_response.get("items")
    attrs_response = client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": offers}, "limit": 1000})
    attrs = attrs_response.get("result")
    if not isinstance(products, list) or len(products) != len(offers) or not isinstance(attrs, list) or len(attrs) != len(offers):
        raise RuntimeError(f"Fresh Ozon product/attribute response is incomplete for {doc['number']}")
    prod_by_offer = {p.get("offer_id"): p for p in products}
    attr_by_offer = {a.get("offer_id"): a for a in attrs}
    row_by_offer = {r["offer_id"]: r for r in rows}
    result = []
    for offer in offers:
        assignment = row_by_offer[offer]
        p = prod_by_offer.get(offer) or {}
        a = attr_by_offer.get(offer) or {}
        attrs_by_id = {str(x.get("id")): x for x in a.get("attributes") or []}
        brands = [str(x.get("value") or "").strip() for x in (attrs_by_id.get("85") or {}).get("values") or []]
        tnved = [str(x.get("value") or "").split(" - ", 1)[0].strip() for x in (attrs_by_id.get("22232") or {}).get("values") or []]
        pid = str(p.get("id") or p.get("product_id") or "")
        sku = sku_from_product(p)
        name = str(p.get("name") or "")
        expected_model = doc["models"][offer]
        if (pid != str(assignment.get("ozon_product_id")) or sku != str(assignment.get("ozon_sku"))
                or p.get("is_archived") is not False or brands != [doc["brand"]] or tnved != [doc["fsa_tnved"]]
                or expected_model.upper() not in name.upper()):
            raise RuntimeError(f"Live identity/scope mismatch for {offer}: {pid=} {sku=} {brands=} {tnved=} {name=}")
        result.append({"offer_id": offer, "product_id": pid, "sku": sku, "name": name,
                       "is_archived": False, "brand_values": brands, "tnved_codes": tnved,
                       "exact_model": expected_model})
    return result


def approved_coverage(snapshot: dict, targets: list[dict]) -> list[dict]:
    by_sku = {str(p.get("sku")): p for p in snapshot["ozon_products"]["products"] if p.get("sku")}
    today = dt.date.today().isoformat()
    matches = []
    target_ids = {str(t["product_id"]) for t in targets}
    for cert in snapshot["ozon_certificates"]["certificates"]:
        if cert.get("status_code") != "approved" or str(cert.get("issue_date") or "")[:10] > today or str(cert.get("expire_date") or "")[:10] < today:
            continue
        for binding in cert.get("live_bindings") or []:
            product_id = str(binding.get("product_id") or "")
            p = by_sku.get(str(binding.get("sku") or ""))
            if (product_id in target_ids and p and str(p.get("product_id")) == product_id
                    and binding.get("product_status_code") == "approved"):
                matches.append({"product_id": product_id, "certificate_number": cert.get("certificate_number"),
                                "certificate_id": cert.get("certificate_id")})
    return matches


def preflight(client: Client, doc: dict, assignments: list[dict], snapshot: dict, source_groups: list[dict]) -> dict:
    source = ROOT / doc["source_rel"]
    if not source.is_file():
        raise RuntimeError(f"Source PDF is missing: {source}")
    source_hash = digest(source)
    evidence = [g for g in source_groups if g.get("brand") == doc["brand"] and norm(g.get("document_number")) == norm(doc["number"])
                and g.get("actual_sha256") == source_hash and g.get("sha256_matches") is True]
    if not evidence:
        raise RuntimeError(f"No confirmed source-evidence group with matching hash for {doc['number']}")
    group = evidence[0]
    declared_targets = int(group.get("missing_ozon_offers", 0))
    targets = fresh_target_rows(client, doc, assignments)
    if declared_targets != len(targets):
        raise RuntimeError(f"Confirmed-source target count mismatch for {doc['number']}: {declared_targets} vs {len(targets)}")
    certs = list_certificates(client)
    duplicates = [c for c in certs if norm(c.get("certificate_number")) == norm(doc["number"])]
    if duplicates:
        raise RuntimeError(f"Ozon already contains this number; reconcile before creating: {doc['number']}")
    coverage = approved_coverage(snapshot, targets)
    if coverage:
        raise RuntimeError(f"At least one target already has another active approved Ozon document: {coverage}")
    if dt.date.today() > dt.date.fromisoformat(doc["expire_date"]):
        raise RuntimeError(f"Document expired before upload: {doc['number']}")
    return {
        "checked_at_utc": now(), "read_only": True, "upload_eligible": True, "platform": "Ozon",
        "brand": doc["brand"], "document_number": doc["number"], "document_type": doc["type_code"],
        "accordance_type": doc["accordance_type"], "issue_date": doc["issue_date"], "expire_date": doc["expire_date"],
        "fsa_record_id": doc["fsa_record_id"], "fsa_record_url": doc["fsa_url"],
        "fsa_status": "active; verified in FSA registry UI on 2026-10-26", "fsa_tnved": doc["fsa_tnved"],
        "fsa_scope": doc["fsa_scope"], "source_file": str(source), "source_sha256": source_hash,
        "confirmed_source_group": {"missing_ozon_offers": declared_targets, "applicability_counts": group.get("applicability_counts"),
                                   "scope_examples": group.get("scope_examples")},
        "ozon_certificate_count_checked": len(certs), "snapshot_checked_at": snapshot["ozon_products"]["checked_at"],
        "baseline_approved_binding_count_for_targets": 0, "target_count": len(targets), "targets": targets,
    }


def process(client: Client, doc: dict, pf: dict) -> dict:
    number = doc["number"]
    source = Path(pf["source_file"])
    if digest(source) != pf["source_sha256"]:
        raise RuntimeError(f"Source file changed after preflight for {number}")
    certs = list_certificates(client)
    if any(norm(c.get("certificate_number")) == norm(number) for c in certs):
        raise RuntimeError(f"Ozon already contains {number}; refusing duplicate create")
    expiry = dt.date.fromisoformat(doc["expire_date"])
    targets = pf["targets"]
    params = {
        "name": "Документ " + number,
        "certificate_type": "DECLARATION",
        "certificate_country": "RU",
        "accordance_type": doc["accordance_type"],
        "number": number,
        "issue_date": doc["issue_date"] + "T00:00:00Z",
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [targets[0]["sku"]],
        "product_type": "UNKNOWN",
        "files": [{"file_content": base64.b64encode(source.read_bytes()).decode("ascii"), "name": source.name}],
        "link_to_registry": doc["fsa_url"],
    }
    payload = {"params": params}
    request_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    append_journal({"phase": "prepared", "operation": "create", "endpoint": "/v2/product/certificate/create",
                    "document_number": number, "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
                    "source_sha256": pf["source_sha256"], "target_count": len(targets),
                    "target_skus": [t["sku"] for t in targets]})
    try:
        created = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
    except Exception as exc:
        append_journal({"phase": "create_uncertain", "document_number": number, "error_type": type(exc).__name__})
        # The create call is never repeated. Reconcile its exact number before doing anything else.
        matches = [c for c in list_certificates(client) if norm(c.get("certificate_number")) == norm(number)]
        if len(matches) != 1:
            raise RuntimeError(f"Create outcome uncertain and no unique Ozon record is visible for {number}") from exc
        created = {"certificate_id": str(matches[0].get("certificate_id")), "status": "RECONCILED", "params": []}
    cert_id = str(created.get("certificate_id") or "")
    states = [p.get("state") for p in created.get("params", []) if isinstance(p, dict)]
    append_journal({"phase": "create_response", "document_number": number, "certificate_id": cert_id,
                    "status": created.get("status"), "param_states": states})
    if not cert_id:
        raise RuntimeError(f"Ozon did not return a certificate id for {number}; reconcile before retry")
    if created.get("status") not in {"COMPLETED", "RECONCILED"} or (states and set(states) != {"VALID"}):
        raise RuntimeError(f"Ozon did not validate the new document {number}; stop for reconciliation")
    bindings = client.ozon_bindings(cert_id)
    by_product = {str(b.get("product_id")): b for b in bindings}
    if any(str(b.get("product_id")) not in {t["product_id"] for t in targets} for b in bindings):
        raise RuntimeError(f"Unexpected product binding appeared on new document {number}")
    missing = []
    for t in targets:
        current = by_product.get(str(t["product_id"]))
        if current:
            if str(current.get("sku")) != str(t["sku"]) or current.get("product_status_code") in {"declined", "rejected"}:
                raise RuntimeError(f"Initial Ozon binding conflicts for {t['offer_id']}")
        else:
            missing.append(t["sku"])
    bind_response = None
    if missing:
        bind_payload = {"certificate_id": int(cert_id), "skus": missing}
        bind_bytes = json.dumps(bind_payload, separators=(",", ":")).encode()
        append_journal({"phase": "prepared", "operation": "bind", "endpoint": "/v1/product/certificate/bind",
                        "document_number": number, "certificate_id": cert_id,
                        "request_sha256": hashlib.sha256(bind_bytes).hexdigest(), "skus": missing})
        bind_response = client.call("ozon", "/v1/product/certificate/bind", bind_payload, mutation=True)
        append_journal({"phase": "bind_response", "document_number": number, "certificate_id": cert_id,
                        "result": bind_response.get("result")})
        if bind_response.get("result") is not True:
            raise RuntimeError(f"Ozon did not confirm binding for {number}; reconcile before retry")
    # Read back once after the mutation; do not claim approval until Ozon reports it.
    bindings_after = client.ozon_bindings(cert_id)
    by_product_after = {str(b.get("product_id")): b for b in bindings_after}
    exact = []
    for t in targets:
        b = by_product_after.get(str(t["product_id"]))
        if not b or str(b.get("sku")) != str(t["sku"]) or b.get("product_status_code") in {"declined", "rejected"}:
            raise RuntimeError(f"Ozon exact binding is missing/conflicting for {t['offer_id']}")
        exact.append({"offer_id": t["offer_id"], "product_id": t["product_id"], "sku": t["sku"],
                      "status": b.get("product_status_code")})
    final_certs = list_certificates(client)
    recs = [c for c in final_certs if norm(c.get("certificate_number")) == norm(number)]
    if len(recs) != 1:
        raise RuntimeError(f"Expected one created Ozon record after upload for {number}, got {len(recs)}")
    record = recs[0]
    statuses = dict(Counter(x["status"] for x in exact))
    result = {"document_number": number, "certificate_id": cert_id, "record_status": record.get("status_code"),
              "type_code": record.get("type_code"), "accordance_type_code": record.get("accordance_type_code"),
              "issue_date": record.get("issue_date"), "expire_date": record.get("expire_date"),
              "target_count": len(targets), "exact_binding_count": len(exact), "binding_status_counts": statuses,
              "bindings": exact, "source_file": str(source), "source_sha256": pf["source_sha256"],
              "fsa_record_url": doc["fsa_url"], "create_param_states": states,
              "bind_response_confirmed": (bind_response or {}).get("result") is True}
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Upload after all live preflights pass")
    args = parser.parse_args()
    if OUT.exists() or JOURNAL.exists():
        raise RuntimeError("Execution/journal already exists; reconcile live Ozon state before rerunning")
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if not snapshot.get("ozon_products", {}).get("complete") or not snapshot.get("ozon_certificates", {}).get("complete"):
        raise RuntimeError("Complete Ozon baseline snapshot is required")
    assignments = __import__("csv").DictReader(ASSIGNMENTS.open(encoding="utf-8-sig", newline=""))
    assignments = list(assignments)
    source_groups = json.loads(REPORT.read_text(encoding="utf-8"))["candidate_source_groups"]
    client = Client()
    preflights = []
    for doc in DOCS:
        pf = preflight(client, doc, assignments, snapshot, source_groups)
        path = HERE / f"{doc['key']}_ozon_preflight_20261026.json"
        path.write_text(json.dumps(pf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        preflights.append((doc, pf))
    if not args.execute:
        print(json.dumps({"preflight_only": True, "eligible": [
            {"number": pf["document_number"], "targets": pf["target_count"], "sha256": pf["source_sha256"]}
            for _, pf in preflights]}, ensure_ascii=False))
        return
    results = []
    for doc, pf in preflights:
        results.append(process(client, doc, pf))
    output = {"checked_at_utc": now(), "complete": True, "platform": "Ozon", "documents": results,
              "local_source_files_deleted": False, "wb_changed": False}
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    append_journal({"phase": "all_documents_readback_complete", "documents": [
        {"number": r["document_number"], "record_status": r["record_status"],
         "binding_status_counts": r["binding_status_counts"]} for r in results]})
    print(json.dumps({"execution": str(OUT), "documents": [
        {"number": r["document_number"], "certificate_id": r["certificate_id"],
         "record_status": r["record_status"], "exact_bindings": r["exact_binding_count"],
         "binding_status_counts": r["binding_status_counts"]} for r in results]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
