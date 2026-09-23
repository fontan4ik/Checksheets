"""Synchronize IEK catalog availability into the far-right column of ТЕСТ.

IEK's client API authenticates with the literal username ``ticket`` and an
API key. The key is read from the macOS Keychain item
``checksheets-iek-api`` (account ``ticket``), or from ``IEK_API_KEY`` when a
runtime environment explicitly supplies it. The account password is never
used or stored by this script.
"""

from __future__ import annotations

import logging
import math
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import requests

import config
import gsheets_utils
from network_bypass import SourceAddressAdapter


BASE_URL = "https://bp.iek.ru"
LOGIN_URL = f"{BASE_URL}/oauth/login"
CATALOG_URL = f"{BASE_URL}/api/catalog/v1/client/catalog"
BALANCES_URL = f"{BASE_URL}/api/catalog/v1/client/category/{{slug}}/balances-json"
KEYCHAIN_SERVICE = "checksheets-iek-api"
API_USERNAME = "ticket"
SHEET_NAME = "ТЕСТ"
BRAND_HEADER = "Бренд"
ARTICLE_HEADER = "МОДЕЛЬ"
STOCK_HEADER = "Остаток IEK"
HTTP_ATTEMPTS = max(1, int(os.getenv("IEK_HTTP_ATTEMPTS", "4")))
HTTP_TIMEOUT = max(5.0, float(os.getenv("IEK_HTTP_TIMEOUT", "30")))
RETRY_BASE_SECONDS = max(0.0, float(os.getenv("IEK_RETRY_BASE_SECONDS", "2")))
CATEGORY_REQUEST_INTERVAL = max(0.0, float(os.getenv("IEK_CATEGORY_REQUEST_INTERVAL", "0.25")))
DETAIL_REQUEST_INTERVAL = max(0.0, float(os.getenv("IEK_DETAIL_REQUEST_INTERVAL", "0.5")))

logger = logging.getLogger("iek_stock_sync")


def get_api_key() -> str:
    """Read the IEK API key from the environment or macOS Keychain."""
    api_key = os.getenv("IEK_API_KEY", "").strip()
    if api_key:
        return api_key

    result = subprocess.run(
        [
            "/usr/bin/security",
            "find-generic-password",
            "-a",
            API_USERNAME,
            "-s",
            KEYCHAIN_SERVICE,
            "-w",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(
            "IEK API key is missing. Add the key from the IEK profile to macOS "
            f"Keychain (service '{KEYCHAIN_SERVICE}', account '{API_USERNAME}')."
        )
    return result.stdout.strip()


def get_active_interface() -> tuple[str, str]:
    """Choose the active LAN/Wi-Fi interface used by local supplier clients."""
    import socket

    preferred = os.getenv("CHECKSHEETS_BYPASS_INTERFACE", "").strip()
    candidates = (preferred,) if preferred else ("en1", "en0")
    for interface in candidates:
        if not interface:
            continue
        result = subprocess.run(
            ["/sbin/ifconfig", interface],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or "status: active" not in result.stdout:
            continue
        match = re.search(r"\binet (\d+\.\d+\.\d+\.\d+)\b", result.stdout)
        if match:
            # Validate that interface names can be bound by the current host.
            socket.if_nametoindex(interface)
            return interface, match.group(1)
    raise RuntimeError(
        "No active LAN/Wi-Fi interface found for IEK API access. "
        "Set CHECKSHEETS_BYPASS_INTERFACE explicitly."
    )


def create_session() -> requests.Session:
    interface, source_ip = get_active_interface()
    session = requests.Session()
    adapter = SourceAddressAdapter(source_ip, interface_name=interface)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "Accept": "application/json",
            "User-Agent": "Checksheets IEK stock sync/1.0",
        }
    )
    logger.info("IEK API network interface: %s (%s)", interface, source_ip)
    return session


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    data: dict[str, str] | None = None,
    expect_json: bool = True,
    allow_not_found: bool = False,
) -> dict[str, Any] | None:
    transient_statuses = {408, 425, 429, 500, 502, 503, 504}
    for attempt in range(1, HTTP_ATTEMPTS + 1):
        try:
            response = session.request(
                method,
                url,
                data=data,
                timeout=HTTP_TIMEOUT,
            )
        except requests.RequestException as exc:
            if attempt >= HTTP_ATTEMPTS:
                raise RuntimeError(
                    f"IEK API request failed ({method} {url}): {type(exc).__name__}"
                ) from exc
            delay = min(RETRY_BASE_SECONDS * (2 ** (attempt - 1)), 60.0)
            logger.warning(
                "IEK API network error on attempt %d/%d (%s); retrying in %.1fs",
                attempt,
                HTTP_ATTEMPTS,
                type(exc).__name__,
                delay,
            )
            time.sleep(delay)
            continue

        if response.status_code in transient_statuses and attempt < HTTP_ATTEMPTS:
            retry_after = response.headers.get("Retry-After", "")
            try:
                delay = min(max(float(retry_after), 0.0), 120.0)
            except ValueError:
                delay = min(RETRY_BASE_SECONDS * (2 ** (attempt - 1)), 60.0)
            logger.warning(
                "IEK API returned HTTP %d on attempt %d/%d; retrying in %.1fs",
                response.status_code,
                attempt,
                HTTP_ATTEMPTS,
                delay,
            )
            time.sleep(delay)
            continue

        if allow_not_found and response.status_code == 404:
            return None
        if not response.ok:
            raise RuntimeError(
                f"IEK API returned HTTP {response.status_code} for {method} {url}"
            )
        if not expect_json:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"IEK API returned non-JSON data for {method} {url}"
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"IEK API returned an invalid object for {method} {url}")
        return payload

    raise RuntimeError("IEK API retry loop exited unexpectedly")


