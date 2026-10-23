"""Fresh read-only recheck of WB cards previously missing exact vendor codes."""
from __future__ import annotations

import csv
import json
import pathlib
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import copy_documents, norm_number  # noqa: E402

EDGES = HERE / "verified_group_edges_current_latest_20261023.csv"
MANIFEST = HERE / "ready_found_documents_manifest_20261023.json"
OUT = HERE / "wb_unmatched_found_groups_fresh_recheck_20261023.json"


def card_tnved(card: dict) -> list[str]:
    out = []
    for row in card.get("characteristics") or []:
        name = "".join(str(row.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = row.get("value")
        for value in raw if isinstance(raw, list) else [raw]:
            if value:
                out.append(str(value).split(" - ", 1)[0].strip())
    return sorted(set(out))


def main() -> None:
    if OUT.exists():
        raise RuntimeError("output_exists")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    groups = {g["number"]: g for g in manifest["groups"]}
    with EDGES.open(encoding="utf-8-sig", newline="") as stream:
        edges = list(csv.DictReader(stream))
    selected = [r for r in edges if r.get("number") in groups
                and r.get("wb_state") == "no_exact_card"
                and r.get("ozon_state") == "approved_link"]
    if not selected:
        raise RuntimeError("no_current_unmatched_targets")

    client = Client()
    results = []
    for row in selected:
        group = groups[row["number"]]
        offer = str(row["offer_id"])
        cards = client.wb_cards(offer)
        details = []
        for card in cards:
            docs = copy_documents(card)
            same = [d for d in docs if norm_number(d.get("number")) == norm_number(group["number"])]
            expected_type = 1 if group["type_code"] == "certificate_of_conformity" else 2
            exact = (len(same) == 1 and int(same[0].get("type") or 0) == expected_type
                     and str(same[0].get("startDate", ""))[:10] == group["issue_date"]
                     and str(same[0].get("endDate", ""))[:10] == group["expire_date"])
            details.append({"nmID": str(card.get("nmID") or ""), "vendorCode": card.get("vendorCode"),
                            "brand": card.get("brand"), "title": card.get("title"),
                            "tnved_codes": card_tnved(card), "same_number_rows": same,
                            "already_exact": exact})
        results.append({"number": row["number"], "offer_id": offer,
                        "ozon_product_id": row.get("product_id"), "ozon_sku": row.get("sku"),
                        "ozon_edge_state_before_recheck": row.get("ozon_state"),
                        "previous_wb_nmID": row.get("wb_nmID"),
                        "previous_wb_state": row.get("wb_state"),
                        "current_exact_wb_card_count": len(cards), "cards": details})

    summary = Counter((r["number"], "exact_card_found" if r["current_exact_wb_card_count"] == 1 else
                       "missing_or_duplicate") for r in results)
    output = {"checked_at_utc": now(), "read_only": True, "target_count": len(selected),
              "groups": {n: {"previously_missing_card_target_count": sum(r["number"] == n for r in selected),
                             "current_exact_card_found": sum(r["number"] == n and r["current_exact_wb_card_count"] == 1 for r in results),
                             "still_missing_or_duplicate": sum(r["number"] == n and r["current_exact_wb_card_count"] != 1 for r in results)}
                         for n in sorted({r["number"] for r in selected})},
              "summary_by_group_and_state": {f"{k[0]}|{k[1]}": v for k,v in summary.items()},
              "results": results, "no_wb_mutation_attempted": True}
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k,v in output.items() if k != "results"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
