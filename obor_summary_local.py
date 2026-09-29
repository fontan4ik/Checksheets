#!/usr/bin/env python3
"""Recalculate the ОБОР summary locally and write its seven value columns."""

from __future__ import annotations

import argparse
import base64
import fcntl
import json
import math
import os
import re
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests

from gsheets_utils import _retry_gsheet_call, get_gsheet_client, resolve_header_columns
from network_bypass import SourceAddressAdapter


ROOT = Path(__file__).resolve().parent
SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI"
TARGET_SHEET = "ОБОР"
WB_REMAINS_URL = "https://seller-analytics-api.wildberries.ru/api/v1/warehouse_remains"
WB_REQUEST_INTERVAL_SECONDS = 12.0
WB_STATUS_POLL_SECONDS = 5.0
WB_MAX_STATUS_POLLS = 12
WB_MAX_429_RETRIES = 4
LOCK_PATH = ROOT / "logs" / "obor_summary.lock"
SHARED_SETTINGS_PATH = ROOT / "Shared_Настройки.js"
WB_TOKEN_FILE = Path(
    os.environ.get(
        "WB_API_TOKEN_FILE",
        str(Path.home() / "AI agents" / "secrets" / "wb_api_token"),
    )
)

OUTPUT_HEADERS = (
    "Озон ост",
    "Уход месяц",
    "Факт выкупа месяц",
    "ВБ всего",
    "ВБ ост",
    "ВБ Ух",
    "ВБ факт выкуп месяц",
)

# The source columns match the existing Apps Script calculation.
SHEET_FIELDS = (
    {"key": "ozonStock", "header": "Озон ост", "sheet": "ТЕСТ", "values": ("F",), "subtract": ()},
    {"key": "ozonMonthWithdrawal", "header": "Уход месяц", "sheet": "ТЕСТ", "values": ("AQ", "AR"), "subtract": ("BH",)},
    {"key": "ozonMonthBuyout", "header": "Факт выкупа месяц", "sheet": "UNIT API", "values": ("M",), "subtract": ()},
    {"key": "wbMonthWithdrawal", "header": "ВБ Ух", "sheet": "ТЕСТ", "values": ("AV", "AW"), "subtract": ()},
    {"key": "wbMonthBuyout", "header": "ВБ факт выкуп месяц", "sheet": "UNIT WB", "values": ("AP",), "subtract": ()},
)


def normalize_article(value) -> str:
    return re.sub(r"[\s\u00a0]", "", "" if value is None else str(value)).strip()


def parse_article(article: str) -> tuple[str, int]:
    match = re.match(r"^(.*)-([0-9]+)$", str(article))
    return (match.group(1), int(match.group(2)) or 1) if match else (str(article), 1)


def parse_number(value) -> float:
    if value is None or value == "" or isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else 0.0
    normalized = re.sub(r"[\s\u00a0%]", "", str(value)).replace(",", ".")
    try:
        result = float(normalized)
    except ValueError:
        return 0.0
    return result if math.isfinite(result) else 0.0


def round_value(value: float) -> float:
    # Match JavaScript Math.round, including its tie direction for negatives.
    return math.floor((float(value or 0.0) * 100.0) + 0.5) / 100.0


def column_number(column: str) -> int:
    result = 0
    for letter in column.upper():
        result = result * 26 + ord(letter) - ord("A") + 1
    return result


def column_letter(number: int) -> str:
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def normalized_wb_base(article: str) -> str:
    base, _ = parse_article(normalize_article(article))
    # Sheets may remove leading zeros from numeric-only article keys.
    return re.sub(r"^0+(?=\d)", "", base) if re.fullmatch(r"\d+", base) else base


def _read_env_token() -> str | None:
    token = os.environ.get("WB_API_TOKEN", "").strip()
    if token:
        return token[7:].strip() if token.lower().startswith("bearer ") else token

    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == "WB_API_TOKEN":
                token = value.strip().strip("\"'")
                return token[7:].strip() if token.lower().startswith("bearer ") else token
    return None


