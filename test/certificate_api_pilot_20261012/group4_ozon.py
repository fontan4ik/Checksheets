"""Conservative Ozon continuation for exact, official Group 4 EAC documents."""
from __future__ import annotations

import argparse
import base64
import collections
import csv
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

from api_client import BASE, ROOT, Client, digest, now, save

OUT_PLAN = "group4_ozon_plan.json"
OUT_RUN = "group4_ozon_execution.json"
MANIFEST = ROOT / "output_to_user/certificates/group_4/manifest.csv"
MASTER_DOCS = ROOT / "output_to_user/certificates/document_catalog_master.csv"
PRODUCTS_FILE = BASE / "ozon_products_live.json"
LIVE_FILE = BASE / "ozon_live.json"

TR = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
                    "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
                    "Ё": "E", "Э": "E", "Д": "D", "П": "P"})


def norm(value: str) -> str:
    return "".join(c for c in str(value or "").upper().translate(TR) if c.isalnum())


def doc_identity(value: str) -> str:
    result = norm(value)
    for prefix in ("EAEC", "EAEU", "EAC"):
        if result.startswith(prefix):
            result = result[len(prefix):]
            break
    if result.startswith("N"):
        result = result[1:]
    for country in ("RU", "KG", "BY", "KZ", "AM"):
        if result.startswith(country):
            result = result[len(country):]
            break
    return result


def date_range(value: str) -> tuple[dt.date, dt.date]:
    matches = re.findall(r"(\d{2})\.(\d{2})\.(\d{4})", value)
    if len(matches) < 2:
        raise RuntimeError(f"Unparseable document validity: {value}")
    start, end = (dt.date(int(y), int(m), int(d)) for d, m, y in matches[:2])
    if end <= start:
        raise RuntimeError(f"Invalid document validity interval: {value}")
    return start, end


def load_rows() -> list[dict[str, str]]:
    with MANIFEST.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def file_by_sha(expected_sha: str, preferred: Path) -> Path | None:
    if preferred.is_file() and not preferred.is_symlink() and digest(preferred).lower() == expected_sha.lower():
        return preferred
    with MASTER_DOCS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("SHA256", "").lower() != expected_sha.lower():
                continue
            for candidate in row.get("Файл/файлы проекта", "").split("; "):
                path = ROOT / candidate
                if path.is_file() and not path.is_symlink() and digest(path).lower() == expected_sha.lower():
                    return path
    return None


