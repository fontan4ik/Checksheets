#!/usr/bin/env python3
"""Delete Gauss 00069/22 sources only after exact cross-market readback."""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from run_all_found_certificates_20261014 import norm_number  # noqa: E402

SNAPSHOT = HERE / "live_marketplaces_snapshot_allbrand_postreconcile_final_20261023.json"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
RESULT = HERE / "gauss_00069_confirmed_source_files_deleted_20261023.json"
JOURNAL = HERE / "confirmed_local_source_deletion_journal_20261023.jsonl"
NUMBER = "ЕАЭС RU С-CN.НВ12.В.00069/22"
SHA = "2e0c5dd4cc303a1ca6a5895f461ddf4d95acf2e30457d0a0e5ae515b97c61461"
ISSUE = "2022-08-24"
EXPIRE = "2027-08-23"


def digest(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    if RESULT.exists():
        raise RuntimeError("cleanup_result_already_exists_inspect_before_retry")
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if snapshot.get("complete") is not True:
        raise RuntimeError("complete_live_snapshot_required")
    checked_at = snapshot["wb_catalog"].get("checked_at")
    key = norm_number(NUMBER)

    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as f:
        all_rows = list(csv.DictReader(f))
    rows = [r for r in all_rows if norm_number(r.get("Номер/название документа")) == key
            and r.get("Применимость") in ("Подтверждено статусом покрытия", "Подтверждено источником")]
    offers = {str(r.get("Артикул продавца") or "") for r in rows if r.get("Артикул продавца")}
    if len(rows) != 526 or len(offers) != 526 or {r.get("Бренд подтвержденный") for r in rows} != {"Gauss"}:
        raise RuntimeError("confirmed_assignment_scope_changed")

    products_by_offer: dict[str, list[dict]] = {}
    for p in snapshot["ozon_products"]["products"]:
        products_by_offer.setdefault(str(p.get("offer_id") or ""), []).append(p)
    certificates = [c for c in snapshot["ozon_certificates"]["certificates"]
                    if norm_number(c.get("certificate_number")) == key
                    and c.get("type_code") == "certificate_of_conformity"
                    and c.get("accordance_type_code") == "EAEU"
                    and str(c.get("issue_date") or "")[:10] == ISSUE
                    and str(c.get("expire_date") or "")[:10] == EXPIRE
                    and c.get("status_code") == "approved"]
    if len(certificates) != 5:
        raise RuntimeError("exact_approved_ozon_records_not_five")
    bindings = {}
    all_binding_count = 0
    for cert in certificates:
        cert_bindings = cert.get("live_bindings") or []
        if any(x.get("product_status_code") != "approved" for x in cert_bindings):
            raise RuntimeError("an_ozon_record_binding_is_not_approved")
        all_binding_count += len(cert_bindings)
        for binding in cert_bindings:
            bindings[(str(binding.get("product_id")), str(binding.get("sku")))] = True
    if all_binding_count != 534:
        raise RuntimeError("unexpected_total_ozon_binding_count")

    wb_by_offer: dict[str, list[dict]] = {}
    for card in snapshot["wb_catalog"]["cards"]:
        wb_by_offer.setdefault(str(card.get("vendorCode") or ""), []).append(card)

    for offer in sorted(offers):
        product_rows = products_by_offer.get(offer, [])
        if len(product_rows) != 1:
            raise RuntimeError("ozon_offer_missing_or_ambiguous:" + offer)
        product = product_rows[0]
        if (product.get("is_archived") is not False or
                (str(product.get("product_id")), str(product.get("sku"))) not in bindings):
            raise RuntimeError("ozon_exact_approved_binding_missing:" + offer)

        card_rows = wb_by_offer.get(offer, [])
        if len(card_rows) != 1 or str(card_rows[0].get("brand") or "").casefold() != "gauss":
            raise RuntimeError("wb_card_missing_duplicate_or_brand_mismatch:" + offer)
        docs = [d for d in ((card_rows[0].get("documents") or {}).get("items") or [])
                if norm_number(d.get("number")) == key and d.get("type") == 1
                and str(d.get("startDate") or "")[:10] == ISSUE
                and str(d.get("endDate") or "")[:10] == EXPIRE]
        if not any((d.get("verdict") or {}).get("verified") is True
                   and (d.get("verdict") or {}).get("status") == 1
                   and (d.get("verdict") or {}).get("reason") == "valid" for d in docs):
            raise RuntimeError("wb_exact_valid_document_missing:" + offer)

    source_root = (ROOT / "output_to_user/certificates").resolve()
    source_paths = set()
    for row in rows:
        if row.get("SHA256 фактический") != SHA and row.get("SHA256 заявленный") != SHA:
            raise RuntimeError("assignment_source_hash_mismatch")
        rel = str(row.get("Локальный файл") or "").strip()
        if not rel:
            raise RuntimeError("assignment_source_path_missing")
        path = pathlib.Path(rel)
        path = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
        if not path.is_relative_to(source_root):
            raise RuntimeError("source_path_outside_certificate_library")
        source_paths.add(path)
    if len(source_paths) != 2:
        raise RuntimeError("expected_two_local_source_copies")

    removed = []
    for path in sorted(source_paths):
        if not path.is_file() or path.suffix.casefold() != ".pdf" or digest(path) != SHA:
            raise RuntimeError("source_missing_or_hash_changed:" + str(path))
        removed.append({"path": str(path), "sha256": SHA, "bytes": path.stat().st_size})
    # Recheck hashes immediately before removal, after all marketplace checks.
    for row in removed:
        path = pathlib.Path(row["path"])
        if digest(path) != SHA:
            raise RuntimeError("source_changed_immediately_before_unlink")
    for row in removed:
        pathlib.Path(row["path"]).unlink()
    remaining = [row["path"] for row in removed if pathlib.Path(row["path"]).exists()]
    if remaining:
        raise RuntimeError("source_files_remain_after_unlink")

    result = {
        "deleted_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "marketplace_snapshot_checked_at_utc": checked_at,
        "document_number": NUMBER,
        "confirmed_assignment_rows": len(rows),
        "unique_target_offers": len(offers),
        "ozon_approved_exact_target_offers": len(offers),
        "ozon_exact_approved_record_ids": [x.get("certificate_id") for x in certificates],
        "ozon_all_record_bindings_approved": all_binding_count,
        "wb_exact_valid_target_offers": len(offers),
        "source_sha256": SHA,
        "removed_files": removed,
        "freed_bytes": sum(x["bytes"] for x in removed),
        "remaining_matching_source_paths": remaining,
        "wb_review_left_pending": True,
    }
    tmp = RESULT.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(RESULT)
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")
        f.flush()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