def get_wb_api_token() -> str:
    # Follow the local stock syncs: prefer an environment/.env override, then
    # the shared local token file. Keep the Apps Script value as last fallback.
    token = _read_env_token()
    if not token and WB_TOKEN_FILE.exists():
        token = WB_TOKEN_FILE.read_text(encoding="utf-8").strip()
        token = token[7:].strip() if token.lower().startswith("bearer ") else token
    if not token:
        source = SHARED_SETTINGS_PATH.read_text(encoding="utf-8")
        match = re.search(r"Authorization\s*:\s*['\"]Bearer\s+([^'\"\s]+)['\"]", source)
        if not match:
            raise RuntimeError("WB token not found in Shared_Настройки.js or WB_API_TOKEN")
        token = match.group(1)

    try:
        claims = token.split(".")[1]
        claims += "=" * ((4 - len(claims) % 4) % 4)
        expiry = json.loads(base64.urlsafe_b64decode(claims)).get("exp")
    except (IndexError, ValueError, json.JSONDecodeError):
        expiry = None
    if isinstance(expiry, (int, float)) and expiry <= time.time():
        expired_at = datetime.fromtimestamp(expiry, timezone.utc).isoformat()
        raise RuntimeError(f"WB Analytics token expired at {expired_at}; refresh it before this run")
    return token


def create_wb_session() -> requests.Session:
    preferred = os.getenv("CHECKSHEETS_BYPASS_INTERFACE", "").strip()
    interfaces = [preferred] if preferred else []
    interfaces.extend(name for name in ("en1", "en0") if name not in interfaces)
    for interface in interfaces:
        result = subprocess.run(
            ["ifconfig", interface], capture_output=True, text=True, check=False
        )
        match = re.search(r"\binet (\d+\.\d+\.\d+\.\d+)", result.stdout)
        if match and (interface == preferred or "status: active" in result.stdout):
            session = requests.Session()
            adapter = SourceAddressAdapter(match.group(1), interface_name=interface)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            print(f"WB bypass interface: {interface} ({match.group(1)})", flush=True)
            return session
    raise RuntimeError(
        "No active LAN/Wi-Fi interface found for WB API. "
        "Set CHECKSHEETS_BYPASS_INTERFACE explicitly."
    )


