"""Exact new-offer CODES preparation, run under the existing CODES job lock.

Complete validated local FTP catalogs supply identities only, never fresh stocks.
The inventory stage separately forces both current FTP warehouse downloads.
"""
import json
import time
from pathlib import Path
from datetime import datetime, timezone
import sync_etm_codes as codes
import gsheets_utils
from resolve_etm_onboarding_codes import resolve_codes


def select_updates(updates, allowed):
    return [u for u in updates if u.article in allowed
            and codes.normalize(u.model) == codes.normalize(allowed[u.article]["model"])
            and codes.normalize_brand(u.brand) == codes.normalize_brand(allowed[u.article]["brand"])]


def cell(row, column):
    return str(row[column - 1]).strip() if len(row) >= column else ""


def verify_updates(rows, columns, updates):
    by_offer = {}
    for row in rows[1:]:
        offer = cell(row, columns["article"])
        if not offer:
            continue
        if offer in by_offer:
            raise RuntimeError("ETM onboarding duplicate current offer")
        by_offer[offer] = row
    for update in updates:
        row = by_offer.get(update.article, [])
        if (cell(row, columns["etm_code"]) != update.code
                or codes.normalize(cell(row, columns["model"])) != codes.normalize(update.model)
                or codes.normalize_brand(cell(row, columns["brand"])) != codes.normalize_brand(update.brand)):
            raise RuntimeError("ETM onboarding identity/CODES read-back mismatch")


def revalidate_api_updates(rows, columns, inputs, resolved):
    updates = []
    for number, row in enumerate(rows[1:], start=2):
        value = lambda key: str(row[columns[key]-1]).strip() if len(row)>=columns[key] else ""
        offer = value("article")
        original = inputs.get(offer)
        if not original or offer not in resolved or value("etm_code"):
            continue
        if codes.normalize(value("model")) != codes.normalize(original["model"]) or codes.normalize(value("brand")) != codes.normalize(original["brand"]):
            continue
        updates.append(codes.Update(number, str(resolved[offer]), value("model"), offer, value("brand"), "exact_goods_api"))
    return updates


def run_onboarding(manifest, dry_run=False):
    requested = json.loads(Path(manifest).read_text(encoding="utf-8"))
    if not isinstance(requested, list) or not requested:
        raise ValueError("Expected nonempty exact onboarding manifest")
    inputs = {str(r["offer_id"]):r for r in requested}
    if len(inputs)!=len(requested):
        raise ValueError("Duplicate onboarding offers")
    if any(not str(r.get("offer_id", "")).strip() or not r.get("model") or not r.get("brand") for r in requested):
        raise ValueError("Missing onboarding identity")
    ws = gsheets_utils.get_worksheet(codes.SHEET_NAME)
    rows = codes.read_sheet_rows(ws)
    columns = codes.resolve_sheet_columns(rows[0])
    report = {"startedAt":datetime.now(timezone.utc).isoformat(),"requested":len(inputs),"sources":[],"written":0,"dryRun":dry_run}
    all_updates = []
    for directory in codes.FTP_REMOTE_DIRS:
        cache = codes.FTP_LOCAL_ROOT / directory.lstrip("/") / "price.csv"
        if cache.exists() and 0 <= time.time()-cache.stat().st_mtime <= 86400:
            content=cache.read_bytes()
            codes.validate_ftp_csv(content,str(cache))
            source=str(cache)
        else:
            source_data=codes.fetch_ftp_source(directory)
            if source_data is None:
                raise RuntimeError("No complete ETM identity catalog")
            content,remote=source_data
            source=remote.remote_path
        mapping,_=codes.load_mapping_from_bytes(content,source)
        if not dry_run:
            rows=codes.read_sheet_rows(ws)
            columns=codes.resolve_sheet_columns(rows[0])
        planned,_=codes.plan_updates(rows,columns,mapping)
        updates=select_updates(planned,inputs)
        if not dry_run:
            codes._write_code_updates(ws,rows,updates)
        codes._apply_updates_to_memory(rows,updates,columns["etm_code"])
        all_updates.extend(updates)
        report["written"]+=len(updates)
        report["sources"].append({"source":source,"matched":len(updates)})
    if not dry_run:
        rows=codes.read_sheet_rows(ws)
        columns=codes.resolve_sheet_columns(rows[0])
        verify_updates(rows, columns, all_updates)
    verified,_=codes.plan_verified_updates(rows,columns,codes.load_verified_matches())
    verified=select_updates(verified,inputs)
    if not dry_run:
        codes._write_code_updates(ws,rows,verified)
    codes._apply_updates_to_memory(rows,verified,columns["etm_code"])
    all_updates.extend(verified)
    report["written"]+=len(verified)
    if not dry_run:
        rows=codes.read_sheet_rows(ws)
        columns=codes.resolve_sheet_columns(rows[0])
        verify_updates(rows, columns, all_updates)
    remaining=[]
    for row in rows[1:]:
        value=lambda key:str(row[columns[key]-1]).strip() if len(row)>=columns[key] else ""
        offer=value("article")
        if (offer in inputs and not value("etm_code")
                and codes.normalize(value("model")) == codes.normalize(inputs[offer]["model"])
                and codes.normalize_brand(value("brand")) == codes.normalize_brand(inputs[offer]["brand"])):
            remaining.append({"offer_id":offer,"model":value("model"),"brand":value("brand"),"title":inputs[offer].get("title","")})
    api = resolve_codes(remaining) if remaining else {"codes":{},"pending":[],"evidence":{},"unique_queries":0}
    if not dry_run:
        rows=codes.read_sheet_rows(ws)
        columns=codes.resolve_sheet_columns(rows[0])
    api_inputs={r["offer_id"]:r for r in remaining}
    updates=revalidate_api_updates(rows,columns,api_inputs,api["codes"])
    if not dry_run:
        codes._write_code_updates(ws,rows,updates)
    codes._apply_updates_to_memory(rows,updates,columns["etm_code"])
    all_updates.extend(updates)
    report.update({"written":report["written"]+len(updates),"api":api,"finishedAt":datetime.now(timezone.utc).isoformat()})
    if not dry_run:
        # Re-resolve current headers and verify every stage, including FTP/registry.
        current=codes.read_sheet_rows(ws)
        current_columns=codes.resolve_sheet_columns(current[0])
        verify_updates(current, current_columns, all_updates)
        target=Path(__file__).resolve().parent/'logs'/'etm-onboarding-last.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary=target.with_name(target.name+'.tmp')
        temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(target)
    print("ETM ONBOARDING COMPLETED "+json.dumps({"written":report['written'],"pending":len(api['pending']),"queries":api['unique_queries']}),flush=True)
    return 0
