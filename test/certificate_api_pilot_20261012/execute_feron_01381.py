"""Bind only the verified missing FERON 01381/22 SKU set to an existing record."""
from __future__ import annotations

import json
import sys

from api_client import BASE, Client, digest, now, save
from prepare_feron_01381 import bindings, list_certificates, live_products, norm, read_rows


def main(execute: bool = False) -> None:
    plan_path = BASE / "feron_01381_plan.json"
    log_path = BASE / "feron_01381_execution.json"
    if not plan_path.is_file():
        raise RuntimeError("Fresh preflight plan is missing")
    if log_path.exists():
        raise RuntimeError("Execution journal exists; reconcile current Ozon bindings before any continuation")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    workbook = plan["workbook"]
    local_file = plan["original_file"]
    if digest(workbook) != plan["workbook_sha256"] or digest(local_file) != plan["original_file_sha256"]:
        raise RuntimeError("Workbook or verified original file changed after preflight")
    rows = read_rows()
    eligible = [row for row in rows if row.get("J") == "Основной реестр"
                and row.get("K", "").startswith("Действует в ФСА до 2027-09-07")
                and row.get("M", "").startswith("Действует;") and not row.get("O")
                and row.get("N") in {"карточка Feron", "серия/модель",
                                     "серия/модель прямо указана в официальном скане и каталоге Feron"}
                and "Feron" in row.get("P", "") and "01381" in row.get("P", "")]
    if len(eligible) != plan["eligible_offer_count"]:
        raise RuntimeError("Eligible workbook rows changed after preflight")
    client = Client()
    current_products = live_products(client, eligible)
    planned_products = plan["offer_to_identity"]
    if any(current_products[o]["product_id"] != planned_products[o]["product_id"]
           or current_products[o]["sku"] != planned_products[o]["sku"]
           or current_products[o]["is_archived"]
           for o in planned_products):
        raise RuntimeError("Ozon catalog changed since preflight")
    certificates = list_certificates(client)
    matching = [item for item in certificates if item.get("type_code") == "certificate_of_conformity"
                and norm(item.get("certificate_number")) == norm(plan["number"])]
    allowed_ids = {row["certificate_id"] for row in plan["matching_existing_records"]}
    if {str(item["certificate_id"]) for item in matching} != allowed_ids:
        raise RuntimeError("Matching Ozon certificate records changed since preflight")
    by_id = {str(item["certificate_id"]): item for item in matching}
    if any(by_id[cid].get("status_code") != "approved" for cid in allowed_ids):
        raise RuntimeError("A matching certificate is no longer approved")
    current_bindings: dict[str, list[dict]] = {}
    covered: dict[str, dict] = {}
    for cert in matching:
        cid = str(cert["certificate_id"])
        current_bindings[cid] = bindings(client, int(cid))
        for item in current_bindings[cid]:
            sku = str(item.get("sku", ""))
            if sku in plan["target_sku_to_product_id"]:
                expected_id = plan["target_sku_to_product_id"][sku]
                if str(item.get("product_id", "")) != expected_id:
                    raise RuntimeError(f"Existing binding identity conflict for SKU {sku}")
                covered.setdefault(sku, {"certificate_id": cid,
                                         "product_status_code": item.get("product_status_code")})
    actual_missing = sorted(set(plan["target_sku_to_product_id"]) - set(covered))
    if actual_missing != plan["missing_skus"]:
        raise RuntimeError("Ozon current binding set differs from prepared plan; rebuild rather than send stale set")
    if not execute:
        print(json.dumps({"ready": True, "planned_missing_skus": len(actual_missing),
                          "selected_certificate_id": plan["selected_certificate_id"],
                          "existing_records": len(matching)}, ensure_ascii=False), flush=True)
        return
    state = {
        "started_at": now(),
        "phase": "prepared",
        "certificate_id": plan["selected_certificate_id"],
        "number": plan["number"],
        "planned_skus": len(actual_missing),
        "batch_size": 500,
        "results": [],
    }
    save("feron_01381_execution.json", state)
    selected = int(plan["selected_certificate_id"])
    for offset in range(0, len(actual_missing), state["batch_size"]):
        batch = actual_missing[offset:offset + state["batch_size"]]
        entry = {"index": len(state["results"]) + 1, "offset": offset,
                 "sku_count": len(batch), "first_sku": batch[0], "last_sku": batch[-1],
                 "phase": "prepared"}
        state["results"].append(entry)
        save("feron_01381_execution.json", state)
        try:
            body = client.call("ozon", "/v1/product/certificate/bind",
                               {"certificate_id": selected, "skus": batch}, mutation=True)
        except Exception as exc:
            entry.update(phase="uncertain", error_type=type(exc).__name__)
            state["phase"] = "uncertain"
            save("feron_01381_execution.json", state)
            raise RuntimeError("Ozon bind outcome uncertain; reconcile live state before retry") from None
        entry["response"] = body
        entry["phase"] = "accepted" if body.get("result") is True else "rejected"
        state["phase"] = "writing"
        save("feron_01381_execution.json", state)
        print(json.dumps({"batch": entry["index"], "phase": entry["phase"],
                          "sku_count": len(batch), "response": body}, ensure_ascii=False)[:1200], flush=True)
        if entry["phase"] != "accepted":
            state["phase"] = "rejected"
            save("feron_01381_execution.json", state)
            raise RuntimeError("Ozon rejected bind batch; reconcile before any further write")
    state["phase"] = "all_batches_accepted"
    state["finished_at"] = now()
    save("feron_01381_execution.json", state)
    print(json.dumps({"phase": state["phase"], "batches": len(state["results"]),
                      "bound_skus": sum(x["sku_count"] for x in state["results"])}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main("--execute" in sys.argv)
