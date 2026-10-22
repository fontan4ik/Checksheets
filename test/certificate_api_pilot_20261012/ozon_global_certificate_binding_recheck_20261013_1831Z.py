"""Full read-only current Ozon certificate and binding snapshot, separate from earlier audits."""
from __future__ import annotations

import collections
import json

from api_client import BASE, Client, now, save

OUT = "ozon_global_certificate_binding_recheck_20261013_1831Z.json"


def main() -> None:
    client = Client()
    certificates: list[dict] = []
    page = 1
    while page <= 100:
        body = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})
        result = body.get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list response is malformed")
        certificates.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    else:
        raise RuntimeError("Ozon certificate list exceeded 100 pages")
    if len({str(x.get("certificate_id")) for x in certificates}) != len(certificates):
        raise RuntimeError("Ozon certificate list contains duplicate IDs")
    state = {"checked_at_utc": now(), "read_only": True, "complete": False,
             "certificate_count": len(certificates), "page_count": page,
             "records": []}
    save(OUT, state)
    for index, cert in enumerate(certificates, 1):
        bindings = client.ozon_bindings(cert["certificate_id"])
        row = {k: cert.get(k) for k in ("certificate_id", "certificate_number", "type_code",
                                           "status_code", "issue_date", "expire_date",
                                           "certificate_country", "accordance_type")}
        row["binding_count"] = len(bindings)
        row["binding_status_counts"] = dict(collections.Counter(
            str(x.get("product_status_code") or "") for x in bindings))
        row["bindings"] = [{"product_id": str(x.get("product_id") or ""),
                            "sku": str(x.get("sku") or ""),
                            "product_status_code": str(x.get("product_status_code") or "")}
                           for x in bindings]
        state["records"].append(row)
        if index % 25 == 0 or index == len(certificates):
            state["checked_at_utc"] = now()
            save(OUT, state)
            print(json.dumps({"processed_certificates": index,
                              "certificate_count": len(certificates)}, ensure_ascii=False), flush=True)
    state["complete"] = True
    state["finished_at_utc"] = now()
    state["total_bindings"] = sum(x["binding_count"] for x in state["records"])
    state["overall_binding_status_counts"] = dict(collections.Counter(
        status for row in state["records"] for status, count in row["binding_status_counts"].items()
        for _ in range(count)))
    save(OUT, state)
    print(json.dumps({"artifact": str(BASE / OUT), "complete": True,
                      "certificates": state["certificate_count"],
                      "total_bindings": state["total_bindings"],
                      "binding_status_counts": state["overall_binding_status_counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