def login(session: requests.Session, api_key: str) -> None:
    payload = request_json(
        session,
        "POST",
        LOGIN_URL,
        data={"username": API_USERNAME, "password": api_key},
        expect_json=False,
    )
    if payload.get("status", 200) not in (200, "200"):
        raise RuntimeError("IEK API authentication failed")
    cookie_pairs = (("kc-access", "kc-state"), ("bp-access", "bp-state"))
    if not any(all(session.cookies.get(name) for name in pair) for pair in cookie_pairs):
        raise RuntimeError(
            "IEK API authentication did not establish the documented session cookies; "
            "check the API key and client API access."
        )


def normalize_article(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def validate_stock(value: Any, article: str) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"IEK returned a non-numeric available value for {article}")
    quantity = float(value)
    if not math.isfinite(quantity) or quantity < 0:
        raise ValueError(f"IEK returned an invalid available value for {article}")
    return int(quantity) if quantity.is_integer() else quantity


def fetch_catalog_stocks(session: requests.Session) -> tuple[dict[str, int | float | None], int]:
    """Read each top-level category's bulk balances file and index by article."""
    catalog = request_json(session, "GET", CATALOG_URL)
    categories = catalog.get("categories")
    if not isinstance(categories, list) or not categories:
        raise RuntimeError("IEK catalog response contains no categories")

    stock_by_article: dict[str, int | float | None] = {}
    category_snapshots: list[str] = []
    total_products = 0
    for category in categories:
        if not isinstance(category, dict) or not category.get("slug"):
            raise RuntimeError("IEK catalog contains a category without a slug")
        slug = str(category["slug"])
        url = BALANCES_URL.format(slug=quote(slug, safe=""))
        balances = request_json(session, "GET", url)
        if balances is None:
            raise RuntimeError(f"IEK balances response for category '{slug}' was empty")
        products = balances.get("products")
        if not isinstance(products, list):
            raise RuntimeError(
                f"IEK balances response for category '{slug}' has no products list"
            )
        snapshot = balances.get("date")
        if snapshot:
            category_snapshots.append(str(snapshot))

        for product in products:
            if not isinstance(product, dict) or not product.get("article"):
                raise RuntimeError(
                    f"IEK balances response for category '{slug}' has an item without article"
                )
            article = str(product["article"]).strip()
            normalized = normalize_article(article)
            stock = validate_stock(product.get("available"), article)
            if normalized in stock_by_article and stock_by_article[normalized] != stock:
                raise RuntimeError(
                    f"IEK returned conflicting balances for article {article}"
                )
            stock_by_article[normalized] = stock
            total_products += 1
        if CATEGORY_REQUEST_INTERVAL:
            time.sleep(CATEGORY_REQUEST_INTERVAL)

    if category_snapshots:
        logger.info(
            "IEK source snapshot date(s): %s",
            ", ".join(sorted(set(category_snapshots))),
        )
    logger.info(
        "IEK catalog loaded: %d categories, %d product records, %d unique articles",
        len(categories),
        total_products,
        len(stock_by_article),
    )
    return stock_by_article, len(categories)


