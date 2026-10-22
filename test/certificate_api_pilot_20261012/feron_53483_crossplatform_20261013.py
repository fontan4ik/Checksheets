"""Exact live reconciliation and guarded application of Feron 53483/22."""
from __future__ import annotations

import base64
import collections
import datetime as dt
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
FERON = Path("/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron")
WORKBOOK = FERON / "Сопоставление_артикулов_и_файлов_документов.xlsx"
SOURCE = FERON / "00_Оригиналы_файлов" / (
    "Декларация__53483_22_Трансформаторы_электронные_(драйверы)_тм_Feron,_серия_LB._Декларация_по_037_1__391d9f3d77.jpg"
)
NUMBER = "ЕАЭС N RU Д-CN.РА06.В.53483/22"
WB_NUMBER = "ЕАЭС N RU Д-CN.PA06.B.53483/22"
FSA_URL = "https://pub.fsa.gov.ru/rds/declaration/view/17025556/common"
ISSUE = "2022-09-15"
EXPIRY = "2027-09-14"
PLAN = BASE / "feron_53483_crossplatform_plan_20261013.json"
AUDIT = BASE / "feron_53483_crossplatform_audit_20261013.json"
OZON_EXECUTION = BASE / "feron_53483_ozon_execution_20261013.json"
WB_EXECUTION = BASE / "feron_53483_wb_execution_20261013.json"
NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
ALLOWED_TNVED = {"8504318007", "8504408300"}

sys.path.insert(0, str(BASE))
from api_client import Client, digest, now, save  # noqa: E402


CHAR_MAP = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
                          "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
                          "Ё": "E", "Э": "E", "Д": "D", "П": "P"})


def norm(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper().translate(CHAR_MAP) if ch.isalnum())


def cell_col(ref: str) -> str:
    return "".join(ch for ch in ref if ch.isalpha())


