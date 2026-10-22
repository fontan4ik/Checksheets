"""Fresh read-only reconciliation for every 53483/22 target on Ozon and WB."""
import collections
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE))
from api_client import Client, now, save

NUMBER = "ЕАЭС N RU Д-CN.РА06.В.53483/22"
CERTIFICATE_ID = 5648411
SOURCE = json.loads((BASE / "brand_certificate_coverage_recheck_20261013_1200.json").read_text(encoding="utf-8"))
DOC = next(x for x in SOURCE["documents"] if x["number"] == NUMBER)
TARGETS = DOC["targets"]
client = Client()

def norm_document(value):
    visual = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "M",
                            "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
                            "У": "Y", "Х": "X", "Д": "D"})
    return "".join(ch for ch in str(value or "").upper().translate(visual) if ch.isalnum())

info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER}).get("result")
if not isinstance(info, dict):
    raise RuntimeError("Ozon certificate info response is missing")
all_bindings = []
last_id = 0
expected_count = None
while True:
    page = client.call("ozon", "/v1/product/certificate/products/list", {
        "certificate_id": CERTIFICATE_ID, "last_id": last_id, "limit": 1000})["result"]
    items = page.get("items")
    count = page.get("count")
    if not isinstance(items, list) or not isinstance(count, int):
        raise RuntimeError("Ozon binding page is incomplete")
    if expected_count is None:
        expected_count = count
    elif expected_count != count:
        raise RuntimeError("Ozon binding count changed during pagination")
    all_bindings.extend(items)
    if len(all_bindings) == expected_count:
        break
    if not items or len(all_bindings) > expected_count:
        raise RuntimeError("Ozon binding pagination is incomplete")
    last_id = items[-1]["product_id"]

product_info = client.call("ozon", "/v3/product/info/list", {"offer_id": [x["offer_id"] for x in TARGETS]})
items = product_info.get("items") or product_info.get("result", {}).get("items")
if not isinstance(items, list):
    raise RuntimeError("Ozon product info list is missing")
products = {str(x.get("offer_id")): x for x in items}

binding_by_sku = collections.defaultdict(list)
for b in all_bindings:
    binding_by_sku[str(b.get("sku"))].append(b)

wb_cards = []
for t in TARGETS:
    offer = t["offer_id"]
    cards = [c for c in client.wb_cards(offer) if c.get("vendorCode") == offer]
    expected_nmid = str(t.get("wb_nmID") or "")
    exact_cards = [c for c in cards if not expected_nmid or str(c.get("nmID")) == expected_nmid]
    card_rows = []
    for c in exact_cards:
        doc_list = (c.get("documents") or {}).get("items") or []
        matching = [d for d in doc_list if d.get("type") == 2 and
                    norm_document(d.get("number")) == norm_document(NUMBER)]
        card_rows.append({
            "nmID": str(c.get("nmID")), "updatedAt": c.get("updatedAt"),
            "matching_rows": [{"type": d.get("type"), "number": d.get("number"), "startDate": d.get("startDate"),
                               "endDate": d.get("endDate"), "isEndless": d.get("isEndless"), "verdict": d.get("verdict")}
                              for d in matching],
            "overallVerdict": (c.get("documents") or {}).get("overallVerdict"),
            "excludeDocuments": (c.get("documents") or {}).get("excludeDocuments"),
        })
    wb_cards.append({"offer_id": offer, "expected_nmID": expected_nmid, "cards_found": len(cards),
                     "exact_cards_found": len(exact_cards), "cards": card_rows})

exact_targets = []
for t in TARGETS:
    product = products.get(t["offer_id"], {})
    binds = binding_by_sku.get(str(t["sku"]), [])
    exact_targets.append({
        "offer_id": t["offer_id"], "expected_product_id": str(t["product_id"]), "live_product_id": str(product.get("id") or ""),
        "expected_sku": str(t["sku"]), "live_sku": str(product.get("sku") or ""),
        "is_archived": product.get("is_archived"),
        "binding_rows": [{"product_id": str(b.get("product_id")), "sku": str(b.get("sku")),
                          "status": b.get("product_status_code")} for b in binds],
    })

result = {
    "checked_at_utc": now(), "read_only": True, "number": NUMBER, "certificate_id": CERTIFICATE_ID,
    "ozon_record": {"certificate_id": info.get("certificate_id"), "certificate_number": info.get("certificate_number"),
                    "type_code": info.get("type_code"), "status_code": info.get("status_code"),
                    "issue_date": info.get("issue_date"), "expire_date": info.get("expire_date")},
    "expected_target_count": len(TARGETS), "ozon_live_binding_count": len(all_bindings),
    "ozon_binding_status_counts": dict(collections.Counter(str(x.get("product_status_code")) for x in all_bindings)),
    "ozon_exact_pairs": exact_targets,
    "ozon_all_exact_pairs_approved": len(exact_targets) == 40 and all(
        x["expected_product_id"] == x["live_product_id"] and x["expected_sku"] == x["live_sku"] and
        x["is_archived"] is False and len(x["binding_rows"]) == 1 and
        x["binding_rows"][0]["product_id"] == x["expected_product_id"] and
        x["binding_rows"][0]["status"] == "approved" for x in exact_targets),
    "wb_cards": wb_cards,
    "wb_all_exact_rows_finally_valid": len(wb_cards) == 40 and all(
        x["cards_found"] == 1 and x["exact_cards_found"] == 1 and len(x["cards"][0]["matching_rows"]) == 1 and
        x["cards"][0]["matching_rows"][0]["startDate"] == "2022-09-15T00:00:00Z" and
        x["cards"][0]["matching_rows"][0]["endDate"] == "2027-09-14T00:00:00Z" and
        (x["cards"][0]["matching_rows"][0]["verdict"] or {}).get("verified") is True and
        (x["cards"][0]["matching_rows"][0]["verdict"] or {}).get("status") == 1 and
        x["cards"][0]["excludeDocuments"] is False for x in wb_cards),
}
save("feron_53483_crossplatform_final_recheck_20261013.json", result)
print(json.dumps({k: v for k, v in result.items() if k not in ("ozon_exact_pairs", "wb_cards")}, ensure_ascii=False, indent=2))