def fetch_missing_product_stocks(
    session: requests.Session,
    worksheet,
    stock_by_article: dict[str, int | float | None],
) -> tuple[int, int]:
    """Use the single-product endpoint for IEK rows omitted by bulk balances."""
    headers = worksheet.row_values(1)
    columns = gsheets_utils.resolve_header_columns(
        headers,
        {"brand": BRAND_HEADER, "article": ARTICLE_HEADER},
        worksheet.title,
    )
    first_column = min(columns.values())
    last_column = max(columns.values())
    source_range = (
        f"{column_letter(first_column)}1:"
        f"{column_letter(last_column)}{worksheet.row_count}"
    )
    rows = worksheet.get(source_range, value_render_option="UNFORMATTED_VALUE")
    brand_offset = columns["brand"] - first_column
    article_offset = columns["article"] - first_column
    missing: dict[str, str] = {}
    for row in rows[1:]:
        brand = row[brand_offset] if brand_offset < len(row) else ""
        article_value = row[article_offset] if article_offset < len(row) else ""
        if gsheets_utils.normalize_header(brand) != "iek":
            continue
        article = str(article_value or "").strip()
        normalized = normalize_article(article)
        if article and normalized not in stock_by_article:
            missing.setdefault(normalized, article)

    loaded = 0
    not_found: list[str] = []
    for normalized, article in missing.items():
        if DETAIL_REQUEST_INTERVAL:
            time.sleep(DETAIL_REQUEST_INTERVAL)
        url = f"{BASE_URL}/api/catalog/v1/client/products/{quote(article, safe='')}"
        product = request_json(session, "GET", url, allow_not_found=True)
        if product is None:
            not_found.append(article)
            continue
        returned_article = str(product.get("article", "")).strip()
        if normalize_article(returned_article) != normalized:
            raise RuntimeError(
                f"IEK product endpoint returned a mismatched article for {article}"
            )
        stock_by_article[normalized] = validate_stock(product.get("available"), article)
        loaded += 1

    if missing:
        logger.info(
            "IEK detail fallback: %d recovered from product endpoint, %d not found",
            loaded,
            len(not_found),
        )
        if not_found:
            logger.warning(
                "%d IEK article(s) are absent from both endpoints; those rows will be blank. Examples: %s",
                len(not_found),
                ", ".join(not_found[:10]),
            )
    return loaded, len(not_found)


def column_letter(column: int) -> str:
    result = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        result = chr(65 + remainder) + result
    return result


def ensure_stock_header(worksheet) -> int:
    headers = worksheet.row_values(1)
    target = gsheets_utils.normalize_header(STOCK_HEADER)
    matches = [
        index
        for index, header in enumerate(headers, start=1)
        if gsheets_utils.normalize_header(header) == target
    ]
    if len(matches) > 1:
        raise ValueError(f"Sheet '{worksheet.title}' has duplicate '{STOCK_HEADER}' headers")
    if matches:
        return matches[0]

    column = worksheet.col_count + 1
    worksheet.add_cols(1)
    worksheet.update_cell(1, column, STOCK_HEADER)
    logger.info("Created sheet header '%s' in column %s", STOCK_HEADER, column_letter(column))
    return column


