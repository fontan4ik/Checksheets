"""Fresh read-only preflight for exact Kosmos 03254/23 WB cards."""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now, digest  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import copy_documents, norm_number, doc_key  # noqa: E402

ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
SOURCE = ROOT / "output_to_user/certificates/group_3/docs/kosmos_cert_03254_23.pdf"
OUT = HERE / "kosmos_03254_wb_preflight_live_20261021.json"
NUMBER = "ЕАЭС RU С-CN.НВ93.В.03254/23"
ISSUE = "2023-05-19"
EXPIRY = "2028-05-18"
ALLOWED_TNVED = {"8539520002", "8539520003", "8539520009"}
ALREADY_ATTACHED_037 = "ЕАЭС N RU Д-CN.РА06.В.78454/22"


def card_tnved(card: dict) -> list[str]:
    values = []
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        for value in raw if isinstance(raw, list) else [raw]:
            if value:
                values.append(str(value).split(" - ", 1)[0].strip())
    return sorted(set(values))


def load_targets() -> dict[str, dict]:
    found: dict[str, dict] = {}
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if norm_number(row.get("Номер/название документа")) != norm_number(NUMBER):
                continue
            if "group_3" not in str(row.get("Группа источника") or ""):
                continue
            offer = str(row.get("Артикул продавца") or "").strip()
            if not offer or offer in found:
                raise RuntimeError("missing_or_duplicate_source_offer:" + offer)
            if row.get("Бренд подтвержденный") != "Космос":
                raise RuntimeError("source_brand_conflict:" + offer)
            evidence = str(row.get("Основание сопоставления") or "")
            evidence_folded = evidence.casefold()
            if not ("совпадает с записью приложения" in evidence_folded
                    or ("точный модельный хвост" in evidence_folded and "снят только этот префикс" in evidence_folded)):
                raise RuntimeError("source_model_match_basis_changed:" + offer)
            found[offer] = {
                "offer_id": offer,
                "ozon_title": str(row.get("Название товара Ozon") or ""),
                "source_file": str(row.get("Локальный файл") or ""),
                "source_url": str(row.get("URL документа") or ""),
                "model_match_evidence": evidence,
            }
    if len(found) != 232:
        raise RuntimeError(f"unexpected_exact_assignment_count:{len(found)}")
    return found


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_output_exists; inspect it before retry")
    if not SOURCE.is_file() or digest(SOURCE) != "55d43e4b61abb6dc006d479d38517ddb7695e6a00131a5eafe6ecfaffe1c2552":
        raise RuntimeError("verified_certificate_pdf_missing_or_hash_changed")
    targets = load_targets()
    client = Client()
    cards = []
    counts = Counter()
    seen_nmids = set()
    for index, offer in enumerate(sorted(targets), 1):
        found = client.wb_cards(offer)
        if len(found) != 1:
            raise RuntimeError(f"wb_exact_card_missing_or_ambiguous:{offer}:{len(found)}")
        card = found[0]
        if str(card.get("vendorCode") or "") != offer or not str(card.get("nmID") or ""):
            raise RuntimeError("wb_card_identity_mismatch:" + offer)
        nm_id = str(card["nmID"])
        if nm_id in seen_nmids:
            raise RuntimeError("duplicate_wb_nmID:" + nm_id)
        seen_nmids.add(nm_id)
        if str(card.get("brand") or "").strip().casefold() != "космос":
            raise RuntimeError("wb_brand_mismatch:" + offer)
        codes = card_tnved(card)
        if not codes or not set(codes) <= ALLOWED_TNVED:
            raise RuntimeError("wb_tnved_outside_fsa_scope:" + offer + ":" + repr(codes))
        title = str(card.get("title") or "")
        if "ламп" not in title.casefold() or not any(x in title.casefold() for x in ("led", "светодиод")):
            raise RuntimeError("wb_product_title_not_led_lamp:" + offer)
        docs_container = card.get("documents") or {}
        if docs_container.get("excludeDocuments") is True:
            raise RuntimeError("wb_card_excludes_documents:" + offer)
        raw_docs = (card.get("documents") or {}).get("items") or []
        docs = copy_documents(card)
        same = [row for row in docs if norm_number(row.get("number")) == norm_number(NUMBER)]
        if same:
            exact = (len(same) == 1 and doc_key(same[0]) == (1, norm_number(NUMBER))
                     and str(same[0].get("startDate", ""))[:10] == ISSUE
                     and str(same[0].get("endDate", ""))[:10] == EXPIRY
                     and same[0].get("isEndless") is False)
            if not exact:
                raise RuntimeError("wb_same_certificate_number_conflict:" + offer)
            counts["already_exact"] += 1
        else:
            counts["missing"] += 1
        current_037 = [row for row in raw_docs if norm_number(row.get("number")) == norm_number(ALREADY_ATTACHED_037)]
        if len(current_037) == 1:
            counts["037_exact_row_present"] += 1
            verdict = current_037[0].get("verdict") or {}
            if verdict.get("verified") is True and verdict.get("reason") == "valid":
                counts["037_valid"] += 1
            else:
                counts["037_pending_or_other"] += 1
        else:
            counts["037_missing_or_ambiguous"] += 1
        cards.append({
            **targets[offer], "nmID": nm_id, "brand": card.get("brand"),
            "title": title, "createdAt": card.get("createdAt"), "tnved_codes": codes,
            "existing_documents": docs,
            "existing_document_verdicts": [
                {"number": row.get("number"), "verdict": row.get("verdict")}
                for row in raw_docs if row.get("verdict") is not None
            ],
            "existing_overall_verdict": docs_container.get("overallVerdict"),
            "source_model_match_evidence": targets[offer]["model_match_evidence"],
        })
        if index % 40 == 0 or index == len(targets):
            print(f"WB read-only preflight {index}/{len(targets)}", flush=True)
    result = {
        "checked_at_utc": now(), "read_only": True,
        "source_pdf": {"path": str(SOURCE), "sha256": digest(SOURCE), "bytes": SOURCE.stat().st_size},
        "official_fsa_record": {
            "url": "https://pub.fsa.gov.ru/rss/certificate/view/3249749/baseInfo",
            "record_id": 3249749, "number": NUMBER, "status_observed": "Действует",
            "issue_date": ISSUE, "expiry_date": EXPIRY, "fsa_tnved": sorted(ALLOWED_TNVED),
            "applicant": "ООО КОСМОС ЭЛЕКТРО", "brand": "КОСМОС / SuperMax",
            "manufacturer": "SHAOXING MEKA ELECTRIC IMP&EXP CO., LTD",
            "sample_manufactured_at": "2022-07-01",
            "sample_cutoff_note": "FSA product section limits covered lots to manufacture no earlier than the sample date; live card creation dates do not prove lot manufacture dates.",
        },
        "target_count": len(cards), "unique_nmID_count": len(seen_nmids),
        "summary": dict(counts), "cards": cards,
        "ozon_write_skipped": True,
        "ozon_skip_reason": "The same offer IDs are currently classified on Ozon as halogen lamps (TN VED 8539213009) or missing/outside this FSA record's LED codes; do not attach this LED certificate to those product records.",
    }
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(OUT)
    print(json.dumps({"preflight": str(OUT), "target_count": result["target_count"],
                      "summary": result["summary"], "ozon_write_skipped": True},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
