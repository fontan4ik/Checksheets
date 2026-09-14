"""Synchronize Arlight API stock into ``ARL TR!AC``.

The supplier portal uses a login session rather than a permanent API token.
The password is read from ``ARLIGHT_ASSETS_PASSWORD`` or from the macOS
Keychain item ``checksheets-arlight-assets``; it is never stored in this file.
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
STOCK_HEADER = "Остаток АПИ"
ARTICLE_COLUMN = 2  # B
STOCK_COLUMN = 29  # AC

MIN_API_ITEMS = max(1, int(os.getenv("ARLIGHT_MIN_API_ITEMS", "10000")))
MIN_MATCH_RATE = float(os.getenv("ARLIGHT_MIN_MATCH_RATE", "0.90"))
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


def parse_price_payload(payload: Any) -> dict[str, int | float]:
    """Validate the price payload and return a unique article-to-stock map."""
    if not isinstance(payload, dict):
        raise ValueError("Arlight response must be a JSON object")
    if payload.get("errors"):
        raise ValueError(f"Arlight API returned errors: {payload['errors']!r}")

    items = payload.get("data", {}).get("price")
    if not isinstance(items, list):
        raise ValueError("Arlight response does not contain data.price list")
    if len(items) < MIN_API_ITEMS:
        raise ValueError(
            f"Arlight returned only {len(items)} items; expected at least {MIN_API_ITEMS}. "
            "Sheet write aborted."
        )

    stock_by_article: dict[str, int | float] = {}
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

    if len(stock_by_article) < MIN_API_ITEMS:
        raise ValueError(
            f"Arlight produced only {len(stock_by_article)} unique articles; "
            f"expected at least {MIN_API_ITEMS}. Sheet write aborted."
        )
    return stock_by_article


def fetch_arlight_stocks() -> dict[str, int | float]:
    """Authenticate and download the current customer-specific price stock."""
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
            stocks = parse_price_payload(payload)
            print(
                f"Arlight API: version={payload.get('version')!r}, "
                f"articles={len(stocks)}, last_modified={response.headers.get('Last-Modified')!r}"
            )
            return stocks
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


def build_stock_values(
    articles: list[Any], stock_by_article: dict[str, int | float]
) -> tuple[list[list[int | float | str]], MatchStats]:
    """Build row-aligned AC values; missing API articles safely become zero."""
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


def sync_arlight(*, dry_run: bool = False) -> MatchStats:
    print("=" * 60)
    print("STARTING ARLIGHT API STOCK SYNCHRONIZATION")
    print("=" * 60)

    stock_by_article = fetch_arlight_stocks()
    worksheet = gsheets_utils.get_worksheet(SHEET_NAME)
    columns = gsheets_utils.get_header_columns(
        worksheet,
        {"article": ARTICLE_HEADER, "stock_api": STOCK_HEADER},
        SHEET_NAME,
    )
    if columns["article"] != ARTICLE_COLUMN or columns["stock_api"] != STOCK_COLUMN:
        raise RuntimeError(
            f"Unsafe ARL TR layout: expected {ARTICLE_HEADER!r} in B and "
            f"{STOCK_HEADER!r} in AC, got columns "
            f"{columns['article']} and {columns['stock_api']}. Sheet write aborted."
        )

    row_count = int(worksheet.row_count)
    article_cells = worksheet.get(
        f"B2:B{row_count}", value_render_option="UNFORMATTED_VALUE"
    )
    articles = [row[0] if row else "" for row in article_cells]
    articles.extend([""] * ((row_count - 1) - len(articles)))

    values, stats = build_stock_values(articles, stock_by_article)
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

    if dry_run:
        print("DRY RUN: AC was not changed")
        return stats

    gsheets_utils.update_column(
        worksheet,
        columns["stock_api"],
        values,
        start_row=2,
    )
    print(f"Updated {SHEET_NAME}!AC2:AC{row_count}")
    print("ARLIGHT API STOCK SYNCHRONIZATION COMPLETED")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Synchronize Arlight API stock to ARL TR column AC"
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
