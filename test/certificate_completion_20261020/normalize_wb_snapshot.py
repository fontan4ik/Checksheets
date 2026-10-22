"""Normalize the complete WB cursor read after verifying cursor-overlap rows."""
from __future__ import annotations

import collections
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client  # noqa: E402

SNAPSHOT = HERE / "live_marketplaces_snapshot.json"
OLD = ROOT / "test/certificate_completion_20261019/live_marketplaces_snapshot.json"
RAW_BACKUP = HERE / "live_marketplaces_snapshot_raw_20261020.json"


def wb_codes(card: dict) -> tuple[str, ...]:
    values = []
    for char in card.get("characteristics") or []:
        label = "".join(str(char.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in label and "тнвед" not in label:
            continue
        raw = char.get("value")
        values.extend(raw if isinstance(raw, list) else [raw])
    return tuple(sorted({str(x).split(" - ", 1)[0].strip() for x in values if x not in (None, "")}))


def identity(card: dict) -> tuple:
    return (str(card.get("vendorCode") or ""), str(card.get("brand") or ""),
            str(card.get("subjectID") or ""), str(card.get("subjectName") or ""))


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_trash(client: Client) -> list[dict]:
    path = "/content/v2/get/cards/trash"
    cursor: dict = {"limit": 100}
    seen: set[tuple] = set()
    cards = []
    pages = 0
    while True:
        response = client.call("wb", path, {"settings": {"sort": {"ascending": True}, "cursor": cursor}}, mutation=False)
        data = response.get("data", response)
        batch = (data.get("cards") or data.get("items") or []) if isinstance(data, dict) else []
        returned = (data.get("cursor") or response.get("cursor") or {}) if isinstance(data, dict) else {}
        if response.get("error") or not isinstance(batch, list) or returned.get("total") != len(batch):
            raise RuntimeError("Invalid WB trash page/cursor")
        pages += 1
        cards.extend(batch)
        if len(batch) < 100:
            break
        signature = (returned.get("trashedAt"), returned.get("nmID"))
        if None in signature or signature in seen:
            raise RuntimeError("WB trash cursor repeated or incomplete")
        seen.add(signature)
        cursor = {"limit": 100, "trashedAt": signature[0], "nmID": signature[1]}
        time.sleep(0.65)
    nmids = [str(x.get("nmID") or "") for x in cards]
    if any(not x for x in nmids) or len(set(nmids)) != len(nmids):
        raise RuntimeError("WB trash rows contain missing/duplicate nmID")
    return cards


def main() -> None:
    snapshot = json.loads(SNAPSHOT.read_text())
    previous = json.loads(OLD.read_text())
    cards = snapshot["wb_catalog"]["cards"]
    prior_cards = previous["wb_catalog"]["cards"]
    by_id: dict[str, list[dict]] = collections.defaultdict(list)
    old_by_id = {str(c.get("nmID") or ""): c for c in prior_cards}
    for card in cards:
        by_id[str(card.get("nmID") or "")].append(card)
    if "" in by_id or len(by_id) != len(old_by_id):
        raise RuntimeError("WB unique ID set differs from prior complete snapshot")
    added = sorted(set(by_id) - set(old_by_id))
    removed = sorted(set(old_by_id) - set(by_id))
    if added or removed:
        raise RuntimeError(f"WB ID set changed: added={len(added)} removed={len(removed)}")

    overlap_ids = []
    cards_by_id = {}
    for nm_id, rows in by_id.items():
        # Cursor overlap is acceptable only if the exact card identity, document
        # rows and TN VED evidence are stable across duplicate responses and the
        # previous complete read.
        reference = rows[0]
        for row in rows[1:]:
            if identity(row) != identity(reference):
                raise RuntimeError(f"WB duplicate card identity conflict: {nm_id}")
            if row.get("documents") != reference.get("documents"):
                raise RuntimeError(f"WB duplicate card documents conflict: {nm_id}")
            if wb_codes(row) != wb_codes(reference):
                raise RuntimeError(f"WB duplicate card TN VED conflict: {nm_id}")
        if identity(reference) != identity(old_by_id[nm_id]):
            raise RuntimeError(f"WB product identity changed from prior full read: {nm_id}")
        if wb_codes(reference) != wb_codes(old_by_id[nm_id]):
            raise RuntimeError(f"WB TN VED changed from prior full read: {nm_id}")
        if any(row.get("documents") != old_by_id[nm_id].get("documents") for row in rows):
            overlap_ids.append(nm_id)
        # Prefer the latest updatedAt payload when a row is repeated.
        cards_by_id[nm_id] = max(rows, key=lambda x: str(x.get("updatedAt") or ""))
        if len(rows) > 1:
            overlap_ids.append(nm_id)

    if not RAW_BACKUP.exists():
        shutil.copy2(SNAPSHOT, RAW_BACKUP)
    fresh_trash = read_trash(Client())
    snapshot["wb_catalog"].update(
        complete=True,
        checked_at=snapshot["wb_catalog"].get("checked_at") or snapshot.get("updated_at"),
        raw_rows=len(cards),
        cards_read=len(cards_by_id),
        duplicate_rows_removed=len(cards) - len(cards_by_id),
        duplicate_nmids=sorted(nm_id for nm_id, rows in by_id.items() if len(rows) > 1),
        id_set_compared_with_previous_complete_read=True,
        unique_id_set_matches_previous_complete_read=True,
        card_identity_and_tnved_stable=True,
        cards=list(cards_by_id.values()),
    )
    snapshot["wb_trash"] = {
        "complete": True,
        "checked_at": stamp(),
        "pages": "read independently by normalize_wb_snapshot.py",
        "cards": fresh_trash,
    }
    snapshot["complete"] = all(snapshot.get(k, {}).get("complete") is True for k in
                               ("ozon_products", "ozon_certificates", "wb_catalog", "wb_trash"))
    snapshot["finished_at"] = stamp()
    snapshot["updated_at"] = snapshot["finished_at"]
    temp = SNAPSHOT.with_suffix(".normalized.tmp")
    temp.write_text(json.dumps(snapshot, ensure_ascii=False))
    temp.replace(SNAPSHOT)
    print(json.dumps({"complete": snapshot["complete"], "ozon_products": len(snapshot["ozon_products"]["products"]),
                      "ozon_certificates": len(snapshot["ozon_certificates"]["certificates"]),
                      "wb_cards": len(snapshot["wb_catalog"]["cards"]), "wb_raw_rows": len(cards),
                      "wb_duplicate_rows_removed": len(cards) - len(cards_by_id),
                      "wb_duplicate_cards": len(snapshot["wb_catalog"]["duplicate_nmids"]),
                      "wb_trash": len(fresh_trash), "snapshot": str(SNAPSHOT), "raw_backup": str(RAW_BACKUP)},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