def build_sheet_values(worksheet, stock_by_article: dict[str, int | float | None]) -> tuple[int, list[list[Any]]]:
    headers = worksheet.row_values(1)
    header_columns = gsheets_utils.resolve_header_columns(
        headers,
        {"brand": BRAND_HEADER, "article": ARTICLE_HEADER, "stock": STOCK_HEADER},
        worksheet.title,
    )
    brand_column = header_columns["brand"]
    article_column = header_columns["article"]
    stock_column = header_columns["stock"]
    first_source_column = min(brand_column, article_column)
    last_source_column = max(brand_column, article_column)
    source_range = (
        f"{column_letter(first_source_column)}1:"
        f"{column_letter(last_source_column)}{worksheet.row_count}"
    )
    source_rows = worksheet.get(source_range, value_render_option="UNFORMATTED_VALUE")
    brand_offset = brand_column - first_source_column
    article_offset = article_column - first_source_column

    output: list[list[Any]] = []
    matched_rows = 0
    missing_articles: list[str] = []
    for row_number in range(2, worksheet.row_count + 1):
        source_index = row_number - 1
        source_row = source_rows[source_index] if source_index < len(source_rows) else []
        brand = source_row[brand_offset] if brand_offset < len(source_row) else ""
        article_value = source_row[article_offset] if article_offset < len(source_row) else ""
        if gsheets_utils.normalize_header(brand) != "iek":
            output.append([""])
            continue

        article = str(article_value or "").strip()
        if not article:
            missing_articles.append(f"row {row_number}: blank {ARTICLE_HEADER}")
            output.append([""])
            continue
        normalized = normalize_article(article)
        if normalized not in stock_by_article:
            missing_articles.append(f"row {row_number}: {article}")
            output.append([""])
            continue
        stock = stock_by_article[normalized]
        output.append(["" if stock is None else stock])
        matched_rows += 1

    if missing_articles:
        logger.warning(
            "%d IEK sheet row(s) have no API article and will be written blank. Examples: %s",
            len(missing_articles),
            "; ".join(missing_articles[:10]),
        )
    if matched_rows == 0:
        raise RuntimeError("No IEK product rows were found on the target sheet")

    logger.info(
        "Prepared %d IEK stock values for %d sheet rows in column %s",
        matched_rows,
        worksheet.row_count - 1,
        column_letter(stock_column),
    )
    return stock_column, output


def sync() -> None:
    started = datetime.now(timezone.utc)
    api_key = get_api_key()
    spreadsheet = gsheets_utils.get_gsheet_client().open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(SHEET_NAME)
    ensure_stock_header(worksheet)
    session = create_session()
    try:
        login(session, api_key)
        stock_by_article, _ = fetch_catalog_stocks(session)
        fetch_missing_product_stocks(session, worksheet, stock_by_article)
    finally:
        session.close()

    stock_column, values = build_sheet_values(worksheet, stock_by_article)
    last_row = len(values) + 1
    range_name = f"{column_letter(stock_column)}2:{column_letter(stock_column)}{last_row}"
    gsheets_utils._retry_gsheet_call(
        "write IEK stocks",
        lambda: worksheet.update(
            range_name,
            values,
            value_input_option="RAW",
        ),
    )
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    logger.info(
        "IEK stock sync completed: %d rows written to %s!%s in %.1fs",
        len(values),
        worksheet.title,
        range_name,
        elapsed,
    )


def main() -> int:
    logging.basicConfig(
        level=os.getenv("IEK_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        sync()
    except Exception:
        logger.exception("IEK stock sync failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
