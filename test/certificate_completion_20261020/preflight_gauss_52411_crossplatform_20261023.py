#!/usr/bin/env python3
"""Fresh read-only exact-scope preflight for Gauss declaration 52411/23."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402
from apply_arlight_52132_wb_20261020 import code_values  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА04.В.52411/23"
SOURCE_REL = "output_to_user/certificates/group_1/documents/gauss/25aeb2f93ed587f14b19dc21.pdf"
SOURCE = ROOT / SOURCE_REL
SOURCE_SHA = "b9503157b344ec2ed68fe168f8b7c9f7046d28a1e7734b8a9949589c5b12ad3d"
SOURCE_RELS = {
    SOURCE_REL,
    "output_to_user/certificates/additional_search/brand_research/gauss/docs/gfl_rechargeable_037.pdf",
}
ISSUE = "2023-06-08"
EXPIRY = "2028-06-07"
ALLOWED_TNVED = {"8513100000"}
FSA_ID = "17768504"
FSA_URL = "https://pub.fsa.gov.ru/rds/declaration/view/17768504/product"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
LIVE_ASSIGNMENTS = HERE / "all_confirmed_source_assignments_live_reconciled_20261023.csv"
OCR = HERE / "gauss_52411_ocr_20261023.txt"
OUT = HERE / "gauss_52411_crossplatform_preflight_20261023.json"


def norm_article(value: object) -> str:
    table = str.maketrans({"Р": "P", "р": "P", "А": "A", "а": "A", "В": "B", "в": "B",
                           "С": "C", "с": "C", "Е": "E", "е": "E", "Н": "H", "н": "H",
                           "К": "K", "к": "K", "М": "M", "м": "M", "О": "O", "о": "O",
                           "Т": "T", "т": "T", "Х": "X", "х": "X"})
    return re.sub(r"[^A-Z0-9]", "", str(value).upper().translate(table))


def attr_values(row: dict, attr_id: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(v.get("value") or "").strip()
            for v in (attrs.get(str(attr_id)) or {}).get("values") or []
            if str(v.get("value") or "").strip()]


def live_certificate_list(client: Client) -> list[dict]:
    rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_invalid")
        rows.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("ozon_certificate_list_page_limit")


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_exists_inspect_first")
    if not SOURCE.is_file() or not OCR.is_file():
        raise RuntimeError("source_or_ocr_missing")
    sha = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if sha != SOURCE_SHA:
        raise RuntimeError("source_sha256_mismatch")
    pdf_text = OCR.read_text(encoding="utf-8")
    if "8513100000" not in norm_article(pdf_text) or "52411/23" not in pdf_text:
        raise RuntimeError("local_pdf_scope_or_number_not_proven")

    by_offer: dict[str, dict] = {}
    assignment_type_labels: Counter = Counter()
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if norm_number(row.get("Номер/название документа")) != norm_number(NUMBER):
                continue
            source_rel = str(row.get("Локальный файл") or "")
            if source_rel not in SOURCE_RELS:
                continue
            if row.get("Применимость") not in ("Подтверждено статусом покрытия", "Подтверждено источником"):
                continue
            if row.get("Тип документа") not in {"Сертификат соответствия", "Декларация ЕАЭС"}:
                raise RuntimeError("assignment_type_label_unrecognized")
            assignment_type_labels[row.get("Тип документа")] += 1
            if str(row.get("Бренд подтвержденный") or "").strip().casefold() != "gauss":
                raise RuntimeError("assignment_brand_conflict")
            offer = str(row.get("Артикул продавца") or "").strip()
            model = offer.split("-", 1)[0]
            evidence = str(row.get("Основание сопоставления") or "")
            official_page = str(row.get("URL карточки/основания") or "")
            digits = re.search(r"\d+", model)
            listed_model = "GFL" + digits.group(0) if digits else ""
            exact_article_evidence = "Точный артикул" in evidence and model in evidence
            official_gfl_evidence = (listed_model and listed_model in evidence
                and "оба PDF прямо охватывают аккумуляторные фонари модели GFL" in evidence
                and official_page.startswith("https://gauss.ru/"))
            if not offer or not (norm_article(model) in norm_article(pdf_text)
                    or exact_article_evidence or official_gfl_evidence):
                raise RuntimeError("assignment_model_not_listed:" + offer)
            assigned_path = ROOT / source_rel
            if (not assigned_path.is_file()
                    or hashlib.sha256(assigned_path.read_bytes()).hexdigest() != sha
                    or row.get("SHA256 фактический") != sha
                    or row.get("Аудит файла") != "SHA-256 совпадает"):
                raise RuntimeError("assignment_source_hash_conflict:" + offer)
            if offer in by_offer:
                raise RuntimeError("duplicate_assignment_offer:" + offer)
            by_offer[offer] = {"offer_id": offer, "model": model,
                "source_evidence": row.get("Основание сопоставления"),
                "source_applicability": row.get("Применимость"),
                "validity_note": row.get("Сроки/валидность")}
    if not by_offer:
        raise RuntimeError("no_confirmed_assignment_targets")

    previous_live = {}
    if LIVE_ASSIGNMENTS.is_file():
        with LIVE_ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                if norm_number(row.get("number")) == norm_number(NUMBER):
                    previous_live.setdefault(str(row.get("offer_id") or ""), []).append(row)

    client = Client()
    offers = sorted(by_offer)
    product_rows: dict[str, list[dict]] = defaultdict(list)
    attr_rows: dict[str, list[dict]] = defaultdict(list)
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        p = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items")
        a = client.call("ozon", "/v4/product/info/attributes",
                        {"filter": {"offer_id": batch}, "limit": len(batch)}).get("result")
        if not isinstance(p, list) or not isinstance(a, list):
            raise RuntimeError("live_ozon_product_response_invalid")
        for row in p:
            product_rows[str(row.get("offer_id") or "")].append(row)
        for row in a:
            attr_rows[str(row.get("offer_id") or "")].append(row)
    records = [x for x in live_certificate_list(client)
               if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(records) > 1:
        raise RuntimeError("duplicate_ozon_certificate_record")
    record = records[0] if records else None
    if record and (record.get("type_code") != "declaration"
                   or str(record.get("issue_date") or "")[:10] != ISSUE
                   or str(record.get("expire_date") or "")[:10] != EXPIRY):
        raise RuntimeError("ozon_existing_record_metadata_conflict")
    bindings = client.ozon_bindings(int(record["certificate_id"])) if record else []
    bind_by_pid: dict[str, list[dict]] = defaultdict(list)
    for row in bindings:
        bind_by_pid[str(row.get("product_id") or "")].append(row)

    targets, wb_skips = [], []
    for offer, source in sorted(by_offer.items()):
        reasons = []
        ps, ats = product_rows.get(offer, []), attr_rows.get(offer, [])
        p, a = ps[0] if len(ps) == 1 else {}, ats[0] if len(ats) == 1 else {}
        if len(ps) != 1 or len(ats) != 1:
            reasons.append("ozon_product_or_attributes_not_unique")
        pid = str(p.get("product_id") or p.get("id") or "")
        sku = str(p.get("sku") or "")
        brands = attr_values(a, 85)
        tnved = sorted({x.split(" - ", 1)[0].strip() for x in attr_values(a, 22232)})
        if p.get("is_archived") is not False:
            reasons.append("ozon_product_archived_or_unclear")
        if brands != ["Gauss"]:
            reasons.append("ozon_brand_mismatch_or_ambiguous")
        if set(tnved) != ALLOWED_TNVED:
            reasons.append("ozon_tnved_mismatch_or_ambiguous")
        old = previous_live.get(offer, [])
        if len(old) != 1:
            reasons.append("previous_live_identity_missing_or_duplicate")
        elif (str(old[0].get("ozon_product_id") or "") != pid
              or str(old[0].get("ozon_sku") or "") != sku):
            reasons.append("ozon_identity_changed_since_assignment_audit")
        existing = bind_by_pid.get(pid, []) if pid else []
        if len(existing) > 1:
            reasons.append("duplicate_existing_binding")
        elif existing and str(existing[0].get("sku") or "") != sku:
            reasons.append("existing_binding_sku_conflict")
        elif existing and str(existing[0].get("product_status_code") or "").casefold() != "approved":
            reasons.append("existing_binding_not_approved")

        cards = [c for c in client.wb_cards(offer) if str(c.get("vendorCode") or "") == offer]
        wb_reason = []
        if len(cards) != 1:
            wb_reason.append("wb_card_missing_or_duplicate")
            card = {}
        else:
            card = cards[0]
            wb_tnved = set(code_values(card))
            if str(card.get("brand") or "").strip().casefold() != "gauss":
                wb_reason.append("wb_brand_mismatch")
            if wb_tnved != ALLOWED_TNVED:
                wb_reason.append("wb_tnved_mismatch_or_ambiguous")
        same = [d for d in ((card.get("documents") or {}).get("items") or [])
                if norm_number(d.get("number")) == norm_number(NUMBER)]
        exact = [d for d in same if int(d.get("type") or 0) == 2
                 and str(d.get("startDate") or "")[:10] == ISSUE
                 and str(d.get("endDate") or "")[:10] == EXPIRY
                 and d.get("isEndless") is False]
        if same and not (len(same) == len(exact) == 1):
            wb_reason.append("wb_existing_document_conflict")
        if wb_reason:
            wb_skips.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                             "reasons": wb_reason, "brand": card.get("brand"),
                             "tnved": sorted(set(code_values(card))) if card else []})
        targets.append({**source, "product_id": pid, "sku": sku, "ozon_name": p.get("name"),
            "ozon_brand_values": brands, "ozon_tnved": tnved,
            "ozon_existing_binding_count": len(existing),
            "ozon_existing_binding_status": existing[0].get("product_status_code") if len(existing) == 1 else None,
            "ozon_safe": not reasons, "ozon_blockers": reasons,
            "wb_nmID": str(card.get("nmID") or ""), "wb_brand": card.get("brand"),
            "wb_tnved": sorted(set(code_values(card))) if card else [],
            "wb_documents_same_number": same, "wb_exact_metadata_count": len(exact),
            "wb_safe": not wb_reason, "wb_blockers": wb_reason})

    result = {"checked_at_utc": now(), "read_only": True, "number": NUMBER,
        "type_code": "declaration", "marketplace_type": {"ozon": "DECLARATION", "wb": 2},
        "assignment_type_label_counts": dict(assignment_type_labels),
        "issue_date": ISSUE, "expire_date": EXPIRY,
        "source_file": SOURCE_REL, "source_sha256": sha, "source_bytes": SOURCE.stat().st_size,
        "fsa": {"record_id": FSA_ID, "status": "Действует", "url": FSA_URL,
                "issue_date": ISSUE, "expiry_date": EXPIRY,
                "tnved": sorted(ALLOWED_TNVED), "scope": "Gauss rechargeable LED flashlights; models Basic, Black, GFL, GFLA, GFLB, GFPRO; serial production; TR EAEU 037/2016."},
        "ozon_record": ({k: record.get(k) for k in ("certificate_id", "certificate_number", "type_code",
                          "status_code", "issue_date", "expire_date", "products_count")} if record else None),
        "assignment_target_count": len(by_offer), "targets": targets,
        "ozon_safe_count": sum(x["ozon_safe"] for x in targets),
        "ozon_blocker_counts": dict(Counter(r for x in targets for r in x["ozon_blockers"])),
        "wb_safe_count": sum(x["wb_safe"] for x in targets),
        "wb_blocker_counts": dict(Counter(r for x in targets for r in x["wb_blockers"])),
        "wb_skips": wb_skips, "fsa_live_verified_in_browser": True,
        "fsa_live_checked_at_utc": now(), "source_file_deleted": False}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("checked_at_utc", "number", "source_sha256",
        "assignment_target_count", "ozon_safe_count", "ozon_blocker_counts", "wb_safe_count",
        "wb_blocker_counts", "ozon_record")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
