"""Read the current WB error-list pages for the five Feron 53483/22 offers."""
from __future__ import annotations

import json
from pathlib import Path

from api_client import BASE, Client, now, save

EXEC = BASE / "feron_53483_wb_execution_20261013.json"
OUT = "feron_53483_wb_errors_recheck_20261013_1235.json"


def read_errors(client: Client) -> list[dict]:
    out: list[dict] = []
    cursor = {"limit": 100}
    for _ in range(100):
        body = client.call("wb", "/content/v2/cards/error/list",
                           {"cursor": cursor, "order": {"ascending": True}})
        if body.get("error"):
            raise RuntimeError("WB error-list returned an API error")
        data = body.get("data") or {}
        out.extend(data.get("items") or [])
        page = data.get("cursor") or {}
        if page.get("next") is not True:
            return out
        if not page.get("updatedAt") or not page.get("batchUUID"):
            raise RuntimeError("WB error-list cursor is incomplete")
        cursor = {"limit": 100, "updatedAt": page["updatedAt"], "batchUUID": page["batchUUID"]}
    raise RuntimeError("WB error-list pagination exceeded 100 pages")


def main() -> None:
    execution = json.loads(EXEC.read_text(encoding="utf-8"))
    targets = execution.get("targets") or []
    offers = {str(x.get("offer_id") or "") for x in targets}
    if len(targets) != 5 or "" in offers or len(offers) != 5:
        raise RuntimeError("Execution journal does not contain five unique target offers")
    batches = read_errors(Client())
    matches = []
    for batch in batches:
        errors = batch.get("errors") or {}
        matching = sorted(offers.intersection(str(x) for x in errors))
        if matching:
            matches.append({"batchUUID": batch.get("batchUUID"),
                            "updatedAt": batch.get("updatedAt"),
                            "errors": {offer: errors[offer] for offer in matching}})
    state = {"checked_at_utc": now(), "batch_count": len(batches),
             "target_vendor_codes": sorted(offers), "matching_error_batches": matches}
    save(OUT, state)
    print(json.dumps({"artifact": str(BASE / OUT), **state}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
