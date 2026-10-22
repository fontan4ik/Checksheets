"""Read-only, full 491-offer preflight for EAEU declaration 06897."""
from __future__ import annotations

import collections
import csv
import datetime as dt
import hashlib
import json
import re
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE))
from api_client import Client, now  # noqa: E402
from preflight_arlight_06897_exact_20261014 import (  # noqa: E402
    EAEU_VIEW, EXPIRY, ISSUE, NUMBER, NUMBER_END, OFFICIAL_PDF_URL,
    SOURCE_SHA256, TNVED, WB_TNVED_CHAR_ID, api_post as ozon_api_post, live_eaeu_record,
    live_ozon_number_lookup, norm, read_ozon_certificates,
    read_ozon_offers,
)

ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
PDF = ROOT / "output_to_user/certificates/group_1/documents/arlight/5F2ED782CCE4CB4CBA510758C10E647A.pdf"
OUT = BASE / "arlight_06897_source_map_live_preflight_20261014.json"
PRIOR_PREFLIGHT = BASE / "arlight_06897_exact_live_preflight_20261014.json"
OZON_BINDING_ID = 5664376


def write_checkpoint(data: dict) -> None:
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(OUT)


def wb_api_post(client: Client, path: str, payload: dict) -> tuple[int, dict]:
    """Rate-limited read-only WB call with bounded handling for 429/5xx."""
    for attempt in range(7):
        response = client.http.post("https://content-api.wildberries.ru" + path, json=payload,
                                    headers=client.wb_headers, timeout=(15, 120))
        try:
            body = response.json()
        except ValueError:
            body = {"non_json_response": True}
        if response.status_code == 429 or response.status_code in (500, 502, 503, 504):
            if attempt == 6:
                raise RuntimeError(f"WB read remained rate-limited/transient after bounded retries: HTTP {response.status_code}")
            retry_after = response.headers.get("Retry-After")
            try:
                delay = max(float(retry_after), 1.0) if retry_after else min(60.0, 2.0 ** (attempt + 1))
            except ValueError:
                delay = min(60.0, 2.0 ** (attempt + 1))
            print(f"WB HTTP {response.status_code}; wait {delay:g}s before retry", flush=True)
            time.sleep(delay)
            continue
        time.sleep(1.05)
        return response.status_code, body
    raise RuntimeError("Unreachable WB retry state")


def read_wb_cards(client: Client, offer: str) -> list[dict]:
    cards = []
    cursor = {"limit": 100}
    seen = set()
    for _ in range(100):
        status, body = wb_api_post(client, "/content/v2/get/cards/list", {"settings": {
            "sort": {"ascending": True}, "cursor": cursor,
            "filter": {"withPhoto": -1, "textSearch": offer}}})
        if status != 200 or body.get("error"):
            raise RuntimeError(f"WB card read failed for {offer}: HTTP {status}")
        batch = body.get("cards")
        if not isinstance(batch, list):
            raise RuntimeError(f"WB card response malformed for {offer}")
        cards.extend(c for c in batch if str(c.get("vendorCode") or "") == offer)
        page = body.get("cursor") or {}
        if page.get("total") != len(batch):
            raise RuntimeError(f"WB page count mismatch for {offer}")
        if len(batch) < 100:
            return cards
        marker = (str(page.get("updatedAt") or ""), str(page.get("nmID") or ""))
        if not all(marker) or marker in seen:
            raise RuntimeError(f"WB cursor repeated or incomplete for {offer}")
        seen.add(marker)
        cursor = {"limit": 100, "updatedAt": marker[0], "nmID": int(marker[1])}
    raise RuntimeError(f"WB pagination exceeded for {offer}")


