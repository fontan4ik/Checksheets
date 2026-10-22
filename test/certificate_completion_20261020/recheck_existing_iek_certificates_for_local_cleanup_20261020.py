"""Read-only live verification for older Ozon-held IEK PDFs before cleanup."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client  # noqa: E402

AUDIT = HERE / "iek_current_ozon_docs_audit_20261020.json"
MANIFEST = HERE / "iek_validated_binding_manifest_20261020.json"
OUT = HERE / "existing_iek_certificates_cleanup_recheck_20261020.json"


def wb_search(client: Client, article: str) -> list[dict]:
    cards: list[dict] = []
    cursor = {"limit": 100}
    seen: set[tuple[str, int]] = set()
    while True:
        data = client.call("wb", "/content/v2/get/cards/list", {"settings": {
            "sort": {"ascending": True}, "cursor": cursor,
            "filter": {"withPhoto": -1, "textSearch": article},
        }})
        if data.get("error") or not isinstance(data.get("cards"), list):
            raise RuntimeError("WB textSearch returned an invalid card list")
        batch = data["cards"]
        cards.extend(batch)
        returned = data.get("cursor") or {}
        if returned.get("total") != len(batch):
            raise RuntimeError("WB result count did not match the returned page")
        if len(batch) < 100:
            return cards
        signature = (returned.get("updatedAt"), returned.get("nmID"))
        if None in signature or signature in seen:
            raise RuntimeError("WB cursor repeated or was incomplete")
        seen.add(signature)
        cursor = {"limit": 100, "updatedAt": signature[0], "nmID": signature[1]}


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    audit_by_number = {row["number"]: row for row in audit["groups"]}
    targets_by_number = {row["number"]: row["targets"] for row in manifest["groups"]}
    wanted_numbers = sorted(targets_by_number)
    client = Client()

    offer_articles: dict[str, str] = {}
    for number in wanted_numbers:
        for row in audit_by_number[number]["offers"]:
            offer_articles[str(row["offer_id"])] = str(row.get("article") or row["offer_id"])

    wb_rows = []
    for offer, article in offer_articles.items():
        cards = wb_search(client, article)
        hits = []
        needle = article.casefold()
        for card in cards:
            vendor = str(card.get("vendorCode") or "")
            title = str(card.get("title") or "")
            if needle in vendor.casefold() or needle in title.casefold() or vendor.casefold() in needle:
                hits.append({"nmID": card.get("nmID"), "vendorCode": vendor,
                             "brand": card.get("brand"), "title": title})
        wb_rows.append({"offer_id": offer, "article": article,
                        "returned_cards": len(cards), "relevant_cards": hits,
                        "exact_offer_cards": sum(row["vendorCode"] == offer for row in hits)})

    doc_rows = []
    for number in wanted_numbers:
        group = next(row for row in manifest["groups"] if row["number"] == number)
        bindings = client.ozon_bindings(group["certificate_id"])
        by_pid = {str(row.get("product_id")): row for row in bindings}
        expected = []
        for target in targets_by_number[number]:
            binding = by_pid.get(str(target["product_id"]))
            expected.append({"offer_id": target["offer_id"],
                             "product_id": str(target["product_id"]),
                             "sku": str(target["sku"]),
                             "exact_binding_visible": bool(binding and str(binding.get("sku")) == str(target["sku"])),
                             "product_status_code": binding.get("product_status_code") if binding else None})
        doc_rows.append({
            "number": number, "certificate_id": str(group["certificate_id"]),
            "ozon_binding_count": len(bindings),
            "ozon_binding_statuses": {status: sum(row.get("product_status_code") == status for row in bindings)
                                      for status in sorted({str(row.get("product_status_code") or "unknown") for row in bindings})},
            "expected_targets": expected,
            "all_expected_links_approved": len(expected) == len(targets_by_number[number]) and
                all(row["exact_binding_visible"] and row["product_status_code"] == "approved" for row in expected),
            "all_live_ozon_links_approved": bool(bindings) and all(row.get("product_status_code") == "approved" for row in bindings),
            "local_pdf": audit_by_number[number]["local_pdf"],
            "local_pdf_sha256": audit_by_number[number]["downloaded_sha256"],
        })

    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "wb_articles_checked": len(wb_rows),
        "wb_articles_with_relevant_cards": sum(bool(row["relevant_cards"]) for row in wb_rows),
        "ozon_documents_checked": len(doc_rows),
        "documents_with_all_expected_links_approved": sum(row["all_expected_links_approved"] for row in doc_rows),
        "documents_with_all_live_links_approved": sum(row["all_live_ozon_links_approved"] for row in doc_rows),
        "documents": doc_rows,
        "wb_article_results": wb_rows,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in ("documents", "wb_article_results")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
