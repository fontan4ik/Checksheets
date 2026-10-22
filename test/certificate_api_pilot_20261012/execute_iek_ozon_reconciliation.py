"""Safely bind verified IEK documents to current Ozon products or create missing docs."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from api_client import BASE, Client, digest, now, save
from group4_ozon import doc_identity

PLAN = BASE / "iek_new_offer_document_plan.json"
OCR = BASE / "iek_new_docs_ocr.json"
DOWNLOADS = BASE / "iek_new_docs_download_audit.json"
RUN = BASE / "iek_ozon_reconciliation_execution.json"
MAX_INFO_BATCH = 100
MAX_CREATE_REQUEST_BYTES = 15_000_000  # gRPC max is 15 MiB; retain margin for JSON framing.


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def exact_key(doc: dict) -> tuple[str, str]:
    return str(doc.get("type_code") or ""), doc_identity(doc.get("number") or doc.get("certificate_number") or "")


def iso_date(value: str) -> str:
    return str(value or "")[:10]


def verify_pdf_evidence(doc: dict, ocr_by_hash: dict[str, list[str]], download_by_hash: dict[str, dict]) -> None:
    url_hash = doc["source_url"].rsplit("/", 1)[-1].split(".", 1)[0].lower()
    local = BASE / "iek_new_docs" / f"{url_hash}.pdf"
    if not re.fullmatch(r"[0-9a-f]{64}", url_hash) or not local.is_file():
        raise RuntimeError(f"Missing content-addressed official IEK PDF: {doc['number']}")
    if digest(local).lower() != url_hash:
        raise RuntimeError(f"PDF SHA-256 differs from official URL: {doc['number']}")
    download = download_by_hash.get(url_hash)
    if not download or download.get("download_status") != "sha_verified":
        raise RuntimeError(f"Official PDF download audit is incomplete: {doc['number']}")
    pages = ocr_by_hash.get(url_hash, [])
    if not pages:
        raise RuntimeError(f"OCR pages missing for {doc['number']}")
    digit_signature = "".join(re.findall(r"\d+", doc["number"]))
    if not digit_signature or not any(digit_signature in "".join(re.findall(r"\d+", p)) for p in pages):
        raise RuntimeError(f"OCR did not confirm the printed registration number: {doc['number']}")
    for key in ("issue_date", "expire_date"):
        target = datetime.strptime(iso_date(doc[key]), "%Y-%m-%d").strftime("%d.%m.%Y")
        # OCR is used as an independent check where the date is printed. The official feed
        # remains the date source when a scanned page has a legible number but OCR misses a date.
        if target not in "\n".join(pages):
            doc.setdefault("ocr_date_not_found", []).append({key: target})


def upload_file_for_group(group: dict) -> tuple[Path, str | None]:
    url_hash = group["source_url"].rsplit("/", 1)[-1].split(".", 1)[0].lower()
    original = BASE / "iek_new_docs" / f"{url_hash}.pdf"
    if original.stat().st_size * 4 // 3 < MAX_CREATE_REQUEST_BYTES - 100_000:
        return original, None
    audit_path = BASE / "iek_large_pdf_optimization_audit.json"
    ocr_path = BASE / "iek_large_pdf_compressed_ocr.json"
    if not audit_path.is_file() or not ocr_path.is_file():
        raise RuntimeError(f"Oversized source PDF lacks a rendered/verified transport copy: {group['number']}")
    audit = read_json(audit_path)
    ocr = read_json(ocr_path)
    output = Path(audit.get("output", ""))
    digit_signature = "".join(re.findall(r"\d+", group["number"]))
    text = "\n".join(x.get("text", "") for x in ocr.get("pages", []))
    if (audit.get("source_sha256") != url_hash or audit.get("page_count") != 6 or
        ocr.get("page_count") != 6 or not output.is_file() or
        output.stat().st_size != audit.get("output_bytes") or
        digest(output) != audit.get("output_sha256") or digit_signature not in "".join(re.findall(r"\d+", text))):
        raise RuntimeError(f"Compressed Ozon upload copy did not pass source, page, hash, or OCR checks: {group['number']}")
    if output.stat().st_size * 4 // 3 >= MAX_CREATE_REQUEST_BYTES - 100_000:
        raise RuntimeError(f"Compressed upload copy still exceeds the verified Ozon request margin: {group['number']}")
    return output, audit["output_sha256"]


def make_groups(plan: dict) -> tuple[dict, dict]:
    existing: dict[int, dict] = {}
    creates: dict[tuple[str, str], dict] = {}
    for row in plan["document_assignments"]:
        action = row["ozon_outcome"]
        if action == "bind_existing_approved_record":
            proof = row.get("ozon_record_proof") or {}
            cert_id = int(proof.get("certificate_id") or 0)
            if not cert_id or proof.get("certificate_status") != "approved":
                raise RuntimeError(f"Missing approved Ozon proof for {row['number']}")
            item = existing.setdefault(cert_id, {"certificate_id": cert_id, "type_code": row["ozon_type_code"],
                "number": row["number"], "issue_date": iso_date(row["issue_date"]),
                "expire_date": iso_date(row["expire_date"]), "offers": {}})
            if (item["type_code"], item["number"], item["issue_date"], item["expire_date"]) != (
                    row["ozon_type_code"], row["number"], iso_date(row["issue_date"]), iso_date(row["expire_date"])):
                raise RuntimeError(f"Conflicting source metadata for Ozon certificate ID {cert_id}")
            item["offers"][row["offer_id"]] = {"product_id": str(row["product_id"]), "sku": str(row["sku"])}
        elif action == "new_upload_requires_pdf_validation":
            key = (row["ozon_type_code"], doc_identity(row["number"]))
            item = creates.setdefault(key, {"type_code": row["ozon_type_code"], "number": row["number"],
                "issue_date": iso_date(row["issue_date"]), "expire_date": iso_date(row["expire_date"]),
                "source_url": row["source_url"], "source_issuer": row.get("source_issuer"), "offers": {}})
            if (item["number"], item["issue_date"], item["expire_date"], item["source_url"]) != (
                    row["number"], iso_date(row["issue_date"]), iso_date(row["expire_date"]), row["source_url"]):
                raise RuntimeError(f"Conflicting official feed rows for {row['number']}")
            item["offers"][row["offer_id"]] = {"product_id": str(row["product_id"]), "sku": str(row["sku"])}
        elif action in {"already_approved_and_bound", "blocked_existing_product_pair_not_approved"}:
            continue
        else:
            raise RuntimeError(f"Unexpected Ozon outcome in selected IEK set: {action}")
    return existing, creates


def plan_only() -> dict:
    plan = read_json(PLAN)
    downloads = read_json(DOWNLOADS)
    ocr = read_json(OCR)
    if not all(read_json(path).get("complete") for path in (PLAN, OCR, DOWNLOADS)):
        # The IEK plan uses its summary as its completeness marker.
        if not plan.get("summary") or ocr.get("page_count") != len(ocr.get("pages", [])):
            raise RuntimeError("Complete source plan, download audit, and OCR evidence required")
    if downloads.get("official_feed_sha256") != plan.get("official_iek_feed_sha256"):
        raise RuntimeError("Official IEK XML changed since plan/download audit")
    ocr_by_hash: dict[str, list[str]] = defaultdict(list)
    for page in ocr.get("pages", []):
        match = re.match(r"([0-9a-f]{64})-", page.get("file", ""))
        if match:
            ocr_by_hash[match[1]].append(page.get("text", ""))
    download_by_hash = {str(x.get("sha256_actual") or "").lower(): x for x in downloads.get("documents", [])}
    existing, creates = make_groups(plan)
    for doc in creates.values():
        verify_pdf_evidence(doc, ocr_by_hash, download_by_hash)
    return {"source_assignments": len(plan["document_assignments"]), "existing_certificates_to_bind": len(existing),
            "existing_product_pairs": sum(len(x["offers"]) for x in existing.values()),
            "new_documents_to_create": len(creates), "new_product_pairs": sum(len(x["offers"]) for x in creates.values()),
            "pdfs_sha_and_ocr_verified": len(creates), "pdfs_with_ocr_date_gaps": sum(bool(x.get("ocr_date_not_found")) for x in creates.values()),
            "official_feed_sha256": plan.get("official_iek_feed_sha256"),
            "create_manifest": [{"number": x["number"], "offer_count": len(x["offers"]),
                                  "pdf_sha256": x["source_url"].rsplit("/", 1)[-1].split(".", 1)[0]}
                                for x in creates.values()]}


def list_certificates(client: Client) -> list[dict]:
    result = []
    page = 1
    while True:
        body = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})["result"]
        result.extend(body["certificates"])
        if page >= body["page_count"]:
            break
        page += 1
    if len({str(x.get("certificate_id")) for x in result}) != len(result):
        raise RuntimeError("Duplicate certificate IDs in current Ozon list")
    return result


def is_confirmed_grpc_size_rejection(result: dict) -> bool:
    request_sha = result.get("request_sha256")
    if not request_sha:
        return False
    log_path = BASE / "api_calls.jsonl"
    if not log_path.is_file():
        return False
    for line in log_path.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        body = event.get("body") or {}
        if (event.get("request_sha256") == request_sha and event.get("phase") == "response"
                and event.get("http_status") == 429 and body.get("code") == 8
                and "received message larger than max" in str(body.get("message", ""))
                and "15728640" in str(body.get("message", ""))):
            return True
    return False


def get_product_info(client: Client, offers: dict[str, dict]) -> dict[str, dict]:
    live = {}
    names = sorted(offers)
    for i in range(0, len(names), MAX_INFO_BATCH):
        batch = names[i:i + MAX_INFO_BATCH]
        body = client.call("ozon", "/v3/product/info/list", {"offer_id": batch})
        items = body.get("items") or []
        for item in items:
            if isinstance(item, dict) and item.get("offer_id"):
                live[str(item["offer_id"])] = item
    if set(live) != set(offers):
        raise RuntimeError(f"Fresh Ozon info returned {len(live)} of {len(offers)} expected offers")
    for offer, target in offers.items():
        row = live[offer]
        product_id = str(row.get("product_id") or row.get("id") or "")
        if product_id != str(target["product_id"]) or str(row.get("sku")) != str(target["sku"]) or row.get("is_archived"):
            raise RuntimeError(f"Current Ozon product/SKU identity changed for {offer}")
    return live


def validate_cert(cert: dict, group: dict) -> None:
    if (cert.get("type_code") != group["type_code"] or
        doc_identity(cert.get("certificate_number", "")) != doc_identity(group["number"]) or
        iso_date(cert.get("issue_date")) != group["issue_date"] or
        iso_date(cert.get("expire_date")) != group["expire_date"] or
        cert.get("accordance_type_code") != "EAEU"):
        raise RuntimeError(f"Live Ozon metadata mismatch for {group['number']}")


def bind_missing(client: Client, run: dict, cert: dict, group: dict) -> dict:
    if cert.get("status_code") != "approved":
        raise RuntimeError(f"Ozon certificate is not approved: {group['number']}")
    bindings = client.ozon_bindings(cert["certificate_id"])
    by_pair = {(str(x.get("sku")), str(x.get("product_id"))): x for x in bindings}
    expected = {(v["sku"], v["product_id"]): offer for offer, v in group["offers"].items()}
    missing = []
    for pair, offer in expected.items():
        current = by_pair.get(pair)
        if current is None:
            missing.append(pair)
    if missing:
        response = client.call("ozon", "/v1/product/certificate/bind", {
            "certificate_id": int(cert["certificate_id"]), "skus": sorted({sku for sku, _ in missing})}, mutation=True)
        if response.get("result") is not True:
            raise RuntimeError(f"Bind returned non-true result for {group['number']}")
    after = client.ozon_bindings(cert["certificate_id"])
    after_by_pair = {(str(x.get("sku")), str(x.get("product_id"))): x for x in after}
    absent = [expected[pair] for pair in expected if pair not in after_by_pair]
    if absent:
        raise RuntimeError(f"Binding accepted but readback misses {len(absent)} pairs for {group['number']}")
    status_counts = {status: sum(after_by_pair[pair].get("product_status_code") == status for pair in expected)
                     for status in sorted({str(after_by_pair[pair].get("product_status_code")) for pair in expected})}
    all_approved = len(status_counts) == 1 and status_counts.get("approved") == len(expected)
    return {"outcome": ("bound_and_verified" if missing else "already_bound_and_verified")
                        if all_approved else "bound_waiting_product_review",
            "certificate_id": cert["certificate_id"], "target_pairs": len(expected),
            "newly_bound_pairs": len(missing), "approved_pairs": sum(
                after_by_pair[pair].get("product_status_code") == "approved" for pair in expected),
            "binding_status_counts": status_counts}


def run_execute(resume: bool = False) -> None:
    summary = plan_only()
    plan = read_json(PLAN)
    existing, creates = make_groups(plan)
    all_offers: dict[str, dict] = {}
    for group in list(existing.values()) + list(creates.values()):
        for offer, value in group["offers"].items():
            if offer in all_offers and all_offers[offer] != value:
                raise RuntimeError(f"Conflicting live product identity for {offer}")
            all_offers[offer] = value

    if RUN.exists():
        if not resume:
            raise RuntimeError(f"Execution journal already exists; use --resume only after reviewing it: {RUN}")
        run = read_json(RUN)
        if run.get("complete"):
            raise RuntimeError("Ozon reconciliation is already marked complete")
        for item in run.get("results", []):
            if (item.get("outcome") not in {"bound_and_verified", "already_bound_and_verified"}
                    and not (item.get("outcome") == "uncertain_create" and is_confirmed_grpc_size_rejection(item))
                    and not (item.get("outcome") == "size_rejection_reconciled_no_live_record"
                             and is_confirmed_grpc_size_rejection(item))
                    and item.get("outcome") != "blocked_live_metadata_conflict"
                    and not (item.get("outcome") == "created_needs_binding_reconciliation"
                             and item.get("response_status") == "COMPLETED" and item.get("response_certificate_id"))
                    and item.get("outcome") != "bound_waiting_product_review"
                    and not (item.get("outcome") is None and item.get("phase") == "creating"
                             and item.get("response_status") == "COMPLETED" and item.get("response_certificate_id"))):
                raise RuntimeError(f"Cannot resume after non-verified result: {item.get('number')}")
    else:
        if resume:
            raise RuntimeError("--resume requires an existing execution journal")
        run = {"started_at": now(), "source_summary": summary, "results": [], "complete": False}
        save(RUN.name, run)
    client = Client()
    get_product_info(client, all_offers)
    fresh_certs = list_certificates(client)
    by_id = {str(x["certificate_id"]): x for x in fresh_certs}
    by_identity: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for cert in fresh_certs:
        by_identity[exact_key(cert)].append(cert)

    # Existing approved records can be safely extended. Each call is journaled and verified.
    for cert_id, group in existing.items():
        completed = next((x for x in run["results"] if str(x.get("certificate_id")) == str(cert_id)
                          and x.get("outcome") == "bound_and_verified"), None)
        if completed:
            continue
        cert = by_id.get(str(cert_id))
        if not cert:
            raise RuntimeError(f"Approved Ozon certificate disappeared: {group['number']}")
        validate_cert(cert, group)
        entry = {"number": group["number"], "certificate_id": cert_id, "phase": "binding_existing"}
        run["results"].append(entry); save(RUN.name, run)
        try:
            entry.update(bind_missing(client, run, cert, group))
        except Exception as exc:
            entry.update({"outcome": "needs_manual_reconciliation", "error_type": type(exc).__name__})
            save(RUN.name, run)
            raise
        save(RUN.name, run)

    for key, group in creates.items():
        completed = next((x for x in run["results"] if x.get("number") == group["number"]
                          and x.get("outcome") in {"bound_and_verified", "already_bound_and_verified"}), None)
        if completed:
            continue
        matches = by_identity.get(key, [])
        previous_uncertain = next((x for x in run["results"] if x.get("number") == group["number"]
                                   and x.get("outcome") == "uncertain_create"), None)
        previous_completed = next((x for x in run["results"] if x.get("number") == group["number"]
                                   and x.get("outcome") in (None, "created_needs_binding_reconciliation",
                                                             "bound_waiting_product_review")
                                   and x.get("response_status") == "COMPLETED"
                                   and x.get("response_certificate_id")), None)
        if previous_uncertain and not is_confirmed_grpc_size_rejection(previous_uncertain):
            raise RuntimeError(f"Uncertain prior Ozon create has no confirmed size rejection: {group['number']}")
        if len(matches) > 1:
            raise RuntimeError(f"Multiple live Ozon records match {group['number']}; refusing create")
        if matches:
            cert = matches[0]
            try:
                validate_cert(cert, group)
            except RuntimeError:
                conflict = {"source_metadata": {"type_code": group["type_code"], "number": group["number"],
                             "issue_date": group["issue_date"], "expire_date": group["expire_date"],
                             "accordance_type_code": "EAEU"},
                            "live_metadata": {k: cert.get(k) for k in ("certificate_id", "certificate_number",
                             "type_code", "issue_date", "expire_date", "accordance_type_code", "status_code")}}
                target = previous_completed or {"number": group["number"], "phase": "fresh_live_record_conflict"}
                if target not in run["results"]:
                    run["results"].append(target)
                target.update({"outcome": "blocked_live_metadata_conflict", "reconciled_at": now(), **conflict})
                save(RUN.name, run)
                continue
            if previous_completed:
                if str(previous_completed.get("response_certificate_id")) != str(cert["certificate_id"]):
                    raise RuntimeError(f"Ozon create response ID differs from live matching record: {group['number']}")
                try:
                    previous_completed.update({"phase": "create_readback_verified", "live_status": cert.get("status_code")})
                    previous_completed.update(bind_missing(client, run, cert, group))
                except Exception as exc:
                    previous_completed.update({"outcome": "created_needs_binding_reconciliation",
                                               "error_type": type(exc).__name__})
                    save(RUN.name, run)
                    raise
                save(RUN.name, run)
                continue
            if previous_uncertain:
                previous_uncertain.update({"outcome": "size_rejection_reconciled_live_record_found",
                                           "reconciled_at": now(), "live_certificate_id": cert["certificate_id"]})
                save(RUN.name, run)
            entry = {"number": group["number"], "certificate_id": cert["certificate_id"],
                     "phase": "fresh_record_found_instead_of_create"}
            run["results"].append(entry); save(RUN.name, run)
            try:
                entry.update(bind_missing(client, run, cert, group))
            except Exception as exc:
                entry.update({"outcome": "needs_manual_reconciliation", "error_type": type(exc).__name__})
                save(RUN.name, run)
                raise
            save(RUN.name, run)
            continue
        if previous_completed:
            previous_completed.update({"outcome": "completed_create_missing_from_live_list",
                                       "reconciled_at": now()})
            save(RUN.name, run)
            continue
        if previous_uncertain:
            previous_uncertain.update({"outcome": "size_rejection_reconciled_no_live_record",
                                       "reconciled_at": now()})
            save(RUN.name, run)

        url_hash = group["source_url"].rsplit("/", 1)[-1].split(".", 1)[0]
        path, derivative_sha = upload_file_for_group(group)
        start = datetime.strptime(group["issue_date"], "%Y-%m-%d")
        end = datetime.strptime(group["expire_date"], "%Y-%m-%d")
        doc_type = "DECLARATION" if group["type_code"] == "declaration" else "CERTIFICATE_OF_CONFORMITY"
        prefix = "Декларация о соответствии № " if doc_type == "DECLARATION" else "Сертификат соответствия № "
        params = {"name": prefix + group["number"], "certificate_type": doc_type,
                  "certificate_country": "RU", "accordance_type": "EAEU", "number": group["number"],
                  "issue_date": start.strftime("%Y-%m-%dT00:00:00Z"),
                  "expired_date": {"date": {"day": end.day, "month": end.month, "year": end.year}},
                  "skus": sorted({v["sku"] for v in group["offers"].values()}), "product_type": "UNKNOWN",
                  "files": [{"file_content": base64.b64encode(path.read_bytes()).decode("ascii"), "name": path.name}]}
        body_bytes = json.dumps({"params": params}, ensure_ascii=False, separators=(",", ":")).encode()
        # Ozon's observed gRPC maximum is 15 MiB; stay below it with framing margin.
        if len(body_bytes) >= MAX_CREATE_REQUEST_BYTES:
            raise RuntimeError(f"Ozon gRPC request would exceed 15 MiB: {group['number']}")
        entry = {"number": group["number"], "offer_count": len(group["offers"]),
                 "target_sku_count": len(params["skus"]), "pdf_sha256": digest(path),
                 "official_source_pdf_sha256": url_hash, "upload_derivative_used": bool(derivative_sha),
                 "phase": "creating", "request_sha256": hashlib.sha256(body_bytes).hexdigest(),
                 "request_bytes": len(body_bytes)}
        run["results"].append(entry); save(RUN.name, run)
        try:
            response = client.call("ozon", "/v2/product/certificate/create", {"params": params}, mutation=True)
        except Exception as exc:
            entry.update({"outcome": "uncertain_create", "error_type": type(exc).__name__})
            save(RUN.name, run)
            raise
        entry["response_status"] = response.get("status")
        entry["response_certificate_id"] = response.get("certificate_id")
        entry["invalid_params"] = [x for x in response.get("params", []) if x.get("state") == "INVALID"]
        if response.get("status") != "COMPLETED" or not response.get("certificate_id") or entry["invalid_params"]:
            entry["outcome"] = "create_incomplete_do_not_retry"
            save(RUN.name, run)
            raise RuntimeError(f"Ozon create incomplete for {group['number']}; reconcile live state first")
        save(RUN.name, run)

        certs_after = list_certificates(client)
        after_matches = [c for c in certs_after if exact_key(c) == key]
        if len(after_matches) != 1:
            entry.update({"outcome": "create_needs_reconciliation", "matching_live_records": len(after_matches)})
            save(RUN.name, run)
            raise RuntimeError(f"Created certificate not unique in live list: {group['number']}")
        cert = after_matches[0]
        validate_cert(cert, group)
        entry["live_status"] = cert.get("status_code")
        entry["certificate_id"] = cert["certificate_id"]
        try:
            entry.update(bind_missing(client, run, cert, group))
        except Exception as exc:
            entry.update({"outcome": "created_needs_binding_reconciliation", "error_type": type(exc).__name__})
            save(RUN.name, run)
            raise
        save(RUN.name, run)

    run["completed_at"] = now()
    run["complete"] = True
    save(RUN.name, run)
    print(json.dumps({"complete": True, "summary": summary,
                      "outcomes": {x.get("outcome"): sum(y.get("outcome") == x.get("outcome") for y in run["results"])
                                   for x in run["results"]},
                      "journal": str(RUN)}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Perform Ozon binds and certificate creates")
    parser.add_argument("--resume", action="store_true", help="Continue only after a fully verified prior journal")
    args = parser.parse_args()
    if args.resume and not args.execute:
        parser.error("--resume requires --execute")
    if not args.execute:
        print(json.dumps(plan_only(), ensure_ascii=False, indent=2))
    else:
        run_execute(resume=args.resume)


if __name__ == "__main__":
    main()
