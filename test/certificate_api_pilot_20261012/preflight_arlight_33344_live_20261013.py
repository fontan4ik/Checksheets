"""Fresh read-only preflight for Arlight declaration ЕАЭС N RU Д-CN.РА03.В.33344/26."""
from __future__ import annotations
import collections, csv, hashlib, json, re
from pathlib import Path
from api_client import BASE, Client, now, save

NUMBER = "ЕАЭС N RU Д-CN.РА03.В.33344/26"
BASE_NUMBER = "RU Д-CN.РА03.В.33344/26"
FSA_ID = 21321061
FSA_URL = f"https://pub.fsa.gov.ru/rds/declaration/view/{FSA_ID}/product"
FSA_CODE = "8537109800"
SOURCE_CSV = Path("output_to_user/certificates/document_assignments.csv")


def norm(value: object) -> str:
    table = str.maketrans({"А":"A","В":"B","Е":"E","К":"K","М":"M","Н":"H","О":"O","Р":"P","С":"C","Т":"T","У":"Y","Х":"X","Ё":"E","Э":"E","Д":"D","П":"P"})
    s = str(value or "").upper().translate(table)
    s = re.sub(r"^(?:EAEU|EAC|EAEC)", "", s)
    return "".join(ch for ch in s if ch.isalnum())


def parse_code(values):
    return sorted({str(v).split(" - ", 1)[0].strip() for v in values if str(v).strip()})


def load_targets():
    targets = {}
    with SOURCE_CSV.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            raw = row.get("Номер/название документа", "")
            if norm(raw) != norm(BASE_NUMBER) or row.get("Бренд подтвержденный") != "Arlight":
                continue
            offer = row.get("Артикул продавца", "").strip()
            if not offer:
                raise RuntimeError("assignment row has no offer id")
            item = {"offer_id": offer, "name": row.get("Название товара Ozon", ""),
                    "brand": row.get("Бренд подтвержденный", ""),
                    "local_file": row.get("Локальный файл", ""),
                    "source_url": row.get("URL документа", ""),
                    "applicability": row.get("Применимость", ""),
                    "validity": row.get("Сроки/валидность", "")}
            prev = targets.get(offer)
            if prev and prev != item:
                raise RuntimeError(f"conflicting assignment rows for {offer}")
            targets[offer] = item
    if not targets:
        raise RuntimeError("no exact assignments found")
    return targets


def get_ozon_products(client, offers):
    out = {}
    for i in range(0, len(offers), 100):
        body = client.call("ozon", "/v3/product/info/list", {"offer_id": offers[i:i+100]})
        rows = body.get("items") or body.get("result", {}).get("items")
        if not isinstance(rows, list):
            raise RuntimeError("malformed Ozon product list")
        for row in rows:
            offer = str(row.get("offer_id") or "")
            if not offer or offer in out:
                raise RuntimeError("missing/duplicate Ozon offer identity")
            out[offer] = row
    if set(out) != set(offers):
        raise RuntimeError(f"Ozon offers incomplete: {len(set(offers)-set(out))} missing")
    return out


def get_ozon_attrs(client, offers):
    out = {}
    for i in range(0, len(offers), 100):
        batch = offers[i:i+100]
        body = client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": batch}, "limit": len(batch)})
        rows = body.get("result") or body.get("items")
        if not isinstance(rows, list):
            raise RuntimeError("malformed Ozon attributes")
        for row in rows:
            offer = str(row.get("offer_id") or "")
            if not offer or offer in out:
                raise RuntimeError("missing/duplicate Ozon attribute identity")
            vals = {str(x.get("id")): x for x in row.get("attributes") or []}
            out[offer] = {
                "brand": [str(x.get("value") or "") for x in (vals.get("85") or {}).get("values") or []],
                "tnved_values": [str(x.get("value") or "") for x in (vals.get("22232") or {}).get("values") or []],
            }
            out[offer]["tnved_codes"] = parse_code(out[offer]["tnved_values"])
    if set(out) != set(offers):
        raise RuntimeError(f"Ozon attributes incomplete: {len(set(offers)-set(out))} missing")
    return out


def list_ozon_certificates(client):
    all_rows=[]
    for page in range(1,101):
        body=client.call("ozon", "/v1/product/certificate/list", {"page":page,"page_size":100}).get("result",{})
        rows=body.get("certificates")
        if not isinstance(rows,list): raise RuntimeError("malformed certificate list")
        all_rows.extend(rows)
        if len(rows)<100:
            ids=[str(x.get("certificate_id")) for x in all_rows]
            if len(ids)!=len(set(ids)): raise RuntimeError("duplicate certificate IDs")
            return all_rows
    raise RuntimeError("certificate pagination exceeded limit")


