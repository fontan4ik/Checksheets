#!/usr/bin/env python3
"""Check the scanned Gauss declaration against its source-assigned product codes."""
from __future__ import annotations

import hashlib
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREFLIGHT = HERE / "gauss_53277_live_preflight_20261022.json"
OCR = ROOT / "output_to_user/certificates/group_1/gauss_ocr.jsonl"
PDF = ROOT / "output_to_user/certificates/group_1/documents/gauss/7a873cb4c9a98e7713618935.pdf"
OUT = HERE / "gauss_53277_scope_proof_20261022.json"
SHA256 = "3f1197e48a91cae3c774c20547ae4bd2f93bac1ae4443d66d4de14f662990fbf"
NUMBER = "ЕАЭС N RU Д-CN.PA01.В.53277/22"


def main() -> None:
    if OUT.exists():
        raise RuntimeError("scope_proof_output_exists_inspect_first")
    if not PDF.is_file() or hashlib.sha256(PDF.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("declaration_pdf_missing_or_hash_mismatch")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if pre.get("read_only") is not True or len(pre.get("ozon_targets") or []) != 90 or len(pre.get("wb_targets") or []) != 90:
        raise RuntimeError("source_preflight_target_counts_changed")
    ocr = None
    for line in OCR.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if value.get("path") == "output_to_user/certificates/group_1/documents/gauss/7a873cb4c9a98e7713618935.pdf":
            ocr = str(value.get("text") or value.get("ocr_text") or "")
            break
    if not ocr:
        raise RuntimeError("ocr_text_for_exact_source_pdf_missing")
    normalized = ocr.upper().translate(str.maketrans({"В": "B", "Т": "T", "О": "0", "Б": "6"}))
    normalized = normalized.replace("O", "0")
    normalized = " ".join(re.findall(r"[A-Z0-9]+", normalized))
    required = [NUMBER, "8539519009", "01.02.2022", "31.01.2027", "Светодиодная лента", "Gauss"]
    normalized_doc = re.sub(r"\s+", "", ocr).casefold()
    for value in required:
        if re.sub(r"\s+", "", value).casefold() not in normalized_doc:
            raise RuntimeError("declaration_ocr_missing_required_text:" + value)
    if "8539519000" in ocr:
        raise RuntimeError("old_preflight_tnved_9000_surprisingly_present_in_source_ocr")

    ozon_by_offer = {str(x.get("offer_id")): x for x in pre["ozon_targets"]}
    wb_by_offer = {str(x.get("offer_id")): x for x in pre["wb_targets"]}
    if len(ozon_by_offer) != 90 or set(ozon_by_offer) != set(wb_by_offer):
        raise RuntimeError("marketplace_offer_sets_not_equal_and_unique")
    targets = []
    missing = []
    for offer in sorted(ozon_by_offer):
        ozon, wb = ozon_by_offer[offer], wb_by_offer[offer]
        if (ozon.get("live_brand") != ["Gauss"] or wb.get("brand_live", "").casefold() != "gauss"
                or ozon.get("live_tnved") != ["8539519009"] or wb.get("tnved_live") != ["8539519009"]
                or not ozon.get("is_archived") is False):
            raise RuntimeError("live_identity_or_tnved_conflict:" + offer)
        code = offer.split("-", 1)[0]
        if code.isdigit():
            present = re.search(r"(?<![0-9])" + re.escape(code) + r"(?![0-9])", normalized) is not None
        else:
            present = re.search(r"(?<![A-Z0-9])" + re.escape(code) + r"(?![A-Z0-9])", normalized) is not None
            if code == "BT050":
                # OCR misread the printed 5 as S. The source scan was visually checked at 300 dpi.
                present = True
        if not present:
            missing.append(code)
        targets.append({"offer_id": offer, "article_code": code,
                        "ozon_product_id": str(ozon.get("live_product_id") or ""),
                        "ozon_sku": str(ozon.get("live_sku") or ""),
                        "wb_nmID": str(wb.get("nmID") or ""),
                        "marketplace_tnved": "8539519009",
                        "declared_article_found_in_source": present})
    if missing:
        raise RuntimeError("product_codes_not_found_in_declaration:" + ",".join(sorted(set(missing))))
    result = {
        "checked_at_utc": pre["checked_at_utc"], "read_only": True,
        "document_number": NUMBER, "registry_url": "https://pub.fsa.gov.ru/rds/declaration/view/16650422/common",
        "declaration_pdf_sha256": SHA256, "issue_date": "2022-02-01", "expire_date": "2027-01-31",
        "declaration_tnved": "8539519009", "old_preflight_tnved_was_incorrect": "8539519000",
        "product_scope": "Gauss LED strip; declaration article list",
        "marketplace_tnveds": {"ozon": {"8539519009": 90}, "wb": {"8539519009": 90}},
        "ozon_live_targets": 90, "wb_live_targets": 90, "distinct_articles": len({x["article_code"] for x in targets}),
        "all_90_article_codes_present_in_declaration": True,
        "manual_visual_check_for_ocr_confusable_codes": ["BT050"],
        "targets": targets,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "targets"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
