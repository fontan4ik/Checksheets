#!/usr/bin/env python3
"""Fresh read-only cross-platform verification before Navigator source cleanup."""
from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
from execute_navigator_nll_08110_06643_20261022 import list_certificates  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import copy_documents, doc_key, norm_number  # noqa: E402

PREFLIGHT = HERE / "navigator_nll_08110_06643_fresh_preflight_20261022.json"
EXTRA_PREFLIGHT = HERE / "navigator_93812_two_docs_live_preflight_20261023.json"
OUT = HERE / "navigator_nll_08110_06643_live_crossplatform_recheck_20261023.json"

DOCS = {
    "declaration": {
        "number": "ЕАЭС N RU Д-CN.РА11.В.08110/24",
        "certificate_id": 5945402,
        "wb_type": 2,
        "startDate": "2024-12-02T00:00:00Z",
        "endDate": "2029-12-01T00:00:00Z",
        "path": ROOT / "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_declaration_14008_6281784d69c8.pdf",
        "sha256": "6281784d69c80c6fb396c095d4fafef82fad9771694f8b74510a7fafc2846fd2",
    },
    "certificate": {
        "number": "ЕАЭС RU С-CN.НВ54.В.06643/24",
        "certificate_id": 5945406,
        "wb_type": 1,
        "startDate": "2024-12-04T00:00:00Z",
        "endDate": "2029-12-03T00:00:00Z",
        "path": ROOT / "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_eac_certificate_14008_c86b71122269.pdf",
        "sha256": "c86b711222697c5131ad96022e0e9d91b5127c0ed60e68bd1995016de2289c38",
    },
}


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def expected_map(rows: list[dict], wb_rows: dict[str, dict] | None = None) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        offer = str(row["offer_id"])
        if offer in result:
            raise RuntimeError("duplicate_expected_offer:" + offer)
        result[offer] = {
            "product_id": str(row["product_id"]),
            "sku": str(row["sku"]),
            "nmID": str(row.get("wb_nmID") or (wb_rows or {}).get(offer, {}).get("nmID") or ""),
        }
    return result


def ozon_check(client: Client, key: str, record: dict, expected: dict[str, dict[str, str]]) -> dict:
    doc = DOCS[key]
    if int(record.get("certificate_id") or 0) != doc["certificate_id"]:
        raise RuntimeError("unexpected_certificate_id:" + key)
    bindings = client.ozon_bindings(doc["certificate_id"])
    by_pid: dict[str, list[dict]] = collections.defaultdict(list)
    for row in bindings:
        by_pid[str(row.get("product_id") or "")].append(row)
    expected_rows = []
    failures = []
    expected_pids = {v["product_id"]: (offer, v["sku"]) for offer, v in expected.items()}
    for pid, (offer, sku) in expected_pids.items():
        rows = by_pid.get(pid, [])
        exact = [x for x in rows if str(x.get("sku") or "") == sku]
        statuses = [str(x.get("product_status_code") or "") for x in exact]
        if len(exact) != 1 or statuses != ["approved"]:
            failures.append({"offer_id": offer, "product_id": pid, "exact_count": len(exact), "statuses": statuses})
        expected_rows.append({"offer_id": offer, "product_id": pid, "sku": sku,
                              "exact_count": len(exact), "statuses": statuses})
    unexpected = []
    for pid, rows in by_pid.items():
        match = expected_pids.get(pid)
        if match is None:
            unexpected.append({"product_id": pid, "skus": [str(x.get("sku") or "") for x in rows],
                               "statuses": [str(x.get("product_status_code") or "") for x in rows]})
        elif any(str(x.get("sku") or "") != match[1] for x in rows):
            unexpected.append({"product_id": pid, "expected_offer_id": match[0],
                               "skus": [str(x.get("sku") or "") for x in rows]})
    return {
        "number": doc["number"], "certificate_id": doc["certificate_id"],
        "record_status": str(record.get("status_code") or ""),
        "binding_rows": len(bindings), "expected_exact_pairs": len(expected),
        "status_counts": dict(collections.Counter(str(x.get("product_status_code") or "") for x in bindings)),
        "expected_pairs": expected_rows, "unexpected_bindings": unexpected,
        "failures": failures,
        "complete": record.get("status_code") == "approved" and not failures and not unexpected,
    }


