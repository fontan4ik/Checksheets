#!/usr/bin/env python3
"""Prove the exact product-model scope of Navigator declaration 61378/25."""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
PREFLIGHT = HERE / "navigator_94200_halogens_preflight_20261022.json"
PDF = ROOT / "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_declaration_94200_d8d8454cac3f.pdf"
OUT = HERE / "navigator_94200_halogens_scope_proof_20261022.json"
PDF_SHA256 = "d8d8454cac3fddbd3251262303f3ee1e82118e31c23525e1ddc3b57f82eeaef4"
DOC_NUMBER = "ЕАЭС N RU Д-CN.РА11.В.61378/25"

# Navigator manufacturer's product codes and the model designations printed in
# the declaration. The model list is independently checked against the PDF.
MODEL_BY_CODE = {
    "94200": "NH-MR11-20-12-GU4",
    "94201": "NH-MR11-35-12-GU4",
    "94202": "NH-MR16-20-12-GU5.3",
    "94203": "NH-MR16-35-12-GU5.3",
    "94204": "NH-MR16-50-12-GU5.3",
    "94205": "NH-JCDR-35-230-GU5.3",
    "94206": "NH-JCDR-50-230-GU5.3",
    "94207": "NH-JCDR-75-230-GU5.3",
    "94208": "NH-JCDRC-50-230-GU10",
    "94209": "NH-JC-10-12-G4-CL",
    "94210": "NH-JC-20-12-G4-CL",
    "94212": "NH-JC-50-12-G6.35-CL",
    "94213": "NH-JCD-35-230-G6.35-CL",
    "94214": "NH-JCD-50-230-G6.35-CL",
    "94215": "NH-JCD9-40-230-G9-CL",
    "94216": "NH-JCD9-60-230-G9-CL",
    "94217": "NH-J78-100-230-R7s",
    "94218": "NH-J78-150-230-R7s",
    "94219": "NH-J117-150-230-R7s",
    "94220": "NH-J117-300-230-R7s",
    "94221": "NH-J117-500-230-R7s",
    "94222": "NH-J189-1000-230-R7s",
    "94223": "NH-MR11-35-230-GU5.3",
    "94225": "NH-JCDRC-35-230-GU10",
    "94232": "NH-JCD9-40-230-G9-FR",
    "94233": "NH-JCD9-60-230-G9-FR",
}


def fail(message: str) -> None:
    raise RuntimeError(message)


def main() -> None:
    if OUT.exists():
        fail("scope_proof_output_exists_inspect_first")
    if not PDF.is_file() or hashlib.sha256(PDF.read_bytes()).hexdigest() != PDF_SHA256:
        fail("declaration_pdf_missing_or_hash_mismatch")
    sys.path.insert(0, "/Users/vladimirgrebennikov/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/lib/python3.12/site-packages")
    from pypdf import PdfReader  # pylint: disable=import-outside-toplevel

    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(str(PDF)).pages)
    compact_pdf = re.sub(r"\s+", "", pdf_text).casefold()
    for required in (DOC_NUMBER, "8539219200", "12.12.2025", "11.12.2030"):
        if re.sub(r"\s+", "", required).casefold() not in compact_pdf:
            fail("declaration_pdf_required_text_missing:" + required)
    missing_models = [model for model in set(MODEL_BY_CODE.values())
                      if re.sub(r"\s+", "", model).casefold() not in compact_pdf]
    if missing_models:
        fail("declared_model_not_found_in_pdf:" + ",".join(sorted(missing_models)))

    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if pre.get("read_only") is not True or pre.get("target_count") != 45:
        fail("preflight_target_scope_changed")
    rows = {}
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if (row.get("Применимость") != "Подтверждено источником"
                    or row.get("Статус покрытия артикула") != "Есть официальный документ"
                    or row.get("Номер/название документа") != DOC_NUMBER):
                continue
            offer = str(row.get("Артикул продавца") or "").strip()
            if offer:
                rows[offer] = json.loads(row.get("Исходная запись JSON") or "{}")

    targets = []
    for target in pre["targets"]:
        offer = str(target.get("offer_id") or "")
        code = offer.split("-", 1)[0]
        expected_model = MODEL_BY_CODE.get(code)
        source = rows.get(offer)
        assignment = target.get("source_assignment_declaration") or {}
        search_result = str(assignment.get("official_search_result") or "")
        product_url = str(assignment.get("official_product_page_url") or "")
        if not expected_model or not source:
            fail("unmapped_or_unassigned_offer:" + offer)
        if (source.get("document_number") != DOC_NUMBER
                or source.get("document_status") != "Действует"
                or source.get("sha256") != PDF_SHA256
                or source.get("provider_exact_product_heading") != assignment.get("provider_exact_product_heading")
                or source.get("official_fsa_registry_url") != "https://pub.fsa.gov.ru/rds/declaration/view/20983684"):
            fail("source_assignment_evidence_conflict:" + offer)
        if not re.search(r"Код:\s*" + re.escape(code) + r"\b", search_result, flags=re.I):
            fail("manufacturer_product_code_not_in_search_evidence:" + offer)
        if not product_url.startswith("https://navigator-light.ru/"):
            fail("manufacturer_product_url_not_official:" + offer)
        targets.append({
            "offer_id": offer,
            "ozon_product_id": target.get("product_id"),
            "ozon_sku": target.get("sku"),
            "wb_nmID": target.get("wb_nmID"),
            "manufacturer_code": code,
            "manufacturer_model_title": assignment.get("provider_exact_product_heading"),
            "declaration_model": expected_model,
            "declaration_model_present_in_pdf": True,
            "official_product_page_url": product_url,
            "ozon_tnved": target.get("ozon_tnved"),
            "wb_tnved": target.get("wb_tnved"),
            "marketplace_tnved_differs_from_declaration": True,
        })
    if len(targets) != 45 or {x["manufacturer_code"] for x in targets} != set(MODEL_BY_CODE):
        fail("target_model_code_coverage_mismatch")
    result = {
        "checked_at_utc": pre.get("checked_at_utc"),
        "read_only": True,
        "declaration_number": DOC_NUMBER,
        "registry_url": "https://pub.fsa.gov.ru/rds/declaration/view/20983684/common",
        "declaration_pdf_sha256": PDF_SHA256,
        "declaration_valid_dates": ["2025-12-12", "2030-12-11"],
        "declaration_tnved": "8539219200",
        "declaration_has_explicit_model_list": True,
        "marketplace_tnved_discrepancy_retained_as_separate_issue": True,
        "target_count": len(targets),
        "distinct_exact_manufacturer_model_codes": len(MODEL_BY_CODE),
        "all_targets_exactly_map_to_model_in_declaration": True,
        "targets": sorted(targets, key=lambda x: x["offer_id"]),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in result if k != "targets"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