class WbWarehouseReport:
    def __init__(self, token: str):
        self.session = create_wb_session()
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        self.last_request_at = 0.0

    def _request(self, url: str, *, params: dict | None = None):
        if params:
            url = f"{url}?{urlencode(params)}"
        for attempt in range(1, WB_MAX_429_RETRIES + 1):
            elapsed = time.monotonic() - self.last_request_at
            if elapsed < WB_REQUEST_INTERVAL_SECONDS:
                time.sleep(WB_REQUEST_INTERVAL_SECONDS - elapsed)
            try:
                self.last_request_at = time.monotonic()
                response = self.session.get(
                    url, headers=self.headers, timeout=(15, 90)
                )
            except requests.RequestException:
                if attempt == WB_MAX_429_RETRIES:
                    raise
                time.sleep(min(3 * (2 ** (attempt - 1)), 30))
                continue

            self.last_request_at = time.monotonic()
            if response.status_code == 429 and attempt < WB_MAX_429_RETRIES:
                retry_seconds = parse_number(response.headers.get("X-RateLimit-Retry"))
                delay = min(300.0, max(WB_REQUEST_INTERVAL_SECONDS, retry_seconds))
                print(f"WB warehouse report: HTTP 429; повтор через {delay:.0f} сек.", flush=True)
                time.sleep(delay)
                continue
            if response.status_code >= 500 and attempt < WB_MAX_429_RETRIES:
                time.sleep(min(3 * (2 ** (attempt - 1)), 30))
                continue
            return response
        raise RuntimeError("WB warehouse report: исчерпаны повторы запроса")

    @staticmethod
    def _json(response, action: str):
        if not 200 <= response.status_code < 300:
            detail = (response.text or "")[:300]
            raise RuntimeError(
                f"WB warehouse report: HTTP {response.status_code} ({action}): {detail}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(f"WB warehouse report: некорректный JSON ({action})") from exc

    def fetch(self) -> list[dict]:
        url = f"{WB_REMAINS_URL}?locale=ru&groupBySa=true&groupByNm=true"
        created = self._json(self._request(url), "создание отчёта")
        task_id = (created.get("data") or {}).get("taskId")
        if not task_id:
            raise RuntimeError("WB warehouse report: в ответе создания нет taskId")

        status = None
        for _ in range(WB_MAX_STATUS_POLLS):
            time.sleep(WB_STATUS_POLL_SECONDS)
            status = self._json(
                self._request(f"{WB_REMAINS_URL}/tasks/{task_id}/status"),
                "проверка готовности",
            )
            if (status.get("data") or {}).get("status") == "done":
                break
        else:
            raise RuntimeError(
                f"WB warehouse report: не готов после {WB_MAX_STATUS_POLLS} проверок"
            )

        rows = self._json(
            self._request(f"{WB_REMAINS_URL}/tasks/{task_id}/download"),
            "загрузка отчёта",
        )
        if not isinstance(rows, list):
            raise RuntimeError("WB warehouse report: ожидался массив товаров")
        return rows


def aggregate_wb_rows(rows: list[dict]) -> dict[str, dict[str, dict[str, float]]]:
    result = {
        "total": {}, "live": {}, "totalByBase": {}, "liveByBase": {},
    }
    for row in rows:
        article = normalize_article((row or {}).get("vendorCode") or (row or {}).get("supplierArticle"))
        warehouses = (row or {}).get("warehouses")
        if not article or not isinstance(warehouses, list):
            continue
        total = sum(
            max(0.0, parse_number(warehouse.get("quantity")))
            for warehouse in warehouses
            if isinstance(warehouse, dict)
            and warehouse.get("warehouseName") == "Всего находится на складах"
        )
        live = sum(
            max(0.0, parse_number(warehouse.get("quantity")))
            for warehouse in warehouses
            if isinstance(warehouse, dict) and warehouse.get("warehouseName") == "Склад WB РФ"
        )
        _, multiplier = parse_article(article)
        total *= multiplier
        live *= multiplier
        base = normalized_wb_base(article)
        result["total"][article] = result["total"].get(article, 0.0) + total
        result["live"][article] = result["live"].get(article, 0.0) + live
        result["totalByBase"][base] = result["totalByBase"].get(base, 0.0) + total
        result["liveByBase"][base] = result["liveByBase"].get(base, 0.0) + live
    return result


def subtract_maps(total: dict[str, float], live: dict[str, float]) -> dict[str, float]:
    return {key: max(0.0, total.get(key, 0.0) - live.get(key, 0.0))
            for key in set(total) | set(live)}


def resolve_wb_value(exact_map: dict[str, float], article: str,
                     base_map: dict[str, float]) -> float:
    exact = normalize_article(article)
    if exact in exact_map:
        return exact_map[exact]
    base, multiplier = parse_article(exact)
    normalized_base = normalized_wb_base(exact)
    if exact == base and normalized_base in base_map:
        return base_map[normalized_base]
    if base in exact_map:
        return exact_map[base] * multiplier
    if exact == base and f"{exact}-1" in exact_map:
        return exact_map[f"{exact}-1"]
    return 0.0


def read_columns(worksheet, columns: list[str]) -> dict[str, list]:
    ranges = [f"{column}2:{column}" for column in columns]
    response = _retry_gsheet_call(
        f"чтение колонок листа {worksheet.title}",
        lambda: worksheet.batch_get(ranges, value_render_option="UNFORMATTED_VALUE"),
    )
    values = {}
    for column, value_range in zip(columns, response):
        values[column] = [row[0] if row else "" for row in value_range]
    return values


def build_source_map(worksheet, field: dict) -> dict[str, float]:
    columns = ["A", *field["values"], *field["subtract"]]
    required_last_column = max(column_number(column) for column in columns)
    if worksheet.col_count < required_last_column:
        raise RuntimeError(
            f"В {field['sheet']} недостаточно колонок для «{field['header']}»"
        )
    data = read_columns(worksheet, columns)
    row_count = max((len(values) for values in data.values()), default=0)
    result: dict[str, float] = {}
    for index in range(row_count):
        article = normalize_article(data["A"][index] if index < len(data["A"]) else "")
        if not article:
            continue
        base, multiplier = parse_article(article)
        value = sum(
            parse_number(data[column][index] if index < len(data[column]) else "")
            for column in field["values"]
        )
        subtract = sum(
            parse_number(data[column][index] if index < len(data[column]) else "")
            for column in field["subtract"]
        )
        result[base] = result.get(base, 0.0) + max(0.0, value - subtract) * multiplier
    return result


def retry_read(label: str, operation):
    return _retry_gsheet_call(label, operation)


@contextmanager
def exclusive_run_lock():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("ОБОР: предыдущий запуск ещё выполняется; этот запуск пропущен.", flush=True)
            yield False
            return
        yield True
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def updateOborSummary(dry_run: bool = False) -> dict:
    """Local equivalent of Apps Script updateOborSummary()."""
    client = get_gsheet_client()
    spreadsheet = retry_read(
        f"открытие таблицы {SPREADSHEET_ID}",
        lambda: client.open_by_key(SPREADSHEET_ID),
    )
    target = retry_read(f"открытие листа {TARGET_SHEET}",
                        lambda: spreadsheet.worksheet(TARGET_SHEET))
    headers = retry_read("чтение заголовков ОБОР", lambda: target.row_values(1))
    target_schema = {header: header for header in OUTPUT_HEADERS}
    target_schema["article"] = "Артикул"
    target_columns = resolve_header_columns(headers, target_schema, TARGET_SHEET)

    source_sheets = {}
    for field in SHEET_FIELDS:
        if field["sheet"] not in source_sheets:
            source_sheets[field["sheet"]] = retry_read(
                f"открытие листа {field['sheet']}",
                lambda name=field["sheet"]: spreadsheet.worksheet(name),
            )
    for field in SHEET_FIELDS:
        worksheet = source_sheets[field["sheet"]]
        required = ["A", *field["values"], *field["subtract"]]
        if worksheet.col_count < max(column_number(column) for column in required):
            raise RuntimeError(
                f"В {field['sheet']} отсутствуют нужные колонки для «{field['header']}»"
            )

    article_column = column_letter(target_columns["article"])
    target_articles = retry_read(
        "чтение артикулов ОБОР",
        lambda: target.get(f"{article_column}:{article_column}", value_render_option="UNFORMATTED_VALUE"),
    )
    target_last_row = len(target_articles)
    if target_last_row < 2:
        print("ОБОР: нет строк для записи.", flush=True)
        return {"rows": 0, "nonZero": {}}
    articles = [row[0] if row else "" for row in target_articles[1:]]

    source_maps = {
        field["key"]: build_source_map(source_sheets[field["sheet"]], field)
        for field in SHEET_FIELDS
    }
    wb_rows = WbWarehouseReport(get_wb_api_token()).fetch()
    wb_maps = aggregate_wb_rows(wb_rows)
    wb_dead = subtract_maps(wb_maps["total"], wb_maps["live"])
    wb_dead_by_base = subtract_maps(wb_maps["totalByBase"], wb_maps["liveByBase"])
    source_maps["wbStock"] = wb_dead
    source_maps["wbStockObor"] = wb_maps["live"]

    wb_source = {
        "wbStock": (wb_dead, wb_dead_by_base),
        "wbStockObor": (wb_maps["live"], wb_maps["liveByBase"]),
    }
    output = {}
    non_zero = {}
    for field in SHEET_FIELDS:
        value_map = source_maps[field["key"]]
        values = []
        for article_value in articles:
            article = normalize_article(article_value)
            if not article:
                value = ""
            else:
                base, _ = parse_article(article)
                value = round_value(value_map.get(base, 0.0))
                if value != 0:
                    non_zero[field["key"]] = non_zero.get(field["key"], 0) + 1
            values.append(value)
        output[field["header"]] = values

    for header, (exact_map, base_map) in wb_source.items():
        values = []
        for article_value in articles:
            article = normalize_article(article_value)
            value = "" if not article else round_value(resolve_wb_value(exact_map, article, base_map))
            if value != "" and value != 0:
                non_zero[header] = non_zero.get(header, 0) + 1
            values.append(value)
        output["ВБ всего" if header == "wbStock" else "ВБ ост"] = values

    print(
        f"WB warehouse report: товаров={len(wb_rows)}; "
        f"vendorCode={len(wb_maps['total'])}; "
        f"базовых артикулов={len(wb_maps['totalByBase'])}; "
        f"всего ед.={sum(wb_maps['totalByBase'].values()):g}; "
        f"склад WB РФ, ед.={sum(wb_maps['liveByBase'].values()):g}",
        flush=True,
    )

    if not dry_run:
        updates = []
        for header in OUTPUT_HEADERS:
            column = target_columns[header]
            letter = column_letter(column)
            updates.append({"range": f"{letter}1", "values": [[header]]})
            updates.append({
                "range": f"{letter}2:{letter}{target_last_row}",
                "values": [[value] for value in output[header]],
            })
        retry_read(
            "пакетная запись показателей ОБОР",
            lambda: target.batch_update(updates, raw=True),
        )

    print(
        f"ОБОР: {'dry-run; без записи' if dry_run else 'расчёт завершён'}; "
        f"строк={len(articles)}; ненулевые={json.dumps(non_zero, ensure_ascii=False, sort_keys=True)}; "
        "СДЭК Остаток отключён",
        flush=True,
    )
    return {"rows": len(articles), "nonZero": non_zero}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="читать источники, не записывать лист")
    args = parser.parse_args()
    with exclusive_run_lock() as acquired:
        if not acquired:
            return 0
        updateOborSummary(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
