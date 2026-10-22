"""Independently reread Ozon certificate and product bindings after the 01381/22 write."""
from __future__ import annotations

import collections
import json
from pathlib import Path

from api_client import Client, now, save
from prepare_feron_01381 import bindings, list_certificates, live_products, norm, read_rows

BASE = Path(__file__).resolve().parent


def main() -> None:
    plan = json.loads((BASE / "feron_01381_plan.json").read_text(encoding="utf-8"))
    rows = read_rows()
    eligible = [row for row in rows if row.get("J") == "Основной реестр"
                and row.get("K", "").startswith("Действует в ФСА до 2027-09-07")
                and row.get("M", "").startswith("Действует;") and not row.get("O")
                and row.get("N") in {"карточка Feron", "серия/модель",
                                     "серия/модель прямо указана в официальном скане и каталоге Feron"}
                and "Feron" in row.get("P", "") and "01381" in row.get("P", "")]
    if len(eligible) != plan["eligible_offer_count"]:
        raise RuntimeError("Workbook eligibility changed after plan was created")
    client = Client()
    product_map = live_products(client, eligible)
    all_certs = list_certificates(client)
    matching = [item for item in all_certs if item.get("type_code") == "certificate_of_conformity"
                and norm(item.get("certificate_number")) == norm(plan["number"])]
    allowed_ids = {row["certificate_id"] for row in plan["matching_existing_records"]}
    if {str(item["certificate_id"]) for item in matching} != allowed_ids:
        raise RuntimeError("Unexpected set of matching Ozon certificates")
    target = plan["target_sku_to_product_id"]
    observations = {}
    outside = []
    by_id = {}
    for cert in matching:
        cid = str(cert["certificate_id"])
        rows_for_cert = bindings(client, int(cid))
        by_id[cid] = {"status_code": cert.get("status_code"), "live_binding_count": len(rows_for_cert)}
        for item in rows_for_cert:
            sku = str(item.get("sku", ""))
            product_id = str(item.get("product_id", ""))
            if sku not in target:
                outside.append({"certificate_id": cid, "sku": sku, "product_id": product_id})
                continue
            if product_id != target[sku]:
                raise RuntimeError(f"Live binding product ID mismatch for SKU {sku}")
            observations.setdefault(sku, []).append({"certificate_id": cid,
                                                     "product_status_code": item.get("product_status_code")})
    missing = sorted(set(target) - set(observations))
    identity_mismatches = []
    for offer, live in product_map.items():
        expected_sku = plan["target_offer_to_sku"][offer]
        if live["sku"] != expected_sku or live["product_id"] != plan["offer_to_identity"][offer]["product_id"]:
            identity_mismatches.append({"offer": offer, "expected_sku": expected_sku, "live": live})
    counts = collections.Counter(
        status for records in observations.values() for status in {r["product_status_code"] for r in records}
    )
    summary = {
        "checked_at": now(),
        "number": plan["number"],
        "target_offer_count": len(plan["target_offer_to_sku"]),
        "target_sku_count": len(target),
        "live_offer_identity_count": len(product_map),
        "identity_mismatch_count": len(identity_mismatches),
        "matching_certificate_records": by_id,
        "matching_certificate_records_all_approved": all(item.get("status_code") == "approved" for item in matching),
        "covered_sku_count": len(observations),
        "missing_skus": missing,
        "product_status_counts": dict(counts),
        "outside_target_bindings": outside,
        "all_target_skus_linked": not missing,
        "all_product_statuses_approved": not counts or set(counts) == {"approved"},
        "all_verified": not missing and not identity_mismatches
                       and all(item.get("status_code") == "approved" for item in matching)
                       and (not counts or set(counts) == {"approved"}),
        "sku_bindings": observations,
    }
    save("feron_01381_verification.json", summary)
    print(json.dumps({key: value for key, value in summary.items() if key != "sku_bindings"},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
