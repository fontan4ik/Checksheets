#!/usr/bin/env python3
"""Fresh read-only Ozon/WB preflight for Arlight declaration 33344/26."""
from __future__ import annotations
import collections, csv, hashlib, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import norm_number

NUMBER = "ЕАЭС N RU Д-CN.РА03.В.33344/26"
SOURCE = "output_to_user/certificates/group_1/documents/arlight/DCE8C157436F3C4E9898E20868978ACD.pdf"
SHA = "284dffc5179434fb9cffd9df16417de57b05e11013edb3055bdfddb9ec86b06e"
ISSUE, EXPIRY, FSA_ID = "2026-04-13", "2031-04-09", "21321061"
TNVED = {"8537109800"}
OUT = HERE / "arlight_33344_crossplatform_preflight_20261023.json"


def values(attrs, ident):
    mapping = {str(x.get("id")): x for x in attrs or []}
    return [str(v.get("value") or "").strip()
            for v in (mapping.get(str(ident)) or {}).get("values") or []
            if str(v.get("value") or "").strip()]


def codes(raw):
    if not isinstance(raw, list): raw = [raw]
    return sorted({str(x).split(" - ", 1)[0].strip() for x in raw if str(x).strip()})


def wb_codes(card):
    result = []
    for ch in card.get("characteristics") or []:
        label = "".join(str(ch.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" in label or "тнвед" in label:
            v = ch.get("value")
            result.extend(v if isinstance(v, list) else [v])
    return codes(result)


def all_records(client):
    items = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list): raise RuntimeError("ozon_certificate_list_invalid")
        items.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0): return items
    raise RuntimeError("ozon_certificate_page_limit")


