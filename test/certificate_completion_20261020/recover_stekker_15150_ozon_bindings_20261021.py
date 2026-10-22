"""Read back and finish Ozon bindings after the API rejected an empty SKU."""
from __future__ import annotations

import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from execute_stekker_15150_ozon_20261021 import eligible, live_check, save, digest  # noqa: E402

PREFLIGHT = HERE / "stekker_15150_crossplatform_preflight_live_20261021.json"
STATE = HERE / "stekker_15150_ozon_execution_20261021.json"
RECOVERY = HERE / "stekker_15150_ozon_recovery_20261021.json"
NUMBER = "ЕАЭС N RU Д-CN.РА07.В.15150/25"


def main() -> None:
    if RECOVERY.exists():
        raise RuntimeError("recovery_artifact_exists_reconcile_before_retry")
    state = json.loads(STATE.read_text(encoding="utf-8"))
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    targets = [row for row in pre.get("ozon_targets") or [] if eligible(row)]
    cert_id = int(state.get("certificate_id") or 0)
    if (not cert_id or state.get("phase") != "ozon_binding"
            or state.get("number") != NUMBER or len(targets) != 371
            or digest(ROOT / "output_to_user/certificates/group_1/documents/stekker/c3e79720d30db2f7da55a3cf.pdf")
               != state.get("source_pdf_sha256")):
        raise RuntimeError("ozon_recovery_precondition_failed")

    client = Client()
    bindings = client.ozon_bindings(cert_id)
    target_by_id = {str(row["product_id"]): row for row in targets}
    if len(target_by_id) != len(targets):
        raise RuntimeError("duplicate_target_product_id")
    binding_by_id = {}
    extra = []
    for binding in bindings:
        pid = str(binding.get("product_id") or "")
        if pid in binding_by_id:
            raise RuntimeError("duplicate_live_binding_product_id")
        binding_by_id[pid] = binding
        target = target_by_id.get(pid)
        if not target:
            extra.append(pid)
            continue
        if str(binding.get("sku") or "") != str(target.get("sku") or ""):
            raise RuntimeError("live_binding_sku_conflict:" + str(target["offer_id"]))
    if extra:
        raise RuntimeError("unexpected_live_certificate_binding")

    missing = [row for row in targets if str(row["product_id"]) not in binding_by_id]
    no_sku = [row for row in missing if not str(row.get("sku") or "").strip()]
    linkable = [row for row in missing if str(row.get("sku") or "").strip()]
    live_rows = live_check(client, linkable)
    if len(live_rows) != len(linkable) or any(not row.get("eligible_now") for row in live_rows):
        raise RuntimeError("remaining_ozon_live_scope_check_failed")

    artifact = {"started_at": now(), "number": NUMBER, "certificate_id": cert_id,
                "live_bindings_before_recovery": len(bindings),
                "target_count": len(targets), "missing_before_recovery": len(missing),
                "excluded_missing_sku_offers": [row["offer_id"] for row in no_sku],
                "eligible_missing_sku_count": len(linkable), "bind_batches": [],
                "phase": "fresh_readback_and_scope_verified", "local_file_deleted": False}
    save(RECOVERY, artifact)
    for start in range(0, len(linkable), 50):
        batch = linkable[start:start + 50]
        response = client.call("ozon", "/v1/product/certificate/bind", {
            "certificate_id": cert_id, "skus": [str(row["sku"]) for row in batch]
        }, mutation=True)
        artifact["bind_batches"].append({"count": len(batch), "result": response.get("result")})
        artifact["phase"] = "binding"
        artifact["updated_at"] = now()
        save(RECOVERY, artifact)
        if response.get("result") is not True:
            artifact["phase"] = "bind_rejected_reconcile_live_before_retry"
            save(RECOVERY, artifact)
            raise RuntimeError("ozon_recovery_bind_rejected")

    final_info = client.call("ozon", "/v1/product/certificate/info",
                             {"certificate_number": NUMBER}).get("result") or {}
    final_bindings = client.ozon_bindings(cert_id)
    final_by_id = {str(row.get("product_id") or ""): row for row in final_bindings}
    verified = []
    for target in targets:
        binding = final_by_id.get(str(target["product_id"]))
        exact = bool(binding and str(binding.get("sku") or "") == str(target.get("sku") or ""))
        verified.append({"offer_id": target["offer_id"], "product_id": target["product_id"],
                         "sku": target.get("sku"), "bound": exact,
                         "status": binding.get("product_status_code") if exact else None})
    status_counts = collections.Counter(str(row["status"]) for row in verified if row["bound"])
    expected_bound = len(targets) - len(no_sku)
    if (sum(row["bound"] for row in verified) != expected_bound
            or any(not row["bound"] for row in verified if row["sku"])
            or str(final_info.get("certificate_id")) != str(cert_id)):
        artifact.update(phase="readback_incomplete", final_info=final_info,
                        missing_offers=[row["offer_id"] for row in verified if not row["bound"]],
                        updated_at=now())
        save(RECOVERY, artifact)
        raise RuntimeError("ozon_recovery_readback_incomplete")
    artifact.update(phase="verified_complete_except_missing_sku", finished_at=now(),
                    final_certificate_info=final_info, final_binding_count=len(final_bindings),
                    verified_bound_count=sum(row["bound"] for row in verified),
                    verified_target_count=len(verified), binding_status_counts=dict(status_counts),
                    verified_bindings=verified, local_file_deleted=False)
    save(RECOVERY, artifact)
    state.update(phase="ozon_verified_complete_with_missing_sku_exclusion",
                 recovery_path=str(RECOVERY), verified_target_pairs=sum(row["bound"] for row in verified),
                 unbound_missing_sku_offers=[row["offer_id"] for row in no_sku],
                 binding_status_counts=dict(status_counts), local_file_deleted=False, updated_at=now())
    save(STATE, state)
    print(json.dumps({"phase": artifact["phase"], "certificate_id": cert_id,
                      "verified_bound_count": artifact["verified_bound_count"],
                      "unbound_missing_sku_offers": artifact["excluded_missing_sku_offers"],
                      "binding_status_counts": dict(status_counts), "source_pdf_deleted": False},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
