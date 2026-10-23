"""Verify and normalize the fresh WB cursor read against the prior full catalog."""
from __future__ import annotations
import collections, json, shutil, sys, time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client  # noqa: E402

RAW = HERE / "live_marketplaces_snapshot_resume_20261023.json"
OLD = ROOT / "test/certificate_completion_20261020/live_marketplaces_snapshot_reconciled_20261022.json"
OUT = HERE / "live_marketplaces_snapshot_reconciled_20261023.json"
BACKUP = HERE / "live_marketplaces_snapshot_raw_20261023.json"

def stamp(): return datetime.now(timezone.utc).isoformat()

def codes(card):
    result=[]
    for char in card.get("characteristics") or []:
        label="".join(str(char.get("name") or "").casefold().split()).replace("ё","е")
        if "тнвэд" not in label and "тнвед" not in label: continue
        raw=char.get("value"); result.extend(raw if isinstance(raw,list) else [raw])
    return tuple(sorted({str(x).split(" - ",1)[0].strip() for x in result if x not in (None,"")}))

def identity(card):
    return (str(card.get("vendorCode") or ""),str(card.get("brand") or ""),
            str(card.get("subjectID") or ""),str(card.get("subjectName") or ""))

def read_trash(client):
    path="/content/v2/get/cards/trash"; cursor={"limit":100}; seen=set(); cards=[]; pages=0
    while True:
        response=client.call("wb",path,{"settings":{"sort":{"ascending":True},"cursor":cursor}},mutation=False)
        data=response.get("data",response); batch=(data.get("cards") or data.get("items") or []) if isinstance(data,dict) else []
        returned=(data.get("cursor") or response.get("cursor") or {}) if isinstance(data,dict) else {}
        if response.get("error") or not isinstance(batch,list) or returned.get("total")!=len(batch):
            raise RuntimeError("Invalid WB trash page/cursor")
        pages+=1; cards.extend(batch)
        if len(batch)<100: break
        sig=(returned.get("trashedAt"),returned.get("nmID"))
        if None in sig or sig in seen: raise RuntimeError("WB trash cursor repeated or incomplete")
        seen.add(sig); cursor={"limit":100,"trashedAt":sig[0],"nmID":sig[1]}; time.sleep(.65)
    ids=[str(x.get("nmID") or "") for x in cards]
    if any(not x for x in ids) or len(set(ids))!=len(ids): raise RuntimeError("WB trash has missing/duplicate nmID")
    return cards,pages

def main():
    data=json.loads(RAW.read_text()); previous=json.loads(OLD.read_text())
    cards=data["wb_catalog"]["cards"]; old_cards=previous["wb_catalog"]["cards"]
    by_id=collections.defaultdict(list); old_by_id={str(c.get("nmID") or ""):c for c in old_cards}
    for card in cards: by_id[str(card.get("nmID") or "")].append(card)
    if "" in by_id or set(by_id)!=set(old_by_id):
        raise RuntimeError(f"WB nmID set differs: added={len(set(by_id)-set(old_by_id))}, removed={len(set(old_by_id)-set(by_id))}")
    normalized={}; duplicate_ids=[]; changed_docs=[]
    for nm_id,rows in by_id.items():
        reference=rows[0]
        for row in rows[1:]:
            if identity(row)!=identity(reference) or row.get("documents")!=reference.get("documents") or codes(row)!=codes(reference):
                raise RuntimeError(f"Cursor-overlap rows conflict for nmID {nm_id}")
        old=old_by_id[nm_id]
        if identity(reference)!=identity(old) or codes(reference)!=codes(old):
            raise RuntimeError(f"WB product identity/TN VED changed for nmID {nm_id}")
        if reference.get("documents")!=old.get("documents"): changed_docs.append(nm_id)
        if len(rows)>1: duplicate_ids.append(nm_id)
        normalized[nm_id]=max(rows,key=lambda x:str(x.get("updatedAt") or ""))
    if not BACKUP.exists(): shutil.copy2(RAW,BACKUP)
    trash,trash_pages=read_trash(Client())
    data["wb_catalog"].update(complete=True,checked_at=data["wb_catalog"].get("checked_at") or data.get("updated_at"),
        pages=200,raw_rows=len(cards),cards_read=len(normalized),duplicate_rows_removed=len(cards)-len(normalized),
        duplicate_nmids=duplicate_ids,id_set_compared_with_previous_complete_read=True,
        unique_id_set_matches_previous_complete_read=True,card_identity_and_tnved_stable=True,
        documents_changed_since_previous_read=len(changed_docs),document_changed_nmids=changed_docs,
        cards=list(normalized.values()))
    data["wb_trash"]={"complete":True,"checked_at":stamp(),"pages":trash_pages,"cards":trash}
    data["complete"]=all(data.get(k,{}).get("complete") is True for k in ("ozon_products","ozon_certificates","wb_catalog","wb_trash"))
    data["finished_at"]=stamp(); data["updated_at"]=data["finished_at"]
    OUT.write_text(json.dumps(data,ensure_ascii=False))
    print(json.dumps({"complete":data["complete"],"ozon_products":len(data["ozon_products"]["products"]),
        "ozon_certificates":len(data["ozon_certificates"]["certificates"]),"wb_cards":len(normalized),
        "wb_raw_rows":len(cards),"duplicate_rows_removed":len(cards)-len(normalized),
        "duplicate_nmids":duplicate_ids,"fresh_document_differences_vs_previous":len(changed_docs),
        "wb_trash":len(trash),"wb_trash_pages":trash_pages,"snapshot":str(OUT),"raw_backup":str(BACKUP)},ensure_ascii=False))

if __name__=="__main__": main()
