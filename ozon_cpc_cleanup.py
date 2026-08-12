#!/usr/bin/env python3
"""Ozon Performance CPC sync for the ``СРС`` sheet.

The worksheet layout (already applied in Google Sheets):

    art | model | brand | pic | SKU OZON | CAMPAIN ID | CAMPAIN NAME |
    Расход день | Расход неделя | Расход месяц |
    Показы день | Показы неделя | Показы месяц |
    Клики день | Клики неделя | Клики месяц |
    CTR, % месяц | Средняя стоимость клика месяц | Продано месяц |
    ДРР в продвижении месяц | Бюджет | Корзины месяц | Статус |
    Фильтр клики день | Фильтр ДРР месяц

Only identity columns ``art/model/brand/pic/SKU OZON`` are static and are never
rewritten.  Everything else is regenerated from the Ozon Performance API on
every run.  The last two columns (``Фильтр клики день`` / ``Фильтр ДРР месяц``)
are per-row thresholds edited by the user; the script reads them and, when a
campaign/SKU crosses a threshold, stops the article (SKU) first and the whole
campaign only if the article cannot be stopped.

Flow:
1. Read campaign/SKU pairs and per-row filter thresholds from ``СРС``.
2. Read running SKU campaigns from Ozon Performance API (title/budget/state).
3. Generate SKU reports for day, week and month periods and parse them.
4. Write day/week/month metrics, budget, status and campaign name back to ``СРС``.
5. Evaluate ``Фильтр клики день`` (day clicks >= threshold) and
   ``Фильтр ДРР месяц`` (month DRR % >= threshold): delete the SKU from the
   campaign, and deactivate the whole campaign if the SKU cannot be deleted.

Credentials are read from the existing local ``config.py`` and are never
printed.  The script does not alter the Google Sheet or Ozon campaigns unless
those actions are explicitly enabled with command-line flags.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import io
import json
import os
import re
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

import config
import gsheets_utils


LOCK_FILE = Path(__file__).resolve().parent / "logs" / "cpc-hourly.lock"
PROGRESS_FILE = Path(__file__).resolve().parent / "logs" / "cpc-progress.json"


def _load_progress() -> dict[str, float]:
    try:
        data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_progress(campaign_ids: list[str]) -> None:
    progress = _load_progress()
    now = time.time()
    for campaign_id in campaign_ids:
        progress[campaign_id] = now
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")


@contextmanager
def run_lock(timeout: int = 0):
    """Межпроцессная блокировка, чтобы agent-прогоны не перекрывались.

    Блокировка в неблокирующем режиме: если другой процесс уже держит прогон,
    сразу выходим (возвращаем False), не дожидаясь. ``timeout`` > 0 ждёт
    указанное число секунд до захвата.
    """
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = open(LOCK_FILE, "a+")
    deadline = time.monotonic() + timeout if timeout > 0 else None
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                yield True
                return
            except OSError:
                if deadline is None or time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"Другой процесс уже выполняет прогон (lock: {LOCK_FILE})"
                    )
                time.sleep(5)
    finally:
        if acquired:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            finally:
                lock_handle.close()


BASE_URL = str(config.OZON_PERF_BASE_URL).rstrip("/")
SHEET_NAME = str(getattr(config, "OZON_CPC_SHEET_NAME", "СРС"))
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
REPORT_MAX_ATTEMPTS = int(os.getenv("OZON_CPC_REPORT_MAX_ATTEMPTS", "180"))
REPORT_SLEEP_SECONDS = int(os.getenv("OZON_CPC_REPORT_SLEEP_SECONDS", "5"))
TRANSIENT_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}

PERIOD_DAY = "day"
PERIOD_WEEK = "week"
PERIOD_MONTH = "month"
PERIODS = (PERIOD_DAY, PERIOD_WEEK, PERIOD_MONTH)
SHEET_WRITE_BATCH_SIZE = 20


class SourceAddressAdapter(HTTPAdapter):
    """Bind requests to the active LAN/Wi-Fi address when configured."""

    def __init__(self, source_ip: str, **kwargs: Any) -> None:
        self._source_address = (source_ip, 0)
        super().__init__(**kwargs)

    def init_poolmanager(self, connections: int, maxsize: int, block: bool = False, **pool_kwargs: Any) -> None:
        pool_kwargs["source_address"] = self._source_address
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            **pool_kwargs,
        )


def get_active_interface_ip() -> tuple[str, str]:
    preferred = os.getenv("CHECKSHEETS_BYPASS_INTERFACE", "").strip()
    interfaces = [preferred] if preferred else ["en1", "en0"]
    for interface in interfaces:
        if not interface:
            continue
        output = os.popen(f"ifconfig {interface}").read()
        if preferred or "status: active" in output:
            match = re.search(r"\binet (\d+\.\d+\.\d+\.\d+)", output)
            if match:
                return interface, match.group(1)
    raise RuntimeError("Не найден активный LAN/Wi-Fi интерфейс для Ozon Performance")


def create_session() -> requests.Session:
    session = requests.Session()
    skip_bypass = any(
        os.getenv(name, "").lower() == "true"
        for name in ("OZON_PERF_SKIP_BYPASS", "OZON_CPC_SKIP_BYPASS")
    )
    if skip_bypass:
        print("Bypass skipped via environment setting")
        return session
    try:
        interface, source_ip = get_active_interface_ip()
        adapter = SourceAddressAdapter(source_ip)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        print(f"Ozon Performance route: {interface} ({source_ip})")
    except Exception as exc:
        print(f"Предупреждение: bypass-маршрут не настроен ({type(exc).__name__}); используется обычный маршрут")
    return session


@dataclass(frozen=True)
class SheetRow:
    row_number: int
    article: str
    sku: str
    campaign_id: str
    filter_clicks: float
    filter_drr: float
    toggle: str
    values: list[str]


@dataclass
class Metric:
    clicks: float = 0.0
    impressions: float = 0.0
    ctr: float = 0.0
    spend: float = 0.0
    average_cpc: float = 0.0
    sold: float = 0.0
    revenue: float = 0.0
    drr: float = 0.0
    carts: float = 0.0


@dataclass
class ReportBlock:
    campaign_id: str | None
    metrics: dict[str, Metric] = field(default_factory=dict)


@dataclass(frozen=True)
class Candidate:
    row_number: int
    campaign_id: str
    sku: str
    clicks: float
    drr: float
    filter_clicks: float
    filter_drr: float
    action: str


def normalize(value: Any) -> str:
    return " ".join(str(value or "").replace("\ufeff", "").replace("\xa0", " ").strip().lower().split())


def normalize_id(value: Any) -> str:
    text = str(value or "").strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def parse_number(value: Any) -> float:
    text = (
        str(value or "")
        .replace("\ufeff", "")
        .replace("\xa0", "")
        .replace(" ", "")
        .replace("₽", "")
        .replace("%", "")
        .replace(",", ".")
        .strip()
    )
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def period_range(period: str, now: datetime | None = None) -> tuple[str, str]:
    """Return RFC3339 ``from``/``to`` bounds for day/week/month in Moscow time."""
    current = (now or datetime.now()).astimezone(MOSCOW_TZ)
    today = current.date()
    if period == PERIOD_DAY:
        start = today
    elif period == PERIOD_WEEK:
        start = today - timedelta(days=6)
    elif period == PERIOD_MONTH:
        start = today.replace(day=1)
    else:
        raise ValueError(f"Неизвестный период: {period}")
    return f"{start.isoformat()}T00:00:00+03:00", f"{today.isoformat()}T23:59:59+03:00"


def build_statistics_payload(
    campaign_ids: list[str],
    date_from: str,
    date_to: str,
    group_by: str = "NO_GROUP_BY",
) -> dict[str, Any]:
    """Build the documented asynchronous campaign-statistics request.

    ``NO_GROUP_BY`` returns one row per SKU aggregated over the requested
    period.  ``DATE`` returns one row per SKU per day, which lets a single
    month-scoped report serve day/week/month aggregations at once.
    """
    if not campaign_ids:
        raise ValueError("Для отчёта нужна хотя бы одна кампания")
    return {
        "campaigns": campaign_ids,
        "from": date_from,
        "to": date_to,
        "groupBy": group_by,
    }


class TokenManager:
    """Получает и обновляет Performance API Bearer-токен.

    Ozon выдаёт токен примерно на 30 минут. Длинный CPC-прогон по сотням
    кампаний может пережить этот срок, поэтому токен нельзя получать только
    один раз в начале запуска.
    """

    def __init__(self, session: requests.Session, refresh_margin_seconds: int = 120) -> None:
        self.session = session
        self.refresh_margin_seconds = max(30, int(refresh_margin_seconds))
        self._token: str | None = None
        self._refresh_at = 0.0
        self._auth_blocked = False

    def get(self, force: bool = False) -> str:
        if self._auth_blocked:
            raise RuntimeError(
                "Ozon Performance authorization is blocked after repeated HTTP 401/403; "
                "прогон остановлен без повторных массовых запросов"
            )
        now = time.monotonic()
        if not force and self._token and now < self._refresh_at:
            return self._token

        data = _fetch_token_data(self.session)
        token = data.get("access_token") if isinstance(data, dict) else None
        if not token:
            raise RuntimeError("Ozon Performance token отсутствует в ответе")
        expires_in = float(data.get("expires_in", 1800) or 1800)
        self._token = str(token)
        self._refresh_at = now + max(30.0, expires_in - self.refresh_margin_seconds)
        print(f"Ozon Performance token refreshed (expires_in={int(expires_in)}s)")
        return self._token

    def force_refresh(self) -> str:
        self._token = None
        return self.get(force=True)

    def mark_auth_failure(self) -> None:
        self._auth_blocked = True


def _resolve_token(token: str | TokenManager | None, force_refresh: bool = False) -> str | None:
    if isinstance(token, TokenManager):
        return token.force_refresh() if force_refresh else token.get()
    return str(token) if token else None


def request_json(
    session: requests.Session,
    method: str,
    path: str,
    token: str | TokenManager | None = None,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: int = 60,
) -> Any:
    auth_retry_attempted = False
    while True:
        token_value = _resolve_token(token, force_refresh=auth_retry_attempted)
        headers = {"Content-Type": "application/json"}
        if token_value:
            headers["Authorization"] = f"Bearer {token_value}"
        response = session.request(
            method,
            f"{BASE_URL}{path}",
            headers=headers,
            params=params,
            json=payload,
            timeout=timeout,
        )
        if response.status_code in (401, 403) and isinstance(token, TokenManager):
            if not auth_retry_attempted:
                auth_retry_attempted = True
                continue
            token.mark_auth_failure()
        break
    if response.status_code >= 400:
        detail = response.text[:1000].replace(config.OZON_PERF_CLIENT_SECRET, "[REDACTED]")
        raise RuntimeError(f"{method} {path} -> HTTP {response.status_code}: {detail}")
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"{method} {path} -> ответ не JSON") from exc


def request_bytes(
    session: requests.Session,
    path: str,
    token: str | TokenManager,
    timeout: int = 180,
) -> bytes:
    auth_retry_attempted = False
    while True:
        token_value = _resolve_token(token, force_refresh=auth_retry_attempted)
        response = session.get(
            path if path.startswith("http") else f"{BASE_URL}{path}",
            headers={"Authorization": f"Bearer {token_value}"},
            timeout=timeout,
        )
        if response.status_code in (401, 403) and isinstance(token, TokenManager):
            if not auth_retry_attempted:
                auth_retry_attempted = True
                continue
            token.mark_auth_failure()
        break
    if response.status_code >= 400:
        raise RuntimeError(f"GET report -> HTTP {response.status_code}: {response.text[:500]}")
    return response.content


def is_auth_error(exc: Exception) -> bool:
    text = str(exc)
    return "HTTP 401" in text or "HTTP 403" in text


def _fetch_token_data(session: requests.Session) -> dict[str, Any]:
    data = request_json(
        session,
        "POST",
        "/api/client/token",
        payload={
            "client_id": config.OZON_PERF_CLIENT_ID,
            "client_secret": config.OZON_PERF_CLIENT_SECRET,
            "grant_type": "client_credentials",
        },
        timeout=30,
    )
    return data if isinstance(data, dict) else {}


def get_token(session: requests.Session) -> str:
    data = _fetch_token_data(session)
    token = data.get("access_token") if isinstance(data, dict) else None
    if not token:
        raise RuntimeError("Ozon Performance token отсутствует в ответе")
    return str(token)


def get_campaigns(session: requests.Session, token: str | TokenManager, state: str | None = None) -> list[dict[str, Any]]:
    params: dict[str, str] = {"advObjectType": "SKU"}
    if state:
        params["state"] = state
    data = request_json(session, "GET", "/api/client/campaign", token=token, params=params)
    campaigns = data.get("list", []) if isinstance(data, dict) else []
    return [campaign for campaign in campaigns if normalize_id(campaign.get("id"))]


def extract_products(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        products = data.get("products")
        if products is None and isinstance(data.get("data"), dict):
            products = data["data"].get("products")
        if isinstance(products, list):
            return [item for item in products if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def get_campaign_products(session: requests.Session, token: str | TokenManager, campaign_id: str) -> set[str]:
    data = request_json(session, "GET", f"/api/client/campaign/{campaign_id}/v2/products", token=token)
    result: set[str] = set()
    for product in extract_products(data):
        sku = product.get("sku", product.get("SKU"))
        if sku is not None and normalize_id(sku):
            result.add(normalize_id(sku))
    return result


def create_statistics_report(
    session: requests.Session,
    token: str | TokenManager,
    campaign_ids: list[str],
    date_from: str,
    date_to: str,
    group_by: str = "NO_GROUP_BY",
    retries: int = 3,
) -> str:
    payload = build_statistics_payload(campaign_ids, date_from, date_to, group_by=group_by)
    for attempt in range(1, retries + 1):
        try:
            data = request_json(session, "POST", "/api/client/statistics", token=token, payload=payload, timeout=60)
            uuid = data.get("UUID") if isinstance(data, dict) else None
            if not uuid:
                raise RuntimeError("Ozon Performance не вернул UUID отчёта")
            return str(uuid)
        except RuntimeError as exc:
            if "429" not in str(exc) or attempt >= retries:
                raise
            time.sleep(10 * attempt)
    raise RuntimeError("Не удалось создать отчёт")


def wait_for_report(
    session: requests.Session,
    token: str | TokenManager,
    report_uuid: str,
    max_attempts: int = REPORT_MAX_ATTEMPTS,
    sleep_seconds: int = REPORT_SLEEP_SECONDS,
) -> bytes:
    report_path = f"/api/client/statistics/report?{urlencode({'UUID': report_uuid})}"
    last_state = "UNKNOWN"
    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            time.sleep(sleep_seconds)
        status = request_json(session, "GET", f"/api/client/statistics/{report_uuid}", token=token, timeout=60)
        state = str(status.get("state", "UNKNOWN")) if isinstance(status, dict) else "UNKNOWN"
        if state != last_state:
            print(f"report_state={state}")
            last_state = state
        if state == "ERROR":
            raise RuntimeError(f"Ошибка генерации отчёта: {status}")
        if state == "OK":
            return request_bytes(session, report_path, token)
    raise TimeoutError(f"Таймаут ожидания отчёта {report_uuid}; последнее состояние={last_state}")


def find_column(headers: list[str], aliases: Iterable[str]) -> int:
    normalized = [normalize(header) for header in headers]
    for alias in aliases:
        alias_normalized = normalize(alias)
        if alias_normalized in normalized:
            return normalized.index(alias_normalized)
    return -1


def campaign_id_from_filename(filename: str) -> str | None:
    match = re.search(r"(?<!\d)(\d{5,})(?!\d)", filename)
    return match.group(1) if match else None


def parse_report_block(
    filename: str,
    text: str,
    fallback_campaign_id: str | None = None,
    day_from: str | None = None,
    day_to: str | None = None,
) -> ReportBlock:
    rows = [row for row in csv.reader(io.StringIO(text), delimiter=";") if any(cell.strip() for cell in row)]
    header_index = -1
    for index, row in enumerate(rows[:20]):
        normalized = [normalize(cell) for cell in row]
        if find_column(normalized, ["sku"]) >= 0 and find_column(normalized, ["клики", "clicks"]) >= 0:
            header_index = index
            break
    if header_index < 0:
        raise RuntimeError(f"В отчёте {filename} не найден заголовок SKU/Клики")

    headers = rows[header_index]
    sku_index = find_column(headers, ["sku"])
    clicks_index = find_column(headers, ["клики", "clicks"])
    campaign_index = find_column(headers, ["campaign id", "campaign_id", "id кампании"])
    day_index = find_column(headers, ["день", "day", "дата"])
    metric_indexes = {
        "impressions": find_column(headers, ["показы", "impressions"]),
        "ctr": find_column(headers, ["ctr, %", "ctr"]),
        "spend": find_column(headers, ["расход, ₽, с ндс", "расход", "spend"]),
        "average_cpc": find_column(headers, ["средняя стоимость клика, ₽", "средняя стоимость клика", "cpc"]),
        "sold": find_column(headers, ["продано товаров", "заказы", "orders"]),
        "revenue": find_column(headers, ["продажи в продвижении, ₽", "продажи в продвижении", "revenue"]),
        "drr": find_column(headers, ["дрр в продвижении, %", "ддр в продвижении, %"]),
        "carts": find_column(headers, ["добавления в корзину", "корзины", "carts"]),
    }
    campaign_id = campaign_id_from_filename(filename) or fallback_campaign_id
    if campaign_index >= 0:
        for row in rows[header_index + 1 :]:
            if len(row) > campaign_index and normalize_id(row[campaign_index]):
                campaign_id = normalize_id(row[campaign_index])
                break

    metrics: dict[str, Metric] = {}
    for row in rows[header_index + 1 :]:
        if len(row) <= max(sku_index, clicks_index):
            continue
        if day_index >= 0 and day_index < len(row) and (day_from or day_to):
            day_raw = normalize(row[day_index])
            if day_from and day_raw < day_from or day_to and day_raw > day_to:
                continue
        sku = normalize_id(row[sku_index])
        if not sku or normalize(sku) in {"sku", "всего", "total"}:
            continue
        metric = Metric(clicks=parse_number(row[clicks_index]))
        for key, index in metric_indexes.items():
            if index >= 0 and index < len(row):
                setattr(metric, key, parse_number(row[index]))
        previous = metrics.setdefault(sku, Metric())
        for key in vars(metric):
            setattr(previous, key, getattr(previous, key) + getattr(metric, key))
    return ReportBlock(campaign_id=campaign_id, metrics=metrics)


def parse_report(
    raw: bytes,
    campaign_ids: list[str],
    day_from: str | None = None,
    day_to: str | None = None,
) -> dict[tuple[str, str], Metric]:
    blocks: list[tuple[str, str]] = []
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for name in archive.namelist():
                if not name.endswith("/"):
                    blocks.append((name, archive.read(name).decode("utf-8-sig", errors="replace")))
    else:
        blocks.append(("report.csv", raw.decode("utf-8-sig", errors="replace")))

    if not blocks:
        raise RuntimeError("Отчёт пустой")
    fallback = campaign_ids[0] if len(campaign_ids) == 1 else None
    result: dict[tuple[str, str], Metric] = {}
    for filename, text in blocks:
        block = parse_report_block(filename, text, fallback, day_from=day_from, day_to=day_to)
        if not block.campaign_id:
            raise RuntimeError(f"Не удалось определить campaign_id для блока {filename}; запись остановлена")
        for sku, metric in block.metrics.items():
            key = (block.campaign_id, sku)
            existing = result.setdefault(key, Metric())
            for field_name in vars(metric):
                setattr(existing, field_name, getattr(existing, field_name) + getattr(metric, field_name))
    return result


def read_sheet_rows() -> tuple[Any, list[str], list[SheetRow]]:
    worksheet = gsheets_utils.get_worksheet(SHEET_NAME)
    headers, rows = rows_from_values(worksheet.get_all_values())
    return worksheet, headers, rows


def rows_from_values(values: list[list[str]]) -> tuple[list[str], list[SheetRow]]:
    if not values:
        raise RuntimeError(f"Лист {SHEET_NAME!r} пустой")
    headers = values[0]
    sku_index = find_column(headers, ["sku ozon", "sku"])
    campaign_index = find_column(headers, ["campain id", "campaign id", "campaign_id"])
    article_index = find_column(headers, ["art", "артикул"])
    filter_clicks_index = find_column(headers, ["фильтр клики день"])
    filter_drr_index = find_column(headers, ["фильтр дрр месяц"])
    toggle_index = find_column(headers, ["включение/отключение компании", "включение отключение компании"])
    if sku_index < 0 or campaign_index < 0:
        raise RuntimeError("В листе СРС нужны колонки 'SKU OZON' и 'CAMPAIN ID'")

    rows: list[SheetRow] = []
    for row_number, values_row in enumerate(values[1:], start=2):
        padded = list(values_row) + [""] * (len(headers) - len(values_row))
        article = str(padded[article_index]).strip() if article_index >= 0 else ""
        if article_index >= 0 and not article:
            continue
        sku = normalize_id(padded[sku_index])
        campaign_id = normalize_id(padded[campaign_index])
        if not sku and not campaign_id:
            continue
        if not sku or not campaign_id:
            continue
        filter_clicks = parse_number(padded[filter_clicks_index]) if filter_clicks_index >= 0 else 0.0
        filter_drr = parse_number(padded[filter_drr_index]) if filter_drr_index >= 0 else 0.0
        toggle = padded[toggle_index].strip() if toggle_index >= 0 else ""
        rows.append(
            SheetRow(
                row_number=row_number,
                article=article,
                sku=sku,
                campaign_id=campaign_id,
                filter_clicks=filter_clicks,
                filter_drr=filter_drr,
                toggle=toggle,
                values=padded,
            )
        )
    return headers, rows


def is_cpc_campaign(campaign: dict[str, Any] | None) -> bool:
    if not campaign:
        return False
    payment_type = normalize(campaign.get("PaymentType", campaign.get("paymentType", "")))
    return not payment_type or payment_type == "cpc"


def build_candidates(
    rows: list[SheetRow],
    metrics_by_period: dict[str, dict[tuple[str, str], Metric]],
    products_by_campaign: dict[str, set[str]],
) -> list[Candidate]:
    day_metrics = metrics_by_period.get(PERIOD_DAY, {})
    month_metrics = metrics_by_period.get(PERIOD_MONTH, {})
    candidates: list[Candidate] = []
    for row in rows:
        if row.filter_clicks <= 0 and row.filter_drr <= 0:
            continue
        day = day_metrics.get((row.campaign_id, row.sku), Metric())
        month = month_metrics.get((row.campaign_id, row.sku), Metric())
        clicks_triggered = row.filter_clicks > 0 and day.clicks >= row.filter_clicks
        drr_triggered = row.filter_drr > 0 and month.drr >= row.filter_drr
        if not clicks_triggered and not drr_triggered:
            continue
        if row.sku not in products_by_campaign.get(row.campaign_id, set()):
            action = "skip_not_in_campaign"
        else:
            action = "delete"
        candidates.append(
            Candidate(
                row_number=row.row_number,
                campaign_id=row.campaign_id,
                sku=row.sku,
                clicks=day.clicks,
                drr=month.drr,
                filter_clicks=row.filter_clicks,
                filter_drr=row.filter_drr,
                action=action,
            )
        )
    unique: dict[tuple[str, str], Candidate] = {}
    for candidate in candidates:
        unique.setdefault((candidate.campaign_id, candidate.sku), candidate)
    return list(unique.values())


def delete_sku(session: requests.Session, token: str | TokenManager, campaign_id: str, sku: str) -> Any:
    return request_json(
        session,
        "POST",
        f"/api/client/campaign/{campaign_id}/products/delete",
        token=token,
        payload={"sku": [sku]},
        timeout=60,
    )


def deactivate_campaign(session: requests.Session, token: str | TokenManager, campaign_id: str) -> Any:
    return request_json(
        session,
        "POST",
        f"/api/client/campaign/{campaign_id}/deactivate",
        token=token,
        payload={},
        timeout=60,
    )


def campaign_budget(campaign: dict[str, Any] | None) -> float:
    """Return the explicit campaign budget, not the technical weekly cap."""
    if not campaign:
        return 0.0
    for field_name in ("budget", "dailyBudget"):
        raw_value = campaign.get(field_name)
        if raw_value not in (None, ""):
            return parse_number(raw_value)
    return 0.0


def write_sheet_metrics(
    worksheet: Any,
    headers: list[str],
    rows: list[SheetRow],
    metrics_by_period: dict[str, dict[tuple[str, str], Metric]],
    campaigns_by_id: dict[str, dict[str, Any]],
) -> None:
    if not rows:
        return
    header_map = {normalize(header): index + 1 for index, header in enumerate(headers)}
    metric_columns = {
        "расход день": (PERIOD_DAY, "spend"),
        "расход неделя": (PERIOD_WEEK, "spend"),
        "расход месяц": (PERIOD_MONTH, "spend"),
        "показы день": (PERIOD_DAY, "impressions"),
        "показы неделя": (PERIOD_WEEK, "impressions"),
        "показы месяц": (PERIOD_MONTH, "impressions"),
        "клики день": (PERIOD_DAY, "clicks"),
        "клики неделя": (PERIOD_WEEK, "clicks"),
        "клики месяц": (PERIOD_MONTH, "clicks"),
        "ctr, % месяц": (PERIOD_MONTH, "ctr"),
        "средняя стоимость клика месяц": (PERIOD_MONTH, "average_cpc"),
        "продано месяц": (PERIOD_MONTH, "sold"),
        "дрр в продвижении месяц": (PERIOD_MONTH, "drr"),
        "корзины месяц": (PERIOD_MONTH, "carts"),
    }
    name_col = header_map.get("campain name")
    budget_col = header_map.get("бюджет")
    status_col = header_map.get("статус")

    start_row = rows[0].row_number
    end_row = rows[-1].row_number
    period_metrics = {period: metrics_by_period.get(period, {}) for period in PERIODS}

    def value_for(row: SheetRow, period: str, field_name: str) -> Any:
        return getattr(period_metrics[period].get((row.campaign_id, row.sku), Metric()), field_name)

    if name_col:
        values = [
            [str(campaigns_by_id[row.campaign_id].get("title", "")) if row.campaign_id in campaigns_by_id else ""]
            for row in rows
        ]
        cell_range = f"{column_letter(name_col)}{start_row}:{column_letter(name_col)}{end_row}"
        worksheet.update(range_name=cell_range, values=values)

    for header, (period, field_name) in metric_columns.items():
        column = header_map.get(header)
        if not column:
            continue
        values = [[value_for(row, period, field_name)] for row in rows]
        cell_range = f"{column_letter(column)}{start_row}:{column_letter(column)}{end_row}"
        worksheet.update(range_name=cell_range, values=values)

    if budget_col:
        values = [[campaign_budget(campaigns_by_id.get(row.campaign_id))] for row in rows]
        cell_range = f"{column_letter(budget_col)}{start_row}:{column_letter(budget_col)}{end_row}"
        worksheet.update(range_name=cell_range, values=values)

    if status_col:
        values = [
            [str(campaigns_by_id[row.campaign_id].get("state", "NOT_RUNNING")) if row.campaign_id in campaigns_by_id else "NOT_RUNNING"]
            for row in rows
        ]
        cell_range = f"{column_letter(status_col)}{start_row}:{column_letter(status_col)}{end_row}"
        worksheet.update(range_name=cell_range, values=values)


def column_letter(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def fetch_report_bytes(
    session: requests.Session,
    token: str | TokenManager,
    batch: list[str],
    date_from: str,
    date_to: str,
    group_by: str = "NO_GROUP_BY",
) -> bytes:
    last_exc: Exception | None = None
    for attempt in range(1, 6):
        try:
            report_uuid = create_statistics_report(session, token, batch, date_from, date_to, group_by=group_by)
        except Exception as exc:
            if is_auth_error(exc):
                raise
            last_exc = exc
            print(f"  Ошибка создания отчёта (попытка {attempt}/5): {exc}")
            time.sleep(15 * attempt)
            continue
        print(f"  Отчёт создан: кампаний={len(batch)}")
        try:
            return wait_for_report(session, token, report_uuid)
        except RuntimeError as exc:
            if is_auth_error(exc):
                raise
            last_exc = exc
            print(f"  Ошибка отчёта (попытка {attempt}/5): {exc}")
            time.sleep(15 * attempt)
    raise RuntimeError(f"Не удалось получить отчёт после 5 попыток: {last_exc}")


def fetch_period_metrics(
    session: requests.Session,
    token: str | TokenManager,
    campaign_ids: list[str],
    batch_size: int,
    on_batch: Callable[[list[str], dict[str, dict[tuple[str, str], Metric]]], None] | None = None,
) -> dict[str, dict[tuple[str, str], Metric]]:
    """Fill day/week/month from a single month-scoped DATE report per batch.

    Ozon limits every statistics report to 10 campaigns and 1 active report at
    a time, so the only reliable speed-up is to fetch one month report per
    batch (groupBy=DATE) and split the daily rows into the three periods.

    ``on_batch`` is called right after each successfully fetched batch so the
    caller can write that slice to the sheet without waiting for the whole run.
    """
    today_str = datetime.now(MOSCOW_TZ).date().strftime("%d.%m.%Y")
    week_from = (datetime.now(MOSCOW_TZ).date() - timedelta(days=6)).strftime("%d.%m.%Y")
    month_from, month_to = period_range(PERIOD_MONTH)
    result: dict[str, dict[tuple[str, str], Metric]] = {period: {} for period in PERIODS}
    for start in range(0, len(campaign_ids), batch_size):
        batch = campaign_ids[start : start + batch_size]
        try:
            raw = fetch_report_bytes(session, token, batch, month_from, month_to, group_by="DATE")
        except Exception as exc:
            if is_auth_error(exc):
                raise
            print(f"Пропущен батч {start // batch_size + 1}: {exc}")
            continue
        filters = {
            PERIOD_DAY: (today_str, today_str),
            PERIOD_WEEK: (week_from, today_str),
            PERIOD_MONTH: (None, None),
        }
        batch_metrics: dict[str, dict[tuple[str, str], Metric]] = {period: {} for period in PERIODS}
        for period, (day_from, day_to) in filters.items():
            metrics = parse_report(raw, batch, day_from=day_from, day_to=day_to)
            for key, metric in metrics.items():
                existing = result[period].setdefault(key, Metric())
                for field_name in vars(metric):
                    setattr(existing, field_name, getattr(existing, field_name) + getattr(metric, field_name))
                batch_metrics[period][key] = metric
        if on_batch is not None:
            on_batch(batch, batch_metrics)
    return result


def _sheet_sku(rows: list[SheetRow], campaign_id: str) -> list[str]:
    return [row.sku for row in rows if row.campaign_id == campaign_id and row.sku]


def _pending_rows(
    headers: list[str],
    rows: list[SheetRow],
    sheet_campaign_ids: list[str],
) -> list[SheetRow]:
    """Строки, ещё не отмеченные в локальном прогрессе успешной выгрузки.

    Прогресс хранится в ``logs/cpc-progress.json``. Каждый инкрементальный
    прогон (``--limit-rows N``) берёт первые N необработанных строк и после
    успешной записи помечает их, следующий прогон продолжает со следующих.
    """
    progress = _load_progress()
    seen: set[str] = set()
    pending: list[SheetRow] = []
    for row in rows:
        if row.campaign_id in seen:
            continue
        if row.campaign_id not in sheet_campaign_ids:
            continue
        if str(row.campaign_id) in progress:
            continue
        seen.add(row.campaign_id)
        pending.append(row)
    return pending


def rows_for_campaign_batch(rows: list[SheetRow], campaign_ids: Iterable[str]) -> list[SheetRow]:
    """Return every sheet row belonging to a successfully fetched batch.

    A campaign can have no activity today while still having valid week/month
    metrics. Incremental writes must therefore not use the day metric map as
    the row-selection gate; otherwise historical metrics are silently skipped
    and the same batch is retried forever.
    """
    selected_ids = {normalize_id(campaign_id) for campaign_id in campaign_ids}
    return [row for row in rows if row.campaign_id in selected_ids]


def contiguous_row_groups(rows: list[SheetRow]) -> list[list[SheetRow]]:
    """Split rows into contiguous sheet ranges safe for rectangular updates."""
    if not rows:
        return []
    ordered = sorted(rows, key=lambda row: row.row_number)
    groups: list[list[SheetRow]] = [[ordered[0]]]
    for row in ordered[1:]:
        if row.row_number == groups[-1][-1].row_number + 1:
            groups[-1].append(row)
        else:
            groups.append([row])
    return groups


def run(args: argparse.Namespace) -> int:
    worksheet, headers, sheet_rows = read_sheet_rows()
    print(f"Лист {SHEET_NAME}: строк с SKU/campaign={len(sheet_rows)}")
    sheet_campaign_ids = sorted({row.campaign_id for row in sheet_rows})

    session = create_session()
    token = TokenManager(session)
    campaigns_by_id = {normalize_id(campaign.get("id")): campaign for campaign in get_campaigns(session, token)}
    running_cpc_ids = {
        campaign_id
        for campaign_id, campaign in campaigns_by_id.items()
        if normalize(campaign.get("state")) == "campaign_state_running" and is_cpc_campaign(campaign)
    }
    report_campaign_ids = [campaign_id for campaign_id in sheet_campaign_ids if campaign_id in campaigns_by_id]
    missing = [campaign_id for campaign_id in sheet_campaign_ids if campaign_id not in campaigns_by_id]
    limit_rows = max(0, int(getattr(args, "limit_rows", 0) or 0))
    if limit_rows > 0:
        pending = _pending_rows(headers, sheet_rows, sheet_campaign_ids)
        selected = pending[:limit_rows]
        if selected:
            report_campaign_ids = sorted({row.campaign_id for row in selected})
            print(f"Инкрементно: строк с метриками={len(pending)} к обработке={len(selected)} кампаний={len(report_campaign_ids)} (лимит {limit_rows})")
        else:
            report_campaign_ids = []
            print(f"Инкрементно: нет незаполненных строк (лимит {limit_rows}), все данные уже внесены")
    print(
        f"SKU-кампаний в Ozon={len(campaigns_by_id)}; из СРС в Ozon={len(report_campaign_ids)}; "
        f"не найдено в Ozon={len(missing)}; running CPC из СРС="
        f"{sum(1 for campaign_id in report_campaign_ids if campaign_id in running_cpc_ids)}"
    )

    products_by_campaign: dict[str, set[str]] = {}
    metrics_by_period: dict[str, dict[tuple[str, str], Metric]] = {period: {} for period in PERIODS}
    written_incremental: set[str] = set()
    streamed_write_count = 0
    filter_deactivated: set[str] = set()
    if report_campaign_ids:
        try:
            if args.apply:
                products_by_campaign = {
                    campaign_id: get_campaign_products(session, token, campaign_id)
                    for campaign_id in report_campaign_ids
                }
            else:
                print("Состав товаров не запрашивается: --apply не задан")
            batch_size = max(1, int(args.batch_size))
            write_buffer_ids: list[str] = []
            write_buffer_metrics: dict[str, dict[tuple[str, str], Metric]] = {
                period: {} for period in PERIODS
            }

            def _flush_write_buffer() -> None:
                nonlocal streamed_write_count, written_incremental
                if not write_buffer_ids:
                    return
                buffer_ids = list(dict.fromkeys(write_buffer_ids))
                buffer_rows = rows_for_campaign_batch(sheet_rows, buffer_ids)
                row_groups = contiguous_row_groups(buffer_rows)
                if not row_groups:
                    write_buffer_ids.clear()
                    for period in PERIODS:
                        write_buffer_metrics[period].clear()
                    return
                try:
                    # Write only after two API batches (20 campaigns), with a
                    # smaller final flush when the total is not divisible by 20.
                    for row_group in row_groups:
                        write_sheet_metrics(
                            worksheet,
                            headers,
                            row_group,
                            write_buffer_metrics,
                            campaigns_by_id,
                        )
                    written_incremental.update(buffer_ids)
                    streamed_write_count += len(buffer_ids)
                    print(
                        f"Порция записана: кампаний={len(buffer_ids)} строк={len(buffer_rows)}"
                    )
                    write_buffer_ids.clear()
                    for period in PERIODS:
                        write_buffer_metrics[period].clear()
                except Exception as exc:
                    print(f"Ошибка записи порции {buffer_ids}: {exc}")

            def _on_batch(
                batch: list[str],
                batch_metrics: dict[str, dict[tuple[str, str], Metric]],
            ) -> None:
                if args.write_sheet:
                    write_buffer_ids.extend(batch)
                    for period in PERIODS:
                        for key, metric in batch_metrics.get(period, {}).items():
                            existing = write_buffer_metrics[period].setdefault(key, Metric())
                            for field_name in vars(metric):
                                setattr(
                                    existing,
                                    field_name,
                                    getattr(existing, field_name) + getattr(metric, field_name),
                                )
                    if len(write_buffer_ids) >= SHEET_WRITE_BATCH_SIZE:
                        _flush_write_buffer()

                if args.stop_on_filter:
                    for row in sheet_rows:
                        if row.campaign_id not in running_cpc_ids or row.filter_clicks <= 0:
                            continue
                        metric = batch_metrics[PERIOD_DAY].get((row.campaign_id, row.sku))
                        if metric is None or metric.clicks < row.filter_clicks:
                            continue
                        if row.campaign_id in filter_deactivated:
                            continue
                        try:
                            deactivate_campaign(session, token, row.campaign_id)
                            filter_deactivated.add(row.campaign_id)
                            print(
                                f"Немедленно остановлена кампания {row.campaign_id}: "
                                f"клики день={metric.clicks:g} >= фильтр={row.filter_clicks:g}"
                            )
                        except RuntimeError as exc:
                            print(f"Не удалось немедленно остановить кампанию {row.campaign_id}: {exc}")

            metrics_by_period = fetch_period_metrics(session, token, report_campaign_ids, batch_size, on_batch=_on_batch)
            if args.write_sheet:
                _flush_write_buffer()
            for period in PERIODS:
                print(f"Период {period}: SKU/кампания пар={len(metrics_by_period[period])}")
        except Exception as exc:
            if is_auth_error(exc):
                raise
            print(f"Ошибка сбора метрик: {exc}; продолжаем с пустыми метриками (фильтры не применяются, но toggle выполнится)")
    else:
        print("Нет кампаний из листа СРС в Ozon; отчёты не создаются")

    candidates: list[Candidate] = []
    try:
        candidates = [
            candidate
            for candidate in build_candidates(sheet_rows, metrics_by_period, products_by_campaign)
            if candidate.campaign_id in running_cpc_ids
        ]
    except Exception as exc:
        print(f"Ошибка построения кандидатов: {exc}; фильтры пропущены")
    deletions = [candidate for candidate in candidates if candidate.action == "delete"]
    skipped = [candidate for candidate in candidates if candidate.action != "delete"]
    print(f"Кандидаты по фильтрам: {len(candidates)}; к удалению={len(deletions)}; пропущено={len(skipped)}")
    for candidate in candidates:
        print(
            f"row={candidate.row_number} campaign={candidate.campaign_id} sku={candidate.sku} "
            f"clicks_day={candidate.clicks:g}/{candidate.filter_clicks:g} drr_month={candidate.drr:g}/{candidate.filter_drr:g} "
            f"action={candidate.action}"
        )

    metrics_ok = any(metrics_by_period.get(period) for period in PERIODS)
    if args.write_sheet:
        if streamed_write_count:
            if limit_rows > 0:
                _save_progress(sorted(written_incremental))
                print(f"Инкрементная запись завершена: помечено {len(written_incremental)} кампаний")
            else:
                print(f"Потоковая запись завершена: кампаний={streamed_write_count}")
        elif not metrics_ok:
            print("Метрики не собраны — запись в таблицу пропущена (прежние данные сохранены); toggle всё равно выполнится")
        else:
            print("Успешных порций для записи нет; прежние данные сохранены")

    if not args.apply and not args.apply_toggle and not args.stop_on_filter:
        print("DRY-RUN: остановка не выполнялась")
        return 0

    if os.getenv("OZON_CPC_CONFIRM_DELETE", "") != "YES":
        raise RuntimeError("Для live-остановки установите OZON_CPC_CONFIRM_DELETE=YES")
    # The report can wait in Ozon's queue for minutes. Re-read campaign
    # membership immediately before every destructive request rather than
    # trusting the earlier discovery snapshot.
    current_products: dict[str, set[str]] = {}
    deactivated_by_filter: set[str] = set()
    if args.apply:
        for candidate in deletions:
            products = current_products.get(candidate.campaign_id)
            if products is None:
                products = get_campaign_products(session, token, candidate.campaign_id)
                current_products[candidate.campaign_id] = products
            if candidate.sku not in products:
                print(
                    f"Пропущен SKU {candidate.sku} из кампании {candidate.campaign_id}: "
                    "на момент удаления товара уже нет в кампании"
                )
                continue
            try:
                delete_sku(session, token, candidate.campaign_id, candidate.sku)
                products.remove(candidate.sku)
                print(f"Остановлен SKU {candidate.sku} из кампании {candidate.campaign_id}")
            except RuntimeError as exc:
                print(
                    f"Не удалось остановить SKU {candidate.sku} ({candidate.campaign_id}): {exc}. "
                    "Останавливаем кампанию целиком"
                )
                try:
                    deactivate_campaign(session, token, candidate.campaign_id)
                    current_products[candidate.campaign_id] = set()
                    deactivated_by_filter.add(candidate.campaign_id)
                    print(f"Остановлена кампания {candidate.campaign_id}")
                except RuntimeError as deactivate_exc:
                    print(f"Не удалось остановить кампанию {candidate.campaign_id}: {deactivate_exc}")

    if args.apply_toggle:
        _apply_toggle(session, token, sheet_rows, campaigns_by_id, deactivated_by_filter)
    return 0


def toggle_set_campaign(
    token: str | TokenManager,
    session,
    campaign_id: str,
    activate: bool,
    max_attempts: int = 5,
) -> None:
    """Вызывает activate/deactivate с ретраем только на 429/5xx.

    401/403 обрабатываются TokenManager одним обновлением токена; повторный
    запрет считается постоянным и не размножается по сотням кампаний.
    """
    action = "activate" if activate else "deactivate"
    path = f"/api/client/campaign/{campaign_id}/{action}"
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            request_json(session, "POST", path, token=token, payload={}, timeout=60)
            return
        except RuntimeError as exc:
            last_exc = exc
            text = str(exc)
            if "429" not in text and "HTTP 5" not in text:
                raise
            time.sleep(min(2 ** attempt, 15))
    raise last_exc  # type: ignore[misc]


def _apply_toggle(
    session,
    token: str | TokenManager,
    sheet_rows: list[SheetRow],
    campaigns_by_id: dict[str, dict[str, Any]],
    deactivated_by_filter: set[str],
) -> None:
    """Применяет переключатель Z (Включение/отключение компании).

    - '1' → activate если кампания не RUNNING
    - '0' → deactivate если кампания RUNNING
    - пусто/прочее → пропуск
    Кампании, остановленные фильтрами в этом же запуске, не активируем.
    """
    on_count = off_count = skip_count = 0
    for row in sheet_rows:
        cid = row.campaign_id
        campaign = campaigns_by_id.get(cid)
        if not campaign:
            continue
        state = normalize(campaign.get("state", ""))
        toggle = (row.toggle or "").strip()
        if toggle not in ("0", "1"):
            skip_count += 1
            continue
        if toggle == "1":
            if state == "campaign_state_running":
                skip_count += 1
                continue
            if cid in deactivated_by_filter:
                print(f"row={row.row_number} campaign={cid}: пропуск activate — остановлена фильтром")
                skip_count += 1
                continue
            try:
                toggle_set_campaign(token, session, cid, activate=True)
                on_count += 1
                print(f"row={row.row_number} campaign={cid}: активирована (toggle=1)")
            except RuntimeError as exc:
                print(f"row={row.row_number} campaign={cid}: ошибка activate: {exc}")
                if is_auth_error(exc):
                    raise
        else:
            if state != "campaign_state_running":
                skip_count += 1
                continue
            try:
                toggle_set_campaign(token, session, cid, activate=False)
                off_count += 1
                print(f"row={row.row_number} campaign={cid}: деактивирована (toggle=0)")
            except RuntimeError as exc:
                print(f"row={row.row_number} campaign={cid}: ошибка deactivate: {exc}")
                if is_auth_error(exc):
                    raise
    print(f"Toggle: активировано={on_count}, деактивировано={off_count}, пропущено={skip_count}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=10, help="Кампаний в одном отчёте")
    parser.add_argument("--write-sheet", action="store_true", help="Записать метрики и статусы в СРС")
    parser.add_argument("--apply", action="store_true", help="Остановить SKU/кампании по фильтрам")
    parser.add_argument(
        "--apply-toggle",
        action="store_true",
        help="Применить вкл/выкл по колонке Z",
    )
    parser.add_argument(
        "--stop-on-filter",
        action="store_true",
        help="Сразу отключать кампанию после получения дневных кликов >= фильтра",
    )
    parser.add_argument(
        "--lock-timeout",
        type=float,
        default=float(os.getenv("OZON_CPC_LOCK_TIMEOUT", "0")),
        help="Секунд ждать захвата lock-файла, прежде чем прерваться (0 = не ждать)",
    )
    parser.add_argument(
        "--limit-rows",
        type=int,
        default=int(os.getenv("OZON_CPC_LIMIT_ROWS", "0")),
        help="Обработать только первые N незаполненных строк (0 = все). Используется для инкрементальной загрузки.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        with run_lock(args.lock_timeout):
            return run(args)
    except RuntimeError as exc:
        print(str(exc))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