def main():
    targets=load_targets(); offers=sorted(targets)
    client=Client()
    products=get_ozon_products(client,offers)
    attrs=get_ozon_attrs(client,offers)
    ozon_docs=list_ozon_certificates(client)
    matching=[x for x in ozon_docs if norm(x.get("certificate_number"))==norm(NUMBER)]
    rows=[]
    for offer in offers:
        cards=client.wb_cards(offer)
        product=products[offer]; attr=attrs[offer]
        wb=[]
        for card in cards:
            chars=card.get("characteristics") or []
            trows=[x for x in chars if str(x.get("id"))=="15000001"]
            vals=[str(v) for row in trows for v in (row.get("value") or [])]
            docs=card.get("documents") or card.get("docs") or {}
            wb.append({"nmID":str(card.get("nmID") or ""),"vendorCode":str(card.get("vendorCode") or ""),
                       "brand":card.get("brand"),"tnved_values":vals,"tnved_codes":parse_code(vals),
                       "excludeDocuments":docs.get("excludeDocuments"),
                       "documents":[{"type":d.get("type"),"number":d.get("number"),"startDate":d.get("startDate"),"endDate":d.get("endDate"),"verdict":d.get("verdict")}
                                    for d in (docs.get("items") or [])]})
        rows.append({"offer_id":offer,"name":product.get("name"),"product_id":str(product.get("id") or ""),
                     "sku":str(product.get("sku") or ""),"is_archived":bool(product.get("is_archived")),
                     "assignment_name":targets[offer]["name"],"assignment_brand":targets[offer]["brand"],
                     "ozon_brand":attr["brand"],"ozon_tnved_values":attr["tnved_values"],"ozon_tnved_codes":attr["tnved_codes"],
                     "ozon_code_in_fsa_scope":FSA_CODE in attr["tnved_codes"],"wb_card_count":len(wb),"wb_cards":wb})
    wb_nmids=[c["nmID"] for x in rows for c in x["wb_cards"]]
    count=collections.Counter(c["verdict"] or "NO_VERDICT" for x in rows for c in x["wb_cards"]
                              for d in c["documents"] if norm(d["number"])==norm(NUMBER))
    wrong_codes=[x for x in rows if x["ozon_tnved_codes"] and FSA_CODE not in x["ozon_tnved_codes"]]
    missing_ozon_attrs=[x["offer_id"] for x in rows if not x["ozon_tnved_codes"]]
    duplicate_cards=[n for n,c in collections.Counter(wb_nmids).items() if c>1]
    summary={"checked_at_utc":now(),"read_only":True,"number":NUMBER,"base_number":BASE_NUMBER,
             "fsa":{"record_id":FSA_ID,"url":FSA_URL,"status":"Действует","registered":"2026-04-13","expires":"2031-04-09",
                    "scope":"Dimmers/microdimmers, Arlight and INTELLIGENT ARLIGHT; series SMART, SR, LN, TY, TUYA, MATTER, ZB, DALI, KNX, ARL, VT, WF, TRIAC, SENS",
                    "tnved":[FSA_CODE],"source":"official FSA registry page read in browser"},
             "assignment_count":len(targets),"live_ozon_products":len(products),"live_ozon_attrs":len(attrs),
             "ozon_matching_document_records":[{k:v for k,v in x.items() if k not in ("certificate_file","file_content")} for x in matching],
             "ozon_brand_mismatch_count":sum(x["ozon_brand"]!=["Arlight"] for x in rows),
             "ozon_code_in_scope_count":sum(x["ozon_code_in_fsa_scope"] for x in rows),"ozon_code_conflict_count":len(wrong_codes),
             "ozon_code_missing_count":len(missing_ozon_attrs),"wb_card_count":sum(x["wb_card_count"] for x in rows),
             "wb_target_missing_card_count":sum(x["wb_card_count"]==0 for x in rows),"wb_duplicate_nmids":duplicate_cards,
             "wb_existing_matching_document_verdicts":dict(count),"targets":rows}
    summary["preflight_eligible"]=(len(matching)==0 and len(products)==len(targets) and len(attrs)==len(targets)
                                   and summary["ozon_brand_mismatch_count"]==0 and summary["ozon_code_in_scope_count"]==len(targets)
                                   and not wrong_codes and not missing_ozon_attrs and not summary["wb_target_missing_card_count"]
                                   and not duplicate_cards)
    save("arlight_33344_live_preflight_20261013.json",summary)
    print(json.dumps({k:v for k,v in summary.items() if k!="targets"},ensure_ascii=False,indent=2))
    print("TARGET_EXAMPLE",json.dumps(rows[:5],ensure_ascii=False,indent=2))

if __name__=="__main__": main()