def wb_check(client: Client, key: str, expected: dict[str, dict[str, str]]) -> dict:
    doc = DOCS[key]
    wanted = {"type": doc["wb_type"], "number": doc["number"],
              "startDate": doc["startDate"], "endDate": doc["endDate"], "isEndless": False}
    rows, failures = [], []
    status_counts: collections.Counter[str] = collections.Counter()
    for offer, identity in expected.items():
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            failures.append({"offer_id": offer, "problem": "card_count", "count": len(cards)})
            continue
        card = cards[0]
        if (str(card.get("vendorCode")) != offer or str(card.get("nmID")) != identity["nmID"]
                or str(card.get("brand") or "").strip().casefold() != "navigator"):
            failures.append({"offer_id": offer, "problem": "identity_mismatch", "nmID": str(card.get("nmID"))})
        docs = copy_documents(card)
        same = [x for x in docs if norm_number(x.get("number")) == norm_number(doc["number"])]
        exact = [x for x in same if doc_key(x) == doc_key(wanted)
                 and str(x.get("startDate", ""))[:10] == doc["startDate"][:10]
                 and str(x.get("endDate", ""))[:10] == doc["endDate"][:10]
                 and x.get("isEndless") is False]
        verdicts = [x.get("verdict") for x in exact]
        statuses = ["valid" if isinstance(v, dict) and v.get("verified") is True and v.get("reason") == "valid"
                    else "pending_or_invalid" for v in verdicts]
        status_counts.update(statuses)
        if len(same) != 1 or len(exact) != 1 or statuses != ["valid"]:
            failures.append({"offer_id": offer, "problem": "document_not_exactly_valid",
                             "same_number_count": len(same), "exact_count": len(exact), "statuses": statuses})
        rows.append({"offer_id": offer, "nmID": str(card.get("nmID")),
                     "exact_count": len(exact), "status": statuses[0] if len(statuses) == 1 else "missing_or_duplicate"})
    return {"number": doc["number"], "target_cards": len(expected), "verified_exact_valid_cards": sum(x["exact_count"] == 1 and x["status"] == "valid" for x in rows),
            "status_counts": dict(status_counts), "failures": failures, "cards": rows,
            "complete": len(rows) == len(expected) and not failures}


def main() -> None:
    pre = json.loads(PREFLIGHT.read_text())
    extra = json.loads(EXTRA_PREFLIGHT.read_text())
    base_targets = [x for x in pre["targets"] if x.get("wb_eligible") and x.get("ozon_eligible")]
    if len(base_targets) != 56:
        raise RuntimeError("unexpected_eligible_base_target_count")
    base = expected_map(base_targets)
    extra_targets = expected_map(extra["targets"], extra["wb"])
    if set(extra_targets) != {"93812-10", "93812-5"}:
        raise RuntimeError("unexpected_navigator_93812_targets")
    ozon_expected = dict(base)
    ozon_expected.update(extra_targets)
    wb_decl_expected = dict(base)
    wb_decl_expected.update(extra_targets)
    wb_cert_expected = dict(base)

    client = Client()
    records = list_certificates(client)
    record_by_number: dict[str, list[dict]] = collections.defaultdict(list)
    for row in records:
        record_by_number[str(row.get("certificate_number") or "")].append(row)
    ozon = {}
    for key, doc in DOCS.items():
        matches = record_by_number.get(doc["number"], [])
        if len(matches) != 1:
            raise RuntimeError("ozon_record_count_conflict:" + key + ":" + str(len(matches)))
        expected = ozon_expected if key == "declaration" else base
        ozon[key] = ozon_check(client, key, matches[0], expected)

    wb = {
        "declaration": wb_check(client, "declaration", wb_decl_expected),
        "certificate": wb_check(client, "certificate", wb_cert_expected),
    }
    local = []
    for key, doc in DOCS.items():
        path = doc["path"]
        actual = sha256(path) if path.is_file() else None
        local.append({"document_key": key, "path": str(path), "exists": path.is_file(),
                      "expected_sha256": doc["sha256"], "actual_sha256": actual,
                      "sha256_matches": actual == doc["sha256"],
                      "size_bytes": path.stat().st_size if path.is_file() else None})
    complete = all(x["complete"] for x in ozon.values()) and all(x["complete"] for x in wb.values()) and all(x["sha256_matches"] for x in local)
    report = {"checked_at_utc": now(), "read_only": True,
              "scope": {"base_targets": 56, "extra_declaration_targets": 2,
                        "ozon_declaration_expected": 58, "ozon_certificate_expected": 56,
                        "wb_declaration_expected": 58, "wb_certificate_expected": 56,
                        "ozon_mismatched_tnved_targets_skipped": 97},
              "ozon": ozon, "wb": wb, "local_sources": local,
              "complete_for_verified_in_scope_targets": complete,
              "local_source_files_deleted": False}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"checked_at_utc": report["checked_at_utc"], "complete": complete,
                      "ozon": {k: {"record_status": v["record_status"], "binding_rows": v["binding_rows"],
                                   "expected_exact_pairs": v["expected_exact_pairs"],
                                   "status_counts": v["status_counts"], "failures": len(v["failures"]),
                                   "unexpected": len(v["unexpected_bindings"])} for k, v in ozon.items()},
                      "wb": {k: {"target_cards": v["target_cards"], "exact_valid": v["verified_exact_valid_cards"],
                                 "status_counts": v["status_counts"], "failures": len(v["failures"])} for k, v in wb.items()},
                      "local_source_sha256_matches": all(x["sha256_matches"] for x in local),
                      "report": str(OUT)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