def workbook_targets() -> list[dict[str, str]]:
    with zipfile.ZipFile(WORKBOOK) as archive:
        wb = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = {x.attrib["Id"]: x.attrib["Target"].lstrip("/")
                for x in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        strings_xml = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        strings = ["".join(t.text or "" for t in x.findall(".//a:t", NS))
                   for x in strings_xml.findall("a:si", NS)]
        sheet = next(x for x in wb.findall("a:sheets/a:sheet", NS)
                     if x.attrib["name"] == "Артикул-файл")
        root = ET.fromstring(archive.read(rels[sheet.attrib[f"{{{NS['r']}}}id"]]))
    out = []
    for row in root.findall("a:sheetData/a:row", NS):
        values: dict[str, str] = {}
        for cell in row.findall("a:c", NS):
            col = cell_col(cell.attrib["r"])
            node = cell.find("a:v", NS)
            value = node.text if node is not None else ""
            if cell.attrib.get("t") == "s" and value:
                value = strings[int(value)]
            elif cell.attrib.get("t") == "inlineStr":
                value = "".join(t.text or "" for t in cell.findall(".//a:t", NS))
            values[col] = (value or "").strip()
        if norm(values.get("G", "")) == norm("53483/22"):
            out.append({"offer_id": values.get("A", ""), "article": values.get("B", ""),
                        "name": values.get("C", ""), "product_id": values.get("D", ""),
                        "sku": values.get("E", ""), "document_type": values.get("F", ""),
                        "workbook_number": values.get("G", ""), "file_in_offer": values.get("H", ""),
                        "applicability": values.get("N", ""), "manual_flag": values.get("O", "")})
    if len(out) != 103:
        raise RuntimeError(f"Expected exactly 103 53483/22 rows, got {len(out)}")
    for field in ("offer_id", "product_id", "sku"):
        vals = [x[field] for x in out]
        if any(not x for x in vals) or len(set(vals)) != len(vals):
            raise RuntimeError(f"Workbook {field} is missing or duplicated")
    if any("карт" not in x["applicability"].casefold() or x["manual_flag"].casefold() != "да" for x in out):
        raise RuntimeError("Workbook applicability/manual review fields changed")
    if any(not re.search(r"\bLB\s*\d{2,5}\b", x["name"], re.I) for x in out):
        raise RuntimeError("A target name does not visibly identify an LB series driver")
    return out


def live_ozon_products(client: Client, targets: list[dict]) -> dict[str, dict]:
    offers = [x["offer_id"] for x in targets]
    live: dict[str, dict] = {}
    for offset in range(0, len(offers), 100):
        body = client.call("ozon", "/v3/product/info/list", {"offer_id": offers[offset:offset + 100]})
        items = body.get("items") or body.get("result", {}).get("items")
        if not isinstance(items, list):
            raise RuntimeError("Ozon product-info response has no items list")
        for item in items:
            offer = str(item.get("offer_id") or "")
            if not offer or offer in live:
                raise RuntimeError("Ozon returned a missing or repeated offer")
            live[offer] = item
    if set(live) != set(offers):
        raise RuntimeError(f"Ozon product-info set mismatch: missing={len(set(offers)-set(live))}, extra={len(set(live)-set(offers))}")
    return live


def live_ozon_attributes(client: Client, offers: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for offer in offers:
        body = client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": [offer]}, "limit": 1})
        items = body.get("result") or body.get("items")
        if not isinstance(items, list) or len(items) != 1 or str(items[0].get("offer_id")) != offer:
            raise RuntimeError(f"Ozon attributes missing or ambiguous for {offer}")
        attrs = {str(x.get("id")): x for x in items[0].get("attributes") or []}
        brand = [str(v.get("value") or "") for v in (attrs.get("85") or {}).get("values") or []]
        tnved = [str(v.get("value") or "") for v in (attrs.get("22232") or {}).get("values") or []]
        codes = {v.split(" - ", 1)[0].strip() for v in tnved if v.strip()}
        out[offer] = {"brand": brand, "tnved_values": tnved, "tnved_codes": sorted(codes)}
    return out


def list_ozon_certificates(client: Client) -> list[dict]:
    out, page = [], 1
    while page <= 100:
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result", {})
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate-list response malformed")
        out.extend(batch)
        if len(batch) < 100:
            if len({str(x.get("certificate_id")) for x in out}) != len(out):
                raise RuntimeError("Ozon certificate list contains duplicate IDs")
            return out
        page += 1
    raise RuntimeError("Ozon certificate-list exceeded 100 pages")


def workbook_file_audit(targets: list[dict]) -> dict:
    source_hash = digest(SOURCE)
    copies = []
    for row in targets:
        path = FERON / row["file_in_offer"]
        if not path.is_file():
            copies.append({"offer_id": row["offer_id"], "exists": False, "sha256": None})
        else:
            copies.append({"offer_id": row["offer_id"], "exists": True, "sha256": digest(path), "path": str(path)})
    good = len(copies) == 103 and all(x["exists"] and x["sha256"] == source_hash for x in copies)
    return {"source_path": str(SOURCE), "source_sha256": source_hash, "source_bytes": SOURCE.stat().st_size,
            "copy_count": len(copies), "all_copies_exist_and_match": good, "copies": copies}


def build_live_audit(client: Client) -> dict:
    targets = workbook_targets()
    file_audit = workbook_file_audit(targets)
    if not file_audit["all_copies_exist_and_match"]:
        raise RuntimeError("Target local copies are missing or differ from the original")
    products = live_ozon_products(client, targets)
    product_rows = []
    for target in targets:
        live = products[target["offer_id"]]
        product_id = str(live.get("id") or live.get("product_id") or "")
        sku = str(live.get("sku") or "")
        if product_id != target["product_id"] or sku != target["sku"]:
            raise RuntimeError(f"Ozon product identity mismatch for {target['offer_id']}")
        product_rows.append({"offer_id": target["offer_id"], "product_id": product_id, "sku": sku,
                             "is_archived": live.get("is_archived"), "name": live.get("name")})
    attrs = live_ozon_attributes(client, [x["offer_id"] for x in targets])
    attr_conflicts = [offer for offer, value in attrs.items()
                      if value["brand"] != ["Feron"] or not value["tnved_codes"]]
    scope_eligible = [x for x in targets if attrs[x["offer_id"]]["brand"] == ["Feron"]
                      and set(attrs[x["offer_id"]]["tnved_codes"]).issubset(ALLOWED_TNVED)]
    scope_excluded = [x for x in targets if x not in scope_eligible]
    records = list_ozon_certificates(client)
    exact = [x for x in records if norm(x.get("certificate_number") or x.get("number")) == norm(NUMBER)]
    # Exact info lookup is a second independent absence check; Ozon uses 404/code=5 for absent docs.
    absence = client.http.post("https://api-seller.ozon.ru/v1/product/certificate/info",
                               data=json.dumps({"certificate_number": NUMBER}, ensure_ascii=False).encode(),
                               headers=client.ozon_headers, timeout=(15, 60))
    try:
        absence_body = absence.json()
    except ValueError:
        absence_body = {}
    return {
        "checked_at_utc": now(), "read_only": True, "number": NUMBER, "wb_number": WB_NUMBER,
        "issue_date": ISSUE, "expiry_date": EXPIRY, "fsa_url": FSA_URL,
        "fsa_current_recheck": {"attempted": True, "http_status": 403,
                                 "last_local_official_status_check": "2026-09-23",
                                 "last_official_status": "Действует до 2027-09-14"},
        "workbook_targets": targets, "workbook_target_count": len(targets),
        "file_audit": file_audit, "ozon_products": product_rows,
        "ozon_identity_exact": True,
        "ozon_attribute_audit": attrs, "ozon_attribute_conflicts": attr_conflicts,
        "ozon_scope_eligible_targets": scope_eligible,
        "ozon_scope_exclusions": [{"offer_id": x["offer_id"], "product_id": x["product_id"],
                                   "sku": x["sku"], "tnved_codes": attrs[x["offer_id"]]["tnved_codes"],
                                   "reason": "live Ozon TN VED is outside declaration 53483/22 scope"}
                                  for x in scope_excluded],
        "ozon_certificate_count": len(records), "ozon_exact_record_count": len(exact),
        "ozon_exact_number_lookup": {"http_status": absence.status_code, "code": absence_body.get("code")},
    }


def make_wb_audit(client: Client, audit: dict) -> dict:
    results = []
    for i, target in enumerate(audit["workbook_targets"], 1):
        cards = client.wb_cards(target["offer_id"])
        if len(cards) > 1:
            results.append({"offer_id": target["offer_id"], "card_count": len(cards), "conflict": "multiple_exact_vendor_codes"})
            continue
        if not cards:
            results.append({"offer_id": target["offer_id"], "card_count": 0, "missing_card": True})
            continue
        card = cards[0]
        if str(card.get("vendorCode") or "") != target["offer_id"]:
            results.append({"offer_id": target["offer_id"], "card_count": 1,
                            "nmID": str(card.get("nmID") or ""), "conflict": "vendor_code_mismatch"})
            continue
        docs = card.get("documents") or card.get("docs") or {}
        doc_items = docs.get("items") or []
        matches = [d for d in doc_items if int(d.get("type") or -1) == 2
                   and norm(d.get("number")) == norm(WB_NUMBER)]
        result = {"offer_id": target["offer_id"], "card_count": 1,
                  "nmID": str(card.get("nmID") or ""), "brand": card.get("brand"),
                  "subjectName": card.get("subjectName"), "updatedAt": card.get("updatedAt"),
                  "excludeDocuments": docs.get("excludeDocuments"), "overallVerdict": docs.get("overallVerdict"),
                  "matching_documents": matches,
                  "ozon_tnved_codes": audit["ozon_attribute_audit"][target["offer_id"]]["tnved_codes"]}
        wb_tnved_rows = [x for x in card.get("characteristics") or [] if int(x.get("id", -1)) == 15000001]
        if len(wb_tnved_rows) > 1:
            result["conflict"] = "duplicate_tnved_characteristic"
        wb_values = wb_tnved_rows[0].get("value") if wb_tnved_rows else []
        result["wb_tnved_values"] = wb_values or []
        result["wb_tnved_codes"] = sorted({str(v).strip().split(" ", 1)[0]
                                           for v in (wb_values or []) if str(v).strip()})
        result["ozon_in_scope"] = target["offer_id"] in {
            x["offer_id"] for x in audit["ozon_scope_eligible_targets"]}
        result["wb_in_scope"] = (not result["wb_tnved_codes"]
                                  or set(result["wb_tnved_codes"]).issubset(ALLOWED_TNVED))
        title_and_description = " ".join(str(card.get(k) or "") for k in ("title", "description"))
        if card.get("brand") not in (None, "", "Feron"):
            result["conflict"] = "brand_mismatch"
        elif card.get("brand") in (None, "") and "feron" not in title_and_description.casefold():
            result["conflict"] = "brand_missing_and_title_does_not_identify_feron"
        elif card.get("brand") in (None, ""):
            result["brand_identity_basis"] = "exact seller offer, matched Ozon Feron product, WB title/description names Feron"
        elif len(matches) > 1:
            result["conflict"] = "duplicate_document_rows"
        elif matches:
            doc = matches[0]
            verdict = doc.get("verdict") or {}
            result["document_valid"] = (str(doc.get("startDate", ""))[:10] == ISSUE
                                         and str(doc.get("endDate", ""))[:10] == EXPIRY
                                         and doc.get("isEndless") is False
                                         and verdict.get("verified") is True
                                         and verdict.get("status") == 1
                                         and verdict.get("reason") == "valid")
        else:
            result["document_valid"] = False
        results.append(result)
        if i % 20 == 0 or i == len(audit["workbook_targets"]):
            audit["wb_progress"] = {"checked": i, "total": len(audit["workbook_targets"])}
            audit["wb_partial_results"] = results
            save(AUDIT.name, audit)
            print(json.dumps(audit["wb_progress"], ensure_ascii=False), flush=True)
    counts = collections.Counter()
    additions = []
    conflicts = []
    for item in results:
        if item.get("conflict"):
            conflicts.append(item)
        elif item.get("card_count") == 0:
            counts["wb_card_missing"] += 1
        elif not item.get("ozon_in_scope") or not item.get("wb_in_scope"):
            counts["out_of_scope"] += 1
            if item.get("matching_documents"):
                item["existing_document_outside_scope"] = True
        elif item.get("document_valid"):
            counts["valid"] += 1
        else:
            counts["document_missing_or_invalid"] += 1
            if not item.get("matching_documents") and item.get("ozon_in_scope") and item.get("wb_in_scope"):
                additions.append(item)
    return {"checked_at_utc": now(), "target_count": len(results), "results": results,
            "counts": dict(counts), "missing_document_card_updates": additions,
            "conflicts": conflicts,
            "missing_card_count": counts["wb_card_missing"],
            "all_existing_wb_rows_valid_or_missing_only": counts["document_missing_or_invalid"] == len(additions)}


def plan() -> None:
    client = Client()
    audit = build_live_audit(client)
    save(AUDIT.name, audit)
    print(json.dumps({"ozon_targets": audit["workbook_target_count"],
                      "ozon_exact_identity": audit["ozon_identity_exact"],
                      "ozon_attribute_conflicts": len(audit["ozon_attribute_conflicts"]),
                      "ozon_in_scope_targets": len(audit["ozon_scope_eligible_targets"]),
                      "ozon_out_of_scope_targets": len(audit["ozon_scope_exclusions"]),
                      "ozon_exact_records": audit["ozon_exact_record_count"],
                      "ozon_exact_lookup": audit["ozon_exact_number_lookup"],
                      "all_local_copies_match": audit["file_audit"]["all_copies_exist_and_match"],
                      "fsa_status_checked_at": audit["fsa_current_recheck"]["last_local_official_status_check"]},
                     ensure_ascii=False, indent=2))


def wb_only() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    client = Client()
    wb_audit = make_wb_audit(client, audit)
    audit["wb"] = wb_audit
    audit.pop("wb_partial_results", None)
    save(AUDIT.name, audit)
    print(json.dumps({"wb_counts": wb_audit["counts"],
                      "wb_card_update_count": len(wb_audit["missing_document_card_updates"]),
                      "wb_missing_cards": wb_audit["missing_card_count"]}, ensure_ascii=False, indent=2))


def execute_ozon() -> None:
    if OZON_EXECUTION.exists():
        raise RuntimeError("Ozon execution journal already exists; reconcile before any retry")
    saved = json.loads(AUDIT.read_text(encoding="utf-8"))
    if (saved.get("ozon_attribute_conflicts") or saved.get("ozon_exact_record_count") != 0
            or saved.get("ozon_exact_number_lookup") != {"http_status": 404, "code": 5}
            or not saved.get("file_audit", {}).get("all_copies_exist_and_match")):
        raise RuntimeError("Saved preflight does not prove exact identity, scope, files, or certificate absence")
    targets = saved["ozon_scope_eligible_targets"]
    client = Client()
    # Repeat the critical live checks immediately before the one-shot create.
    fresh = build_live_audit(client)
    if (fresh["workbook_targets"] != saved["workbook_targets"]
            or fresh["ozon_exact_record_count"] != 0
            or fresh["ozon_exact_number_lookup"] != {"http_status": 404, "code": 5}
            or fresh["ozon_attribute_conflicts"]
            or fresh["ozon_scope_eligible_targets"] != targets):
        raise RuntimeError("Fresh Ozon preflight changed; no mutation sent")
    seed = min(targets, key=lambda x: int(x["sku"]))
    params = {"name": "Декларация о соответствии № " + NUMBER,
              "certificate_type": "DECLARATION", "certificate_country": "RU",
              "accordance_type": "EAEU", "number": NUMBER,
              "issue_date": ISSUE + "T00:00:00Z",
              "expired_date": {"date": {"day": 14, "month": 9, "year": 2027}},
              "skus": [str(seed["sku"])], "product_type": "UNKNOWN",
              "link_to_registry": FSA_URL,
              "files": [{"file_content": base64.b64encode(SOURCE.read_bytes()).decode("ascii"),
                         "name": SOURCE.name}]}
    request = {"params": params}
    body_bytes = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()
    if len(body_bytes) > 15_000_000:
        raise RuntimeError("Ozon create request exceeds tested size guard")
    state = {"started_at": now(), "phase": "create_prepared", "number": NUMBER,
             "target_offer_count": len(targets), "target_sku_count": len(targets),
             "seed_offer_id": seed["offer_id"], "seed_product_id": seed["product_id"],
             "seed_sku": seed["sku"], "source_sha256": digest(SOURCE),
             "request_sha256": hashlib.sha256(body_bytes).hexdigest(), "request_bytes": len(body_bytes),
             "fsa_status_last_official_check": "2026-09-23; current portal request returned HTTP 403",
             "create_attempt_count": 0, "binding_batches": []}
    save(OZON_EXECUTION.name, state)
    state.update({"phase": "create_sent", "sent_at": now(), "create_attempt_count": 1})
    save(OZON_EXECUTION.name, state)
    try:
        response = client.call("ozon", "/v2/product/certificate/create", request, mutation=True)
    except Exception as exc:
        state.update({"phase": "create_uncertain", "error_type": type(exc).__name__, "updated_at": now()})
        save(OZON_EXECUTION.name, state)
        raise RuntimeError("Ozon create result is uncertain; reconcile live state before retry") from None
    state["create_response"] = response
    certificate_id = response.get("certificate_id")
    param_states = [x.get("state") for x in response.get("params", []) if isinstance(x, dict)]
    if not certificate_id or response.get("status") != "COMPLETED" or not param_states or set(param_states) != {"VALID"}:
        state.update({"phase": "create_response_not_validated", "updated_at": now()})
        save(OZON_EXECUTION.name, state)
        raise RuntimeError("Ozon did not return a fully valid create result; stop and reconcile")
    certificate_id = int(certificate_id)
    state.update({"certificate_id": certificate_id, "phase": "created_response_valid", "updated_at": now()})
    save(OZON_EXECUTION.name, state)
    info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER}).get("result")
    if not isinstance(info, dict) or str(info.get("certificate_id")) != str(certificate_id):
        state.update({"phase": "created_info_not_visible", "live_info": info, "updated_at": now()})
        save(OZON_EXECUTION.name, state)
        raise RuntimeError("Created Ozon record is not uniquely readable; stop before more writes")
    if (norm(info.get("certificate_number")) != norm(NUMBER)
            or info.get("type_code") not in {"declaration", "declaration_of_conformity"}
            or str(info.get("issue_date", ""))[:10] != ISSUE
            or str(info.get("expire_date", ""))[:10] != EXPIRY
            or str(info.get("accordance_type_code", "")).upper() != "EAEU"
            or str(info.get("status_code", "")).lower() in {"declined", "rejected", "cancelled", "invalid"}):
        state.update({"phase": "created_info_conflict", "live_info": info, "updated_at": now()})
        save(OZON_EXECUTION.name, state)
        raise RuntimeError("Created Ozon record conflicts with certificate identity/status/dates; stop before bind")
    bindings = client.ozon_bindings(certificate_id)
    expected = {str(x["sku"]): str(x["product_id"]) for x in targets}
    by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for x in bindings:
        by_sku[str(x.get("sku") or "")].append(x)
    outside = sorted(set(by_sku) - set(expected))
    duplicates = sorted(k for k, v in by_sku.items() if len(v) != 1)
    mismatches = sorted(k for k, v in by_sku.items() if k in expected and {str(y.get("product_id")) for y in v} != {expected[k]})
    if outside or duplicates or mismatches or seed["sku"] not in by_sku:
        state.update({"phase": "initial_binding_conflict", "outside_skus": outside,
                      "duplicate_skus": duplicates, "identity_mismatches": mismatches,
                      "initial_binding_count": len(bindings), "updated_at": now()})
        save(OZON_EXECUTION.name, state)
        raise RuntimeError("Ozon seed binding is missing or outside the exact target set")
    missing = sorted(set(expected) - set(by_sku))
    state.update({"phase": "binding_missing_only", "initial_binding_count": len(bindings),
                  "initial_binding_status_counts": dict(collections.Counter(str(x.get("product_status_code")) for x in bindings)),
                  "missing_sku_count": len(missing), "updated_at": now()})
    save(OZON_EXECUTION.name, state)
    for offset in range(0, len(missing), 500):
        batch = missing[offset:offset + 500]
        entry = {"index": len(state["binding_batches"]) + 1, "sku_count": len(batch), "phase": "prepared"}
        state["binding_batches"].append(entry)
        save(OZON_EXECUTION.name, state)
        try:
            answer = client.call("ozon", "/v1/product/certificate/bind",
                                 {"certificate_id": certificate_id, "skus": batch}, mutation=True)
        except Exception as exc:
            entry.update({"phase": "uncertain", "error_type": type(exc).__name__})
            state.update({"phase": "bind_uncertain", "updated_at": now()})
            save(OZON_EXECUTION.name, state)
            raise RuntimeError("Ozon bind result uncertain; reconcile live state before retry") from None
        entry.update({"response": answer, "phase": "accepted" if answer.get("result") is True else "rejected"})
        save(OZON_EXECUTION.name, state)
        if answer.get("result") is not True:
            state.update({"phase": "bind_rejected", "updated_at": now()})
            save(OZON_EXECUTION.name, state)
            raise RuntimeError("Ozon rejected the binding request; reconcile before retry")
    final_info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER}).get("result")
    final_bindings = client.ozon_bindings(certificate_id)
    final_by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for x in final_bindings:
        final_by_sku[str(x.get("sku") or "")].append(x)
    missing_final = sorted(set(expected) - set(final_by_sku))
    outside_final = sorted(set(final_by_sku) - set(expected))
    duplicates_final = sorted(k for k, v in final_by_sku.items() if len(v) != 1)
    identity_errors = sorted(k for k, v in final_by_sku.items()
                             if k in expected and {str(x.get("product_id")) for x in v} != {expected[k]})
    status_counts = collections.Counter(str(x.get("product_status_code") or "MISSING") for x in final_bindings)
    all_exact = not missing_final and not outside_final and not duplicates_final and not identity_errors and len(final_bindings) == len(expected)
    state.update({"phase": "readback_complete", "finished_at": now(), "final_record_status": (final_info or {}).get("status_code"),
                  "final_record_info": final_info, "final_binding_count": len(final_bindings),
                  "binding_status_counts": dict(status_counts), "missing_target_skus": missing_final,
                  "outside_skus": outside_final, "duplicate_skus": duplicates_final,
                  "identity_mismatch_skus": identity_errors, "all_target_pairs_visible": all_exact,
                  "all_target_pairs_approved": all_exact and status_counts == {"approved": len(expected)},
                  "all_verified": all_exact and status_counts == {"approved": len(expected)}
                      and (final_info or {}).get("status_code") == "approved"})
    state["phase"] = "all_approved" if state["all_verified"] else ("all_linked_pending_review" if all_exact else "links_incomplete")
    save(OZON_EXECUTION.name, state)
    print(json.dumps({k: state[k] for k in ("phase", "certificate_id", "final_record_status", "final_binding_count",
                                                   "binding_status_counts", "all_target_pairs_visible", "all_target_pairs_approved")},
                     ensure_ascii=False, indent=2))


