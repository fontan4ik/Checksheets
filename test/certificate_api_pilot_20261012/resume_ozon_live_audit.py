"""Finish a read-only Ozon certificate and binding snapshot after interruption.

The live certificate endpoint returned a changing page_count during a 12 Oct
2026 read. This reader therefore stops on a short page and rejects duplicate
certificate IDs. It resumes only complete binding reads from the interrupted
snapshot; no marketplace records are created or changed.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from api_client import Client, save  # noqa: E402


def main() -> None:
    snapshot_path = BASE / "ozon_live.json"
    interrupted = json.loads(snapshot_path.read_text())
    old_by_id = {
        str(item["certificate_id"]): item
        for item in interrupted.get("certificates", [])
    }
    api = Client()

    certificates: list[dict] = []
    seen: set[str] = set()
    page = 1
    page_counts: list[int | None] = []
    while True:
        result = api.call(
            "ozon",
            "/v1/product/certificate/list",
            {"page": page, "page_size": 100},
        )["result"]
        batch = result.get("certificates")
        if not isinstance(batch, list) or len(batch) > 100:
            raise RuntimeError(f"Invalid certificate page {page}")
        page_counts.append(result.get("page_count"))
        for certificate in batch:
            certificate_id = str(certificate.get("certificate_id", ""))
            if not certificate_id or certificate_id in seen:
                raise RuntimeError(f"Missing or duplicate certificate ID on page {page}")
            seen.add(certificate_id)
            certificates.append(certificate)
        if len(batch) < 100:
            break
        page += 1

    if not certificates:
        raise RuntimeError("Empty certificate list")

    state = {
        **interrupted,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "complete": False,
        "listing_pages": page,
        "listing_page_count_values": page_counts,
        "certificates": certificates,
        "certificate_statuses": api.call(
            "ozon", "/v1/product/certificate/status/list", {}
        ),
        "product_statuses": api.call(
            "ozon", "/v1/product/certificate/product_status/list", {}
        ),
    }

    for index, certificate in enumerate(state["certificates"], start=1):
        old = old_by_id.get(str(certificate["certificate_id"]), {})
        previous_bindings = old.get("live_bindings")
        previous_count = old.get("live_binding_count")
        previous_product_ids = {
            str(item.get("product_id") or "")
            for item in previous_bindings or []
            if isinstance(item, dict)
        }
        if (
            isinstance(previous_bindings, list)
            and previous_count is not None
            and len(previous_bindings) == int(previous_count)
            and len(previous_product_ids) == int(previous_count)
            and "" not in previous_product_ids
        ):
            certificate["live_bindings"] = previous_bindings
            certificate["live_binding_count"] = len(previous_bindings)
        else:
            bindings = api.ozon_bindings(certificate["certificate_id"])
            certificate["live_bindings"] = bindings
            certificate["live_binding_count"] = len(bindings)

        if index % 25 == 0 or index == len(state["certificates"]):
            save("ozon_live.json", state)
            print(
                json.dumps(
                    {
                        "progress": index,
                        "total": len(state["certificates"]),
                        "readback_rows": sum(
                            "live_bindings" in item for item in state["certificates"]
                        ),
                        "binding_rows": sum(
                            int(item.get("live_binding_count", 0))
                            for item in state["certificates"]
                        ),
                    }
                ),
                flush=True,
            )

    state["complete"] = True
    state["checked_at"] = datetime.now(timezone.utc).isoformat()
    save("ozon_live.json", state)
    print(
        json.dumps(
            {
                "complete": True,
                "checked_at": state["checked_at"],
                "certificate_count": len(certificates),
                "binding_count": sum(
                    int(item.get("live_binding_count", 0)) for item in certificates
                ),
                "listing_pages": page,
                "page_count_values": page_counts,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