def make_plan() -> dict:
    products_doc = json.loads(PRODUCTS_FILE.read_text())
    live_doc = json.loads(LIVE_FILE.read_text())
    if not products_doc.get("complete") or not live_doc.get("complete"):
        raise RuntimeError("Complete live Ozon product and certificate snapshots are required")
    products = {x["offer_id"]: x for x in products_doc["products"]}
    certs_by_key: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for cert in live_doc["certificates"]:
        certs_by_key[(cert.get("type_code", ""), doc_identity(cert.get("certificate_number", "")))].append(cert)

    grouped: dict[tuple[str, str], dict] = {}
    excluded: list[dict] = []
    for row in load_rows():
        description = row.get("Doc type/number", "")
        pieces = description.split(" / ")
        if len(pieces) < 2:
            continue
        label, number = pieces[0], pieces[-1].strip()
        lower = (label + " " + row.get("Validity", "") + " " + row.get("Статус документа", "")).casefold().replace("ё", "е")
        if "сертификат соответствия еаэс" not in lower and "декларация соответствия еаэс" not in lower:
            continue
        if "истек" in lower or "expired" in lower or "прекращ" in lower or "не действует" in lower:
            excluded.append({"offer": row.get("Артикул", ""), "number": number, "reason": "expired_or_not_current"})
            continue
        if row.get("Статус документа", "").casefold().strip() != "действует / официальный":
            excluded.append({"offer": row.get("Артикул", ""), "number": number, "reason": "source_status_not_confirmed"})
            continue
        file_path = file_by_sha(row.get("SHA256", ""), ROOT / row["Local file"])
        if file_path is None:
            excluded.append({"offer": row.get("Артикул", ""), "number": number, "reason": "source_file_missing_or_symlink"})
            continue
        actual_sha = digest(file_path)
        if actual_sha.lower() != row.get("SHA256", "").lower():
            excluded.append({"offer": row.get("Артикул", ""), "number": number, "reason": "source_sha_mismatch"})
            continue
        article = row["Артикул"].strip()
        product = products.get(article)
        if not product or not product.get("sku") or product.get("is_archived"):
            excluded.append({"offer": article, "number": number, "reason": "not_in_current_active_ozon_catalog"})
            continue
        start_date, end_date = date_range(row["Validity"])
        if end_date <= dt.datetime.now(dt.timezone.utc).date():
            excluded.append({"offer": article, "number": number, "reason": "expired_today"})
            continue
        type_code = "declaration" if "декларация" in label.casefold() else "certificate_of_conformity"
        key = (type_code, doc_identity(number))
        target_key = (type_code, doc_identity(number), actual_sha)
        item = grouped.setdefault(target_key, {
            "number": number, "type_code": type_code,
            "ozon_create_type": "DECLARATION" if type_code == "declaration" else "CERTIFICATE_OF_CONFORMITY",
            "certificate_country": "RU", "accordance_type": "EAEU",
            "issue_date": start_date.isoformat(), "expire_date": end_date.isoformat(),
            "file": str(file_path), "file_name": file_path.name, "file_sha256": actual_sha,
            "file_size": file_path.stat().st_size, "source_url": row.get("Source URL", ""),
            "evidence": row.get("Доказательство model/series match", ""),
            "offers": {}, "existing_records": certs_by_key.get(key, []),
        })
        if (item["issue_date"] != start_date.isoformat() or item["expire_date"] != end_date.isoformat()
                or item["file"] != str(file_path)):
            raise RuntimeError(f"Conflicting evidence for {number}")
        item["offers"][article] = {"product_id": product["product_id"], "sku": product["sku"]}

    actions = []
    for item in grouped.values():
        records = item["existing_records"]
        conflicting = [x for x in records if x.get("type_code") != item["type_code"]]
        if conflicting:
            item["action"] = "blocked_conflicting_type"
        elif records:
            approved = [x for x in records if x.get("status_code") == "approved"]
            if not approved:
                item["action"] = "blocked_existing_pending_or_declined"
            else:
                already = {(str(b.get("sku")), str(b.get("product_id")))
                           for cert in approved for b in cert.get("live_bindings", [])
                           if b.get("product_status_code") == "approved"}
                item["bound_approved"] = [offer for offer, product in item["offers"].items()
                                         if (str(product["sku"]), str(product["product_id"])) in already]
                item["bound_pending_or_declined"] = [offer for offer, product in item["offers"].items()
                                                    if any(str(b.get("sku")) == str(product["sku"])
                                                           for cert in approved for b in cert.get("live_bindings", []))
                                                    and offer not in item["bound_approved"]]
                item["unbound_offers"] = [offer for offer in item["offers"]
                                         if offer not in item["bound_approved"] and offer not in item["bound_pending_or_declined"]]
                item["certificate_id"] = approved[0]["certificate_id"]
                if item["unbound_offers"]:
                    item["action"] = "bind_missing"
                elif item["bound_pending_or_declined"]:
                    item["action"] = "already_attached_pending_or_declined"
                else:
                    item["action"] = "already_bound"
        else:
            item["action"] = "create"
        item.pop("existing_records")
        actions.append(item)
    return {
        "planned_at": now(), "ozon_catalog_checked_at": products_doc.get("checked_at"),
        "ozon_certificates_checked_at": live_doc.get("checked_at"), "actions": actions,
        "excluded": excluded,
    }


def list_certificates(client: Client) -> list[dict]:
    result = []
    page = 1
    page_count = None
    while True:
        body = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})["result"]
        result.extend(body["certificates"])
        page_count = body["page_count"]
        if page >= page_count:
            break
        page += 1
    if len({str(x["certificate_id"]) for x in result}) != len(result):
        raise RuntimeError("Ozon certificate list contains duplicate IDs")
    return result


def exact_records(certs: list[dict], action: dict) -> list[dict]:
    return [c for c in certs if c.get("type_code") == action["type_code"]
            and doc_identity(c.get("certificate_number", "")) == doc_identity(action["number"])]


