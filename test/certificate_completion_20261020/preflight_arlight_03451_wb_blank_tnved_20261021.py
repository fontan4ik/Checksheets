"""Read-only live preflight for Arlight 03451/22 WB cards with blank TN VED."""
from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number, copy_documents  # noqa: E402

INITIAL = HERE / "arlight_03451_preflight_live_20261021.json"
OZON_STATE = HERE / "arlight_03451_ozon_execution_20261021.json"
OUT = HERE / "arlight_03451_wb_blank_tnved_preflight_20261021.json"
NUMBER = "ЕАЭС RU С-HK.НА46.В.03451/22"
ISSUE = "2022-04-16"
EXPIRY = "2027-04-15"
TNVED = "8504408300"
CERT_ID = "5925989"
MODEL_RE = re.compile(r"\bAR(?:PJ|PV|J|V)-[A-Z0-9]+(?:-[A-Z0-9]+)*\b", re.I)


def save(value: dict) -> None:
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(OUT)


def tnved(card: dict) -> list[str]:
    values = []
    for char in card.get("characteristics") or []:
        name = "".join(str(char.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = char.get("value")
        values.extend(str(v or "").split(" - ", 1)[0].strip()
                      for v in (raw if isinstance(raw, list) else [raw]) if v)
    return sorted(set(values))


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_artifact_exists_reconcile_before_retry")
    initial = json.loads(INITIAL.read_text(encoding="utf-8"))
    ozon_state = json.loads(OZON_STATE.read_text(encoding="utf-8"))
    if (initial.get("read_only") is not True or initial.get("assignment_rows") != 462
            or initial.get("source_pdf_sha256") != "22f5bd0657cf8c55754b3bd0d73d102de1b9520d6c167242555ae63349398add"
            or ozon_state.get("phase") != "ozon_verified_complete"
            or str(ozon_state.get("certificate_id")) != CERT_ID
            or ozon_state.get("verified_target_pairs") != 462):
        raise RuntimeError("source_or_existing_cross_platform_evidence_incomplete")
    ozon_by_offer = {x["offer_id"]: x for x in initial.get("ozon_targets") or []}
    candidates = [x for x in initial.get("wb_targets") or []
                  if x.get("brand", "").strip().casefold() == "arlight"
                  and not x.get("tnved_codes")]
    if len(candidates) != 256 or len({x.get("offer_id") for x in candidates}) != 256:
        raise RuntimeError(f"unexpected_blank_tnved_target_count:{len(candidates)}")
    source_offers = {x.get("offer_id") for x in initial.get("wb_targets") or []}
    if any(x.get("offer_id") not in source_offers for x in candidates):
        raise RuntimeError("source_assignment_offer_missing")

    client = Client()
    info = client.call("ozon", "/v1/product/certificate/info", {
        "certificate_number": NUMBER
    }).get("result") or {}
    if (str(info.get("certificate_id")) != CERT_ID
            or norm_number(info.get("certificate_number")) != norm_number(NUMBER)
            or info.get("type_code") != "certificate_of_conformity"
            or str(info.get("issue_date", ""))[:10] != ISSUE
            or str(info.get("expire_date", ""))[:10] != EXPIRY
            or str(info.get("accordance_type_code", "")).upper() != "EAEU"
            or info.get("status_code") in {"declined", "rejected", "invalid", "cancelled"}):
        raise RuntimeError("ozon_certificate_live_metadata_conflict")
    bindings = client.ozon_bindings(int(CERT_ID))
    binding_by_id = {str(x.get("product_id")): x for x in bindings}
    if len(bindings) != 462 or len(binding_by_id) != 462:
        raise RuntimeError(f"ozon_live_binding_count_changed:{len(bindings)}")
    for row in candidates:
        product = ozon_by_offer.get(row["offer_id"])
        binding = binding_by_id.get(str(product.get("product_id") if product else ""))
        if (not product or not product.get("identity_matches") or not product.get("in_scope")
                or product.get("brand_values") != ["Arlight"]
                or product.get("tnved_codes") != [TNVED]
                or not binding or str(binding.get("sku")) != str(product.get("sku"))):
            raise RuntimeError("ozon_scope_or_binding_mismatch:" + str(row.get("offer_id")))

    rows = []
    reasons = collections.Counter()
    for index, planned in enumerate(sorted(candidates, key=lambda x: x["offer_id"]), 1):
        offer = str(planned["offer_id"])
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            row = {"offer_id": offer, "reason": "live_card_missing_or_ambiguous",
                   "live_card_count": len(cards)}
            rows.append(row); reasons[row["reason"]] += 1
            continue
        card = cards[0]
        product = ozon_by_offer[offer]
        ozon_models = sorted(set(x.upper() for x in MODEL_RE.findall(product.get("product_name") or "")))
        wb_title = str(card.get("title") or "")
        wb_models = sorted(set(x.upper() for x in MODEL_RE.findall(wb_title)))
        model_match = len(ozon_models) == 1 and ozon_models == wb_models
        identity = (str(card.get("vendorCode") or "") == offer
                    and str(card.get("nmID") or "") == str(planned.get("nmID") or ""))
        brand_ok = str(card.get("brand") or "").strip().casefold() == "arlight"
        blank_code = tnved(card) == []
        docs = copy_documents(card)
        same = [d for d in docs if norm_number(d.get("number")) == norm_number(NUMBER)]
        exact = [d for d in same if int(d.get("type") or 0) == 1
                 and str(d.get("startDate") or "")[:10] == ISSUE
                 and str(d.get("endDate") or "")[:10] == EXPIRY
                 and d.get("isEndless") is False]
        if not identity:
            reason = "live_identity_changed"
        elif not brand_ok:
            reason = "live_brand_changed"
        elif not blank_code:
            reason = "tnved_is_no_longer_blank_or_conflicting"
        elif not model_match:
            reason = "ozon_wb_model_not_exactly_matched"
        elif same and len(exact) == 1:
            reason = "already_exact_document_present"
        elif same:
            reason = "same_number_document_conflict"
        else:
            reason = "eligible_by_exact_offer_brand_model_and_ozon_scope"
        row = {"offer_id": offer, "nmID": str(card.get("nmID") or ""),
               "brand": card.get("brand"), "tnved_codes": tnved(card),
               "wb_title": wb_title, "ozon_product_name": product.get("product_name"),
               "ozon_models": ozon_models, "wb_models": wb_models,
               "model_match": model_match, "identity_matches": identity,
               "ozon_product_id": str(product.get("product_id")),
               "ozon_sku": str(product.get("sku")), "ozon_in_scope": product.get("in_scope"),
               "ozon_binding_verified": True, "matching_number_docs": len(same),
               "exact_matching_docs": len(exact), "reason": reason,
               "current_documents": docs}
        rows.append(row); reasons[reason] += 1
        if index % 50 == 0:
            print(json.dumps({"phase": "read_only_live_preflight", "checked": index,
                              "total": len(candidates), "reasons": dict(reasons)},
                             ensure_ascii=False), flush=True)
    eligible = [r for r in rows if r.get("reason") == "eligible_by_exact_offer_brand_model_and_ozon_scope"]
    output = {"checked_at": now(), "read_only": True, "certificate_number": NUMBER,
              "certificate_id": int(CERT_ID), "source_pdf_sha256": initial["source_pdf_sha256"],
              "ozon_certificate_live_info": info, "ozon_live_binding_count": len(bindings),
              "target_count": len(candidates), "checked_cards": len(rows),
              "eligible_for_add": len(eligible), "reason_counts": dict(reasons),
              "scope_basis": {"wb_exact_offer_and_nmID": True, "wb_brand": "Arlight",
                              "wb_tnved_blank": True, "ozon_exact_offer_brand_tnved": TNVED,
                              "ozon_binding_verified": True, "matching_model_in_current_titles": True},
              "cards": rows, "mutation_performed": False, "local_file_deleted": False}
    save(output)
    print(json.dumps({k: output[k] for k in ("checked_at", "target_count", "checked_cards",
                  "eligible_for_add", "reason_counts", "mutation_performed", "local_file_deleted")},
                  ensure_ascii=False, indent=2))
    if len(rows) != len(candidates):
        raise RuntimeError("incomplete_live_preflight")


if __name__ == "__main__":
    main()
