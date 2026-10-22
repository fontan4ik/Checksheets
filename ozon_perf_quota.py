"""Cross-process circuit breaker for Ozon Performance's account request quota.

This is separate from the asynchronous report quota. A cooldown schedules a
single probe; it does not assume when Ozon's rolling 24-hour quota resets.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

import config

_ACCOUNT = hashlib.sha256(str(config.OZON_PERF_CLIENT_ID).encode()).hexdigest()[:16]
STATE_PATH = Path(__file__).resolve().parent / 'logs' / f'ozon-perf-quota-{_ACCOUNT}.json'
COOLDOWN_SECONDS = 15 * 60
PROBE_LEASE_SECONDS = 5 * 60


class PerformanceQuotaError(RuntimeError):
    """Stop the whole job, rather than treating quota as a per-product error."""

    def __init__(self, retry_at: float, *, newly_blocked: bool = False):
        self.retry_at = retry_at
        self.newly_blocked = newly_blocked
        when = datetime.fromtimestamp(retry_at, timezone.utc).isoformat(timespec='seconds')
        super().__init__(
            'Ozon Performance: общий лимит запросов исчерпан; '
            f'работа отложена, следующая разрешённая проверка после {when}. '
            'Время сброса квоты API не сообщено.'
        )


@contextmanager
def _state():
    path = STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a+') as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            try:
                data = json.loads(path.read_text(encoding='utf8'))
            except (OSError, ValueError):
                data = {}
            if not isinstance(data, dict):
                data = {}
            yield data
            temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
            try:
                temporary.write_text(json.dumps(data, indent=2) + '\n', encoding='utf8')
                os.chmod(temporary, 0o600)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _number(value, default=0.0):
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _reserve_probe() -> str | None:
    now = time.time()
    with _state() as data:
        if not data.get('blocked_since'):
            return None
        retry_at = max(_number(data.get('retry_at')), _number(data.get('probe_until')))
        if now < retry_at:
            raise PerformanceQuotaError(retry_at)
        probe_id = uuid.uuid4().hex
        data['probe_id'] = probe_id
        data['probe_until'] = now + PROBE_LEASE_SECONDS
        return probe_id


def is_account_quota_response(response) -> bool:
    if response.status_code not in (400, 429):
        return False
    text = str(response.text).lower()
    # Do not confuse report/day, per-second or endpoint-specific write limits
    # with the account-wide request quota returned by campaign/product reads.
    return ('request limit has been reached' in text
            and 'request' in text
            and re.search(r'100[\s,_]*000', text) is not None
            and ('24h' in text or '24 h' in text or '86400' in text))


def _retry_after(response, now: float) -> float:
    raw = getattr(response, 'headers', {}).get('Retry-After')
    if raw:
        try:
            return now + max(1.0, float(raw))
        except (ValueError, TypeError):
            try:
                return max(now + 1, parsedate_to_datetime(str(raw)).timestamp())
            except (ValueError, TypeError, OverflowError):
                pass
    return now + COOLDOWN_SECONDS


def _block(response) -> PerformanceQuotaError:
    now = time.time()
    retry_at = _retry_after(response, now)
    with _state() as data:
        newly_blocked = not bool(data.get('blocked_since'))
        if newly_blocked:
            data['alert_pending'] = True
        data.setdefault('blocked_since', now)
        data['retry_at'] = max(retry_at, _number(data.get('retry_at')))
        data['probe_until'] = 0
        data.pop('probe_id', None)
        data['last_quota_response_at'] = now
        retry_at = data['retry_at']
    return PerformanceQuotaError(retry_at, newly_blocked=newly_blocked)


def claim_quota_alert() -> bool:
    """Any job observing the outage can claim its one notification atomically."""
    with _state() as data:
        if not data.get('alert_pending'):
            return False
        data['alert_pending'] = False
        return True


def _release_probe(probe_id: str | None, recovered: bool) -> None:
    if probe_id is None:
        return
    with _state() as data:
        if data.get('probe_id') != probe_id:
            return
        data.pop('probe_id', None)
        data['probe_until'] = 0
        if recovered:
            data.clear()
            data['last_recovered_at'] = time.time()
        else:
            data['retry_at'] = max(_number(data.get('retry_at')), time.time() + COOLDOWN_SECONDS)


def request_with_quota(call):
    """Call once, preserving the existing caller's transient retry policy."""
    probe_id = _reserve_probe()
    try:
        response = call()
    except BaseException:
        _release_probe(probe_id, False)
        raise
    if is_account_quota_response(response):
        raise _block(response)
    _release_probe(probe_id, 200 <= response.status_code < 300)
    return response