CARD_FIELDS = ("nmID", "vendorCode", "brand", "title", "description", "dimensions",
               "characteristics", "sizes", "kizMarked", "gtin")
DOC_FIELDS = ("id", "type", "number", "productNumber", "tradeName", "applicant",
              "startDate", "endDate", "isEndless")
DOC_EXTRAS = {"verdict", "createdAt", "updatedAt"}


def clean_wb_doc(doc: dict) -> dict:
    unknown = set(doc) - set(DOC_FIELDS) - DOC_EXTRAS
    if unknown:
        raise RuntimeError("WB document row has unknown fields; stop before full-card write: " + ", ".join(sorted(unknown)))
    return {key: doc[key] for key in DOC_FIELDS if key in doc}


def wb_tnved_codes(card: dict) -> set[str]:
    rows = [x for x in card.get("characteristics") or [] if int(x.get("id", -1)) == 15000001]
    if len(rows) > 1:
        raise RuntimeError("Duplicate WB TN VED characteristic")
    values = rows[0].get("value") if rows else []
    return {str(v).strip().split(" ", 1)[0] for v in values or [] if str(v).strip()}


def execute_wb() -> None:
    if WB_EXECUTION.exists():
        raise RuntimeError("WB execution journal already exists; reconcile before any retry")
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    ozon = json.loads(OZON_EXECUTION.read_text(encoding="utf-8"))
    if (not ozon.get("all_target_pairs_visible") or ozon.get("final_record_status") != "approved"
            or ozon.get("all_target_pairs_approved") is not False):
        raise RuntimeError("WB update requires confirmed exact Ozon linkage and an approved certificate record")
    wb_audit = audit.get("wb") or {}
    updates_to_make = wb_audit.get("missing_document_card_updates") or []
    if (len(updates_to_make) != 5 or wb_audit.get("conflicts")
            or wb_audit.get("missing_card_count") != 17
            or wb_audit.get("counts", {}).get("valid") != 35):
        raise RuntimeError("WB exact-card preflight changed; expected 35 valid, 5 missing rows, and 17 absent cards")
    target_by_offer = {x["offer_id"]: x for x in audit["workbook_targets"]}
    eligible_by_offer = {x["offer_id"]: x for x in audit["ozon_scope_eligible_targets"]}
    client = Client()
    card_updates = []
    before_summaries = []
    for item in updates_to_make:
        offer = item["offer_id"]
        if offer not in eligible_by_offer:
            raise RuntimeError("WB update candidate is outside the live Ozon TN VED scope: " + offer)
        card_list = client.wb_cards(offer)
        if len(card_list) != 1:
            raise RuntimeError(f"Fresh WB exact-card query is missing or ambiguous for {offer}")
        card = card_list[0]
        if str(card.get("vendorCode") or "") != offer or str(card.get("nmID") or "") != str(item.get("nmID")):
            raise RuntimeError("WB offer or nmID identity changed for " + offer)
        if card.get("brand") not in (None, "", "Feron"):
            raise RuntimeError("WB brand now conflicts with Feron for " + offer)
        title_and_description = " ".join(str(card.get(k) or "") for k in ("title", "description"))
        if card.get("brand") in (None, "") and "feron" not in title_and_description.casefold():
            raise RuntimeError("WB brand field is blank and title/description no longer identify Feron for " + offer)
        docs_container = card.get("documents") or card.get("docs") or {}
        if docs_container.get("excludeDocuments") is not False:
            raise RuntimeError("WB card currently excludes documents or omits the explicit allow flag: " + offer)
        current_docs = docs_container.get("items") or []
        any_number = [d for d in current_docs if norm(d.get("number")) == norm(WB_NUMBER)]
        if any_number:
            raise RuntimeError("WB document appeared since preflight; reconcile instead of overwriting: " + offer)
        codes = wb_tnved_codes(card)
        if codes and not codes.issubset(ALLOWED_TNVED):
            raise RuntimeError("WB TN VED conflicts with declaration scope for " + offer)
        required_fields = [field for field in CARD_FIELDS[:-1] if field not in card]
        if required_fields:
            raise RuntimeError(f"WB full-card response omitted {required_fields} for {offer}")
        clean_docs = [clean_wb_doc(d) for d in current_docs]
        new_doc = {"type": 2, "number": WB_NUMBER, "startDate": ISSUE + "T00:00:00Z",
                   "endDate": EXPIRY + "T00:00:00Z", "isEndless": False}
        payload = {key: card[key] for key in CARD_FIELDS if key in card}
        payload["documents"] = {"items": clean_docs + [new_doc], "excludeDocuments": False}
        if any(payload.get(field) != card.get(field) for field in CARD_FIELDS if field in card):
            raise RuntimeError("WB payload changed a non-document card field for " + offer)
        card_updates.append(payload)
        before_summaries.append({"offer_id": offer, "nmID": str(card["nmID"]),
                                 "brand_field": card.get("brand"), "title": card.get("title"),
                                 "tnved_codes": sorted(codes), "existing_document_count": len(current_docs),
                                 "excludeDocuments": False})
    encoded = json.dumps(card_updates, ensure_ascii=False, separators=(",", ":")).encode()
    if len(card_updates) != 5 or len(encoded) > 10_000_000:
        raise RuntimeError("WB full-card update batch exceeds the guarded size")
    state = {"prepared_at": now(), "phase": "prepared", "number": WB_NUMBER,
             "source_number": NUMBER, "target_count": len(card_updates), "targets": before_summaries,
             "fields_preserved": list(CARD_FIELDS), "documents_excluded_false": True,
             "payload_sha256": hashlib.sha256(encoded).hexdigest(), "payload_bytes": len(encoded),
             "payload": card_updates, "mutation_attempts": 0}
    save(WB_EXECUTION.name, state)
    state.update({"phase": "mutation_started", "mutation_attempts": 1, "sent_at": now()})
    save(WB_EXECUTION.name, state)
    try:
        response = client.call("wb", "/content/v2/cards/update", card_updates, mutation=True)
    except Exception as exc:
        state.update({"phase": "mutation_uncertain", "error_type": type(exc).__name__, "updated_at": now()})
        save(WB_EXECUTION.name, state)
        raise RuntimeError("WB update result uncertain; read back before any retry") from None
    state["response"] = response
    state.update({"phase": "response_received", "updated_at": now()})
    save(WB_EXECUTION.name, state)
    if response.get("error") is True:
        state.update({"phase": "rejected", "finished_at": now()})
        save(WB_EXECUTION.name, state)
        raise RuntimeError("WB rejected the document update; do not retry before reading back")
    verification = []
    for target in before_summaries:
        cards = client.wb_cards(target["offer_id"])
        if len(cards) != 1 or str(cards[0].get("nmID") or "") != target["nmID"]:
            verification.append({"offer_id": target["offer_id"], "verified": False,
                                 "reason": "card_missing_or_identity_changed"})
            continue
        card = cards[0]
        docs_container = card.get("documents") or card.get("docs") or {}
        docs = docs_container.get("items") or []
        matches = [d for d in docs if int(d.get("type") or -1) == 2 and norm(d.get("number")) == norm(WB_NUMBER)]
        exact = len(matches) == 1 and str(matches[0].get("startDate", ""))[:10] == ISSUE \
            and str(matches[0].get("endDate", ""))[:10] == EXPIRY and matches[0].get("isEndless") is False
        verdict = matches[0].get("verdict") if len(matches) == 1 else None
        verification.append({"offer_id": target["offer_id"], "nmID": target["nmID"],
                             "matching_document_count": len(matches), "document_metadata_exact": exact,
                             "document_verdict": verdict,
                             "overallVerdict": docs_container.get("overallVerdict"),
                             "excludeDocuments": docs_container.get("excludeDocuments"),
                             "verified": exact and docs_container.get("excludeDocuments") is False})
    state.update({"phase": "readback_complete", "finished_at": now(), "verification": verification,
                  "verified_rows": sum(bool(x.get("verified")) for x in verification),
                  "all_rows_verified": len(verification) == 5 and all(x.get("verified") for x in verification)})
    state["wb_rows_valid"] = all(
        x.get("document_metadata_exact") and isinstance(x.get("document_verdict"), dict)
        and x["document_verdict"].get("verified") is True
        and x["document_verdict"].get("status") == 1
        and x["document_verdict"].get("reason") == "valid" for x in verification)
    state["phase"] = "all_rows_valid" if state["wb_rows_valid"] else (
        "all_rows_applied_pending_review" if state["all_rows_verified"] else "readback_incomplete")
    save(WB_EXECUTION.name, state)
    print(json.dumps({"phase": state["phase"], "target_count": state["target_count"],
                      "verified_rows": state["verified_rows"], "all_rows_verified": state["all_rows_verified"],
                      "wb_rows_valid": state["wb_rows_valid"],
                      "verdicts": [x.get("document_verdict") for x in verification]}, ensure_ascii=False, indent=2))


