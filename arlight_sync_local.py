"""Synchronize Arlight stock and catalog price to Google Sheets.

The supplier portal uses a login session rather than a permanent API token.
The password is read from ``ARLIGHT_ASSETS_PASSWORD`` or from the macOS
Keychain item ``checksheets-arlight-assets``; it is never stored in this file.

The API exposes a generic ``price`` field, not a field explicitly identified
as minimum internet price. The requested ``Миц Arlight`` sheet header receives
that current API price value for Arlight rows matched by manufacturer article.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Any

import requests

import gsheets_utils
from network_bypass import SourceAddressAdapter


ARLIGHT_BASE_URL = "https://assets.transistor.ru"
ARLIGHT_LOGIN_URL = f"{ARLIGHT_BASE_URL}/"
ARLIGHT_PRICE_PAGE_URL = f"{ARLIGHT_BASE_URL}/price/v3/sites/price.html"
ARLIGHT_PRICE_JSON_URL = f"{ARLIGHT_BASE_URL}/price/v3/sites/price.json"
ARLIGHT_LOGIN = os.getenv("ARLIGHT_ASSETS_LOGIN", "ntc-es@yandex.ru").strip()
ARLIGHT_KEYCHAIN_SERVICE = "checksheets-arlight-assets"

SHEET_NAME = "ARL TR"
ARTICLE_HEADER = "Артикул производителя"
STOCK_HEADER = "Остаток"
ARTICLE_COLUMN = 2  # B
STOCK_COLUMN = 6  # F
TEST_SHEET_NAME = "ТЕСТ"
TEST_MODEL_HEADER = "МОДЕЛЬ"
TEST_BRAND_HEADER = "Бренд"
TEST_PRICE_HEADER = "Миц Arlight"

MIN_API_ITEMS = max(1, int(os.getenv("ARLIGHT_MIN_API_ITEMS", "10000")))
MIN_MATCH_RATE = float(os.getenv("ARLIGHT_MIN_MATCH_RATE", "0.90"))
MIN_PRICE_MATCH_RATE = float(os.getenv("ARLIGHT_MIN_PRICE_MATCH_RATE", "0.90"))
HTTP_ATTEMPTS = max(1, int(os.getenv("ARLIGHT_HTTP_ATTEMPTS", "4")))


@dataclass(frozen=True)
class MatchStats:
    sheet_rows: int
    nonempty_articles: int
    matched: int
    not_found: int
    positive_stock: int
    zero_stock: int

    @property
    def match_rate(self) -> float:
        if not self.nonempty_articles:
            return 0.0
        return self.matched / self.nonempty_articles


@dataclass(frozen=True)
class ArlightCatalog:
    stock_by_article: dict[str, int | float]
    price_by_article: dict[str, int | float]


@dataclass(frozen=True)
class PriceMatchStats:
    sheet_rows: int
    arlight_rows: int
    matched: int
    not_found: int
    positive_prices: int

    @property
    def match_rate(self) -> float:
        if not self.arlight_rows:
            return 0.0
        return self.matched / self.arlight_rows


def get_arlight_password() -> str:
    """Load the portal password without writing it to the repository."""
    password = os.getenv("ARLIGHT_ASSETS_PASSWORD", "")
    if password:
        return password

    result = subprocess.run(
        [
            "/usr/bin/security",
            "find-generic-password",
            "-a",
            ARLIGHT_LOGIN,
            "-s",
            ARLIGHT_KEYCHAIN_SERVICE,
            "-w",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(
            "Arlight password was not found. Set ARLIGHT_ASSETS_PASSWORD or "
            f"add account '{ARLIGHT_LOGIN}' to macOS Keychain service "
            f"'{ARLIGHT_KEYCHAIN_SERVICE}'."
        )
    return result.stdout.strip()


def get_active_interface_ip() -> tuple[str, str]:
    """Return the active physical interface used to bypass full-tunnel VPNs."""
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
            return interface, match.group(1)

    raise RuntimeError(
        "No active LAN/Wi-Fi interface found for Arlight API access. "
        "Set CHECKSHEETS_BYPASS_INTERFACE explicitly."
    )


def create_arlight_session() -> requests.Session:
    interface, source_ip = get_active_interface_ip()
    session = requests.Session()
    adapter = SourceAddressAdapter(source_ip, interface_name=interface)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            ),
        }
    )
    print(f"Arlight network interface: {interface} ({source_ip})")
    return session


def _login(session: requests.Session, password: str) -> None:
    response = session.post(
        ARLIGHT_LOGIN_URL,
        data={
            "action": "POST",
            "loginUser": ARLIGHT_LOGIN,
            "loginPass": password,
        },
        timeout=30,
    )
    response.raise_for_status()
    if not session.cookies.get("authToken") or not session.cookies.get("authKey"):
        raise RuntimeError("Arlight portal did not issue authentication cookies")


def _stock_number(value: Any) -> int | float:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"Invalid Arlight stock value: {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid Arlight stock value: {value!r}") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"Invalid Arlight stock value: {value!r}")
    return int(number) if number.is_integer() else number


def _price_number(value: Any) -> int | float:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"Invalid Arlight price value: {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid Arlight price value: {value!r}") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"Invalid Arlight price value: {value!r}")
    return int(number) if number.is_integer() else number


def _parse_arlight_payload(payload: Any, *, require_price: bool) -> ArlightCatalog:
    """Validate the supplier payload and build article-indexed values."""
    if not isinstance(payload, dict):
        raise ValueError("Arlight response must be a JSON object")
    if payload.get("errors"):
        raise ValueError(f"Arlight API returned errors: {payload['errors']!r}")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("Arlight response does not contain a data object")
    items = data.get("price")
    if not isinstance(items, list):
        raise ValueError("Arlight response does not contain data.price list")
    if len(items) < MIN_API_ITEMS:
        raise ValueError(
            f"Arlight returned only {len(items)} items; expected at least {MIN_API_ITEMS}. "
            "Sheet write aborted."
        )

    stock_by_article: dict[str, int | float] = {}
    price_by_article: dict[str, int | float] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Arlight data.price contains a non-object item")
        article = str(item.get("article") or "").strip()
        if not article:
            continue
        stock = _stock_number(item.get("stock"))
        previous = stock_by_article.get(article)
        if previous is not None and previous != stock:
            raise ValueError(
                f"Arlight returned conflicting stock values for article {article!r}: "
                f"{previous!r} and {stock!r}"
            )
        stock_by_article[article] = stock

        if require_price:
            price = _price_number(item.get("price"))
            previous_price = price_by_article.get(article)
            if article in price_by_article and previous_price != price:
                raise ValueError(
                    f"Arlight returned conflicting price values for article {article!r}: "
                    f"{previous_price!r} and {price!r}"
                )
            price_by_article[article] = price

    if len(stock_by_article) < MIN_API_ITEMS:
        raise ValueError(
            f"Arlight produced only {len(stock_by_article)} unique articles; "
            f"expected at least {MIN_API_ITEMS}. Sheet write aborted."
        )
    if require_price and len(price_by_article) < MIN_API_ITEMS:
        raise ValueError(
            f"Arlight produced only {len(price_by_article)} priced articles; "
            f"expected at least {MIN_API_ITEMS}. Sheet write aborted."
        )
    return ArlightCatalog(stock_by_article, price_by_article)


def parse_price_payload(payload: Any) -> dict[str, int | float]:
    """Validate the payload and return a unique article-to-stock map."""
    return _parse_arlight_payload(payload, require_price=False).stock_by_article


def parse_arlight_catalog(payload: Any) -> ArlightCatalog:
    """Validate and return both stock and current price indexed by article."""
    return _parse_arlight_payload(payload, require_price=True)


def fetch_arlight_catalog() -> ArlightCatalog:
    """Authenticate and download the current customer-specific price catalog."""
    password = get_arlight_password()
    last_error: Exception | None = None

    for attempt in range(1, HTTP_ATTEMPTS + 1):
        session = create_arlight_session()
        try:
            _login(session, password)
            response = session.get(
                ARLIGHT_PRICE_JSON_URL,
                headers={"Referer": ARLIGHT_PRICE_PAGE_URL},
                timeout=120,
            )
            response.raise_for_status()
            payload = response.json()
            catalog = parse_arlight_catalog(payload)
            print(
                f"Arlight API: version={payload.get('version')!r}, "
                f"articles={len(catalog.stock_by_article)}, "
                f"priced={len(catalog.price_by_article)}, "
                f"last_modified={response.headers.get('Last-Modified')!r}"
            )
            return catalog
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt >= HTTP_ATTEMPTS:
                break
            delay = min(5 * (2 ** (attempt - 1)), 30)
            print(
                f"Arlight request failed ({attempt}/{HTTP_ATTEMPTS}): "
                f"{type(exc).__name__}: {exc}. Retrying in {delay}s..."
            )
            time.sleep(delay)
        finally:
            session.close()

    raise RuntimeError(
        f"Arlight API failed after {HTTP_ATTEMPTS} attempts: {last_error}"
    )


def fetch_arlight_stocks() -> dict[str, int | float]:
    """Backward-compatible stock-only wrapper around the full catalog fetch."""
    return fetch_arlight_catalog().stock_by_article


def build_stock_values(
    articles: list[Any], stock_by_article: dict[str, int | float]
) -> tuple[list[list[int | float | str]], MatchStats]:
    """Build row-aligned F values; missing API articles safely become zero."""
    values: list[list[int | float | str]] = []
    nonempty = matched = not_found = positive = zero = 0

    for raw_article in articles:
        article = str(raw_article or "").strip()
        if not article:
            values.append([""])
            continue

        nonempty += 1
        if article in stock_by_article:
            matched += 1
            stock = stock_by_article[article]
        else:
            not_found += 1
            stock = 0

        if stock > 0:
            positive += 1
        else:
            zero += 1
        values.append([stock])

    return values, MatchStats(
        sheet_rows=len(articles),
        nonempty_articles=nonempty,
        matched=matched,
        not_found=not_found,
        positive_stock=positive,
        zero_stock=zero,
    )


def build_arlight_price_values(
    models: list[Any],
    brands: list[Any],
    price_by_article: dict[str, int | float],
) -> tuple[list[list[int | float | str]], PriceMatchStats]:
    """Build row-aligned prices for Arlight models; non-Arlight rows stay blank."""
    if len(models) != len(brands):
        raise ValueError("Arlight model and brand columns have different row counts")

    values: list[list[int | float | str]] = []
    arlight_rows = matched = not_found = positive = 0

    for raw_model, raw_brand in zip(models, brands):
        model = str(raw_model or "").strip()
        brand = str(raw_brand or "").strip().casefold()
        if not model or brand != "arlight":
            values.append([""])
            continue

        arlight_rows += 1
        if model not in price_by_article:
            not_found += 1
            values.append([""])
            continue

        price = price_by_article[model]
        matched += 1
        if price > 0:
            positive += 1
        values.append([price])

    return values, PriceMatchStats(
        sheet_rows=len(models),
        arlight_rows=arlight_rows,
        matched=matched,
        not_found=not_found,
        positive_prices=positive,
    )


def sync_arlight(*, dry_run: bool = False) -> MatchStats:
    print("=" * 60)
    print("STARTING ARLIGHT API STOCK AND PRICE SYNCHRONIZATION")
    print("=" * 60)

    catalog = fetch_arlight_catalog()
    worksheet = gsheets_utils.get_worksheet(SHEET_NAME)
    columns = gsheets_utils.get_header_columns(
        worksheet,
        {"article": ARTICLE_HEADER, "stock": STOCK_HEADER},
        SHEET_NAME,
    )
    if columns["article"] != ARTICLE_COLUMN or columns["stock"] != STOCK_COLUMN:
        raise RuntimeError(
            f"Unsafe ARL TR layout: expected {ARTICLE_HEADER!r} in B and "
            f"{STOCK_HEADER!r} in F, got columns "
            f"{columns['article']} and {columns['stock']}. Sheet write aborted."
        )

    test_worksheet = gsheets_utils.get_worksheet(TEST_SHEET_NAME)
    test_columns = gsheets_utils.get_header_columns(
        test_worksheet,
        {
            "model": TEST_MODEL_HEADER,
            "brand": TEST_BRAND_HEADER,
            "price": TEST_PRICE_HEADER,
        },
        TEST_SHEET_NAME,
    )

    row_count = int(worksheet.row_count)
    article_cells = worksheet.get(
        f"B2:B{row_count}", value_render_option="UNFORMATTED_VALUE"
    )
    articles = [row[0] if row else "" for row in article_cells]
    articles.extend([""] * ((row_count - 1) - len(articles)))

    stock_values, stats = build_stock_values(articles, catalog.stock_by_article)
    print(
        "Sheet match: "
        f"matched={stats.matched}/{stats.nonempty_articles} "
        f"({stats.match_rate:.2%}), not_found={stats.not_found}, "
        f"positive={stats.positive_stock}, zero={stats.zero_stock}"
    )

    if stats.nonempty_articles == 0:
        raise RuntimeError("ARL TR contains no manufacturer articles; sheet write aborted")
    if stats.match_rate < MIN_MATCH_RATE:
        raise RuntimeError(
            f"Arlight match rate {stats.match_rate:.2%} is below safety threshold "
            f"{MIN_MATCH_RATE:.2%}; sheet write aborted"
        )
    if stats.positive_stock == 0:
        raise RuntimeError(
            "Arlight matching produced zero positive stocks; sheet write aborted"
        )

    test_row_count = int(test_worksheet.row_count)

    def read_column_values(sheet, column: int, last_row: int) -> list[Any]:
        column_letter = gsheets_utils.gspread.utils.rowcol_to_a1(1, column).rstrip("1")
        cells = sheet.get(
            f"{column_letter}2:{column_letter}{last_row}",
            value_render_option="UNFORMATTED_VALUE",
        )
        values = [row[0] if row else "" for row in cells]
        values.extend([""] * (max(0, last_row - 1 - len(values))))
        return values

    models = read_column_values(test_worksheet, test_columns["model"], test_row_count)
    brands = read_column_values(test_worksheet, test_columns["brand"], test_row_count)
    price_values, price_stats = build_arlight_price_values(
        models,
        brands,
        catalog.price_by_article,
    )
    print(
        "Arlight price match: "
        f"matched={price_stats.matched}/{price_stats.arlight_rows} "
        f"({price_stats.match_rate:.2%}), not_found={price_stats.not_found}, "
        f"positive_prices={price_stats.positive_prices}"
    )

    if price_stats.arlight_rows == 0:
        raise RuntimeError("ТЕСТ contains no Arlight models; sheet write aborted")
    if price_stats.match_rate < MIN_PRICE_MATCH_RATE:
        raise RuntimeError(
            f"Arlight price match rate {price_stats.match_rate:.2%} is below safety threshold "
            f"{MIN_PRICE_MATCH_RATE:.2%}; sheet write aborted"
        )
    if price_stats.positive_prices == 0:
        raise RuntimeError(
            "Arlight matching produced zero positive prices; sheet write aborted"
        )

    if dry_run:
        print("DRY RUN: Google Sheets were not changed")
        return stats

    gsheets_utils.update_column(
        worksheet,
        columns["stock"],
        stock_values,
        start_row=2,
    )
    print(f"Updated {SHEET_NAME}!F2:F{row_count}")
    gsheets_utils.update_column_by_schema(
        test_worksheet,
        {
            "model": TEST_MODEL_HEADER,
            "brand": TEST_BRAND_HEADER,
            "price": TEST_PRICE_HEADER,
        },
        "price",
        price_values,
        start_row=2,
    )
    print(
        f"Updated {TEST_SHEET_NAME}!'{TEST_PRICE_HEADER}' "
        f"for {price_stats.matched} Arlight rows"
    )
    print("ARLIGHT API STOCK AND PRICE SYNCHRONIZATION COMPLETED")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Synchronize Arlight API stock and price to Google Sheets"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and validate data without writing Google Sheets",
    )
    args = parser.parse_args()
    sync_arlight(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"CRITICAL ERROR: {type(exc).__name__}: {exc}")
        raise SystemExit(1)
