"""
Ozon Performance API - sync ad-attributed orders/revenue/spend into Google Sheets.

Uses the same source-bound bypass pattern as rs_sync_local.py because Ozon
Performance requests are unstable on the default route in this environment.
"""

from __future__ import annotations

import io
import os
import re
import time
import zipfile
from datetime import date, timedelta

import requests

import config
import gsheets_utils
from network_bypass import SourceAddressAdapter


def get_active_interface_ip() -> tuple[str, str]:
    preferred_interface = os.getenv("CHECKSHEETS_BYPASS_INTERFACE", "").strip()

    if preferred_interface:
        output = os.popen(f"ifconfig {preferred_interface}").read()
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", output)
        if match:
            return preferred_interface, match.group(1)

    for interface in ("en1", "en0"):
        output = os.popen(f"ifconfig {interface}").read()
        if "status: active" not in output:
            continue
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", output)
        if match:
            return interface, match.group(1)

    raise RuntimeError(
        "No active LAN/Wi-Fi interface found for Ozon Performance bypass. "
        "Set CHECKSHEETS_BYPASS_INTERFACE explicitly."
    )


def create_perf_session() -> requests.Session:
    session = requests.Session()
    if os.getenv("OZON_PERF_SKIP_BYPASS", "").lower() == "true":
        print("Bypass skipped via OZON_PERF_SKIP_BYPASS")
        return session

    try:
        interface, source_ip = get_active_interface_ip()
        adapter = SourceAddressAdapter(source_ip, interface_name=interface)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        print(f"Ozon Perf bypass interface: {interface} ({source_ip})")
    except Exception as e:
        print(f"Warning: Could not initialize bypass adapter: {e}. Using default routing.")
    return session


HTTP = create_perf_session()
BASE_URL = config.OZON_PERF_BASE_URL.rstrip("/")
SHEET_NAME = getattr(config, "OZON_PERF_SHEET_NAME", "ТЕСТ")
SKU_COL_INDEX = 22  # V / SKU Ozon
TARGET_ARTICLE = "39171-1"


def parse_money(raw: str) -> float:
    cleaned = (
        str(raw or "")
        .replace("\xa0", "")
        .replace(" ", "")
        .replace("₽", "")
        .replace(",", ".")
        .strip()
    )
    return float(cleaned) if cleaned else 0.0


def format_report_timestamp(day: str, end_of_day: bool = False) -> str:
    suffix = "23:59:59.000Z" if end_of_day else "00:00:00.000Z"
    return f"{day}T{suffix}"


