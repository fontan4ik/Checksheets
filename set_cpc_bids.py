#!/usr/bin/env python3
"""Synchronize Ozon CPC bids from the ``Размер ставки`` column of ``СРС``.

Each non-empty bid is read as rubles (``8``, ``16`` or ``8,50``), converted to
microrubles, sent to the matching campaign/SKU only if it differs, and then
verified with ``GET /v2/products``.  Scheduled runs check changed sheet values
immediately and audit a small rotating batch, instead of spending one API
request on every campaign every 15 minutes. The default mode only prints the
plan; ``--apply`` is required to change Ozon.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import gsheets_utils
import requests
import config
from ozon_perf_quota import PerformanceQuotaError, claim_quota_alert, request_with_quota
from ozon_cpc_cleanup import (
    BASE_URL,
    SHEET_NAME,
    create_session,
    find_column,
    get_token,
    normalize_id,
)


MAX_ATTEMPTS = 5
BID_STATE_FILE = Path(__file__).resolve().parent / "logs" / "cpc-bids-state.json"
DEFAULT_AUDIT_BATCH_SIZE = 20
DEFAULT_RETRY_BATCH_SIZE = 20
DEFAULT_MAX_ROWS = 100
REJECTED_BID_RETRY_SECONDS = 24 * 60 * 60


class BidReadError(RuntimeError):
    """The current Ozon bid could not be read reliably."""


class BidWriteError(RuntimeError):
    """A bid write failed, with a safe HTTP/network diagnostic."""

    def __init__(self, message: str, attempts: int, status_code: int | None = None):
        super().__init__(message)
        self.attempts = attempts
        self.status_code = status_code

    @property
    def invalid_bid_range(self) -> bool:
        message = str(self)
        try:
            message = json.dumps(json.loads(message.split(": ", 1)[1]), ensure_ascii=False)
        except (IndexError, TypeError, ValueError):
            pass
        return self.status_code == 400 and (
            "ставка не входит в диапазон допустимых значений" in message.casefold()
        )


@dataclass(frozen=True)
class BidRow:
    row_number: int
    campaign_id: str
    sku: str
    bid_microrubles: int


def bid_row_key(row: BidRow) -> str:
    return f"{row.campaign_id}:{row.sku}"


def rejected_bid_records(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rejected = state.get("rejected")
    if not isinstance(rejected, dict):
        return {}
    return {key: dict(value) for key, value in rejected.items() if isinstance(value, dict)}


def active_rejected_bid_keys(rows: list[BidRow], state: dict[str, Any]) -> set[str]:
    rejected = rejected_bid_records(state)
    now = time.time()
    keys = set()
    for row in rows:
        key = bid_row_key(row)
        record = rejected.get(key, {})
        try:
            retry_at = float(record.get("retry_at", 0))
        except (TypeError, ValueError):
            retry_at = 0
        if record.get("desired_bid") == row.bid_microrubles and retry_at > now:
            keys.add(key)
    return keys


def load_bid_state(path: Path = BID_STATE_FILE) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_bid_state(state: dict[str, Any], path: Path = BID_STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def select_bid_rows(
    rows: list[BidRow],
    state: dict[str, Any],
    audit_batch_size: int = DEFAULT_AUDIT_BATCH_SIZE,
    full_audit: bool = False,
    retry_batch_size: int = DEFAULT_RETRY_BATCH_SIZE,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> tuple[list[BidRow], dict[str, int], int]:
    """Compatibility wrapper returning selected rows, desired bids and audit cursor."""
    selected, desired, audit_cursor, _ = select_bid_plan(
        rows, state, audit_batch_size, full_audit, retry_batch_size, max_rows
    )
    return selected, desired, audit_cursor


def select_bid_plan(
    rows: list[BidRow],
    state: dict[str, Any],
    audit_batch_size: int = DEFAULT_AUDIT_BATCH_SIZE,
    full_audit: bool = False,
    retry_batch_size: int = DEFAULT_RETRY_BATCH_SIZE,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> tuple[list[BidRow], dict[str, int], int, int]:
    """Select changed bids first, then bounded rotating failed and audit slices.

    On the first cache-backed run the current sheet is used as the baseline and
    only the audit slice is queried. Previous full logs establish that baseline;
    subsequent sheet changes are detected by comparing desired values.
    """
    if not rows:
        return [], {}, 0, 0

    desired = {bid_row_key(row): row.bid_microrubles for row in rows}
    quarantined_keys = active_rejected_bid_keys(rows, state)
    if full_audit:
        return [row for row in rows if bid_row_key(row) not in quarantined_keys], desired, 0, 0

    initialized = state.get("initialized") is True
    previous_desired = state.get("desired") if isinstance(state.get("desired"), dict) else {}
    failed_keys = set(state.get("failed", [])) if isinstance(state.get("failed"), list) else set()
    # Rejected values become eligible for the bounded retry queue after a day.
    rejected = rejected_bid_records(state)
    failed_keys.update(
        key for key, value in desired.items()
        if key in rejected and rejected[key].get("desired_bid") == value
        and key not in quarantined_keys
    )
    failed_keys -= quarantined_keys
    row_by_key = {bid_row_key(row): row for row in rows}

    changed_keys: list[str] = []
    if initialized:
        changed_keys.extend(
            key for key, value in desired.items()
            if previous_desired.get(key) != value and key not in quarantined_keys
        )

    selected: list[BidRow] = []
    seen: set[str] = set()
    limit = max(1, int(max_rows))

    def add(row: BidRow) -> bool:
        key = bid_row_key(row)
        if key in seen:
            return True
        if len(selected) >= limit:
            return False
        selected.append(row)
        seen.add(key)
        return True

    for key in changed_keys:
        if not add(row_by_key[key]):
            break

    # Cursors index the full sheet order, so removing successful failed keys
    # cannot repeatedly send the first failed rows and starve the queue tail.
    retry_cursor = max(0, int(state.get("retry_cursor", 0) or 0)) % len(rows)
    next_retry_cursor = retry_cursor
    retries = 0
    if retry_batch_size > 0 and failed_keys:
        for offset in range(len(rows)):
            index = (retry_cursor + offset) % len(rows)
            row = rows[index]
            if bid_row_key(row) in failed_keys:
                if retries >= retry_batch_size or not add(row):
                    break
                retries += 1
            next_retry_cursor = (index + 1) % len(rows)

    cursor = max(0, int(state.get("audit_cursor", 0) or 0)) % len(rows)
    next_cursor = cursor
    for offset in range(min(len(rows), max(0, audit_batch_size))):
        index = (cursor + offset) % len(rows)
        if bid_row_key(rows[index]) not in quarantined_keys and not add(rows[index]):
            break
        next_cursor = (index + 1) % len(rows)
    return selected, desired, next_cursor, next_retry_cursor


def observed_desired_bids(
    desired: dict[str, int], state: dict[str, Any], processed_keys: set[str]
) -> dict[str, int]:
    """Leave capped, unprocessed sheet changes pending for the next run."""
    if state.get("initialized") is not True:
        return dict(desired)
    previous = state.get("desired") if isinstance(state.get("desired"), dict) else {}
    observed = {key: value for key, value in previous.items() if key in desired}
    observed.update({key: desired[key] for key in processed_keys if key in desired})
    return observed


def safe_response_error(response, token: str) -> str:
    detail = str(response.text)[:1000]
    for secret in (token, str(getattr(config, "OZON_PERF_CLIENT_SECRET", ""))):
        if secret:
            detail = detail.replace(secret, "[REDACTED]")
    detail = re.sub(r"(?:bot)?\d{5,}:[A-Za-z0-9_-]+", "[REDACTED]", detail)
    detail = re.sub(r'(?i)(bearer\s+)[A-Za-z0-9._-]+', r'\1[REDACTED]', detail)
    return f"HTTP {response.status_code}: {detail}"


def parse_bid_microrubles(value: object) -> int | None:
    """Parse a user-entered ruble amount without floating-point rounding."""
    normalized = str(value or "").strip().replace("\u00a0", "").replace(" ", "")
    if not normalized:
        return None
    try:
        bid = Decimal(normalized.replace(",", "."))
    except InvalidOperation:
        return None
    microrubles = bid * Decimal(1_000_000)
    if bid <= 0 or microrubles != microrubles.to_integral_value():
        return None
    return int(microrubles)


def read_bid_rows(values: list[list[str]]) -> tuple[list[BidRow], list[tuple[int, str]]]:
    """Read valid bid requests and report rows with malformed non-empty AD."""
    if not values:
        raise RuntimeError(f"Лист {SHEET_NAME} пуст")
    headers = values[0]
    sku_index = find_column(headers, ["sku ozon", "sku"])
    campaign_index = find_column(headers, ["campain id", "campaign id", "campaign_id"])
    bid_index = find_column(headers, ["размер ставки"])
    if min(sku_index, campaign_index, bid_index) < 0:
        raise RuntimeError(
            "В СРС нужны колонки 'SKU OZON', 'CAMPAIN ID' и 'Размер ставки'"
        )

    rows: list[BidRow] = []
    invalid: list[tuple[int, str]] = []
    for row_number, values_row in enumerate(values[1:], start=2):
        padded = list(values_row) + [""] * (len(headers) - len(values_row))
        raw_bid = padded[bid_index].strip()
        if not raw_bid:
            continue
        bid_microrubles = parse_bid_microrubles(raw_bid)
        if bid_microrubles is None:
            invalid.append((row_number, raw_bid))
            continue
        sku = normalize_id(padded[sku_index])
        campaign_id = normalize_id(padded[campaign_index])
        if sku and campaign_id:
            rows.append(BidRow(row_number, campaign_id, sku, bid_microrubles))
    return rows, invalid


def get_bid(session, token: str, campaign_id: str, sku: str) -> str | None:
    """Return the current bid, or None only when the SKU is truly absent."""
    last_error = "unknown error"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = request_with_quota(lambda: session.get(
                f"{BASE_URL}/api/client/campaign/{campaign_id}/v2/products",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            ))
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError as exc:
                    last_error = f"invalid JSON: {exc}"
                else:
                    for product in data.get("products", []):
                        if str(product.get("sku")) == sku:
                            return str(product.get("bid"))
                    return None
            else:
                last_error = safe_response_error(response, token)
                if response.status_code not in (429, 500, 502, 503, 504):
                    raise BidReadError(last_error)
        if attempt < MAX_ATTEMPTS:
            time.sleep(min(2 ** attempt, 15))
    raise BidReadError(last_error)


def put_bid(
    session, token: str, campaign_id: str, sku: str, bid_microrubles: int
) -> tuple[bool, int]:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            r = request_with_quota(lambda: session.put(
                f"{BASE_URL}/api/client/campaign/{campaign_id}/products",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"bids": [{"sku": sku, "bid": str(bid_microrubles)}]},
                timeout=60,
            ))
        except requests.RequestException as exc:
            if attempt < MAX_ATTEMPTS:
                time.sleep(min(2 ** attempt, 15))
                continue
            raise BidWriteError(f"{type(exc).__name__}: request failed", attempt) from exc
        if r.status_code == 200:
            return True, attempt
        if r.status_code in (429, 500, 502, 503, 504) and attempt < MAX_ATTEMPTS:
            time.sleep(min(2 ** attempt, 15))
            continue
        raise BidWriteError(safe_response_error(r, token), attempt, status_code=r.status_code)
    return False, MAX_ATTEMPTS


def run() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--retry-batch-size",
        type=int,
        default=DEFAULT_RETRY_BATCH_SIZE,
        help="Сколько ранее неудачных ставок повторять за один запуск.",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=DEFAULT_MAX_ROWS,
        help="Максимум ставок за плановый запуск (кроме --full-audit).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Записать ставки в Ozon. Без флага только показать план.",
    )
    parser.add_argument(
        "--audit-batch-size",
        type=int,
        default=DEFAULT_AUDIT_BATCH_SIZE,
        help="Сколько неизменённых ставок перепроверять за один запуск.",
    )
    parser.add_argument(
        "--full-audit",
        action="store_true",
        help="Проверить все ставки (только для редкого ручного запуска).",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=BID_STATE_FILE,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    worksheet = gsheets_utils.get_worksheet(SHEET_NAME)
    values = gsheets_utils._retry_gsheet_call("read CPC bid rows", worksheet.get_all_values)
    rows, invalid = read_bid_rows(values)
    print(f"Строк со ставкой в AD: {len(rows)}; некорректных: {len(invalid)}")
    for row_number, raw_bid in invalid[:20]:
        print(f"  row={row_number}: некорректная ставка AD={raw_bid!r}")
    if invalid:
        return 2
    if not rows:
        print("Нет ставок для синхронизации")
        return 0

    state = load_bid_state(args.state_file)
    quarantined_keys = active_rejected_bid_keys(rows, state)
    current_keys = {bid_row_key(row) for row in rows}
    rejected = {
        key: value for key, value in rejected_bid_records(state).items()
        if key in current_keys
    }
    selected_rows, desired, next_cursor, next_retry_cursor = select_bid_plan(
        rows,
        state,
        audit_batch_size=max(0, args.audit_batch_size),
        full_audit=args.full_audit,
        retry_batch_size=max(0, args.retry_batch_size),
        max_rows=max(1, args.max_rows),
    )
    changed_count = 0
    if state.get("initialized") is True and isinstance(state.get("desired"), dict):
        changed_count = sum(
            1 for key, value in desired.items() if state["desired"].get(key) != value
        )
    print(
        f"К проверке Ozon: {len(selected_rows)} из {len(rows)}; "
        f"изменено в таблице={changed_count}; skipped_invalid={len(quarantined_keys)}; "
        f"следующий audit cursor={next_cursor}"
    )
    if not selected_rows:
        if args.apply:
            save_bid_state(
                {
                    "initialized": True,
                    "desired": observed_desired_bids(desired, state, set()),
                    "failed": [key for key in state.get("failed", []) if key in desired and key not in quarantined_keys],
                    "rejected": rejected,
                    "audit_cursor": next_cursor,
                    "retry_cursor": next_retry_cursor,
                    "updated_at": int(time.time()),
                },
                args.state_file,
            )
        return 0

    workers = max(1, min(args.workers, len(selected_rows)))
    pool = [create_session() for _ in range(workers)]
    tokens = [get_token(s) for s in pool]

    def process(item: tuple[int, BidRow]):
        idx, row = item
        sess = pool[idx % workers]
        tok = tokens[idx % workers]
        try:
            bid = get_bid(sess, tok, row.campaign_id, row.sku)
        except BidReadError as exc:
            return row, f"read_failed({exc})", 0, None
        if bid is None:
            return row, "sku_not_in_campaign", 0, None
        if bid == str(row.bid_microrubles):
            return row, "ok", 0, bid
        if not args.apply:
            return row, "planned", 0, bid
        try:
            ok, attempts = put_bid(sess, tok, row.campaign_id, row.sku, row.bid_microrubles)
        except BidWriteError as exc:
            if exc.invalid_bid_range:
                return row, "rejected_invalid_bid", exc.attempts, str(exc)
            return row, f"put_failed({exc})", exc.attempts, bid
        if not ok:
            return row, "put_failed", attempts, bid
        # верифицируем
        time.sleep(0.2)
        new_bid = get_bid(sess, tok, row.campaign_id, row.sku)
        if new_bid == str(row.bid_microrubles):
            return row, "ok", attempts, new_bid
        return row, f"verify_mismatch(bid={new_bid})", attempts, new_bid

    ok = 0
    already = 0
    planned = 0
    failed: list[tuple[BidRow, str, int]] = []
    rejected_rows: list[tuple[BidRow, str]] = []
    newly_rejected = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(process, (i, row)) for i, row in enumerate(selected_rows)]
        done = 0
        for f in as_completed(futs):
            row, status, attempts, detail = f.result()
            if status == "ok":
                rejected.pop(bid_row_key(row), None)
                if attempts == 0:
                    already += 1
                else:
                    ok += 1
            elif status == "planned":
                planned += 1
            elif status == "rejected_invalid_bid":
                key = bid_row_key(row)
                reason = str(detail)
                old_rejection = rejected.get(key, {})
                if old_rejection.get("desired_bid") != row.bid_microrubles or old_rejection.get("reason") != reason:
                    newly_rejected += 1
                rejected[key] = {
                    "desired_bid": row.bid_microrubles,
                    "reason": reason,
                    "retry_at": time.time() + REJECTED_BID_RETRY_SECONDS,
                }
                rejected_rows.append((row, reason))
            else:
                failed.append((row, status, attempts))
            done += 1
            if done % 50 == 0 or done == len(selected_rows):
                print(
                    f"[{done}/{len(selected_rows)}] updated={ok} already={already} "
                    f"planned={planned} failed={len(failed)}",
                    flush=True,
                )

    mode = "применено" if args.apply else "dry-run"
    print(
        f"\n{mode}: updated={ok}, already_correct={already}, "
        f"planned={planned}, failed={len(failed)}, rejected_invalid={len(rejected_rows)}, "
        f"new_rejected={newly_rejected}, skipped_invalid={len(quarantined_keys)}"
    )
    for row, status, attempts in failed[:20]:
        print(
            f"  row={row.row_number} campaign={row.campaign_id} sku={row.sku}: "
            f"{status} (attempts={attempts})"
        )
    for row, reason in rejected_rows[:20]:
        print(
            f"  row={row.row_number} campaign={row.campaign_id} sku={row.sku}: "
            f"rejected_invalid_bid({reason}); значение в таблице сохранено, повтор через 24 часа"
        )
    if args.apply:
        previous_failed = (
            set(state.get("failed", [])) if isinstance(state.get("failed"), list) else set()
        )
        processed_keys = {bid_row_key(row) for row in selected_rows}
        failed_keys = {bid_row_key(row) for row, _, _ in failed}
        remaining_failed = ((previous_failed - processed_keys) | failed_keys) - quarantined_keys
        save_bid_state(
            {
                "initialized": True,
                "desired": observed_desired_bids(desired, state, processed_keys),
                "failed": sorted(key for key in remaining_failed if key in desired),
                "rejected": rejected,
                "audit_cursor": next_cursor,
                "retry_cursor": next_retry_cursor,
                "updated_at": int(time.time()),
            },
            args.state_file,
        )
    return 0 if not failed and not newly_rejected else 1


def main() -> int:
    try:
        return run()
    except PerformanceQuotaError as exc:
        # The shared guard stops remaining reads/writes; do not replace cached
        # desired/failure state with a partially observed sheet baseline.
        print(f"Ozon Performance: ставки отложены из-за квоты: {exc}", flush=True)
        return 1 if claim_quota_alert() else 0


if __name__ == "__main__":
    raise SystemExit(main())