def execute(plan: dict) -> dict:
    run = {"started_at": now(), "actions": []}
    save(OUT_RUN, run)
    client = Client()
    expected_products = {offer: product for action in plan["actions"]
                        for offer, product in action.get("offers", {}).items()}
    live_info = client.call("ozon", "/v3/product/info/list", {"offer_id": sorted(expected_products)}).get("items", [])
    by_offer = {str(x.get("offer_id")): x for x in live_info if isinstance(x, dict)}
    if set(by_offer) != set(expected_products):
        raise RuntimeError("Current Ozon product info does not exactly cover planned offers")
    for offer, expected in expected_products.items():
        current = by_offer[offer]
        current_id = str(current.get("product_id") or current.get("id") or "")
        if (current_id != str(expected["product_id"]) or str(current.get("sku")) != str(expected["sku"])
                or current.get("is_archived")):
            raise RuntimeError(f"Ozon offer/product/SKU mapping changed since plan: {offer}")
    for action in plan["actions"]:
        if action["action"] == "already_bound":
            run["actions"].append({"number": action["number"], "outcome": "already_bound"})
            save(OUT_RUN, run)
            continue
        if action["action"].startswith("blocked_") or action["action"] == "already_attached_pending_or_declined":
            run["actions"].append({"number": action["number"], "outcome": action["action"]})
            save(OUT_RUN, run)
            continue

        fresh = list_certificates(client)
        matches = exact_records(fresh, action)
        if len(matches) > 1:
            raise RuntimeError(f"Multiple live Ozon entries for {action['number']}; reconcile manually")
        if matches:
            cert = matches[0]
            if cert.get("status_code") != "approved":
                run["actions"].append({"number": action["number"], "outcome": "blocked_live_pending_or_declined",
                                       "certificate_id": cert.get("certificate_id"), "status": cert.get("status_code")})
                save(OUT_RUN, run)
                continue
            bindings = client.ozon_bindings(cert["certificate_id"])
            attached = {(str(x.get("sku")), str(x.get("product_id"))): x for x in bindings}
            missing = [v for v in action["offers"].values()
                       if (str(v["sku"]), str(v["product_id"])) not in attached]
            if not missing:
                outcome = "already_bound_after_fresh_read"
                run["actions"].append({"number": action["number"], "outcome": outcome,
                                       "certificate_id": cert["certificate_id"], "bindings": bindings})
                save(OUT_RUN, run)
                continue
            # Existing pending or declined pairs need diagnosis; never rebind them blindly.
            bad = [attached[(str(v["sku"]), str(v["product_id"]))] for v in missing
                   if (str(v["sku"]), str(v["product_id"])) in attached]
            if bad:
                run["actions"].append({"number": action["number"], "outcome": "blocked_existing_pair_not_approved",
                                       "certificate_id": cert["certificate_id"], "pairs": bad})
                save(OUT_RUN, run)
                continue
            body = client.call("ozon", "/v1/product/certificate/bind", {
                "certificate_id": int(cert["certificate_id"]),
                "skus": sorted({str(v["sku"]) for v in missing}),
            }, mutation=True)
            if body.get("result") is not True:
                run["actions"].append({"number": action["number"], "outcome": "bind_response_not_true",
                                       "certificate_id": cert["certificate_id"], "response": body})
                save(OUT_RUN, run)
                raise RuntimeError("Ozon bind response needs reconciliation")
            fresh_bindings = client.ozon_bindings(cert["certificate_id"])
            after = {(str(x.get("sku")), str(x.get("product_id"))): x for x in fresh_bindings}
            wanted = {(str(v["sku"]), str(v["product_id"])) for v in missing}
            if not wanted.issubset(after):
                outcome = "bind_accepted_but_missing_on_readback"
            else:
                outcome = "bound_and_readback_present"
            run["actions"].append({"number": action["number"], "outcome": outcome,
                                   "certificate_id": cert["certificate_id"], "response": body,
                                   "new_bindings": [after[x] for x in sorted(wanted) if x in after]})
            save(OUT_RUN, run)
            if outcome != "bound_and_readback_present":
                raise RuntimeError("Ozon bind readback incomplete")
            continue

        if action["action"] == "bind_missing":
            run["actions"].append({"number": action["number"], "outcome": "blocked_stale_plan_no_live_record"})
            save(OUT_RUN, run)
            continue

        path = Path(action["file"])
        if not path.is_file() or digest(path).lower() != action["file_sha256"]:
            raise RuntimeError(f"Source file changed before upload: {path}")
        if len(action["offers"]) != 1:
            raise RuntimeError("This continuation intentionally creates one document per exact offer batch")
        start = dt.date.fromisoformat(action["issue_date"])
        end = dt.date.fromisoformat(action["expire_date"])
        params = {
            "name": ("Декларация о соответствии № " if action["type_code"] == "declaration" else "Сертификат соответствия № ") + action["number"],
            "certificate_type": action["ozon_create_type"],
            "certificate_country": action["certificate_country"],
            "accordance_type": action["accordance_type"],
            "number": action["number"],
            "issue_date": start.isoformat() + "T00:00:00Z",
            "expired_date": {"date": {"day": end.day, "month": end.month, "year": end.year}},
            "skus": sorted({str(v["sku"]) for v in action["offers"].values()}),
            "product_type": "UNKNOWN",
            "files": [{"file_content": base64.b64encode(path.read_bytes()).decode("ascii"), "name": path.name}],
        }
        if len(json.dumps({"params": params}, ensure_ascii=False).encode()) > 15_000_000:
            raise RuntimeError("Ozon create payload exceeds previously observed transport ceiling")
        # Reconcile once more immediately before create; a matching record blocks duplication.
        before = list_certificates(client)
        if exact_records(before, action):
            raise RuntimeError(f"Record appeared during preflight for {action['number']}; do not create")
        try:
            body = client.call("ozon", "/v2/product/certificate/create", {"params": params}, mutation=True)
        except Exception as exc:
            run["actions"].append({"number": action["number"], "outcome": "uncertain_mutation",
                                   "error_type": type(exc).__name__})
            save(OUT_RUN, run)
            raise
        record = {"number": action["number"], "response": body,
                  "certificate_id": body.get("certificate_id"), "status": body.get("status"),
                  "invalid_params": [x for x in body.get("params", []) if x.get("state") == "INVALID"]}
        record["outcome"] = "create_completed" if body.get("certificate_id") and body.get("status") == "COMPLETED" and not record["invalid_params"] else "create_incomplete"
        run["actions"].append(record)
        save(OUT_RUN, run)
        if record["outcome"] != "create_completed":
            raise RuntimeError("Ozon did not confirm a complete create; reconcile before any repeat")
        certs_after = list_certificates(client)
        matches_after = exact_records(certs_after, action)
        if len(matches_after) != 1:
            record["outcome"] = "create_needs_reconciliation"
            record["matching_records"] = len(matches_after)
            save(OUT_RUN, run)
            raise RuntimeError("Created document not present exactly once in live certificate list")
        fresh = matches_after[0]
        bindings = client.ozon_bindings(fresh["certificate_id"])
        wanted = {(str(v["sku"]), str(v["product_id"])) for v in action["offers"].values()}
        after = {(str(x.get("sku")), str(x.get("product_id"))): x for x in bindings}
        record.update({"certificate_id": fresh["certificate_id"], "live_status": fresh.get("status_code"),
                       "live_binding_readback": [after[x] for x in sorted(wanted) if x in after],
                       "all_target_pairs_present": wanted.issubset(after)})
        record["outcome"] = "created_and_bound_readback_present" if record["all_target_pairs_present"] else "create_binding_readback_incomplete"
        save(OUT_RUN, run)
        if not record["all_target_pairs_present"]:
            raise RuntimeError("New Ozon document is not bound to every target SKU on readback")
    run["finished_at"] = now()
    save(OUT_RUN, run)
    return run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    plan = make_plan()
    save(OUT_PLAN, plan)
    summary = collections.Counter(x["action"] for x in plan["actions"])
    print(json.dumps({"actions": dict(summary), "documents": len(plan["actions"]),
                      "excluded_rows": len(plan["excluded"]), "plan": str(BASE / OUT_PLAN)}, ensure_ascii=False))
    if args.execute:
        print(json.dumps(execute(plan), ensure_ascii=False))


if __name__ == "__main__":
    main()