def source_rows() -> list[dict]:
    if hashlib.sha256(PDF.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("Local 06897 PDF hash changed")
    selected = []
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if str(row.get("Номер/название документа") or "").strip() != "809001271":
                continue
            if row.get("Бренд подтвержденный") != "Arlight":
                continue
            if row.get("SHA256 фактический", "").lower() != SOURCE_SHA256:
                continue
            if row.get("SHA256 заявленный", "").lower() != SOURCE_SHA256:
                raise RuntimeError("A mapped source row has a conflicting declared PDF hash")
            if row.get("Аудит файла") != "SHA-256 совпадает":
                raise RuntimeError("A mapped source row has a failed source-file audit")
            if row.get("URL документа") != OFFICIAL_PDF_URL:
                raise RuntimeError("A mapped source row points at a different document URL")
            if "arlight.ru/support/files-and-programs/" not in row.get("URL карточки/основания", ""):
                raise RuntimeError("A mapped source row lacks an official Arlight support page")
            if not str(row.get("Основание сопоставления") or "").startswith("Точный артикул в официальном листинге/карточке:"):
                raise RuntimeError("A mapped source row lacks exact-article manufacturer evidence")
            if "документ приложен" not in str(row.get("Основание сопоставления") or "").lower():
                raise RuntimeError("Official product page does not record this declaration as an attachment")
            try:
                source_record = json.loads(row.get("Исходная запись JSON") or "{}")
            except json.JSONDecodeError as exc:
                raise RuntimeError("A source-map JSON row is malformed") from exc
            if (source_record.get("SHA256") != SOURCE_SHA256
                    or source_record.get("Source URL") != OFFICIAL_PDF_URL):
                raise RuntimeError("Embedded original source-map row conflicts with 06897")
            selected.append(row)
    by_offer = {str(row.get("Артикул продавца") or "").strip(): row for row in selected}
    if len(selected) != 491 or len(by_offer) != 491 or "" in by_offer:
        raise RuntimeError(f"Expected 491 unique, hash-verified offers; got rows={len(selected)}, unique={len(by_offer)}")
    return [by_offer[k] for k in sorted(by_offer)]


def read_bindings(client: Client, certificate_id: int) -> list[dict]:
    items: list[dict] = []
    last_id = 0
    expected = None
    seen = set()
    while True:
        status, body = ozon_api_post(client, "ozon", "/v1/product/certificate/products/list",
                                     {"certificate_id": certificate_id, "last_id": last_id, "limit": 500})
        if status != 200:
            raise RuntimeError(f"Ozon binding read failed: HTTP {status}")
        result = body.get("result") or {}
        batch, count = result.get("items"), result.get("count")
        if not isinstance(batch, list) or not isinstance(count, int):
            raise RuntimeError("Ozon binding page omitted items/count")
        if expected is None:
            expected = count
        elif count != expected:
            raise RuntimeError("Ozon binding count changed during readback")
        items.extend(batch)
        if len(items) == expected:
            pairs = [(str(x.get("product_id") or ""), str(x.get("sku") or "")) for x in items]
            if len(pairs) != len(set(pairs)):
                raise RuntimeError("Ozon returned duplicate product/SKU pairs")
            return items
        if len(items) > expected or not batch:
            raise RuntimeError("Ozon binding pagination incomplete")
        next_id = max(int(x.get("product_id") or 0) for x in batch)
        if next_id <= last_id or next_id in seen:
            raise RuntimeError("Ozon binding cursor repeated")
        seen.add(next_id)
        last_id = next_id


def series_from_name(name: str) -> str:
    found = re.search(r"(?<![A-Z0-9])(RTW|RT|S2|UL)(?![A-Z0-9])", name.upper())
    return found.group(1) if found else "unknown"


def wb_code(card: dict) -> list[str]:
    raw = [str(v) for char in card.get("characteristics") or []
           if str(char.get("id")) == str(WB_TNVED_CHAR_ID)
           for v in char.get("value") or []]
    return sorted({v.split(" ", 1)[0].strip() for v in raw if v.strip()})


def compact_wb(card: dict, offer: str) -> dict:
    container = card.get("documents") or card.get("docs") or {}
    docs = container.get("items") or []
    matches = [d for d in docs if norm(d.get("number")) == norm(NUMBER)]
    return {
        "nmID": str(card.get("nmID") or ""), "vendorCode": str(card.get("vendorCode") or ""),
        "brand": card.get("brand"), "title": card.get("title"), "tnved_codes": wb_code(card),
        "excludeDocuments": container.get("excludeDocuments"), "matching_06897_rows": matches,
        "other_document_count": len(docs), "offer_id": offer, "wb_card_raw": card,
    }


def assess_wb_target(target: dict, card_rows: list[dict]) -> None:
    offer = target["offer_id"]
    target["wb_cards"] = card_rows
    target["wb_ready"] = (len(card_rows) == 1 and bool(card_rows[0]["nmID"])
                          and card_rows[0]["vendorCode"] == offer and card_rows[0]["brand"] == "Arlight"
                          and card_rows[0]["tnved_codes"] == [TNVED]
                          and card_rows[0]["excludeDocuments"] in (False, True)
                          and target["family_series"] in {"RT", "RTW", "S2", "UL"})
    blockers = []
    if len(card_rows) != 1:
        blockers.append("wb_card_missing_or_ambiguous")
    for card in card_rows:
        if not card["nmID"]:
            blockers.append("wb_nmid_missing")
        if card["vendorCode"] != offer or card["brand"] != "Arlight":
            blockers.append("wb_brand_or_offer_mismatch")
        if card["tnved_codes"] != [TNVED]:
            blockers.append("wb_tnved_mismatch")
        if card["excludeDocuments"] not in (False, True):
            blockers.append("wb_documents_flag_missing")
        matches = card["matching_06897_rows"]
        if len(matches) > 1:
            blockers.append("wb_duplicate_document_rows")
        if matches and card["excludeDocuments"] is True:
            blockers.append("wb_existing_document_excluded_flag_conflict")
        if matches:
            row = matches[0]
            if (int(row.get("type") or 0) != 2 or str(row.get("startDate") or "")[:10] != ISSUE
                    or str(row.get("endDate") or "")[:10] != EXPIRY or row.get("isEndless") is not False):
                blockers.append("wb_document_metadata_conflict")
    target["wb_blockers"] = sorted(set(blockers))
    target["wb_document_present"] = (len(card_rows) == 1 and len(card_rows[0]["matching_06897_rows"]) == 1)
    target["wb_verdict"] = (card_rows[0]["matching_06897_rows"][0].get("verdict")
                             if target["wb_document_present"] else None)
    target["wb_mutation_needed"] = bool(target["wb_ready"] and not target["wb_document_present"]
                                        and not target["wb_blockers"])
    target["preflight_ready_both"] = (target["ozon_ready"] and target["wb_ready"]
                                      and not target["wb_blockers"])


def main() -> None:
    previous_targets = {}
    previous_done = 0
    if OUT.exists():
        saved = json.loads(OUT.read_text(encoding="utf-8"))
        if saved.get("complete"):
            raise RuntimeError(f"Completed output already exists; inspect instead of rerunning: {OUT}")
        previous_done = int(saved.get("targets_completed") or 0)
        previous_targets = {str(x["offer_id"]): x for x in saved.get("targets") or []}
        if (not 0 < previous_done < 491 or len(previous_targets) != 491
                or any("wb_cards" not in previous_targets.get(str(r["Артикул продавца"]), {})
                       for r in source_rows()[:previous_done])):
            raise RuntimeError("Saved partial preflight is inconsistent; inspect before resuming")
        print(f"Resuming from {previous_done}/491 WB cards", flush=True)
    rows = source_rows()
    offers = [str(row["Артикул продавца"]) for row in rows]
    source_index = {str(r["Артикул продавца"]): r for r in rows}
    client = Client()
    registry = live_eaeu_record(client)
    if norm(registry.get("docId")) != norm(NUMBER):
        raise RuntimeError("Live EAEU record number mismatch")
    details = registry.get("technicalRegulationObjectDetails") or {}
    products_scope = details.get("productDetails") or []
    official_scope = [{"productName": x.get("productName"), "productId": x.get("productId"),
                       "commodityCode": x.get("commodityCode")} for x in products_scope]
    registry_series = {s.upper().replace("СЕРИЯ ", "") for x in products_scope
                       for s in (x.get("productId") or []) if str(s).upper().startswith("СЕРИЯ ")}
    if not {"RT", "RTW", "S2", "UL"}.issubset(registry_series):
        raise RuntimeError(f"Live EAEU series scope changed: {sorted(registry_series)}")
    status_details = registry.get("docStatusDetails") or {}
    if (status_details.get("docStatusCode") != "01"
            or str(status_details.get("startDate") or "")[:10] != ISSUE
            or str(status_details.get("endDate") or "")[:10] != EXPIRY):
        raise RuntimeError("Live EAEU document status or dates changed")
    if not any(TNVED in (x.get("commodityCode") or []) for x in products_scope):
        raise RuntimeError("Live EAEU TN VED scope changed")

    product_details, attrs = read_ozon_offers(client, offers)
    certs = read_ozon_certificates(client)
    exact_records = [c for c in certs if norm(c.get("certificate_number") or c.get("number")) == norm(NUMBER)]
    lookup = live_ozon_number_lookup(client)
    bindings = read_bindings(client, OZON_BINDING_ID)
    if len(exact_records) != 1 or int(exact_records[0].get("certificate_id") or -1) != OZON_BINDING_ID:
        raise RuntimeError("Ozon certificate list does not show exactly record 5664376")
    if not lookup.get("exact_record_absent") is False or int(lookup.get("certificate_id") or -1) != OZON_BINDING_ID:
        raise RuntimeError("Ozon exact-number lookup does not agree with record 5664376")
    record = lookup
    if (record.get("type_code") != "declaration" or str(record.get("issue_date") or "")[:10] != ISSUE
            or str(record.get("expire_date") or "")[:10] != EXPIRY
            or record.get("status_code") in {"declined", "rejected", "cancelled", "invalid"}):
        raise RuntimeError("Ozon record metadata/status is not suitable for product binding")

    current_bindings = []
    for b in bindings:
        current_bindings.append({"product_id": str(b.get("product_id") or ""), "sku": str(b.get("sku") or ""),
                                 "status": b.get("status") or b.get("status_code"),
                                 "offer_id": b.get("offer_id")})
    prior = json.loads(PRIOR_PREFLIGHT.read_text(encoding="utf-8"))
    if (prior.get("number") != NUMBER or prior.get("source_pdf", {}).get("sha256") != SOURCE_SHA256
            or prior.get("source_assignment_count") != 12):
        raise RuntimeError("The prior exact 12-offer preflight is missing or does not match this declaration")
    prior_pairs = {(str(x.get("product_id") or ""), str(x.get("sku") or ""))
                   for x in prior.get("targets") or []}
    if len(prior_pairs) != 12:
        raise RuntimeError("The prior verified 06897 group has incomplete product identities")
    current_pairs = {(x["product_id"], x["sku"]) for x in current_bindings}
    if not current_pairs.issubset(prior_pairs):
        raise RuntimeError("Existing Ozon bindings are outside the previously verified 06897 group")
    targets = []
    for offer in offers:
        p = product_details[offer]
        attr = attrs[offer]
        brand = [str(v.get("value") or "") for v in (attr.get("85") or {}).get("values") or []]
        raw_codes = [str(v.get("value") or "") for v in (attr.get("22232") or {}).get("values") or []]
        codes = sorted({v.split(" - ", 1)[0].strip() for v in raw_codes if v.strip()})
        pid, sku = str(p.get("id") or p.get("product_id") or ""), str(p.get("sku") or "")
        name = str(p.get("name") or "")
        source = source_index[offer]
        targets.append({
            "offer_id": offer, "product_id": pid, "sku": sku, "active": p.get("is_archived") is False,
            "ozon_name": name, "family_series": series_from_name(name), "ozon_brand": brand,
            "ozon_tnved_codes": codes, "source_page": source.get("URL карточки/основания"),
            "source_article_evidence": source.get("Основание сопоставления"),
            "source_page_attachment": True,
        })

    bound_pairs = {(x["product_id"], x["sku"]) for x in current_bindings}
    by_offer_identity = {(x["product_id"], x["sku"]): x["offer_id"] for x in targets}
    if any(not x["product_id"] or not x["sku"] or x["sku"] == "0" for x in targets):
        raise RuntimeError("One or more current Ozon target identities are missing")
    if len({(x["product_id"], x["sku"]) for x in targets}) != len(targets):
        raise RuntimeError("Ozon target Product ID/SKU pairs are not unique")
    for target in targets:
        pair = (target["product_id"], target["sku"])
        target["ozon_binding_present"] = pair in bound_pairs
        target["ozon_ready"] = (target["active"] and target["ozon_brand"] == ["Arlight"]
                                and target["ozon_tnved_codes"] == [TNVED]
                                and target["family_series"] in registry_series)
        target["ozon_blockers"] = []
        if not target["active"]: target["ozon_blockers"].append("archived_or_not_active")
        if target["ozon_brand"] != ["Arlight"]: target["ozon_blockers"].append("brand_mismatch")
        if target["ozon_tnved_codes"] != [TNVED]: target["ozon_blockers"].append("tnved_mismatch")
        if target["family_series"] not in registry_series: target["ozon_blockers"].append("series_missing_from_live_registry_scope")

    wb_errors = []
    for i, target in enumerate(targets, 1):
        offer = target["offer_id"]
        if i <= previous_done:
            old = previous_targets.get(offer)
            if not old or old.get("product_id") != target["product_id"] or old.get("sku") != target["sku"]:
                raise RuntimeError(f"Saved preflight identity changed for {offer}; restart is unsafe")
            if (old.get("wb_cards") and old["wb_cards"][0].get("wb_card_raw")):
                assess_wb_target(target, old["wb_cards"])
                continue
        cards = read_wb_cards(client, offer)
        card_rows = [compact_wb(c, offer) for c in cards]
        assess_wb_target(target, card_rows)
        if target["wb_blockers"]: wb_errors.extend(f"{offer}:{x}" for x in target["wb_blockers"])
        if i % 10 == 0 or i == len(targets):
            partial = {
                "checked_at_utc": now(), "read_only": True, "complete": False,
                "number": NUMBER, "source_count": len(rows), "targets_completed": i,
                "official_eaeu_record_url": EAEU_VIEW, "official_eaeu_live_record": registry,
                "official_registry_series": sorted(registry_series), "official_registry_product_scope": official_scope,
                "source_pdf": {"path": str(PDF), "sha256": SOURCE_SHA256,
                               "bytes": PDF.stat().st_size, "official_url": OFFICIAL_PDF_URL},
                "ozon_certificate_record": lookup, "ozon_binding_count_before": len(bindings),
                "ozon_existing_bindings": current_bindings, "targets": targets,
            }
            write_checkpoint(partial)
            print(f"WB progress {i}/{len(targets)}", flush=True)

    family_counts = collections.Counter(x["family_series"] for x in targets)
    ozon_blockers = collections.Counter(b for x in targets for b in x["ozon_blockers"])
    wb_blockers = collections.Counter(b for x in targets for b in x["wb_blockers"])
    verdicts = collections.Counter(
        str((x.get("wb_verdict") or {}).get("reason") or (x.get("wb_verdict") or {}).get("status") or "no_existing_row")
        for x in targets)
    result = {
        "checked_at_utc": now(), "read_only": True, "complete": True,
        "marketplace_mutation_allowed": False, "number": NUMBER, "issue_date": ISSUE,
        "expiry_date": EXPIRY, "tnved": TNVED,
        "official_eaeu_record_url": EAEU_VIEW, "official_eaeu_live_record": registry,
        "official_registry_series": sorted(registry_series), "official_registry_product_scope": official_scope,
        "source_pdf": {"path": str(PDF), "sha256": SOURCE_SHA256,
                       "bytes": PDF.stat().st_size, "official_url": OFFICIAL_PDF_URL},
        "source_count": len(rows), "ozon_certificate_record": lookup,
        "ozon_binding_count_before": len(bindings), "ozon_existing_bindings": current_bindings,
        "family_counts": dict(family_counts), "ozon_blocker_counts": dict(ozon_blockers),
        "wb_blocker_counts": dict(wb_blockers), "wb_existing_verdicts": dict(verdicts),
        "wb_existing_document_count": sum(x["wb_document_present"] for x in targets),
        "wb_missing_document_count": sum(not x["wb_document_present"] for x in targets),
        "ozon_missing_binding_count": sum(x["ozon_ready"] and not x["ozon_binding_present"] for x in targets),
        "ozon_ready_count": sum(x["ozon_ready"] for x in targets),
        "wb_ready_count": sum(x["wb_ready"] for x in targets),
        "both_ready_count": sum(x["preflight_ready_both"] for x in targets),
        "wb_mutation_needed_count": sum(x["wb_mutation_needed"] for x in targets),
        "wb_errors": wb_errors, "targets": targets,
    }
    result["marketplace_mutation_allowed"] = (result["both_ready_count"] == len(targets)
                                                and result["ozon_binding_count_before"] <= len(targets))
    write_checkpoint(result)
    summary = {k: v for k, v in result.items() if k not in ("official_eaeu_live_record", "official_registry_product_scope", "ozon_existing_bindings", "targets", "wb_errors")}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("SAMPLE_BLOCKERS", json.dumps([x for x in targets if x["ozon_blockers"] or x["wb_blockers"]][:12], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
