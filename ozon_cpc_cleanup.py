#!/usr/bin/env python3
"""Ozon Performance CPC cleanup for the ``СРС`` sheet.

The normal invocation is a read-only dry-run.  Real SKU deletion requires
``--apply`` and is intentionally separate from the optional Sheets write.

Flow:
1. Read campaign/SKU pairs from the ``СРС`` worksheet.
2. Read running SKU campaigns from Ozon Performance API.
3. Read campaign products and keep only SKU pairs present in both sources.
4. Generate a current-day SKU report and wait for it to become ready.
5. Parse clicks from the CSV/ZIP report.
6. Plan deletion for rows with clicks >= threshold.
7. Optionally write metrics/status back to ``СРС`` and/or delete SKU from Ozon.

Credentials are read from the existing local ``config.py`` and are never
printed.  The script does not alter the Google Sheet or Ozon campaigns unless
those actions are explicitly enabled with command-line flags.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

import config
import gsheets_utils


BASE_URL = str(config.OZON_PERF_BASE_URL).rstrip("/")
SHEET_NAME = str(getattr(config, "OZON_CPC_SHEET_NAME", "СРС"))
DEFAULT_THRESHOLD = float(getattr(config, "OZON_CPC_CLICK_THRESHOLD", 10))
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
TRANSIENT_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}


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
    if os.getenv("OZON_PERF_SKIP_BYPASS", "").lower() == "true":
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
    values: list[str]


@dataclass
class Metric:
    clicks: float = 0.0
    impressions: float = 0.0
    ctr: float = 0.0
    spend: float = 0.0
    average_cpc: float = 0.0
    sold: float = 0.0
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


def current_day_period(now: datetime | None = None) -> tuple[str, str]:
    current = now.astimezone(MOSCOW_TZ) if now else datetime.now(MOSCOW_TZ)
    day = current.date().isoformat()
    return f"{day}T00:00:00+03:00", f"{day}T23:59:59+03:00"


def request_json(
    session: requests.Session,
    method: str,
    path: str,
    token: str | None = None,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: int = 60,
) -> Any:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = session.request(
        method,
        f"{BASE_URL}{path}",
        headers=headers,
        params=params,
        json=payload,
        timeout=timeout,
    )
    if response.status_code >= 400:
        detail = response.text[:1000].replace(config.OZON_PERF_CLIENT_SECRET, "[REDACTED]")
        raise RuntimeError(f"{method} {path} -> HTTP {response.status_code}: {detail}")
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"{method} {path} -> ответ не JSON") from exc


def request_bytes(session: requests.Session, path: str, token: str, timeout: int = 180) -> bytes:
    response = session.get(
        path if path.startswith("http") else f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"GET report -> HTTP {response.status_code}: {response.text[:500]}")
    return response.content


def get_token(session: requests.Session) -> str:
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
    token = data.get("access_token") if isinstance(data, dict) else None
    if not token:
        raise RuntimeError("Ozon Performance token отсутствует в ответе")
    return str(token)


def get_running_campaigns(session: requests.Session, token: str) -> list[dict[str, Any]]:
    data = request_json(
        session,
        "GET",
        "/api/client/campaign",
        token=token,
        params={"advObjectType": "SKU", "state": "CAMPAIGN_STATE_RUNNING"},
    )
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


def get_campaign_products(session: requests.Session, token: str, campaign_id: str) -> set[str]:
    data = request_json(session, "GET", f"/api/client/campaign/{campaign_id}/v2/products", token=token)
    result: set[str] = set()
    for product in extract_products(data):
        sku = product.get("sku", product.get("SKU"))
        if sku is not None and normalize_id(sku):
            result.add(normalize_id(sku))
    return result


def create_statistics_report(
    session: requests.Session,
    token: str,
    campaign_ids: list[str],
    date_from: str,
    date_to: str,
    retries: int = 3,
) -> str:
    payload = {
        "campaigns": campaign_ids,
        "from": date_from,
        "to": date_to,
        "groupBy": "DATE",
    }
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
    token: str,
    report_uuid: str,
    max_attempts: int = 60,
    sleep_seconds: int = 5,
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


def parse_report_block(filename: str, text: str, fallback_campaign_id: str | None = None) -> ReportBlock:
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
    metric_indexes = {
        "impressions": find_column(headers, ["показы", "impressions"]),
        "ctr": find_column(headers, ["ctr, %", "ctr"]),
        "spend": find_column(headers, ["расход, ₽, с ндс", "расход", "spend"]),
        "average_cpc": find_column(headers, ["средняя стоимость клика, ₽", "средняя стоимость клика", "cpc"]),
        "sold": find_column(headers, ["продано товаров", "заказы", "orders"]),
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


def parse_report(raw: bytes, campaign_ids: list[str]) -> dict[tuple[str, str], Metric]:
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
        block = parse_report_block(filename, text, fallback)
        if not block.campaign_id:
            raise RuntimeError(f"Не удалось определить campaign_id для блока {filename}; удаление остановлено")
        for sku, metric in block.metrics.items():
            key = (block.campaign_id, sku)
            existing = result.setdefault(key, Metric())
            for field_name in vars(metric):
                setattr(existing, field_name, getattr(existing, field_name) + getattr(metric, field_name))
    return result


def read_sheet_rows() -> tuple[Any, list[str], list[SheetRow]]:
    worksheet = gsheets_utils.get_worksheet(SHEET_NAME)
    values = worksheet.get_all_values()
    if not values:
        raise RuntimeError(f"Лист {SHEET_NAME!r} пустой")
    headers = values[0]
    sku_index = find_column(headers, ["sku ozon", "sku"])
    campaign_index = find_column(headers, ["campain id", "campaign id", "campaign_id"])
    article_index = find_column(headers, ["art", "артикул"])
    if sku_index < 0 or campaign_index < 0:
        raise RuntimeError("В листе СРС нужны колонки 'SKU OZON' и 'CAMPAIN ID'")

    rows: list[SheetRow] = []
    for row_number, values_row in enumerate(values[1:], start=2):
        padded = list(values_row) + [""] * (len(headers) - len(values_row))
        sku = normalize_id(padded[sku_index])
        campaign_id = normalize_id(padded[campaign_index])
        if not sku and not campaign_id:
            continue
        if not sku or not campaign_id:
            raise RuntimeError(f"СРС строка {row_number}: SKU OZON и CAMPAIN ID должны быть заполнены вместе")
        rows.append(
            SheetRow(
                row_number=row_number,
                article=str(padded[article_index]).strip() if article_index >= 0 else "",
                sku=sku,
                campaign_id=campaign_id,
                values=padded,
            )
        )
    return worksheet, headers, rows


def build_candidates(
    rows: list[SheetRow],
    metrics: dict[tuple[str, str], Metric],
    products_by_campaign: dict[str, set[str]],
    threshold: float,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for row in rows:
        metric = metrics.get((row.campaign_id, row.sku), Metric())
        if metric.clicks < threshold:
            continue
        if row.sku not in products_by_campaign.get(row.campaign_id, set()):
            candidates.append(Candidate(row.row_number, row.campaign_id, row.sku, metric.clicks, "skip_not_in_campaign"))
        else:
            candidates.append(Candidate(row.row_number, row.campaign_id, row.sku, metric.clicks, "delete"))
    unique: dict[tuple[str, str], Candidate] = {}
    for candidate in candidates:
        unique.setdefault((candidate.campaign_id, candidate.sku), candidate)
    return list(unique.values())


def delete_sku(session: requests.Session, token: str, campaign_id: str, sku: str) -> Any:
    return request_json(
        session,
        "POST",
        f"/api/client/campaign/{campaign_id}/products/delete",
        token=token,
        payload={"sku": [sku]},
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
    metrics: dict[tuple[str, str], Metric],
    campaigns_by_id: dict[str, dict[str, Any]],
) -> None:
    if not rows:
        return
    header_map = {normalize(header): index + 1 for index, header in enumerate(headers)}
    metric_columns = {
        "расход": "spend",
        "показы": "impressions",
        "клики": "clicks",
        "ctr, %": "ctr",
        "средняя стоимость клика": "average_cpc",
        "продано": "sold",
        "дрр в продвижении": "drr",
        "корзины": "carts",
    }
    all_values: list[list[Any]] = [list(row.values) for row in rows]
    budget_col = header_map.get("бюджет")
    status_col = header_map.get("статус")
    for row_offset, row in enumerate(rows):
        metric = metrics.get((row.campaign_id, row.sku), Metric())
        for header, field_name in metric_columns.items():
            column = header_map.get(header)
            if column:
                all_values[row_offset][column - 1] = getattr(metric, field_name)

        campaign = campaigns_by_id.get(row.campaign_id)
        if budget_col:
            all_values[row_offset][budget_col - 1] = campaign_budget(campaign)
        if status_col:
            all_values[row_offset][status_col - 1] = (
                str(campaign.get("state", "NOT_RUNNING")) if campaign else "NOT_RUNNING"
            )

    start_row = rows[0].row_number
    end_row = rows[-1].row_number
    # The current СРС data block is contiguous (rows 2..5).
    worksheet.update(f"A{start_row}:{column_letter(len(headers))}{end_row}", all_values)


def column_letter(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def run(args: argparse.Namespace) -> int:
    worksheet, headers, sheet_rows = read_sheet_rows()
    print(f"Лист {SHEET_NAME}: строк с SKU/campaign={len(sheet_rows)}")
    sheet_campaign_ids = sorted({row.campaign_id for row in sheet_rows})

    session = create_session()
    token = get_token(session)
    running = get_running_campaigns(session, token)
    running_by_id = {
        normalize_id(campaign.get("id")): campaign
        for campaign in running
        if not normalize(campaign.get("PaymentType", campaign.get("paymentType", "")))
        or normalize(campaign.get("PaymentType", campaign.get("paymentType", ""))) == "cpc"
    }
    campaign_ids = [campaign_id for campaign_id in sheet_campaign_ids if campaign_id in running_by_id]
    inactive = [campaign_id for campaign_id in sheet_campaign_ids if campaign_id not in running_by_id]
    print(f"Running campaigns={len(running)}; из СРС активных={len(campaign_ids)}; неактивных={len(inactive)}")
    if not campaign_ids:
        print("Нет активных кампаний из листа СРС; отчёт не создаётся")
        return 0

    products_by_campaign = {campaign_id: get_campaign_products(session, token, campaign_id) for campaign_id in campaign_ids}
    date_from, date_to = current_day_period()
    metrics: dict[tuple[str, str], Metric] = {}
    batch_size = max(1, int(args.batch_size))
    for start in range(0, len(campaign_ids), batch_size):
        batch = campaign_ids[start : start + batch_size]
        report_uuid = create_statistics_report(session, token, batch, date_from, date_to)
        print(f"Отчёт создан: кампаний={len(batch)}")
        metrics.update(parse_report(wait_for_report(session, token, report_uuid), batch))

    candidates = build_candidates(sheet_rows, metrics, products_by_campaign, args.threshold)
    deletions = [candidate for candidate in candidates if candidate.action == "delete"]
    skipped = [candidate for candidate in candidates if candidate.action != "delete"]
    print(f"Кандидаты clicks>={args.threshold:g}: {len(candidates)}; к удалению={len(deletions)}; пропущено={len(skipped)}")
    for candidate in candidates:
        print(f"row={candidate.row_number} campaign={candidate.campaign_id} sku={candidate.sku} clicks={candidate.clicks:g} action={candidate.action}")

    if args.write_sheet:
        write_sheet_metrics(worksheet, headers, sheet_rows, metrics, running_by_id)
        print("Метрики/статусы записаны в СРС")

    if not args.apply:
        print("DRY-RUN: удаление не выполнялось")
        return 0

    if os.getenv("OZON_CPC_CONFIRM_DELETE", "") != "YES":
        raise RuntimeError("Для live-удаления установите OZON_CPC_CONFIRM_DELETE=YES вместе с --apply")
    for candidate in deletions:
        delete_sku(session, token, candidate.campaign_id, candidate.sku)
        print(f"Удалён SKU {candidate.sku} из кампании {candidate.campaign_id}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="Порог кликов, по умолчанию 10")
    parser.add_argument("--batch-size", type=int, default=10, help="Кампаний в одном отчёте")
    parser.add_argument("--write-sheet", action="store_true", help="Записать метрики и статусы в СРС")
    parser.add_argument("--apply", action="store_true", help="Выполнить удаление SKU из кампаний")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