def get_perf_token() -> str:
    response = HTTP.post(
        f"{BASE_URL}/api/client/token",
        json={
            "client_id": config.OZON_PERF_CLIENT_ID,
            "client_secret": config.OZON_PERF_CLIENT_SECRET,
            "grant_type": "client_credentials",
        },
        timeout=30,
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError(f"Missing access_token in response: {response.text[:500]}")
    print("Ozon Performance token obtained")
    return token


def get_perf_campaigns(token: str) -> list[dict]:
    response = HTTP.get(
        f"{BASE_URL}/api/client/campaign",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    response.raise_for_status()
    campaigns = response.json().get("list", [])
    print(f"Found {len(campaigns)} campaigns")
    return campaigns


def request_perf_report(token: str, campaign_ids: list[int], date_from: str, date_to: str) -> str:
    payload = {
        "from": format_report_timestamp(date_from),
        "to": format_report_timestamp(date_to, end_of_day=True),
    }
    if campaign_ids:
        payload["campaigns"] = campaign_ids

    response = HTTP.post(
        f"{BASE_URL}/api/client/statistics/orders/generate",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )

    if response.status_code == 429 and "максимум 1" in response.text.lower():
        raise RuntimeError(
            "Ozon Performance has another active report. Wait for it to finish and rerun."
        )

    response.raise_for_status()
    data = response.json()
    uuid = data.get("UUID")
    if not uuid:
        raise RuntimeError(f"Missing UUID in report response: {response.text[:500]}")
    print(f"Created report UUID: {uuid}")
    return uuid


def wait_perf_report(token: str, uuid: str, max_attempts: int = 60, sleep_seconds: int = 5) -> bytes:
    report_url = f"{BASE_URL}/api/client/statistics/report?UUID={uuid}"
    headers = {"Authorization": f"Bearer {token}"}

    for attempt in range(1, max_attempts + 1):
        time.sleep(sleep_seconds)

        report_response = HTTP.get(report_url, headers=headers, timeout=60)
        if report_response.status_code == 200:
            content = report_response.content
            if content[:2] == b"PK" or b";" in content[:200] or b"sku" in content[:200].lower():
                print(f"Report ready via /statistics/report on attempt {attempt}")
                return content
            try:
                payload = report_response.json()
            except ValueError:
                payload = None

            if isinstance(payload, dict) and payload.get("error") == "report not found":
                if attempt % 6 == 0:
                    print(f"Waiting for report {uuid}: not ready yet, attempt={attempt}/{max_attempts}")
                continue

        if attempt % 6 == 0:
            print(f"Waiting for report {uuid}: attempt={attempt}/{max_attempts}")

    raise TimeoutError(f"Timeout waiting for report {uuid}")


def unpack_report_content(content: bytes) -> list[str]:
    """Return list of CSV text blocks — one per file in ZIP (or one block for plain CSV)."""
    if content[:2] == b"PK":
        archive = zipfile.ZipFile(io.BytesIO(content))
        blocks = []
        for name in archive.namelist():
            blocks.append(archive.read(name).decode("utf-8-sig"))
        return blocks
    return [content.decode("utf-8-sig")]


def detect_csv_indices(headers: list[str]) -> dict[str, int]:
    normalized = [header.strip().lower() for header in headers]
    indices = {
        "sku": -1,
        "promo_sku": -1,
        "article": -1,
        "orders": -1,
        "revenue": -1,
        "spend": -1,
    }

    for idx, header in enumerate(normalized):
        if header == "sku":
            indices["sku"] = idx
        elif "sku продвигаемого товара" in header:
            indices["promo_sku"] = idx
        elif header == "артикул":
            indices["article"] = idx
        elif header == "количество":
            indices["orders"] = idx
        elif header == "стоимость, ₽":
            indices["revenue"] = idx
        elif header == "расход, ₽":
            indices["spend"] = idx

    if indices["sku"] == -1:
        indices["sku"] = 3
    if indices["promo_sku"] == -1:
        indices["promo_sku"] = indices["sku"]
    if indices["article"] == -1:
        indices["article"] = 5
    if indices["orders"] == -1:
        indices["orders"] = 8
    if indices["revenue"] == -1:
        indices["revenue"] = 10
    if indices["spend"] == -1:
        indices["spend"] = 13

    return indices


def parse_single_csv_block(text: str, block_index: int, indices_cache: dict) -> dict[str, dict[str, float]]:
    """Parse one CSV block (one campaign file). Handles the meta-line before the real header."""
    lines = [line for line in text.replace("\ufeff", "").splitlines() if line.strip()]
    if not lines:
        return {}

    # Ozon ZIP structure: line 0 = campaign meta (starts with ';'), line 1 = real header
    header_line_idx = 0
    campaign_name = "Unknown"
    if lines[0].startswith(";") or (lines[0].split(";")[0].strip() == "" and len(lines) > 1):
        header_line_idx = 1
        campaign_name = lines[0].strip("; ").split(",")[0]

    if header_line_idx >= len(lines):
        return {}

    headers = lines[header_line_idx].split(";")
    if block_index not in indices_cache:
        indices_cache[block_index] = detect_csv_indices(headers)
        print(f"Block {block_index} ({campaign_name}) indices: {indices_cache[block_index]}")
    indices = indices_cache[block_index]

    stats: dict[str, dict[str, float]] = {}
    for line in lines[header_line_idx + 1:]:
        if line.startswith(";") or "Всего" in line:
            continue

        parts = line.split(";")
        required = max(indices.values())
        if len(parts) <= required:
            continue

        promo_sku = parts[indices["promo_sku"]].strip().strip('"')
        sku = promo_sku or parts[indices["sku"]].strip().strip('"')
        if not sku:
            continue

        try:
            spend = parse_money(parts[indices["spend"]])
            orders = int(parse_money(parts[indices["orders"]]))
            revenue = parse_money(parts[indices["revenue"]])
        except (ValueError, IndexError):
            continue

        if orders == 0 and spend == 0 and revenue == 0:
            continue

        if os.getenv("OZON_PERF_DIAGNOSE_ARTICLE") and (
            sku == "986315608" or parts[indices["article"]].strip() == TARGET_ARTICLE
        ):
             print(f"  [Found target SKU in {campaign_name}]")
             print(f"    Raw indices: orders={parts[indices['orders']] if len(parts)>indices['orders'] else 'N/A'}, rev={parts[indices['revenue']] if len(parts)>indices['revenue'] else 'N/A'}, spend={parts[indices['spend']] if len(parts)>indices['spend'] else 'N/A'}")
             print(f"    Values: Orders={orders}, Rev={revenue}, Spend={spend}")

        bucket = stats.setdefault(sku, {"orders": 0, "spend": 0.0, "revenue": 0.0})
        bucket["orders"] += orders
        bucket["spend"] += spend
        bucket["revenue"] += revenue

    return stats


def parse_perf_csv(content: bytes) -> dict[str, dict[str, float]]:
    blocks = unpack_report_content(content)
    indices_cache: dict = {}
    all_stats: dict[str, dict[str, float]] = {}

    for i, block in enumerate(blocks):
        block_stats = parse_single_csv_block(block, i, indices_cache)
        for sku, data in block_stats.items():
            bucket = all_stats.setdefault(sku, {"orders": 0, "spend": 0.0, "revenue": 0.0})
            bucket["orders"] += data["orders"]
            bucket["spend"] += data["spend"]
            bucket["revenue"] += data["revenue"]

    print(f"Parsed {len(all_stats)} unique SKUs with data")
    return all_stats


def fetch_perf_stats(token: str, campaigns: list[dict], date_from: str, date_to: str) -> dict[str, dict[str, float]]:
    campaign_ids = [int(c["id"]) for c in campaigns]
    print(f"Creating one account-level orders report for {len(campaign_ids)} campaigns")

    uuid = request_perf_report(token, campaign_ids, date_from, date_to)
    raw_report = wait_perf_report(token, uuid)
    stats = parse_perf_csv(raw_report)

    print(f"Total unique SKUs from orders report: {len(stats)}")
    return stats


def get_period() -> tuple[str, str]:
    env_from = os.getenv("OZON_PERF_DATE_FROM", "").strip()
    env_to = os.getenv("OZON_PERF_DATE_TO", "").strip()
    if env_from and env_to:
        return env_from, env_to

    today = date.today()
    date_to = today - timedelta(days=1)
    date_from = date_to - timedelta(days=6)
    return date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d")


def sync_perf_ads() -> None:
    print("=" * 60)
    print("Starting Ozon Performance Ads Sync...")
    print("=" * 60)

    token = get_perf_token()
    date_from, date_to = get_period()
    print(f"Period: {date_from} -> {date_to}")

    campaigns = get_perf_campaigns(token)
    stats = fetch_perf_stats(token, campaigns, date_from, date_to)

    ws = gsheets_utils.get_worksheet(SHEET_NAME)
    sku_values = ws.col_values(SKU_COL_INDEX)[1:]
    print(f"Found {len(sku_values)} SKUs in sheet '{SHEET_NAME}' column V")

    col_qty_data = []
    col_rev_data = []
    col_spend_data = []
    found_count = 0

    for sku in sku_values:
        sku_str = str(sku).strip() if sku else ""
        if sku_str and sku_str in stats:
            data = stats[sku_str]
            col_qty_data.append([data["orders"]])
            col_rev_data.append([data["revenue"]])
            col_spend_data.append([data["spend"]])
            found_count += 1
        else:
            col_qty_data.append([0])
            col_rev_data.append([0])
            col_spend_data.append([0])

    gsheets_utils.update_column(worksheet=ws, col_num=53, values=col_qty_data)
    gsheets_utils.update_column(worksheet=ws, col_num=54, values=col_rev_data)
    gsheets_utils.update_column(worksheet=ws, col_num=55, values=col_spend_data)

    print(f"Updated rows with ad stats: {found_count}/{len(sku_values)}")


def diagnose_reference_article() -> None:
    print("=" * 60)
    print(f"Reference check for article {TARGET_ARTICLE}")
    print("=" * 60)

    ws = gsheets_utils.get_worksheet(SHEET_NAME)
    matches = ws.findall(TARGET_ARTICLE)
    if not matches:
        raise RuntimeError(f"Article {TARGET_ARTICLE} not found in sheet {SHEET_NAME}")

    row_index = matches[0].row
    row = ws.row_values(row_index)
    row_sku = row[SKU_COL_INDEX - 1].strip()
    print(f"Sheet row: {row_index}")
    print(f"Article: {row[0]}")
    print(f"Vendor/model: {row[1]}")
    print(f"SKU Ozon: {row_sku}")

    token = get_perf_token()
    campaigns = get_perf_campaigns(token)
    # Don't filter campaigns for diagnostics to ensure we find all data for the SKU
    print(f"Using all {len(campaigns)} campaigns for diagnostics to find accurate reference values")

    date_from, date_to = get_period()
    print(f"Reference period: {date_from} -> {date_to}")
    stats = fetch_perf_stats(token, campaigns, date_from, date_to)

    data = stats.get(row_sku)
    if not data:
        print(f"SKU {row_sku} not found in Ozon Performance report")
        return

    print(
        "Resolved values:",
        f"Количество={data['orders']}",
        f"Стоимость={data['revenue']:.2f}",
        f"Расход={data['spend']:.2f}",
    )


if __name__ == "__main__":
    if os.getenv("OZON_PERF_DIAGNOSE_ARTICLE", "").strip() == TARGET_ARTICLE:
        diagnose_reference_article()
    else:
        sync_perf_ads()