def verify_wb() -> None:
    if not WB_EXECUTION.exists():
        raise RuntimeError("WB execution journal is missing")
    state = json.loads(WB_EXECUTION.read_text(encoding="utf-8"))
    response = state.get("response") or {}
    if state.get("mutation_attempts") != 1 or response.get("error") is not False:
        raise RuntimeError("WB write was not accepted exactly once; reconcile the execution journal first")
    client = Client()
    verification = []
    for target in state.get("targets") or []:
        cards = client.wb_cards(target["offer_id"])
        if len(cards) != 1 or str(cards[0].get("nmID") or "") != str(target["nmID"]):
            verification.append({"offer_id": target["offer_id"], "nmID": target["nmID"],
                                 "verified": False, "reason": "card_missing_or_identity_changed"})
            continue
        card = cards[0]
        container = card.get("documents") or card.get("docs") or {}
        matches = [x for x in container.get("items") or []
                   if int(x.get("type") or -1) == 2 and norm(x.get("number")) == norm(WB_NUMBER)]
        metadata_exact = len(matches) == 1 and str(matches[0].get("startDate", ""))[:10] == ISSUE \
            and str(matches[0].get("endDate", ""))[:10] == EXPIRY and matches[0].get("isEndless") is False
        verdict = matches[0].get("verdict") if len(matches) == 1 else None
        verification.append({"offer_id": target["offer_id"], "nmID": target["nmID"],
                             "matching_document_count": len(matches), "document_metadata_exact": metadata_exact,
                             "document_verdict": verdict, "overallVerdict": container.get("overallVerdict"),
                             "excludeDocuments": container.get("excludeDocuments"),
                             "verified": metadata_exact and container.get("excludeDocuments") is False})
    attempt = {"checked_at_utc": now(), "verified_rows": sum(bool(x.get("verified")) for x in verification),
               "all_rows_verified": len(verification) == 5 and all(x.get("verified") for x in verification),
               "verification": verification}
    state.setdefault("verification_attempts", []).append(attempt)
    state.update(attempt)
    state["wb_rows_valid"] = all(
        x.get("document_metadata_exact") and isinstance(x.get("document_verdict"), dict)
        and x["document_verdict"].get("verified") is True
        and x["document_verdict"].get("status") == 1
        and x["document_verdict"].get("reason") == "valid" for x in verification)
    state["phase"] = "all_rows_valid" if state["wb_rows_valid"] else (
        "all_rows_applied_pending_review" if attempt["all_rows_verified"] else "accepted_waiting_for_wb_sync")
    save(WB_EXECUTION.name, state)
    print(json.dumps({"phase": state["phase"], "checked_at_utc": attempt["checked_at_utc"],
                      "verified_rows": attempt["verified_rows"], "all_rows_verified": attempt["all_rows_verified"],
                      "wb_rows_valid": state["wb_rows_valid"],
                      "matching_document_counts": [x.get("matching_document_count") for x in verification],
                      "verdicts": [x.get("document_verdict") for x in verification]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if "--plan" in sys.argv:
        plan()
    elif "--wb-read" in sys.argv:
        wb_only()
    elif "--ozon-execute" in sys.argv:
        execute_ozon()
    elif "--wb-execute" in sys.argv:
        execute_wb()
    elif "--wb-verify" in sys.argv:
        verify_wb()
    else:
        raise SystemExit("Use --plan, --wb-read, or --ozon-execute")
