#!/usr/bin/env python3
"""Bind eligible Arlight 33344 offers to the existing approved Ozon declaration."""
from __future__ import annotations
import collections, hashlib, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import norm_number

PREFLIGHT = HERE / "arlight_33344_crossplatform_preflight_20261023.json"
STATE = HERE / "arlight_33344_ozon_execution_20261023.json"
JOURNAL = HERE / "arlight_33344_ozon_mutation_journal_20261023.jsonl"
READBACK = HERE / "arlight_33344_ozon_readback_20261023.json"
NUMBER = "ЕАЭС N RU Д-CN.РА03.В.33344/26"
ISSUE, EXPIRY = "2026-04-13", "2031-04-09"
TNVED = {"8537109800"}


def save(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def journal(event):
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at_utc": now(), **event}, ensure_ascii=False) + "\n")
        f.flush()


def values(attrs, ident):
    by_id = {str(x.get("id")): x for x in attrs or []}
    return [str(v.get("value") or "").strip()
            for v in (by_id.get(str(ident)) or {}).get("values") or []
            if str(v.get("value") or "").strip()]


def codes(raw):
    if not isinstance(raw, list): raw = [raw]
    return sorted({str(x).split(" - ", 1)[0].strip() for x in raw if str(x).strip()})


def records(client):
    out = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list): raise RuntimeError("ozon_certificate_list_invalid")
        out.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0): return out
    raise RuntimeError("ozon_certificate_page_limit")


def main():
    if any(p.exists() for p in (STATE, JOURNAL, READBACK)):
        raise RuntimeError("execution_artifact_exists_reconcile_before_retry")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if (pre.get("read_only") is not True or pre.get("document", {}).get("number") != NUMBER
            or pre.get("document", {}).get("fsa_status_from_live_ui") != "Действует"
            or pre.get("document", {}).get("issue_date") != ISSUE
            or pre.get("document", {}).get("expiry_date") != EXPIRY):
        raise RuntimeError("preflight_document_status_or_dates_mismatch")
    targets = {x["offer_id"]: x for x in pre["targets"] if x.get("eligible_ozon")}
    if len(targets) != 26 or pre.get("summary", {}).get("eligible_ozon") != 26:
        raise RuntimeError("eligible_target_count_changed")
    client = Client()
    offers = sorted(targets)
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items") or []
    attrs = client.call("ozon", "/v4/product/info/attributes",
                        {"filter": {"offer_id": offers}, "limit": len(offers)}).get("result") or []
    pm = {str(x.get("offer_id")): x for x in products}
    am = {str(x.get("offer_id")): x for x in attrs}
    current = {}
    for offer, row in targets.items():
        p, a = pm.get(offer) or {}, am.get(offer) or {}
        pid, sku = str(p.get("product_id") or p.get("id") or ""), str(p.get("sku") or "")
        brand, tnved = values(a.get("attributes"), 85), codes(values(a.get("attributes"), 22232))
        if (pid != str(row["product_id"]) or sku != str(row["sku"])
                or p.get("is_archived") is not False or [x.casefold() for x in brand] != ["arlight"]
                or not tnved or not set(tnved).issubset(TNVED)):
            raise RuntimeError("fresh_ozon_identity_or_scope_changed:" + offer)
        current[offer] = {"offer_id": offer, "product_id": pid, "sku": sku, "tnved": tnved}
    matches = [r for r in records(client)
               if norm_number(r.get("certificate_number")) == norm_number(NUMBER)]
    if len(matches) != 1: raise RuntimeError("ozon_record_missing_or_duplicate")
    record = matches[0]
    if (record.get("type_code") != "declaration" or record.get("status_code") != "approved"
            or str(record.get("issue_date") or "")[:10] != ISSUE
            or str(record.get("expire_date") or "")[:10] != EXPIRY):
        raise RuntimeError("ozon_record_not_exact_approved")
    cid = int(record["certificate_id"])
    before = client.ozon_bindings(cid)
    by_pid = collections.defaultdict(list)
    for b in before: by_pid[str(b.get("product_id") or "")].append(b)
    missing = []
    for offer, target in current.items():
        prior = by_pid.get(target["product_id"], [])
        if prior and (len(prior) != 1 or str(prior[0].get("sku") or "") != target["sku"]):
            raise RuntimeError("existing_binding_identity_conflict:" + offer)
        if not prior: missing.append(target["sku"])
    state = {"started_at_utc": now(), "phase": "fresh_prewrite_verified", "document_number": NUMBER,
             "certificate_id": cid, "record_status": record.get("status_code"),
             "target_offers": offers, "eligible_target_count": len(current),
             "binding_count_before": len(before), "missing_before": len(missing),
             "ozon_tnved_skipped_count": 64, "wb_documents_already_present": 77,
             "local_file_deleted": False}
    save(STATE, state)
    bind_response = None
    if missing:
        body = {"certificate_id": cid, "skus": missing}
        state["phase"] = "bind_prepared_no_retry_after_uncertain"
        state["bind_request_sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        save(STATE, state)
        journal({"phase": "bind_prepared", "certificate_id": cid,
                 "request_sha256": state["bind_request_sha256"], "sku_count": len(missing)})
        try:
            bind_response = client.call("ozon", "/v1/product/certificate/bind", body, mutation=True)
            journal({"phase": "bind_response", "response": bind_response})
        except Exception as exc:
            journal({"phase": "bind_uncertain", "error_type": type(exc).__name__})
    after = client.ozon_bindings(cid)
    rows = []
    for offer, target in sorted(current.items()):
        exact = [b for b in after if str(b.get("product_id") or "") == target["product_id"]
                 and str(b.get("sku") or "") == target["sku"]]
        rows.append({"offer_id": offer, "product_id": target["product_id"], "sku": target["sku"],
                     "exact_binding_count": len(exact),
                     "binding_status": exact[0].get("product_status_code") if len(exact) == 1 else None})
    report = {"checked_at_utc": now(), "read_only": True, "document_number": NUMBER,
              "certificate_id": cid, "record_status": record.get("status_code"),
              "exact_bindings": sum(r["exact_binding_count"] == 1 for r in rows),
              "target_count": len(rows),
              "binding_status_counts": dict(collections.Counter(str(r.get("binding_status")) for r in rows)),
              "rows": rows, "local_file_deleted": False}
    save(READBACK, report)
    state["phase"] = "readback_complete"
    state["bind_response"] = bind_response
    state["readback_file"] = READBACK.name
    state["exact_bindings"] = report["exact_bindings"]
    state["binding_status_counts"] = report["binding_status_counts"]
    state["finished_at_utc"] = now()
    save(STATE, state)
    print(json.dumps({k: v for k, v in report.items() if k not in {"rows", "read_only"}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