def main():
    if OUT.exists(): raise RuntimeError("preflight_artifact_exists_inspect_before_retry")
    source = ROOT / SOURCE
    digest = hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else None
    if digest != SHA: raise RuntimeError("source_missing_or_hash_mismatch")
    with (ROOT / "output_to_user/certificates/document_assignments.csv").open(
            encoding="utf-8-sig", newline="") as f:
        assignments = [r for r in csv.DictReader(f)
                       if r.get("Локальный файл") == SOURCE and r.get("SHA256 фактический") == SHA
                       and "33344/26" in str(r.get("Номер/название документа") or "")]
    assignments.sort(key=lambda r: r.get("Артикул продавца") or "")
    offers = [r.get("Артикул продавца") for r in assignments]
    if len(offers) != 90 or len(set(offers)) != 90:
        raise RuntimeError("assignment_count_or_duplicate_conflict")
    client = Client()
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items") or []
    attrs = client.call("ozon", "/v4/product/info/attributes",
                        {"filter": {"offer_id": offers}, "limit": len(offers)}).get("result") or []
    pm, am = collections.defaultdict(list), collections.defaultdict(list)
    for x in products: pm[str(x.get("offer_id") or "")].append(x)
    for x in attrs: am[str(x.get("offer_id") or "")].append(x)
    records = [r for r in all_records(client)
               if norm_number(r.get("certificate_number")) == norm_number(NUMBER)]
    if len(records) > 1: raise RuntimeError("duplicate_ozon_records_for_document")
    record = records[0] if records else None
    record_exact = bool(record and record.get("type_code") == "declaration"
                        and str(record.get("issue_date") or "")[:10] == ISSUE
                        and str(record.get("expire_date") or "")[:10] == EXPIRY)
    bindings = client.ozon_bindings(int(record["certificate_id"])) if record else []
    by_pid = collections.defaultdict(list)
    for b in bindings: by_pid[str(b.get("product_id") or "")].append(b)
    targets = []
    for row in assignments:
        offer = row["Артикул продавца"]
        conflicts = []
        if len(pm[offer]) != 1 or len(am[offer]) != 1:
            p, a = {}, {}; conflicts.append("ozon_identity_missing_or_ambiguous")
        else: p, a = pm[offer][0], am[offer][0]
        pid, sku = str(p.get("product_id") or p.get("id") or ""), str(p.get("sku") or "")
        brand, tnved = values(a.get("attributes"), 85), codes(values(a.get("attributes"), 22232))
        if not pid or not sku: conflicts.append("ozon_identity_missing")
        if p.get("is_archived") is not False: conflicts.append("ozon_archived_or_unknown")
        if [x.casefold() for x in brand] != ["arlight"]: conflicts.append("ozon_brand_mismatch")
        if not tnved or not set(tnved).issubset(TNVED): conflicts.append("ozon_tnved_out_of_scope")
        if record and (not record_exact or record.get("status_code") not in {"approved", "under_review"}):
            conflicts.append("ozon_record_metadata_or_status_conflict")
        prior = by_pid.get(pid, [])
        if prior and (len(prior) != 1 or str(prior[0].get("sku") or "") != sku):
            conflicts.append("ozon_existing_binding_conflict")
        wb_cards = [c for c in client.wb_cards(offer) if str(c.get("vendorCode") or "") == offer]
        card = wb_cards[0] if len(wb_cards) == 1 else {}
        if len(wb_cards) != 1: conflicts.append("wb_card_missing_or_ambiguous")
        wbrand, wtnved = str(card.get("brand") or ""), wb_codes(card)
        if wbrand.casefold() != "arlight": conflicts.append("wb_brand_mismatch")
        if not card.get("nmID"): conflicts.append("wb_nm_id_missing")
        if not wtnved or not set(wtnved).issubset(TNVED): conflicts.append("wb_tnved_out_of_scope")
        docs = ((card.get("documents") or {}).get("items") or [])
        same = [d for d in docs if norm_number(d.get("number")) == norm_number(NUMBER)]
        exact = [d for d in same if str(d.get("type")) == "2"
                 and str(d.get("startDate") or "")[:10] == ISSUE
                 and str(d.get("endDate") or "")[:10] == EXPIRY and d.get("isEndless") is False]
        if same and len(exact) != 1: conflicts.append("wb_document_metadata_conflict")
        targets.append({"offer_id": offer, "product_id": pid, "sku": sku, "brand": brand,
                        "ozon_tnved": tnved, "wb_nmID": str(card.get("nmID") or ""),
                        "wb_tnved": wtnved, "wb_same_number_count": len(same),
                        "wb_exact_count": len(exact),
                        "wb_verdicts": [d.get("verdict") for d in exact],
                        "conflicts": conflicts, "eligible_ozon": not any(c.startswith("ozon_") for c in conflicts),
                        "eligible_wb": not any(c.startswith("wb_") for c in conflicts)})
    report = {"checked_at_utc": now(), "read_only": True,
              "document": {"number": NUMBER, "type_code": "declaration", "issue_date": ISSUE,
                           "expiry_date": EXPIRY, "fsa_registry_id": FSA_ID,
                           "fsa_registry_url": "https://pub.fsa.gov.ru/rds/declaration/view/" + FSA_ID + "/common",
                           "fsa_status_from_live_ui": "Действует", "fsa_tnved": sorted(TNVED),
                           "fsa_scope": "Arlight dimmers/microdimmers series SMART, SR, LN, TY, TUYA, MATTER, ZB, DALI, KNX, ARL, VT, WF, TRIAC, SENS; TR EAEU 037/2016",
                           "source": SOURCE, "source_sha256": digest},
              "ozon_record": ({k: record.get(k) for k in ["certificate_id", "certificate_number", "type_code", "status_code", "issue_date", "expire_date"]} if record else None),
              "targets": targets,
              "summary": {"offers": len(targets), "eligible_ozon": sum(x["eligible_ozon"] for x in targets),
                          "eligible_wb": sum(x["eligible_wb"] for x in targets),
                          "wb_exact_document_present": sum(x["wb_exact_count"] == 1 for x in targets),
                          "ozon_blockers": dict(collections.Counter(c for x in targets for c in x["conflicts"] if c.startswith("ozon_"))),
                          "wb_blockers": dict(collections.Counter(c for x in targets for c in x["conflicts"] if c.startswith("wb_"))),
                          "wb_verdicts": dict(collections.Counter(str(v.get("reason", "unknown")) for x in targets for v in x["wb_verdicts"] if isinstance(v, dict)))},
              "writes_performed": False, "local_files_deleted": False,
              "limitation": "The source FSA page was read earlier today at 07:20 UTC. Product scope, active status, model assignments and marketplace codes were rechecked in this preflight."}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
