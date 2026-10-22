"""Export full live WB cards only for the planned certificate target offers."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent
sys_path = str(ROOT)
import sys
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)
from network_bypass import SourceAddressAdapter


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("before", "after"), required=True)
    parser.add_argument("--plan", default="wb_ozon_reconciliation_plan.json")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    plan = json.loads((BASE / args.plan).read_text())
    targets = {x["offer_id"]: x for x in plan.get("updates") or []}
    if not targets:
        raise RuntimeError("Original exact Ozon-to-WB target plan missing")

    config = (ROOT / "Shared_Настройки.js").read_text()
    block = config.split("const wbHeaders", 1)[1].split("};", 1)[0]
    match = re.search(r"Authorization\s*:\s*['\"]([^'\"]+)['\"]", block)
    if not match:
        raise RuntimeError("WB authorization unavailable")
    session = requests.Session()
    session.trust_env = False
    for iface in ("en1", "en0"):
        info = subprocess.run(["ifconfig", iface], capture_output=True, text=True).stdout
        ip = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", info)
        if ip and "status: active" in info:
            session.mount("https://", SourceAddressAdapter(ip.group(1), interface_name=iface))
            break
    else:
        raise RuntimeError("Active physical interface unavailable")
    headers = {"Authorization": match.group(1), "Content-Type": "application/json"}
    rows: dict[str, dict] = {}
    seen_nmids = set()
    duplicate_nmids = 0
    cursor = {"limit": 100}
    page = 0
    started = datetime.now(timezone.utc).isoformat()
    complete = False
    out = BASE / (args.out or f"wb_target_full_{args.stage}.json")

    def save(error=None):
        state = {"stage": args.stage, "started_at": started,
                 "checked_at": datetime.now(timezone.utc).isoformat(),
                 "complete": complete, "pages": page, "full_catalog_cards": len(seen_nmids),
                 "duplicate_nmids": duplicate_nmids, "target_count": len(targets),
                 "targets_found": len(rows), "cursor": cursor, "cards_by_offer": rows}
        if error:
            state["error_type"] = error
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")))
        tmp.replace(out)

    try:
        while True:
            payload = {"settings": {"sort": {"ascending": True}, "cursor": cursor,
                                    "filter": {"withPhoto": -1}}}
            for attempt in range(8):
                response = session.post("https://content-api.wildberries.ru/content/v2/get/cards/list",
                                        headers=headers, json=payload, timeout=90)
                if response.status_code == 429:
                    time.sleep(min(60, 5 * (attempt + 1)))
                    continue
                response.raise_for_status()
                break
            else:
                raise RuntimeError("WB rate limit retry exhausted")
            body = response.json()
            if body.get("error") or not isinstance(body.get("cards"), list):
                raise RuntimeError("WB returned invalid card page")
            batch = body["cards"]
            page += 1
            if body.get("cursor", {}).get("total") != len(batch):
                raise RuntimeError("WB cursor total/card count mismatch")
            for card in batch:
                nm_id = card.get("nmID")
                offer = card.get("vendorCode")
                if not nm_id or not offer:
                    raise RuntimeError("WB card identity missing")
                if nm_id in seen_nmids:
                    duplicate_nmids += 1
                seen_nmids.add(nm_id)
                if offer in targets:
                    if offer in rows:
                        raise RuntimeError(f"Duplicate exact WB vendorCode {offer}")
                    if str(card.get("nmID")) != str(targets[offer]["nmID"]):
                        raise RuntimeError(f"WB nmID changed for {offer}")
                    rows[offer] = card
            if page % 50 == 0:
                save()
                print(json.dumps({"stage": args.stage, "pages": page,
                                  "catalog_cards": len(seen_nmids), "targets_found": len(rows),
                                  "target_count": len(targets)}, ensure_ascii=False), flush=True)
            if len(batch) < 100:
                complete = True
                if duplicate_nmids:
                    raise RuntimeError("Duplicate WB nmID in complete catalog")
                missing = set(targets) - set(rows)
                if missing:
                    raise RuntimeError(f"Full WB catalog missing {len(missing)} planned offers")
                save()
                break
            c = body["cursor"]
            nxt = {k: c[k] for k in ("updatedAt", "nmID") if k in c}
            if len(nxt) != 2:
                raise RuntimeError("WB page cursor incomplete")
            cursor = {"limit": 100, **nxt}
            time.sleep(0.55)
        print(json.dumps({"stage": args.stage, "complete": complete, "pages": page,
                          "catalog_cards": len(seen_nmids), "targets_found": len(rows),
                          "target_count": len(targets), "path": str(out)}, ensure_ascii=False), flush=True)
    except Exception as exc:
        save(type(exc).__name__)
        raise


if __name__ == "__main__":
    main()
