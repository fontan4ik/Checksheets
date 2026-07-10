import os
import subprocess
import time
from contextlib import contextmanager


DEFAULT_VPN_SERVICE = "V2BOX"
DEFAULT_TRANSITION_TIMEOUT = 20
DEFAULT_SETTLE_SECONDS = 3


def _run_scutil(*args):
    return subprocess.run(
        ["scutil", "--nc", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def get_vpn_service_name():
    return os.getenv("CHECKSHEETS_VPN_SERVICE", DEFAULT_VPN_SERVICE)


def vpn_guard_enabled():
    raw = os.getenv("CHECKSHEETS_DISABLE_VPN_GUARD", "").strip().lower()
    return raw not in {"1", "true", "yes", "on"}


def get_vpn_status(service_name=None):
    service = service_name or get_vpn_service_name()
    result = _run_scutil("status", service)
    first_line = (result.stdout or result.stderr or "").splitlines()
    status = first_line[0].strip() if first_line else "Unknown"
    return status, result


def wait_for_vpn_status(target_status, service_name=None, timeout=DEFAULT_TRANSITION_TIMEOUT):
    service = service_name or get_vpn_service_name()
    deadline = time.time() + timeout

    while time.time() < deadline:
        status, _ = get_vpn_status(service)
        if status == target_status:
            return True
        time.sleep(1)

    return False


@contextmanager
def temporary_vpn_disconnect(task_name, service_name=None):
    service = service_name or get_vpn_service_name()

    if not vpn_guard_enabled():
        print(f"[{task_name}] VPN guard disabled via CHECKSHEETS_DISABLE_VPN_GUARD.")
        yield
        return

    original_status, _ = get_vpn_status(service)
    restore_required = original_status == "Connected"

    if restore_required:
        print(f"[{task_name}] Disconnecting VPN service '{service}'...")
        stop_result = _run_scutil("stop", service)
        if stop_result.returncode != 0:
            raise RuntimeError(
                f"Failed to disconnect VPN '{service}': "
                f"{(stop_result.stderr or stop_result.stdout).strip()}"
            )
        if not wait_for_vpn_status("Disconnected", service):
            raise RuntimeError(f"VPN '{service}' did not disconnect in time.")
        time.sleep(DEFAULT_SETTLE_SECONDS)
        print(f"[{task_name}] VPN '{service}' disconnected.")
    else:
        print(f"[{task_name}] VPN '{service}' already not connected ({original_status}).")

    try:
        yield
    finally:
        if restore_required:
            print(f"[{task_name}] Restoring VPN service '{service}'...")
            start_result = _run_scutil("start", service)
            if start_result.returncode != 0:
                print(
                    f"[{task_name}] WARNING: failed to reconnect VPN '{service}': "
                    f"{(start_result.stderr or start_result.stdout).strip()}"
                )
            elif not wait_for_vpn_status("Connected", service):
                print(f"[{task_name}] WARNING: VPN '{service}' did not reconnect in time.")
            else:
                time.sleep(DEFAULT_SETTLE_SECONDS)
                print(f"[{task_name}] VPN '{service}' reconnected.")
