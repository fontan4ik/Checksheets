#!/usr/bin/env python3
"""Build a read-only, exact-target preflight for Arlight certificate 04824/22."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SNAPSHOT = HERE / "live_marketplaces_snapshot_latest_20261023.json"
OUT = HERE / "arlight_04824_crossplatform_preflight_20261023.json"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/arlight/B5C5BB7F9BA5554A937519F74325C68F.pdf"
NUMBER = "ЕАЭС RU С-HK.АБ53.В.04824/22"
ISSUE_DATE = "2022-06-20"
EXPIRY_DATE = "2027-06-19"
ALLOWED_TNVED = {"9405310000"}
FSA = {
    "record_id": "3109217",
    "registry_url": "https://pub.fsa.gov.ru/rss/certificate/view/3109217/product",
    "checked_at_utc": "2026-10-23T09:24:15Z",
    "status": "Действует",
    "issue_date": ISSUE_DATE,
    "expiry_date": EXPIRY_DATE,
    "applicant": "ООО ТРАНЗИСТОР.РУ",
    "manufacturer": "SUNRISE HOLDINGS (H.K.) LIMITED",
    "product_scope": "Оборудование световое: гирлянды светодиодные; торговая марка Ardecoled, серия ARD.",
    "tnved": "9405310000",
    "evidence_source": "ФГИС Росаккредитации, сведения о продукции карточки сертификата.",
}
EXPECTED_TARGETS = 120

TRANSLATE = str.maketrans({
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
    "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
    "Ё": "E", "Э": "E", "Д": "D", "П": "P",
})


def norm(value: object) -> str:
    text = str(value or "").strip().upper().translate(TRANSLATE)
    text = re.sub(r"^(?:ЕАЭС|EAEU|EAEC|EAC)\s*", "", text)
    text = re.sub(r"^(?:N|№)\s*", "", text)
    return "".join(char for char in text if char.isalnum())


def codes(values: list[object]) -> set[str]:
    return {str(value or "").split(" - ", 1)[0].strip() for value in values
            if str(value or "").split(" - ", 1)[0].strip()}


def wb_codes(card: dict) -> set[str]:
    found: set[str] = set()
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        for value in raw if isinstance(raw, list) else [raw]:
            if value:
                found.add(str(value).split(" - ", 1)[0].strip())
    return found


def wb_document_state(card: dict) -> tuple[str, list[dict]]:
    rows = [doc for doc in ((card.get("documents") or {}).get("items") or [])
            if norm(doc.get("number")) == norm(NUMBER)]
    exact = [doc for doc in rows if int(doc.get("type") or 0) == 1
             and str(doc.get("startDate") or "")[:10] == ISSUE_DATE
             and str(doc.get("endDate") or "")[:10] == EXPIRY_DATE
             and doc.get("isEndless") is False]
    if len(exact) == 1 and len(rows) == 1:
        verdict = exact[0].get("verdict") or {}
        if verdict.get("verified") is True and verdict.get("status") == 1 and verdict.get("reason") == "valid":
            return "valid_existing", exact
        return "exact_metadata_existing", exact
    if not rows:
        return "missing", []
    return "metadata_conflict", rows


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_exists_inspect_before_replacing")
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    for key in ("ozon_products", "ozon_certificates", "wb_catalog"):
        if snap.get(key, {}).get("complete") is not True:
            raise RuntimeError(f"incomplete_snapshot:{key}")
    for key in ("ozon_products", "ozon_certificates", "wb_catalog"):
        checked = datetime.fromisoformat(str(snap[key]["checked_at"]).replace("Z", "+00:00"))
        if (datetime.now(timezone.utc) - checked).total_seconds() > 1800:
            raise RuntimeError(f"snapshot_too_old:{key}")
    if not ISSUE_DATE <= date.today().isoformat() <= EXPIRY_DATE:
        raise RuntimeError("certificate_not_current_today")
    if not SOURCE.is_file():
        raise RuntimeError("source_file_missing")
    source_sha = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if source_sha != "36244cfcdf8583978b0528ed4e39338edf0f0fdfdf8fbe81894715ed7dfb10d9":
        raise RuntimeError("source_sha256_mismatch")

    assignment_rows = []
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if norm(row.get("Номер/название документа")) != norm(NUMBER):
                continue
            if row.get("Применимость") not in ("Подтверждено статусом покрытия", "Подтверждено источником"):
                continue
            assignment_rows.append(row)
    by_offer: dict[str, dict] = {}
    for row in assignment_rows:
        offer = str(row.get("Артикул продавца") or "").strip()
        if not offer:
            raise RuntimeError("empty_assignment_offer")
        if row.get("Локальный файл") != "output_to_user/certificates/group_1/documents/arlight/B5C5BB7F9BA5554A937519F74325C68F.pdf":
            raise RuntimeError("source_assignment_file_conflict:" + offer)
        if row.get("SHA256 фактический") != source_sha or row.get("Аудит файла") != "SHA-256 совпадает":
            raise RuntimeError("source_assignment_hash_conflict:" + offer)
        if row.get("Тип документа") != "Сертификат соответствия":
            raise RuntimeError("source_assignment_type_conflict:" + offer)
        if str(row.get("Бренд подтвержденный") or "").strip().casefold() != "arlight":
            raise RuntimeError("source_assignment_brand_conflict:" + offer)
        basis = str(row.get("Основание сопоставления") or "")
        if "Точный артикул" not in basis or "официальной" not in basis:
            raise RuntimeError("source_assignment_scope_proof_missing:" + offer)
        if offer in by_offer and by_offer[offer] != row:
            raise RuntimeError("duplicate_conflicting_source_assignment:" + offer)
        by_offer[offer] = row
    if len(by_offer) != EXPECTED_TARGETS:
        raise RuntimeError(f"unexpected_assignment_target_count:{len(by_offer)}")

    products = {str(row.get("offer_id")): row for row in snap["ozon_products"]["products"]}
    wb_cards: dict[str, list[dict]] = defaultdict(list)
    for card in snap["wb_catalog"]["cards"]:
        wb_cards[str(card.get("vendorCode") or "")].append(card)
    ozon_certificates = snap["ozon_certificates"]["certificates"]
    exact_records = [row for row in ozon_certificates
                     if norm(row.get("certificate_number")) == norm(NUMBER)]
    if len(exact_records) > 1:
        raise RuntimeError("duplicate_ozon_certificate_records")

    targets = []
    blockers = []
    wb_states: Counter[str] = Counter()
    for offer, assignment in sorted(by_offer.items()):
        product = products.get(offer)
        if (not product or product.get("is_archived") is not False or not product.get("product_id")
                or not product.get("sku")):
            blockers.append({"offer_id": offer, "reason": "ozon_product_missing_or_inactive"})
            continue
        if product.get("brand_values") != ["Arlight"]:
            blockers.append({"offer_id": offer, "reason": "ozon_brand_conflict",
                             "brand_values": product.get("brand_values")})
            continue
        live_codes = codes(product.get("tnved_values") or [])
        if live_codes != ALLOWED_TNVED:
            blockers.append({"offer_id": offer, "reason": "ozon_tnved_conflict",
                             "tnved": sorted(live_codes)})
            continue
        basis = str(assignment.get("Основание сопоставления") or "")
        article_match = re.search(r"Точный артикул[^:]*:\s*([^;]+)", basis, re.IGNORECASE)
        offer_article = offer.split("-", 1)[0].split("(", 1)[0]
        product_name = str(product.get("name") or "").casefold()
        if (not article_match or article_match.group(1).strip() != offer_article
                or not ("ard" in product_name or "ardecoled" in product_name)):
            blockers.append({"offer_id": offer, "reason": "manufacturer_article_or_series_not_confirmed",
                             "title": product.get("name"),
                             "offer_article": offer_article,
                             "manufacturer_article": article_match.group(1).strip() if article_match else None})
            continue
        matching_cards = wb_cards.get(offer, [])
        if len(matching_cards) != 1:
            blockers.append({"offer_id": offer, "reason": "wb_card_missing_or_ambiguous",
                             "card_count": len(matching_cards)})
            continue
        card = matching_cards[0]
        if not card.get("nmID") or str(card.get("vendorCode") or "") != offer:
            blockers.append({"offer_id": offer, "reason": "wb_card_identity_conflict"})
            continue
        if str(card.get("brand") or "").strip().casefold() != "arlight":
            blockers.append({"offer_id": offer, "reason": "wb_brand_conflict",
                             "brand": card.get("brand")})
            continue
        card_codes = wb_codes(card)
        if card_codes != ALLOWED_TNVED:
            blockers.append({"offer_id": offer, "reason": "wb_tnved_conflict",
                             "tnved": sorted(card_codes)})
            continue
        state, matching_docs = wb_document_state(card)
        wb_states[state] += 1
        targets.append({
            "offer_id": offer,
            "product_id": str(product["product_id"]),
            "sku": str(product["sku"]),
            "ozon_title": product.get("name"),
            "ozon_brand": product.get("brand_values"),
            "ozon_tnved": sorted(live_codes),
            "wb_nmID": str(card["nmID"]),
            "wb_title": card.get("title"),
            "wb_brand": card.get("brand"),
            "wb_tnved": sorted(card_codes),
            "wb_document_state": state,
            "wb_existing_documents": matching_docs,
            "manufacturer_assignment_basis": assignment.get("Основание сопоставления"),
            "manufacturer_source_url": assignment.get("URL карточки/основания"),
        })
    if blockers:
        raise RuntimeError("target_scope_or_identity_blockers:" + json.dumps(blockers[:12], ensure_ascii=False))
    if len(targets) != EXPECTED_TARGETS:
        raise RuntimeError(f"target_count_changed:{len(targets)}")
    for key in ("product_id", "sku"):
        values = [row[key] for row in targets]
        if len(values) != len(set(values)):
            raise RuntimeError(f"duplicate_ozon_{key}")
    nmids = [row["wb_nmID"] for row in targets]
    if len(nmids) != len(set(nmids)):
        raise RuntimeError("duplicate_wb_nmID")

    result = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "snapshot": {
            "path": str(SNAPSHOT),
            "ozon_products_checked_at": snap["ozon_products"]["checked_at"],
            "ozon_certificates_checked_at": snap["ozon_certificates"]["checked_at"],
            "wb_catalog_checked_at": snap["wb_catalog"]["checked_at"],
        },
        "fsa_evidence": FSA,
        "source_file": str(SOURCE),
        "source_sha256": source_sha,
        "ozon_exact_record_count_before_write": len(exact_records),
        "target_count": len(targets),
        "ozon_target_count": len(targets),
        "wb_target_count": len(targets),
        "wb_existing_document_states": dict(wb_states),
        "local_file_deletion_allowed": False,
        "targets": targets,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "preflight": "ready",
        "target_count": len(targets),
        "ozon_existing_record_count": len(exact_records),
        "wb_document_states": dict(wb_states),
        "snapshot": result["snapshot"],
        "output": str(OUT),
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
